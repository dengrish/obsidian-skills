# Running in Codex and Claude

Read this once when using any skill in this plugin. The Markdown instructions
and Python helpers are shared by Codex and Claude Code; they do not require
one host's internal tool names. Installing the plugin does not grant access
to a vault, install Python packages, or enable browser tools.

`SKILL.md` gives the active workflow and its decision gates. Follow its links
when a step requires a reference; do not load every reference preemptively.
[`CONVENTIONS.md`](CONVENTIONS.md) owns shared layout, naming, metadata and
ownership rules. Read its §§1b–1c safety rules before handling external
values or content; consult §1's layout only when resolving folders or routes,
then follow the active workflow's links for other subjects. Its §§5 and 10
concern development and troubleshooting.

Before creating, replacing, moving, or removing a vault artifact, follow the
shared [safe-write protocol](SAFE_WRITES.md). A scan or preflight does not
reserve a pathname, and permission to edit the version that was read does not
authorize overwriting a later editor save.

## Resolve the paths before acting

- `<skill>` is the absolute directory containing the loaded `SKILL.md`.
- `<plugin>` is two directories above `<skill>`, containing `skills/` and
  `shared/`. Resolve sibling skills and references from this directory, never
  from the vault or a guessed host cache path. Install the whole plugin tree.
- `<vault>` is the vault explicitly selected by the user or already established
  in the task. Otherwise use the current workspace, or an ancestor of the
  named input, only when it is unambiguously an Obsidian vault (for example,
  it contains `.obsidian/`). If several vaults qualify or none does, ask which
  vault to use before writing. Never create a vault at a remembered home path.
- Individual folder overrides apply to the requested run. Confirm existing
  inputs and keep the skills' normal output folders under the selected vault.
  Do not edit installed skills to configure a different user's vault.

Single-quote literal paths and URLs in POSIX shell examples, escaping embedded
single quotes as described in `CONVENTIONS.md` §1b. Replace placeholders before
running a command. Create scratch files in a unique per-run temporary directory
**outside the vault**; `/tmp/` examples are illustrative, not shared filenames
to reuse concurrently. Page renders, crops, decrypted working copies, and other
review intermediates must not become vault content merely because the run was
interrupted.

Guarded publication of regular files also needs hard links on the vault's
filesystem and a final staging directory on that same filesystem. This is a
filesystem capability, not an operating-system promise: FAT/exFAT and some
network mounts do not support it. `atomic_move.py` reports that condition as
`LinkUnavailable`; keep the staged result and report the limitation instead of
falling back to an overwrite-capable copy or cross-device move. See
[`SAFE_WRITES.md`](SAFE_WRITES.md) for the recovery rules.

## Use one Python environment

The helpers support Python 3.9+. Examples use `python3`; substitute the full
path to a suitable interpreter supplied by the host when available. Check its
imports before installing anything. Wiki and clipping helpers use the standard
library; PDF reading/splitting needs `pypdf`, and figure extraction needs
PyMuPDF and Pillow. `requirements.txt` at the plugin root supplies the full set.

If dependencies are missing, create a virtual environment in an approved,
writable location outside the installed plugin cache, then use its interpreter
for both installation and every script invocation:

```bash
python3 -m venv '<venv>'
'<venv>/bin/python' -m pip install -r '<plugin>/requirements.txt'
'<venv>/bin/python' - <<'PY'
import pypdf
import PIL
try:
    import pymupdf
except ImportError:
    import fitz
PY
```

Older supported PyMuPDF versions expose `fitz` instead of `pymupdf`; the
scripts handle both. On Windows the environment's interpreter is
`<venv>/Scripts/python.exe`. Shell examples elsewhere use POSIX syntax; use a
POSIX shell (such as WSL) or translate arguments for the active shell.
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
