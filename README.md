# Obsidian skills

Eight skills are packaged as two independently installable plugins for Codex
and Claude Code. Both can use the same selected Obsidian vault:

| Plugin | Purpose | Namespace |
|---|---|---|
| **knowledge** | Organize sources and maintain a knowledge base | `knowledge:` |
| **investments** | Research buying opportunities and evaluate earlier recommendations | `investments:` |

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
| Build or enrich wiki entries from new evidence | [knowledge:wiki-build](skills/wiki-build/SKILL.md) | PDF or URL-origin source note → entries in `Wiki/` |
| Research and add missing requested topics | [knowledge:wiki-add](skills/wiki-add/SKILL.md) | vault-root `add-to-wiki.md` → durable sources and new requested entries only |
| Audit, correct or explicitly refactor existing wiki entries | [knowledge:wiki-lint](skills/wiki-lint/SKILL.md) | existing `Wiki/`, its cited sources or an exact producer mapping → scoped repairs, links, parents and MOCs |
| Research market catalysts and developing momentum | [investments:market-research](skills/market-research/SKILL.md) | current market evidence and earlier analyses → brief daily note in `Investments/` |

A PDF attached without a stated goal has no default workflow; ask what result
the user wants. An inbox-wide request splits captured `.md` files and `.pdf`
files between the two intake skills. Other file types are named in the report
and left in place.

## The pipeline

The routes branch; a document does not have to pass through every skill.

```text
Inbox/*.pdf → pdf-organize → Sources/PDFs/
                                ├─ figure-extract → Sources/Images/
                                ├─ paper-summarize → Articles/ reading note
                                └─ wiki-build → Wiki/

Inbox/*.md → clipping-clean → Articles/ cleaned clipping
                                     └─ wiki-build → Wiki/

add-to-wiki.md → wiki-add → durable sources → missing requested entries in Wiki/

Existing Wiki/ → wiki-lint → entry repairs, links, parents, MOCs and proposals

Market evidence + prior Investments/ notes → market-research → daily research note
```

Figure extraction supplies images to paper-summarize and wiki-build.
Both paper-summarize and wiki-build read the **original PDF**; the summary
is a finished reading note, not a source for wiki-build. A cleaned clipping
is itself the source and can be used directly. wiki-add can reuse existing
sources, acquire PDFs through pdf-organize, or save a clearly marked,
agent-written research extract for each web page in `Articles/`; these extracts
are durable evidence, not full-text captures or multi-page summaries. Its
[research guide](skills/wiki-add/references/research.md) owns that procedure.

**Organize PDFs before deriving filenames and links from them.** Later renames
must carry the dependent notes, figures, references and sidecars together,
using pdf-organize's reviewed plan and any required authorization. The
[source-filename contract](shared/CONVENTIONS.md#1a-source-file-names-and-why-pdf-organize-runs-first)
defines that boundary. A summary is not required before building wiki entries,
and wiki-lint can run independently of any source-processing task.

wiki-build adds source-supported content only to the entries in its current
run. wiki-lint owns retrospective work across the existing wiki. Their
[linking ownership](shared/CONVENTIONS.md#9-ownership-split-for-linking) prevents
later source merges from reversing deliberate maintenance decisions.
For a named existing entry, wiki-lint may correct it from sources it already
cites or carry out an explicitly requested structural or producer-mapped
repair. Enriching an existing entry with new-source evidence still belongs to
wiki-build.

wiki-add is the queue-first, create-only route. An existing requested identity
is skipped without auditing or editing it. New entries use
builder's writing rules with `parents: []` and `read: false`, but wiki-add never
adds an unrequested entity to satisfy a builder audit. It checks off only
successfully published or already-existing queue items; uncertain or blocked
items remain unchecked. Existing-entry enrichment remains wiki-build's job.

market-research finds long-only buying opportunities in liquid U.S.-listed
stocks over a 3–12 month momentum horizon. It combines repeatable announcement
and price screens with verified business evidence and bounded social research.
Each note has a short decision brief and a detailed research record for future
runs, including thesis changes, daily checks of two-week and 1/3/6/12/24/60-month
outcomes and monthly summaries of evidence-backed lessons. Quoted recommendation prices stay
separate from the fixed hypothetical entry convention. No qualifying
buying opportunity is a valid result. Scheduled and user-requested manual editions
use the skill's [note format](skills/market-research/references/note-format.md) in
`Investments/`, sharing one thesis and outcome history; they are not
Wiki entries or source notes for automatic wiki-build intake. It researches
opportunities without reviewing current holdings, recommending sales, placing
trades, or rewriting earlier records.
Its optional [data retrieval helpers](skills/market-research/references/data-access.md)
cover SEC filings/facts, Nasdaq directories/halts, Alpaca prices/actions/sessions/news,
Alpha Vantage news/earnings calendars, and FRED macro series/release dates. Setup
can be checked offline; keyed sources use local environment variables or an
explicit private JSON file passed to the bundled script with `--credentials-file`.
Credentials remain outside the plugin, repository and vault; no separate local
credential launcher is required. Retrieval retains explicit feed and coverage limits.

The [offline screener](skills/market-research/references/screening.md) calculates
calendar-month momentum, benchmark-relative returns, moving averages and a
clearly labeled daily liquidity proxy from saved Alpaca/calendar responses.
The research method adds bounded thematic discovery and checks decision-critical
claims and earnings comparisons before publication. Optional exact-accession SEC
filing extraction uses pinned EdgarTools as a local parser, without delegating
network requests or installing another framework. Core retrieval, screening and
note handling remain standard-library-only.

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

Invoke skills as `knowledge:wiki-build`, `knowledge:wiki-add`,
`knowledge:wiki-lint`, or `investments:market-research`. Start a fresh
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

Update scheduled skill references from `obsidian:market-research` to
`investments:market-research` only after the new installed plugin is available.
Keep the selected vault, credentials file, interpreter and schedule unchanged;
shared-helper overrides must point to the selected investments installation.
The default daily edition remains 08:30 `America/Los_Angeles` / 11:30
`America/New_York`, including closed-market days and daylight-saving changes.
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
├── Articles/                 clippings, PDF reading notes and research extracts
├── Sources/
│   ├── PDFs/                 organized PDFs
│   │   └── <Work>/           a split book's chapter PDFs
│   └── Images/               flat folder for extracted/downloaded images
├── Wiki/                     entity notes, scanned recursively
├── Investments/              dated market research, separate from the Wiki
├── MOCs/                     generated navigation outlines
│   ├── <discipline>.md       e.g. machine-learning.md (no -moc suffix)
│   └── misc.md               Wiki entries tagged #misc
├── add-to-wiki.md            wiki-add's requested-topic queue
└── Reviews/                  open suggestion logs
    ├── <current-skill>-suggestions.md  one per skill
    └── wiki-notes-suggestions.md      note-content backlog
```

PDFs move out of `Inbox/`; raw clippings stay as the record of what was
captured. The clipping dedup index determines whether a capture was processed.
All three source-note producers share `Articles/`: `sources:` item 1 identifies
the origin used for deduplication, and a body marker distinguishes wiki-add's
research extracts from full-text clippings. wiki-add reuses suitable existing
source notes and images without overwriting them. Market research, MOCs, proposal
logs and the topic queue stay outside `Wiki/` so they are not treated as entries. MOC
links and root parents use `[[MOCs/<discipline>]]`, so a same-named entity
can coexist in `Wiki/`. Generated outline links use qualified entry paths
such as `[[Wiki/machine-learning|Machine learning]]`. Each recognized discipline
MOC is generated as a whole note: a nested bullet outline without marker
comments, H1, or frontmatter. Task 3 reads the existing outline for continuity,
regenerates from current entries, and skips unchanged output. Obsolete MOC
markers or prose need no separate formatting approval; safe snapshots still
protect later edits and unrelated files. Wiki entries require a nonempty tag list. When no specific discipline fits,
use `"#misc"` alone; these entries appear alphabetically by title in
`MOCs/misc.md` with parent `[[MOCs/misc]]`. Blank, missing, malformed, or mixed
misc/specific tags remain QC errors until resolved. New entries from wiki-build/wiki-add still start with
`parents: []`; wiki-lint supplies their hierarchy placement.

Every skill can record evidenced improvements in its own suggestion log or
the log of a producer whose output it used. Verified resolutions are removed
automatically; logs hold only open issues. Routine runs do not edit skill
sources. An explicit plugin review fixes source issues with validation and Git
history instead of creating dated review reports; existing reports remain
untouched. The [shared suggestion protocol](shared/SUGGESTIONS.md) owns these
rules and log format.

Workflow scratch lives in a hidden `.obsidian-skills-tmp-<unique-id>` directory
outside the vault, never a visible `_to_delete` folder. Skills clean their own
ordinary temporary material when no longer needed and report anything retained
for review, retry, or guarded-write recovery. Same-filesystem publication
staging keeps its separate safety rules; see [runtime guidance](shared/RUNTIME.md#one-owned-scratch-directory-per-run).

No skill discards user content. An authorized reprocess or refactor may
conditionally remove an obsolete path only after its replacement and dependent
references are safely published and verified; a later occupant always survives.
pdf-organize may rename or move PDFs in its authorized scope but never
overwrite another file. Unrelated folders and legacy notes remain untouched.
The full path/ownership table is in
[conventions §1](shared/CONVENTIONS.md#1-vault-folder-layout).

## Where guidance lives

| Location | Owns |
|---|---|
| `skills/<name>/SKILL.md` | Discovery, scope, normal workflow and decision gates |
| `skills/<name>/references/` | Detailed rules, examples or procedures, linked where the workflow needs them |
| [shared/RUNTIME.md](shared/RUNTIME.md) | Host-independent paths, Python setup and tool fallbacks |
| [shared/CONVENTIONS.md](shared/CONVENTIONS.md) | Shared layout, schemas, enums, naming, links and ownership |
| [shared/SAFE_WRITES.md](shared/SAFE_WRITES.md) | Exclusive creation, conditional replacement, cleanup and rollback safety |
| [shared/PROVENANCE.md](shared/PROVENANCE.md) | Exact skill identity on generated notes and preservation of creator attribution |
| [shared/SUGGESTIONS.md](shared/SUGGESTIONS.md) | Reviews/ log attribution, open-issue lifecycle, format and publication |
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

The shared implementations are `slugify.py` (wiki slugs), `atomic_move.py`
(exclusive moves and verified regular-file publication/removal), `naming.py`
(source filenames and book identity),
`plurals.py` (English singularization), `note_provenance.py` (verified bundle identity and note attribution),
`yaml_scalars.py` (decoded metadata), `portable_names.py` (portable file identity), `figure_state.py` (figure ownership and
review sidecars), `vault_artifacts.py` (portable PDF and source-figure
inventories), `organism_names.py` (Organism title/name classification),
`entry_structure.py` (shared Wiki text, image and source-identity parsing,
plus sentence, opener, answer-surface and flashcard checks), `introduced_aliases.py`
(body-introduced alias candidates), `code_typography.py` (literal prose shapes
that require backticks), `equation_coverage.py` (a conservative missing-display
equation candidate shared by both Wiki skills), `markdown_tables.py` (GFM table
spans and caption checks), and `plugin_paths.py` (shared-module lookup). Skill
scripts import these instead of copying their algorithms.

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
.venv/bin/python tests/test_market_research_eval.py
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

The [research evaluation workflow](tools/market-research-evals.md) exports frozen
financial evidence cases without answer keys, grades structured responses and
compares runs under matching conditions. Its synthetic cases are regression
checks; use fresh held-out documents for generalization tests. These measurements
evaluate research quality, not investment returns. Subsequent recommendation
performance continues to use the unchanged prospective outcome journal.

When Claude Code is available, validate both manifests and skill trees:

```bash
claude plugin validate .claude-plugin/marketplace.json --strict
claude plugin validate plugins/knowledge/.claude-plugin/plugin.json --strict
claude plugin validate plugins/investments/.claude-plugin/plugin.json --strict
claude plugin validate plugins/knowledge/skills --strict
claude plugin validate plugins/investments/skills --strict
```

Author each plugin manifest in `plugins/<name>/.claude-plugin/plugin.json`,
along with that plugin's README and any plugin-specific requirements file.
Those files are inputs; all other files under `plugins/` are generated. Edit
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

Generated Markdown notes record the producing skill, plugin version, source
commit link and verified runtime fingerprint under the shared
[provenance contract](shared/PROVENANCE.md). Existing notes are not backfilled
with a guessed creator, and unchanged notes stay unchanged.
