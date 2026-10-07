# Obsidian skills

Nine skills are packaged as two independently installable plugins for Codex
and Claude Code. Both can use the same selected Obsidian vault:

| Plugin | Purpose | Namespace |
|---|---|---|
| **knowledge** | Organize sources and maintain a knowledge base | `knowledge:` |
| **investments** | Collect source posts, research buying opportunities and evaluate earlier recommendations | `investments:` |

They share one GitHub repository and the `obsidian-skills` marketplace. Each
plugin has its own version and includes its skills, references and shared helpers.
Knowledge workflows use the [vault conventions](shared/CONVENTIONS.md);
investment notes follow their own format. Common input safety, safe writes and
suggestion-log protocols keep both plugins compatible with the same vault.

## The skills

Choose by the requested result, not just the input's file type.

| Requested result | Skill | Main input and output |
|---|---|---|
| Rename, file or split PDFs | [knowledge:pdf-organize](skills/pdf-organize/SKILL.md) | PDFs → organized PDFs and chapter files |
| Extract figure images | [knowledge:figure-extract](skills/figure-extract/SKILL.md) | PDFs → cropped PNGs in `Sources/Images/` |
| Explain a paper, chapter, report, standard or publication notice | [knowledge:paper-summarize](skills/paper-summarize/SKILL.md) | PDF → reading note in `Articles/` |
| Clean Web Clipper captures | [knowledge:clipping-clean](skills/clipping-clean/SKILL.md) | raw capture → cleaned note in `Articles/` |
| Build or enrich wiki entries from new evidence | [knowledge:wiki-build](skills/wiki-build/SKILL.md) | organized PDF or cleaned source note → entries in `Wiki/` |
| Research and add missing requested topics | [knowledge:wiki-add](skills/wiki-add/SKILL.md) | vault-root `add-to-wiki.md`, another selected backlog or topics named in the request → new requested entries citing vault sources or web pages by URL, plus any newly filed PDFs |
| Audit, repair and refactor existing wiki entries | [knowledge:wiki-lint](skills/wiki-lint/SKILL.md) | existing `Wiki/`, its cited sources, issues you flag in entries and open note suggestions → content repairs, merges, splits, retitles, missing entries, links, parents and MOCs |
| Record selected X posts and RSS/Atom articles without interpretation | [investments:feed-collect](skills/feed-collect/SKILL.md) | `Investments/x-accounts.md` and `rss-feeds.md` → maintained X notes and RSS article notes in `Investments/Sources/` |
| Analyze stock ideas from collected feeds | [investments:stock-research](skills/stock-research/SKILL.md) | saved posts + verified financial evidence → daily report and maintained stock notes |

A PDF attached without a stated goal has no default workflow; ask what result
the user wants. An inbox-wide request splits captured `.md` files and `.pdf`
files between the two intake skills. Other file types are named in the report
and left in place.

## The pipeline

The routes branch; a document does not have to pass through every skill.
When one request asks for several results, run each requested skill once in
pipeline order; wiki-lint, when requested, runs last.

```text
Inbox/*.pdf → pdf-organize → Sources/PDFs/
                                ├─ figure-extract → Sources/Images/
                                ├─ paper-summarize → Articles/ reading note
                                └─ wiki-build → Wiki/

Inbox/*.md → clipping-clean → Articles/ cleaned clipping
                                     └─ wiki-build → Wiki/

add-to-wiki.md or named topics → wiki-add → missing requested entries in Wiki/ (web pages cited by URL)

Existing Wiki/ + flagged issues + open note suggestions → wiki-lint → entry repairs, missing entries, links, parents and MOCs

Investments/x-accounts.md + rss-feeds.md → feed-collect → X notes + RSS articles
  → stock-research
  + targeted financial verification + prior research → daily report + Stocks/ notes
```

Feed collection saves images and PDFs locally, and retains videos as labeled
source links without downloading or transcribing them.

Figure extraction supplies images to paper-summarize and wiki-build; each runs
figure-extract on a source PDF whose figures are missing.
Both paper-summarize and wiki-build read the **original PDF**. The summary
is a finished reading note; builder may use it only under its
[verified missing-PDF fallback](skills/wiki-build/references/source-cases.md#resolve-a-markdown-source).
A cleaned clipping is itself the source and can be used directly. wiki-build
never cites a raw `Inbox/` file; clipping-clean or pdf-organize handles it
first. wiki-add can reuse sources that Wiki entries already cite, file newly
acquired PDFs itself under pdf-organize's naming rules, or cite a web page it
researched by its URL in the entry's `sources:`; it never creates a note just
to have something to cite. Its
[research guide](skills/wiki-add/references/research.md) owns that procedure.

**Organize PDFs before deriving filenames and links from them.** Later renames
must carry the dependent notes, figures, references and sidecars together,
using pdf-organize's reviewed plan. The
[source-filename contract](shared/CONVENTIONS.md#1a-source-file-names-and-why-pdf-organize-runs-first)
defines that boundary. A summary is not required before building wiki entries,
and wiki-lint can run independently of any source-processing task.

**Renames repair their links automatically.** When a skill renames a vault
file (pdf-organize renaming or filing a PDF, clipping-clean reprocessing a
clipping under a new slug, wiki-lint retitling an entry, figure-extract
moving Extended Data crops to their ED names), it rewrites every link to that
file in the same run, as Obsidian does. Each also repairs Obsidian Canvas
boards: file cards, group backgrounds and text cards follow the moved files. The request that leads to the rename
authorizes the repair; no skill asks again or hands it to another skill. A reference it cannot rewrite safely keeps the old file in
place, and the run reports it.

wiki-build adds source-supported content only to the entries in its current
run. wiki-lint owns retrospective work across the existing wiki. Their
[linking ownership](shared/CONVENTIONS.md#9-ownership-split-for-linking) prevents
later source merges from reversing deliberate maintenance decisions.

A default wiki-lint run, such as "lint my wiki", works in this order:

1. **Task 1** checks every entry against the writing rules and fixes what
   needs no source.
2. **Task 1b** repairs content from the sources each entry already cites or
   accurate background. It corrects and simplifies claims, deepens thin
   explanations, settles conflicting claims (reading standard references
   online, never citing them), consolidates an explanation duplicated across
   entries into its owner, aligns notation, merges duplicate entries that name
   one entity, splits an entry that defines several subjects, retitles
   ambiguous bare titles and creates the missing entries the wiki's own
   entries need. Each new or merged entry is marked unread.
3. **Task 2** adds and prunes links, including links to the new entries.
4. **Task 3** rebuilds `parents:` and the MOCs.

The run also works through the open items in
`Reviews/wiki-notes-suggestions.md`: it re-verifies each one, fixes it and
moves it to Fixed, leaving open only what it cannot complete, with the reason.
A request for a narrower task or a set of entries limits the run. A thin entry
whose teaching lives only in a chapter not yet built waits for that chapter's
wiki-build. A split or merge that is a close call is reported with both
options instead of applied, and deleting an entry still needs an explicit
request. Enriching an existing entry with new-source evidence still belongs
to wiki-build.

**Flag issues for the next lint.** Every Wiki entry has an `issues` property
after `read`, blank as `issues: ""`; the next wiki-lint run adds it to older
entries. When you notice a problem while reviewing a note, describe it there
on one line; several issues may share the line. The next wiki-lint run treats
each issue as your request for that note: it fixes the issue, or checks it and
explains in the report why it does not hold, then removes the resolved issues
and unchecks `read` so you review the note again. An issue it cannot act on,
such as one needing a deletion or a source the entry does not cite, stays in
the field, and the report says why. In Obsidian, set the
`issues` property's type to Text, or to List if you prefer one issue per item.
The [field's rules](shared/CONVENTIONS.md#2d-issues--the-users-issue-inbox)
own the details.

[wiki-add](skills/wiki-add/SKILL.md) is the create-only research route for
topics queued in `add-to-wiki.md` or a backlog the user selects, or named
directly without a source document. A queue holds one flush-left list item
per topic, such as `- [ ] Topic`; wiki-add reports plain lines, table rows
and nested open tasks instead of processing them. It leaves every existing
entry unchanged and checks off only queued topics it created or found already
present; enriching an existing entry from a new source remains wiki-build's
job, and deepening it from the sources it already cites is wiki-lint's.
wiki-lint also creates a missing entry its own run establishes, researched the
same way but citing only a document the entries using the term already cite or
a web page by URL, and links and places it in the same run.

stock-research analyzes ideas in feed-collect’s saved X notes and RSS articles for long-only
buying opportunities in liquid U.S.-listed stocks over a 3–12 month momentum
horizon. Run feed-collect first, then stock-research. Posts nominate ideas; targeted
price, filing and business checks establish whether the buying case holds.
It does not collect posts itself or silently substitute a broad market scan.
Every substantively analyzed stock, including watch and rejected ideas, gets a
maintained note in `Investments/Stocks/`, with its latest assessment and links
to the immutable daily reports that record earlier conclusions.
Each note has a short decision brief and a detailed research record for future
runs, including thesis changes, daily checks of two-week and 1/3/6/12/24/60-month
outcomes and monthly summaries of evidence-backed lessons. Quoted recommendation prices stay
separate from the fixed hypothetical entry convention. No qualifying
buying opportunity is a valid result. Scheduled and user-requested manual editions
use the skill's [note format](skills/stock-research/references/note-format.md) in
`Investments/`, sharing one thesis and outcome history; they are not
Wiki entries or source notes for automatic wiki-build intake. It researches
opportunities without reviewing current holdings, recommending sales, placing
trades, or rewriting earlier records.
Its optional [data retrieval helpers](skills/stock-research/references/data-access.md)
cover SEC filings/facts, Nasdaq directories/halts, Alpaca prices/actions/sessions/news,
Alpha Vantage news/earnings calendars and estimates, and FRED macro series/release dates. Setup
can be checked offline; keyed sources use local environment variables or an
explicit private JSON file passed to the bundled script with `--credentials-file`.
Credentials remain outside the plugin, repository and vault; no separate local
credential launcher is required. Retrieval retains explicit feed and coverage limits.

[feed-collect](skills/feed-collect/SKILL.md) independently records timestamped
original posts, quote posts and reposts from public X accounts selected in
`Investments/x-accounts.md`, using the official API. It includes self-replies and
thread continuations while excluding replies to other accounts.
It maintains one account note under `Investments/Sources/X/`,
with durable cursors and recovery state under `Investments/Sources/.feed-collect/`.
Ordinary runs collect all available eligible posts from the past three days,
reusing saved progress and retaining previously saved older posts. There is no
default request or returned-post cap; explicit budgets and provider limits can
leave partial coverage. An explicitly requested latest-post sample can reach
older history and has a separate target for each account. Photo attachments are
saved in `Sources/Images/` and embedded; directly linked PDFs go to `Sources/PDFs/`. Download receipts allow
attachment retries without rereading paid X posts.
Reposts retain their own timestamps and original-source links; returned text may
be truncated, and referenced originals are not fetched separately.
Routine updates avoid replaying saved pages and reuse saved responses when
publication needs retrying. Ambiguous paid requests stop for
resolution instead of silently retrying. Source edits and removals have a
separate reconciliation procedure. The collector does not summarize posts,
select stocks or change the stock-research schedule. Read its
[X API guide](skills/feed-collect/references/x-api.md) for credentials, bounded
backfills, coverage limitations and compliance maintenance.

For public blogs/newsletters, enable RSS 2.0 or Atom feeds in
`Investments/rss-feeds.md`. The [RSS/Atom adapter](skills/feed-collect/references/rss-atom.md)
saves one note per article and a publication index under `Investments/Sources/RSS/`,
with durable state in `Investments/Sources/.rss-collect/`. It saves the current feed
on first collection and unseen articles/revisions on later runs, without X's
three-day cutoff. Conditional requests avoid unchanged transfers where supported;
revision identities prevent both duplicate research and reuse of outdated text.
Feed-provided summaries remain labeled as such. It does not crawl article pages,
collect subscriber credentials or bypass paywalls. Both adapters retain images
and direct PDFs locally, with bounded downloads and publication guards.

The [offline screener](skills/stock-research/references/screening.md) calculates
calendar-month momentum, benchmark-relative returns, moving averages and a
clearly labeled daily liquidity proxy from saved Alpaca/calendar responses.
The research method verifies feed-nominated candidates and checks decision-critical
claims and earnings comparisons before publication. Optional exact-accession SEC
filing extraction uses pinned EdgarTools as a local parser, without delegating
network requests or installing another framework. Core retrieval, screening and
note handling remain standard-library-only. Exact Form 4/4-A XML supplies selective
insider context. Immutable selected estimate snapshots preserve what was observed
and saved before each cutoff. A targeted acquisition coordinator batches needed
current prices, justified daily/minute history with exchange calendars, and
estimates for the explicit nominees under one bounded request budget before
freezing the report cutoff. Price conditions specify their measurement, session,
duration and any later-hold test when the thesis opens.
Prospective comparisons freeze those nominees and their initial research states,
including unfinished work, to evaluate future outcomes without selecting only
eventual recommendations. Earlier independent momentum cohorts retain their
original definitions and checkpoints.

This product uses the FRED® API but is not endorsed or certified by the Federal
Reserve Bank of St. Louis. Use of its FRED integration is subject to the
[FRED API Terms of Use](https://fred.stlouisfed.org/docs/api/terms_of_use.html).

## Codex and Claude

Both plugins run on **macOS and Linux** in Codex and Claude Code, including
local desktop workflows with filesystem and shell access. These are skill
packages, not Obsidian community plugins or MCP servers. Installing them does
not install Python dependencies, grant vault access or schedule work.

Install either or both through the existing shared marketplace:

```bash
# Codex: add the marketplace once, then select the plugins you want.
codex plugin marketplace add https://github.com/dengrish/obsidian-skills.git
codex plugin add knowledge@obsidian-skills
codex plugin add investments@obsidian-skills

# Claude Code
claude plugin marketplace add dengrish/obsidian-skills
claude plugin install knowledge@obsidian-skills
claude plugin install investments@obsidian-skills
```

Invoke any skill by its plugin namespace, for example `knowledge:pdf-organize`,
`knowledge:wiki-build` or `investments:feed-collect`. Start a fresh
session/task after installation or updates to refresh the host's catalog.
Each plugin uses its own packaged `skills/` and `shared/` resources; copying
one SKILL.md or relying on a sibling installation is unsupported.

| Purpose | Location |
|---|---|
| Contributor guidance | `AGENTS.md`; `CLAUDE.md` imports it with `@AGENTS.md` |
| Marketplace for both hosts | `.claude-plugin/marketplace.json` |
| Authored manifests | `plugins/<name>/.claude-plugin/plugin.json` |
| Generated Codex manifests | `plugins/<name>/.codex-plugin/plugin.json` |
| Canonical runtime sources | root `skills/` and `shared/` |
| Self-contained runtime trees | `plugins/knowledge/` and `plugins/investments/` |
| Reproducible archives | `knowledge.plugin` and `investments.plugin` |

Contributor instructions stay in the repository; installed skills load their
packaged runtime guidance explicitly. For local Claude development, use
`claude --plugin-dir plugins/knowledge` or `claude --plugin-dir plugins/investments`
after building the source tree.

### Migrating from the former obsidian plugin

Publish the split source, refresh the existing marketplace in each host, and
install `knowledge@obsidian-skills` and `investments@obsidian-skills`. Verify
both new plugins before removing the former `obsidian@obsidian-skills`
installation; do not keep duplicate skill catalogs enabled after migration.
Do not manually edit caches or replace the GitHub marketplace with a local one.

Update scheduled skill references to `investments:stock-research` only after the new installed plugin is available.
Earlier `*-market-research.md` daily reports and their outcome links remain
readable without renaming or rewriting historical files.
Keep the selected vault, credentials file, interpreter and schedule unchanged;
shared-helper overrides must point to the selected investments installation.
The default daily start remains 08:30 `America/Los_Angeles` / 11:30
`America/New_York`, including closed-market days and daylight-saving changes.
Fresh scheduled and manual reviews complete bounded targeted acquisition before
freezing their actual preparation cutoff. Existing reports and run receipts keep
their original cutoff; late data never changes a frozen edition.
A source edit alone does not switch an existing automation or install a plugin.

No vault migration is needed. Existing notes, recommendation IDs, review logs,
figure sidecars, raw captures and ownership markers retain their meanings.
The `OBSIDIAN_VAULT_SHARED` setting and hidden `.obsidian-skills-tmp-` scratch
prefix are durable protocols, independent of the plugin namespace.

## Vault layout

`<vault>` is the user-selected vault or an unambiguous workspace vault. Resolve
it and any per-run path overrides through [RUNTIME.md](shared/RUNTIME.md).

```text
<vault>/
├── Inbox/                    raw clippings and incoming PDFs
├── Articles/                 clippings, PDF reading notes and legacy research extracts
├── Sources/
│   ├── PDFs/                 organized PDFs
│   │   └── <Work>/           a split book's chapter PDFs
│   └── Images/               flat folder for extracted/downloaded images
├── Wiki/                     entity notes, scanned recursively
├── Investments/              dated market research, separate from the Wiki
│   ├── x-accounts.md         user-maintained X account roster
│   ├── rss-feeds.md          user-maintained public RSS/Atom roster
│   ├── Sources/
│   │   ├── X/                one maintained note per collected account
│   │   ├── RSS/              publication indexes and article notes
│   │   ├── .feed-collect/    durable X cursors and recovery state
│   │   └── .rss-collect/     durable RSS identities, revisions and receipts
│   └── Snapshots/            research evidence
├── MOCs/                     generated navigation outlines
│   ├── <discipline>-moc.md   e.g. machine-learning-moc.md
│   └── misc-moc.md           Wiki entries tagged #misc
├── add-to-wiki.md            wiki-add's requested-topic queue
└── Reviews/                  suggestion logs: open issues, then fixed ones
    ├── <current-skill>-suggestions.md  one per skill
    ├── wiki-notes-suggestions.md      note-content backlog
    └── .wiki-lint-settled.json        wiki-lint's private ledger of settled link decisions
```

PDFs move out of `Inbox/`; raw clippings stay as the record of what was
captured. The clipping dedup index determines whether a capture was processed.
The source-note producers share `Articles/`: `sources:` item 1 identifies
the origin used for deduplication, and a body marker distinguishes legacy
wiki-add research extracts from full-text clippings. wiki-add reuses existing source
notes only when Wiki entries already cite them (or, read-only, a legacy
research extract), and reuses existing images,
without overwriting either. Market research, MOCs, suggestion logs and the topic
queue stay outside `Wiki/` so they are not treated as entries.

Each Wiki entry has exactly one discipline tag, or `"#misc"` alone when none
fits. Each active tag has a `Wiki/<discipline>.md` root with empty parents, a cited
source like every entry (often the reference page it is derived from) and a
generated outline in `MOCs/<discipline>-moc.md`; `parents:` name Wiki entries
only, a root by its bare slug such as `[[biology]]`. New entries from wiki-build and wiki-add start with `parents: []` and
stay out of the MOCs until wiki-lint places them; wiki-lint places the entries
it creates in the same run. wiki-lint reviews every tree
and parent for conceptual coherence, without a fixed depth limit. The
[tag and hierarchy rules](shared/CONVENTIONS.md#3-the-discipline-tag-enum) and
wiki-lint's [MOC procedure](skills/wiki-lint/references/hierarchy.md#build-or-maintain-the-moc-files)
own the details.

Every skill can record evidenced improvements in its own suggestion log or
the log of the skill that produced or governs an output it used. Routine runs
do not edit skill sources. An explicit plugin review fixes the source
repository, never an installed cache, with validation and Git history instead
of creating dated review reports; existing reports remain untouched. The
[shared suggestion protocol](shared/SUGGESTIONS.md) owns these rules and log
format.

Workflow scratch lives in a hidden `.obsidian-skills-tmp-<unique-id>` directory
outside the vault, never a visible `_to_delete` folder. Skills clean their own
ordinary temporary material when no longer needed and report anything retained
for review, retry, or guarded-write recovery. Same-filesystem publication
staging keeps its separate [safe-write rules](shared/SAFE_WRITES.md#stage-complete-bytes-off-the-public-path).

No skill discards user content. A reprocess, retitle or refactor within its
workflow's authorized scope may conditionally remove an obsolete path only
after its replacement and dependent references are safely published and
verified; a later occupant always survives.
Content the user explicitly names for deletion, such as a wiki-lint
[deletion refactor](skills/wiki-lint/references/refactors.md#delete-an-entry),
is removed only through that protocol, after its inbound references are
resolved. Every wiki-lint card check (Task 1) and every wiki-build merge
keeps an entry's one definition card and removes any other card once no link
targets its block ID, quoting it in the run report.
pdf-organize may rename or move PDFs in its authorized scope but never
overwrite another file. Unrelated folders and legacy notes remain untouched.
The full path/ownership table is in
[conventions §1](shared/CONVENTIONS.md#1-vault-folder-layout).

## Where guidance lives

| Location | Owns |
|---|---|
| `skills/<name>/SKILL.md` | Discovery, scope, normal workflow and decision gates |
| `skills/<name>/references/` | Detailed rules, examples or procedures, linked where the workflow needs them |
| [shared/RUNTIME.md](shared/RUNTIME.md) | Host-independent paths, Python setup, tool fallbacks and the suggestion-log closeout gate |
| [shared/INPUT_SAFETY.md](shared/INPUT_SAFETY.md) | Untrusted filenames, titles and URLs, shell quoting, and source content as data |
| [shared/CONVENTIONS.md](shared/CONVENTIONS.md) | Shared layout, schemas, enums, naming, links and ownership |
| [shared/SAFE_WRITES.md](shared/SAFE_WRITES.md) | Exclusive creation, conditional replacement, cleanup and rollback safety |
| [shared/PROVENANCE.md](shared/PROVENANCE.md) | Internal build identity and legacy note compatibility |
| [shared/SUGGESTIONS.md](shared/SUGGESTIONS.md) | Reviews/ log attribution, open-to-fixed lifecycle, format and publication |
| `skills/<name>/scripts/` | Executable helpers and their embedded self-tests |
| `shared/scripts/` | Canonical implementations used by several skills |
| [AGENTS.md](AGENTS.md), [CLAUDE.md](CLAUDE.md) | Repository contribution instructions, with one authored copy |
| `tests/`, `tools/` | Cross-skill validation, integration checks and packaging |

Keep critical scope, authorization, preservation and validation gates visible
at the relevant action in `SKILL.md`. Put substantial conditional procedures
in references, with a clear read trigger. Define shared facts in conventions
and link to them rather than maintaining independent copies. Short reminders
at a risky step are useful; duplicated schemas, exhaustive dispatch lists and
historical explanations are harder to keep aligned.

Skill scripts import the canonical implementations in `shared/scripts/`
instead of copying their algorithms;
[conventions §5](shared/CONVENTIONS.md#5-reaching-sharedscripts-from-a-skill)
maps each module to the rule it owns. Each plugin ships only the modules its
skills use, as listed in [`tools/package-files.json`](tools/package-files.json).

## Developing and packaging

Edit the source in this repository, not an installed plugin cache. Use
Python 3.10+ and one isolated environment, using a Python release that still
receives security fixes. This floor matches the supported PyMuPDF and Pillow
versions used for untrusted documents and images. From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python tests/test_conventions.py
.venv/bin/python tools/build_plugin.py
.venv/bin/python tests/test_end_to_end.py
.venv/bin/python -m unittest discover -s tests -p 'test_knowledge_*_review.py'
.venv/bin/python tests/test_market_research_eval.py
.venv/bin/python tests/test_market_comparison.py
.venv/bin/python tests/test_market_acquire.py
.venv/bin/python tests/test_market_price_capture.py
.venv/bin/python tests/test_stock_feed.py
.venv/bin/python tests/test_stock_coverage.py
.venv/bin/python tests/test_stock_dossiers.py
.venv/bin/python tests/test_stock_acquire.py
.venv/bin/python tests/test_stock_history.py
.venv/bin/python tests/test_stock_cohorts.py
.venv/bin/python tests/test_feed_collect.py
.venv/bin/python tests/test_feed_recent.py
.venv/bin/python tests/test_rss_source.py
.venv/bin/python tests/test_rss_collect.py
.venv/bin/python tests/test_feed_media.py
.venv/bin/python tests/test_feed_attachments.py
.venv/bin/python tests/test_compatibility.py
.venv/bin/python tools/build_plugin.py --check
.venv/bin/python tests/test_provenance.py
```

The convention suite checks shared contracts, schemas, examples, command
quoting, skill routing and reachable references, and runs every bundled
script self-test. Use `-v` for passing checks or `--json` for structured
output. Every detected defect fails validation.

The end-to-end suite exercises public commands in temporary vaults: PDF
filing, figure repair, source renames, clipping reprocessing and the wiki
index/collision/lint/scan workflow, plus market-note publication, retry and outcome
continuity. It does not edit a real vault or fetch
network content. The compatibility suite checks manifests, archive contents,
execution from another working directory and platform-sensitive paths and
interpreter handling. These tests do not establish prose quality, correct
source interpretation or visually accurate crops; review those separately.

The [research evaluation workflow](tools/stock-research-evals.md) exports frozen
financial evidence cases without answer keys, grades structured responses and
compares runs under matching conditions. Its document suite compares raw financial
tables with curated evidence, separately checking source selection, extraction
and arithmetic. These public synthetic cases are regression checks; use fresh
held-out documents for generalization tests. They evaluate evidence handling,
not investment returns. Subsequent performance uses the prospective recommendation
and separate fixed-comparison journals.

When Claude Code is available, validate both manifests and skill trees:

```bash
claude plugin validate .claude-plugin/marketplace.json --strict
claude plugin validate plugins/knowledge/.claude-plugin/plugin.json --strict
claude plugin validate plugins/investments/.claude-plugin/plugin.json --strict
claude plugin validate plugins/knowledge/skills --strict
claude plugin validate plugins/investments/skills --strict
```

Author each plugin manifest in `plugins/<name>/.claude-plugin/plugin.json`,
along with that plugin's README and any plugin-specific requirements file,
and its Codex short description and default prompts in its entry of
[`tools/codex-interface.json`](tools/codex-interface.json). Those files are
inputs; all other files under `plugins/` are generated. Edit
canonical root `skills/` and `shared/` files rather than generated runtime
copies. Development tests, build tools and contributor instructions are not
included in installed packages.

[`tools/package-files.json`](tools/package-files.json) maps each plugin's
package-relative destinations to exact repository-relative source files. Shared
files have one editable source and are copied into each consuming runtime.
Add every intentional skill/shared asset to the map. The build rejects missing
inputs and unlisted generated files; when removing an asset, inspect and remove
its obsolete generated copy too. Paths must be NFC-normalized and free of
case-folding collisions. [`.gitattributes`](.gitattributes) preserves LF text and
binary archive bytes across supported hosts.

The build stages complete output and uses guarded publication to preserve later
edits. Authored input changes invalidate the plan; authored metadata is never
written as generated output. `--check` verifies both loose trees and archives
without changing them. Tests exercise isolated extracted packages so neither can
silently import from the repository or the other plugin.

Each plugin starts at **1.0.0** under its new identity and advances independently.
Before distributing a runtime change, bump every affected plugin's authored
version and validate the changes. Commit the authored inputs first, then run
`python3 tools/build_plugin.py`, validate the generated distributions, and
commit their trees and archives separately. Push both commits together. The
bundled `provenance.json` can then point to the exact source commit without
trying to embed a commit's own hash inside itself. Do not amend the source
commit after building; rebuild if its identity or authored inputs change.
Builds with uncommitted inputs remain useful for local validation but report
uncommitted provenance, not a release commit. CI needs complete Git history
to reproduce the source identity used by the build.
A shared input change requires a bump for all consuming plugins; a skill-specific
change affects only its owner. CI compares the per-plugin source maps and
versions against the appropriate Git baseline. Pushing does not refresh an
already-running session; update the installed plugins and start a fresh session
when delivering a release.

Markdown notes contain no skill-provenance footer. Build identity remains in
bundled `provenance.json`, and collection/dossier helpers retain any operational
producer records in private state. See [build identity](shared/PROVENANCE.md)
for verification and compatibility with older notes.
