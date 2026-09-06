# obsidian

Eight skills turn PDFs, Web Clipper captures and queued research topics into
reading notes and interlinked Obsidian wiki entries, maintain the existing
wiki, and produce daily market research. They run in Codex and Claude Code and
share one set of [vault conventions](shared/CONVENTIONS.md).

## The skills

Choose by the requested result, not just the input's file type.

| Requested result | Skill | Main input and output |
|---|---|---|
| Rename, file or split PDFs | [pdf-organize](skills/pdf-organize/SKILL.md) | PDFs → organized PDFs and chapter files |
| Extract figure images | [figure-extract](skills/figure-extract/SKILL.md) | PDFs → cropped PNGs in `Sources/Images/` |
| Explain a paper, chapter, report, standard or publication notice | [paper-summarize](skills/paper-summarize/SKILL.md) | PDF → reading note in `Articles/` |
| Clean Web Clipper captures | [clipping-clean](skills/clipping-clean/SKILL.md) | raw capture → cleaned note in `Articles/` |
| Build or enrich wiki entries from new evidence | [wiki-build](skills/wiki-build/SKILL.md) | PDF or URL-origin source note → entries in `Wiki/` |
| Research and add missing requested topics | [wiki-add](skills/wiki-add/SKILL.md) | vault-root `add-to-wiki.md` → durable sources and new requested entries only |
| Audit, correct or explicitly refactor existing wiki entries | [wiki-lint](skills/wiki-lint/SKILL.md) | existing `Wiki/`, its cited sources or an exact producer mapping → scoped repairs, links, parents and MOCs |
| Research premarket catalysts and developing momentum | [market-research](skills/market-research/SKILL.md) | current market evidence and earlier analyses → brief daily note in `Investments/` |

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
buying opportunity is a valid result. Daily notes use
`Investments/YYYY-MM-DD-market-research.md` and the skill's
[note format](skills/market-research/references/note-format.md); they are not
Wiki entries or source notes for automatic wiki-build intake. It researches
opportunities without reviewing current holdings, recommending sales, placing
trades, or rewriting earlier daily records.
Its optional [data retrieval helpers](skills/market-research/references/data-access.md)
cover SEC filings/facts, Nasdaq directories/halts, Alpaca prices/actions/sessions,
and Alpha Vantage news/earnings calendars. Setup can be checked offline; keyed
sources use local environment variables, with explicit feed and coverage limits.

## Codex and Claude

The same eight skills run in **Codex and Claude Code** on **macOS and Linux**,
including their desktop surfaces when local files and shell execution are
available. This is a skill package, not an Obsidian community plugin or an MCP
server. Ordinary chats
without filesystem access cannot run the vault workflow.

Invoke the Wiki skills as `obsidian:wiki-build`, `obsidian:wiki-add`, and
`obsidian:wiki-lint`. Suggestion logs use current skill names under `Reviews/`
and follow the [shared protocol](shared/SUGGESTIONS.md). MOCs are fully generated
nested outlines at `MOCs/<discipline>.md`, without marker comments. Unexpected
root `<discipline>-moc.md` files are preserved and reported, not moved or
replaced during routine maintenance.

| Purpose | Codex | Claude Code |
|---|---|---|
| Contributor instructions | `AGENTS.md` | `CLAUDE.md` imports `AGENTS.md` |
| Plugin manifest | generated `.codex-plugin/plugin.json` | authored `.claude-plugin/plugin.json` |
| Marketplace | `.claude-plugin/marketplace.json` (compatibility format) | same catalog |
| Runtime instructions and helpers | `skills/` and `shared/` | the same files |

`CLAUDE.md` contains only `@AGENTS.md`, the
[documented Claude import](https://code.claude.com/docs/en/memory#agentsmd).
This avoids duplicated instructions and symlink requirements. These files
govern contributions to the repository; installed skills explicitly link
their [runtime setup](shared/RUNTIME.md) instead of depending on either host
to load repository instructions in the user's vault.

Install the **whole repository** through its marketplace; copying only a
`SKILL.md` loses references, sibling skills and shared Python helpers.
The Codex CLI accepts the Claude marketplace format (verified with Codex CLI
0.147.0), so both hosts use one catalog.

```bash
# Codex
codex plugin marketplace add https://github.com/dengrish/obsidian-skills.git
codex plugin add obsidian@obsidian-skills

# Claude Code
claude plugin marketplace add dengrish/obsidian-skills
claude plugin install obsidian@obsidian-skills
```

For local Claude development, `claude --plugin-dir .` loads this checkout.
Start a fresh task/session after installing or updating. Installation does
not install Python dependencies or grant vault access; follow the runtime
guide. Shell examples use POSIX syntax.

Recurring market research is configured separately in the active host when
requested; installing or manually running the skill does not activate a job.
Its default daily research time is 09:00 `America/New_York`, following New York's
daylight-saving changes. Closed-market days produce a short status note.

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
`plurals.py` (English singularization),
`yaml_scalars.py` (decoded metadata), `figure_state.py` (figure ownership and
review sidecars), `vault_artifacts.py` (portable PDF and source-figure
inventories), `organism_names.py` (Organism title/name classification),
`entry_structure.py` (shared sentence, opener, answer-surface, and flashcard
structure checks), `introduced_aliases.py`
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
.venv/bin/python tests/test_end_to_end.py
.venv/bin/python tools/build_plugin.py
.venv/bin/python tests/test_compatibility.py
.venv/bin/python tools/build_plugin.py --check
```

The convention suite checks shared contracts, schemas, examples, command
quoting, skill routing and reachable references, and runs every bundled
script self-test. Use `-v` for passing checks or `--json` for structured
output. Every detected defect fails validation.

The end-to-end suite exercises public commands in temporary vaults: PDF
filing, figure repair, source renames, clipping reprocessing and the wiki
index/collision/lint/scan workflow. It does not edit a real vault or fetch
network content. The compatibility suite checks manifests, archive contents,
execution from another working directory and platform-sensitive paths and
interpreter handling. These tests do not establish prose quality, correct
source interpretation or visually accurate crops; review those separately.

When Claude Code is available, also run:

```bash
claude plugin validate .claude-plugin/plugin.json
claude plugin validate .claude-plugin/marketplace.json
claude plugin validate skills
```

The plugin-manifest command may report that the repository-root `CLAUDE.md` is
not loaded as plugin context. That file exists for contributors working on this
repository and imports `AGENTS.md`; runtime plugin guidance lives in the eight
skills. The warning is expected, while the marketplace and skill validations
should pass cleanly (including with `--strict`).

Author common metadata in `.claude-plugin/plugin.json`. The build command
generates `.codex-plugin/plugin.json` and `obsidian.plugin`, including all
references and shared helpers while excluding local environments and Git
state. Completed outputs are staged on the destination filesystem and replace
only the exact generated files observed before publication; a late edit or
occupant stops publication unchanged. `--check` detects stale generated files
without rewriting them.

[`tools/package-files.txt`](tools/package-files.txt) is the exact authored-file
inventory for the archive. Add an intentional new reference, script, or asset
there; an unlisted or missing file under a shipped tree makes the build fail.
This supports arbitrary asset types without silently packaging editor residue
or secrets. Archive paths must also be NFC-normalized and free of case-folding
collisions. [`.gitattributes`](.gitattributes) keeps tracked text at LF so the
same revision produces the same archive from macOS and Linux clones.

For a release, bump the authored manifest's version, validate, rebuild, then
commit source and generated files together before pushing. An explicit
version is a cache key: pushing changed code with the same version does not
deliver a Claude plugin update. See
[Claude version management](https://code.claude.com/docs/en/plugins-reference#version-management).
Refresh the marketplace and update/reinstall the plugin in each host afterward;
a push does not refresh an already-running session.
