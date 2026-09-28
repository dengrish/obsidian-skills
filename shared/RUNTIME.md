# Running in Codex and Claude

Read this once when using any skill in this plugin. The Markdown instructions
and Python helpers run on macOS and Linux and are shared by Codex and Claude
Code; they do not require one host's internal tool names. Installing the plugin
does not grant access to a vault, install Python packages, or enable browser tools.

`SKILL.md` gives the active workflow and its decision gates. Follow its links
when a step requires a reference; do not load every reference preemptively.
The active skill and its references define workflow-specific procedures and
scope. For a shared schema, naming, ownership or publication rule, use the
shared guide the workflow names; a workflow summary is not a competing
definition. Read [input safety](INPUT_SAFETY.md)
before handling external values or content. Do not append skill-provenance
footers to Markdown notes; [build identity](PROVENANCE.md) stays in the
plugin's bundled `provenance.json`. At closeout, follow the
[shared suggestion-log rules](SUGGESTIONS.md).

Before creating, replacing, moving, or removing a vault artifact, follow the
shared [safe-write protocol](SAFE_WRITES.md). A scan or preflight does not
reserve a pathname, and permission to edit the version that was read does not
authorize overwriting a later editor save. An explicit immutable-history rule
in the active workflow remains in force; safe replacement is a capability,
not permission to revise a historical record.

For research, use the search, page-reading and data-access capabilities
available in the active host. No particular browser, connector or host-specific
tool name is required. Follow the active workflow's evidence and coverage
rules, record material access limitations, and leave unsupported conclusions
or completion claims unresolved. Do not substitute unverified recollection
for sources or quotes.

Scheduling is external to the skills: configure recurring execution in the
active host only when the user requests it, using an explicit vault and
timezone. Installing a plugin or invoking a skill manually does not activate
a schedule. No particular host's automation tool is required.

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
- Independent plugins can use the same selected vault. Keep each workflow's
  normal output folders there; installing another plugin does not create a
  separate vault, move existing artifacts, or change their ownership. Folder
  overrides apply only where the selected workflow supports them. Follow its
  layout rules for navigation notes, source files and dated records.
- Shared helper discovery uses the installed plugin's own `shared/scripts/`.
  `OBSIDIAN_VAULT_SHARED` remains the supported explicit override, with no
  fallback from an invalid override. It is a durable helper-discovery setting,
  not a vault selector or a plugin namespace to rename. Do not edit installed
  skills or caches to configure a different user's vault. Existing on-disk
  ownership, staging and recovery markers keep their documented meanings.

Single-quote literal paths and URLs in POSIX shell examples, escaping embedded
single quotes as described in [input safety](INPUT_SAFETY.md#filenames-titles-and-urls-are-untrusted-text).
Replace placeholders before running a command.

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

Final publication staging and helper staging/recovery entries follow the
[safe-write protocol](SAFE_WRITES.md#stage-complete-bytes-off-the-public-path),
not this section.

## Use one Python environment

The helpers require Python 3.10+; use a release that is still receiving security
fixes. Examples use `python3`; substitute the full path to a suitable interpreter
supplied by the host when available. Use the same interpreter for dependency
installation and every script invocation. Standard-library-only workflows need
no package installation. Install only the active workflow's dependencies, from
the current plugin's `requirements.txt` or an optional requirements file that
workflow documents; another plugin is never a setup dependency.

A workflow using named timezones also needs the system IANA timezone database,
normally present on macOS and Linux. If that data is unavailable, report the
missing timezone data; do not substitute a fixed UTC offset that breaks
daylight-saving cutoffs.

When required dependencies are missing, create a virtual environment in an
approved, writable location outside the installed plugin cache, then use its
interpreter for both installation and every script invocation:

```bash
python3 -m venv '<venv>'
'<venv>/bin/python' -m pip install -r '<plugin>/requirements.txt'
```

Use the environment's `bin/python` interpreter with the POSIX shell examples
throughout the skills. Do not override an externally managed Python
installation or install globally as a fallback. If installation is blocked,
report the missing dependency and complete only work that does not depend on it.

### Only for PDF and image workflows

PDFs and existing image files are untrusted parser input. A workflow that
parses them names its installed-version check in its setup. Run that check
with the environment's interpreter before the first step that parses a PDF or
image, because an import-only check can accept an old vulnerable package; a
run that parses neither needs no parser packages or check. While the check
fails, run no helper that parses PDFs or images: repair the permitted
environment or use the workflow's stated fallback, and report the failed
check. Do not disable Pillow's decompression-bomb protection, and do not run
the helpers with elevated operating-system privileges.

## Use the host's available tools

Read/write files and run scripts with the host's file and shell tools. Inspect
PDFs or rendered page images with its available viewing tools. Search/fetch
source pages with its web tools. Use an available browser when
rendered content is needed and follow that browser's access rules. If the host
cannot provide the required view, report the limitation rather than claiming
the source or image was verified.

A sibling skill name in the active workflow means read its `SKILL.md` from
the same plugin and follow it, including setup, scope, and validation. It does
not require delegation, an agent framework, or a host-specific skill invocation
tool. The independently installable plugins do not require one another.
A separately installed PDF or browser skill is optional; use it only when
available and relevant.

Playwright/Chromium and OCR are optional, task-specific dependencies named by
the workflow that uses them. Check the existing environment first and install
missing packages only into the chosen virtual environment. Never purge
unrelated caches or scratch files to make room. If setup or network access is
unavailable, use that workflow's documented fallback and name what could not
be checked or converted.
