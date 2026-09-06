# Running in Codex and Claude

Read this once when using any skill in this plugin. The Markdown instructions
and Python helpers run on macOS and Linux and are shared by Codex and Claude
Code; they do not require one host's internal tool names. Installing the plugin
does not grant access to a vault, install Python packages, or enable browser tools.

When wiki-add or market-research needs web research, use the search and
page-reading capabilities available in the active host; no particular browser, connector or host-specific
tool name is required. market-research also provides optional read-only
[data retrieval helpers](../skills/market-research/references/data-access.md)
and uses available market-data tools, with source and observation times
recorded under its research method. If
adequate evidence cannot be accessed, report the limitation: wiki-add leaves
affected queue items unchecked; market-research records the missing evidence
without making an unsupported investment assessment. Do not substitute
unverified recollection for sources or quotes.

`SKILL.md` gives the active workflow and its decision gates. Follow its links
when a step requires a reference; do not load every reference preemptively.
[`CONVENTIONS.md`](CONVENTIONS.md) owns shared layout, naming, metadata and
ownership rules. Read its §§1b–1c safety rules before handling external
values or content; consult §1's layout only when resolving folders or routes,
then follow the active workflow's links for other subjects. Its §§5 and 10
concern development and troubleshooting. At closeout, read
[`SUGGESTIONS.md`](SUGGESTIONS.md) for the shared `Reviews/` logs: record only
evidenced issues in the owning skill or consumed producer's log, remove
specifically verified resolutions, and make no log writes on a report-only run.

Before creating, replacing, moving, or removing a vault artifact, follow the
shared [safe-write protocol](SAFE_WRITES.md). A scan or preflight does not
reserve a pathname, and permission to edit the version that was read does not
authorize overwriting a later editor save.

wiki-add reads `add-to-wiki.md` at the selected vault root. Its
[research guide](../skills/wiki-add/references/research.md) distinguishes
temporary research material from durable sources: publish and verify any new
source notes, organized PDFs and selected images before the Wiki entries that
cite them, and verify entries before checking off queue items. Existing source
notes, images and requested Wiki identities are reused or skipped without edits.

market-research reads earlier daily analyses and publishes to `Investments/`
under its own [note format](../skills/market-research/references/note-format.md):
a short buying-opportunity brief followed by a detailed research record.
It does not evaluate current holdings or recommend sales. Social research uses
only accessible sources; no social feed or comprehensive monitoring is assumed.
These notes are separate from Wiki entries, source notes, and MOCs; earlier
dated records remain unchanged. Scheduling is external to the skill: configure
recurring execution in the active host only when the user requests it, using
an explicit vault and timezone. Installing the plugin or invoking the skill
manually does not activate a schedule. The shared workflow does not require a
particular host's automation tool.

## Resolve the paths before acting

- `<skill>` is the absolute directory containing the loaded `SKILL.md`.
- `<plugin>` is two directories above `<skill>`, containing `skills/` and
  `shared/`. Resolve sibling skills and references from this directory, never
  from the vault or a guessed host cache path. Install the whole plugin tree.
- `<vault>` is the vault explicitly selected by the user or already established
  in the task. Otherwise use the current workspace, or an ancestor of the
  named input, only when it is unambiguously an Obsidian vault (for example,
  it contains `.obsidian/`). For a workflow that needs vault outputs, ask which
  vault to use if several qualify or none does. Workflows that explicitly
  support standalone PDF input/output paths may run without a vault; keep those
  paths and do not select or create a vault solely for suggestion logs. Never
  create a vault at a remembered home path.
- wiki-lint writes discipline navigation notes to `<vault>/MOCs/<discipline>.md`
  and links them as `[[MOCs/<discipline>]]`. Each specific-discipline MOC
  is a fully generated nested outline; `MOCs/misc.md` is the flat title-ordered
  list for Wiki entries whose sole discipline tag is `"#misc"`. Every misc member
  receives `[[MOCs/misc]]` as parent during wiki-lint; producers still write
  `parents: []` for new entries and assign `"#misc"` when no specific
  discipline fits. Wiki tag lists must be nonempty; source-note schemas keep
  their own blank-tag rules. All MOCs have no marker comments, H1, or
  frontmatter. Task 3 snapshots and regenerates its whole file within the
  authorized closure; unknown files and suggestion logs are not generated
  MOCs. Keep this folder outside `Wiki/`. An authorized misc refresh clears
  a zero-member list to empty and retains the file; an explicit request may
  create empty misc.
  Before creation, reject a non-directory or symlink occupant at `MOCs/` and
  portable-equivalent folder collisions; never overwrite or follow one to
  create navigation artifacts. Unexpected root `<discipline>-moc.md` notes are
  preserved and reported; do not create duplicate navigation notes or move
  existing files during plugin setup.
- Individual folder overrides apply to the requested run where the selected
  workflow supports them; market-research fixes its output at `Investments/`
  under the selected vault. Confirm existing
  inputs and keep the skills' normal output folders under the selected vault.
  Do not edit installed skills to configure a different user's vault.

Single-quote literal paths and URLs in POSIX shell examples, escaping embedded
single quotes as described in `CONVENTIONS.md` §1b. Replace placeholders before
running a command.

### One owned scratch directory per run

`<scratch>` is the current run's private `.obsidian-skills-tmp-<unique-id>`
directory under system temporary storage, or an approved writable base that
resolves **outside the vault**. Confirm that boundary before creating it,
including when temporary storage is overridden. Create it once when needed,
then reuse its returned absolute path throughout the active run and across
skills; never reuse another run's directory. For example:

```bash
python3 - <<'PY'
import tempfile
print(tempfile.mkdtemp(prefix=".obsidian-skills-tmp-"))
PY
```

For an approved alternative base, pass it as `mkdtemp`'s `dir` argument. Put
workflow drafts, scan reports, page renders, crops, decrypted working copies,
and temporary drivers under `<scratch>`, using unique child paths when a step
needs an empty directory. Do not create visible vault scratch folders such as
`_to_delete`, `tmp`, or `Scratch`, and do not copy plugin trees or shipped
scripts into scratch; invoke the selected plugin's actual helpers. A temporary
driver may import those helpers from their original paths.

Automatically remove this run's ordinary scratch files once they are no longer
needed, after required publication and verification. Remove the owned run
directory when nothing must remain. Preserve material still needed for a retry,
pending review, or a user-requested deliverable, and preserve every staging or
recovery path named by a failed guarded write until its state is reconciled.
Report any residual paths and why they remain. Never delete original sources,
unknown additions, another run's files, a shared temporary base, or unrelated
caches. Dependencies and reusable virtual environments belong outside disposable
scratch unless deliberately created as disposable for this run.

Helper-managed internal temporary files and existing hidden staging/recovery
names retain their own guards and cleanup rules. Final publication staging is
the narrow exception to ordinary scratch staying outside the vault: it may
need a hidden directory beside the resolved real destination on its filesystem,
always outside scanned output folders. Do not relocate it to `<scratch>` when
that would cross filesystems or discard recovery state.

Guarded publication of regular files also needs hard links on the vault's
filesystem and a final staging directory on that same filesystem. This is a
filesystem capability, not an operating-system promise: FAT/exFAT and some
network mounts do not support it. `atomic_move.py` reports that condition as
`LinkUnavailable`; keep the staged result and report the limitation instead of
falling back to an overwrite-capable copy or cross-device move. See
[`SAFE_WRITES.md`](SAFE_WRITES.md) for the recovery rules.

## Use one Python environment

The helpers require Python 3.10+; use a release that is still receiving security
fixes. Examples use `python3`; substitute the full path to a suitable interpreter
supplied by the host when available. Python 3.9 is end-of-life, and the supported
PyMuPDF and Pillow security floors require Python 3.10 or newer. Wiki, clipping,
and market-research helpers use the standard library; PDF reading/splitting
needs `pypdf`, and figure extraction needs PyMuPDF and Pillow.
`requirements.txt` at the plugin root supplies the full set.
market-research also needs the system IANA timezone database for
`America/New_York`, normally present on macOS and Linux. If unavailable, report
the missing timezone data; do not substitute a fixed UTC offset that breaks
daylight-saving cutoffs.

PDFs and existing image files are untrusted parser input. An import-only check
can silently accept an old vulnerable package, so verify installed versions as
well. Do not disable Pillow's decompression-bomb protection, and do not run the
helpers with elevated operating-system privileges. The minimum versions below
mirror `requirements.txt`; keep the two locations synchronized.

If dependencies are missing or below these floors, create a virtual environment
in an approved, writable location outside the installed plugin cache, then use
its interpreter for both installation and every script invocation:

```bash
python3 -m venv '<venv>'
'<venv>/bin/python' -m pip install -r '<plugin>/requirements.txt'
'<venv>/bin/python' - <<'PY'
import re
import sys
from importlib.metadata import PackageNotFoundError, version

minimums = {
    "pypdf": (6, 16, 1),
    "PyMuPDF": (1, 28, 0),
    "Pillow": (12, 3, 0),
}
problems = []
if sys.version_info < (3, 10):
    problems.append("Python 3.10 or newer is required")
for package, minimum in minimums.items():
    try:
        installed = version(package)
    except PackageNotFoundError:
        problems.append(f"{package} is not installed")
        continue
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", installed)
    release = tuple(map(int, match.groups())) if match else ()
    suffix = installed[match.end():].lower() if match else ""
    prerelease_at_floor = (
        release == minimum
        and suffix.startswith(("a", "b", "rc", ".dev", "dev"))
    )
    if release < minimum or prerelease_at_floor:
        problems.append(
            f"{package} {installed} is below {'.'.join(map(str, minimum))}"
        )
if problems:
    raise SystemExit("dependency check failed: " + "; ".join(problems))

import pypdf
import PIL
import pymupdf
PY
```

Use the environment's `bin/python` interpreter with the POSIX shell examples
throughout the skills.
Do not override an externally managed Python installation or install globally
as a fallback. If installation is blocked, report the missing dependency and
complete only work that does not depend on it.

## Use the host's available tools

Read/write files and run scripts with the host's file and shell tools. Inspect
PDFs or rendered page images with its available viewing tools. Search/fetch
source pages with its web tools; `web_fetch` in older examples means that
capability, not a required callable tool name. Use an available browser when
rendered content is needed and follow that browser's access rules. If the host
cannot provide the required view, report the limitation rather than claiming
the source or image was verified.

A sibling skill name means read its `SKILL.md` from the same plugin and follow
it, including setup, scope, and validation. It does not require delegation,
an agent framework, or a host-specific skill invocation tool. A separately
installed PDF or browser skill is optional; use it only when available.

Playwright/Chromium and OCR are optional, task-specific dependencies. The
Lottie conversion recipe needs Playwright, Pillow, and a usable browser; check
the existing environment first and install missing packages only into the
chosen virtual environment. Never purge unrelated caches or scratch files to
make room. If setup or network access is unavailable, use the documented
poster/link fallback and name what could not be checked or converted.
