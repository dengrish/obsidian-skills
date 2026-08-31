# obsidian

Six skills turn PDFs and Web Clipper captures into reading notes and
interlinked Obsidian wiki entries, then maintain the existing wiki. They run
in Codex and Claude Code and share one set of
[vault conventions](shared/CONVENTIONS.md).

## The skills

Choose by the requested result, not just the input's file type.

| Requested result | Skill | Main input and output |
|---|---|---|
| Rename, file or split PDFs | [pdf-organizer](skills/pdf-organizer/SKILL.md) | PDFs → organized PDFs and chapter files |
| Extract figure images | [pdf-figure-extractor](skills/pdf-figure-extractor/SKILL.md) | PDFs → cropped PNGs in `Sources/Images/` |
| Explain a research paper's findings | [paper-summarizer](skills/paper-summarizer/SKILL.md) | PDF → summary in `Articles/` |
| Clean Web Clipper captures | [clipping-processor](skills/clipping-processor/SKILL.md) | raw capture → cleaned note in `Articles/` |
| Build or enrich wiki entries from a source | [wiki-builder](skills/wiki-builder/SKILL.md) | PDF or cleaned clipping → entries in `Wiki/` |
| Audit, link or organize existing wiki entries | [wiki-linter](skills/wiki-linter/SKILL.md) | existing `Wiki/` → repairs, links, parents and root-level MOCs |

A PDF attached without a stated goal has no default workflow; ask what result
the user wants. An inbox-wide request splits captured `.md` files and `.pdf`
files between the two intake skills. Other file types are named in the report
and left in place.

## The pipeline

The routes branch; a document does not have to pass through every skill.

```text
Inbox/*.pdf → pdf-organizer → Sources/PDFs/
                                ├─ pdf-figure-extractor → Sources/Images/
                                ├─ paper-summarizer → Articles/ summary
                                └─ wiki-builder → Wiki/

Inbox/*.md → clipping-processor → Articles/ cleaned clipping
                                     └─ wiki-builder → Wiki/

Existing Wiki/ → wiki-linter → entry repairs, links, parents, MOCs and proposals
```

Figure extraction supplies images to paper-summarizer and wiki-builder.
Both paper-summarizer and wiki-builder read the **original PDF**; the summary
is a finished reading note, not a source for wiki-builder. A cleaned clipping
is itself the source and can be used directly.

**Organize PDFs before deriving filenames and links from them.** Later renames
must carry the dependent notes, figures, references and sidecars together,
using pdf-organizer's reviewed plan and any required authorization. The
[source-filename contract](shared/CONVENTIONS.md#1a-source-file-names-and-why-pdf-organizer-runs-first)
defines that boundary. A summary is not required before building wiki entries,
and wiki-linter can run independently of any source-processing task.

wiki-builder adds source-supported content only to the entries in its current
run. wiki-linter owns retrospective work across the existing wiki. Their
[linking ownership](shared/CONVENTIONS.md#9-ownership-split-for-linking) prevents
later source merges from reversing deliberate maintenance decisions.

## Codex and Claude

The same six skills run in **Codex and Claude Code**, including their desktop
surfaces when local files and shell execution are available. This is a skill
package, not an Obsidian community plugin or an MCP server. Ordinary chats
without filesystem access cannot run the vault workflow.

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
guide. Shell examples use POSIX syntax (macOS, Linux or WSL); native PowerShell
commands need translation.

## Vault layout

`<vault>` is the user-selected vault or an unambiguous workspace vault. Resolve
it and any per-run path overrides through [RUNTIME.md](shared/RUNTIME.md).

```text
<vault>/
├── Inbox/                    raw clippings and incoming PDFs
├── Articles/                 cleaned clippings and paper summaries
├── Sources/
│   ├── PDFs/                 organized PDFs
│   │   └── <Work>/           a split book's chapter PDFs
│   └── Images/               flat folder for extracted/downloaded images
├── Wiki/                     entity notes, scanned recursively
├── <discipline>-moc.md       maps of content at the vault root
└── *-suggestions.md          the linter's three proposal logs
```

PDFs move out of `Inbox/`; raw clippings stay as the record of what was
captured. The clipping dedup index determines whether a capture was processed.
Both note writers share `Articles/` and check provenance before claiming an
existing note: `sources:` item 1 identifies its origin. MOCs and proposal logs
stay outside `Wiki/` so they are not treated as entries.

No skill deletes user files. A reprocess may remove its own old note after
safely publishing a renamed replacement; pdf-organizer may rename or move the
PDFs in its authorized scope but never overwrite another file. Unrelated
folders and legacy notes remain untouched. The full path/ownership table is
in [conventions §1](shared/CONVENTIONS.md#1-vault-folder-layout).

## Where guidance lives

| Location | Owns |
|---|---|
| `skills/<name>/SKILL.md` | Discovery, scope, normal workflow and decision gates |
| `skills/<name>/references/` | Detailed rules, examples or procedures, linked where the workflow needs them |
| [shared/RUNTIME.md](shared/RUNTIME.md) | Host-independent paths, Python setup and tool fallbacks |
| [shared/CONVENTIONS.md](shared/CONVENTIONS.md) | Shared layout, schemas, enums, naming, links and ownership |
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

The shared implementations are `slugify.py` (wiki slugs), `naming.py` (source
filenames and book identity), `plurals.py` (English singularization),
`yaml_scalars.py` (decoded metadata), `figure_state.py` (figure ownership and
review sidecars), and `plugin_paths.py` (shared-module lookup). Skill scripts
import these instead of copying their algorithms.

## Developing and packaging

Edit the source in this repository, not an installed plugin cache. Use
Python 3.9+ and one isolated environment. From the repository root:

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
output. Registered unresolved defects appear as `PENDING`, never as passes.

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

Author common metadata in `.claude-plugin/plugin.json`. The build command
generates `.codex-plugin/plugin.json` and `obsidian.plugin`, including all
references and shared helpers while excluding local environments and Git
state. `--check` detects stale generated files without rewriting them.

For a release, bump the authored manifest's version, validate, rebuild, then
commit source and generated files together before pushing. An explicit
version is a cache key: pushing changed code with the same version does not
deliver a Claude plugin update. See
[Claude version management](https://code.claude.com/docs/en/plugins-reference#version-management).
Refresh the marketplace and update/reinstall the plugin in each host afterward;
a push does not refresh an already-running session.
