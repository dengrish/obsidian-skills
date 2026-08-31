# Project context

This repository, https://github.com/dengrish/obsidian-skills, is the source of
the `obsidian` plugin for both Codex and Claude Code. The marketplace is named
obsidian-skills. Both hosts use the `obsidian:` namespace for its skills.

Keep shared contributor instructions in this file. `CLAUDE.md` imports it with
`@AGENTS.md`; do not maintain a second copy or require a filesystem symlink.
These files guide work on this repository, not installed-plugin execution.
Runtime guidance belongs in the skills and `shared/RUNTIME.md`.

The user's intended workflow is to edit the skills in this repository and
push the changes to that GitHub repository to update the plugin. Make lasting
skill changes here, rather than editing installed plugin cache copies.

Skill sources live in `skills/`; shared conventions and helpers live in
`shared/`. Author shared plugin metadata in `.claude-plugin/plugin.json`.
`tools/build_plugin.py` generates `.codex-plugin/plugin.json` from it, with
Codex presentation metadata, and rebuilds `obsidian.plugin`. The marketplace
definition is in `.claude-plugin/marketplace.json`, which both hosts support.
Keep one shared skill tree and preserve relative paths inside the package.

When editing skills, follow `shared/CONVENTIONS.md` and the validation guidance
in `README.md`, including `python3 tests/test_conventions.py` and any relevant
script self-tests. Install `requirements-dev.txt` in an isolated Python environment
first; use that same interpreter for validation. Run
`python3 tests/test_compatibility.py` for packaging and portability checks.
Run `python3 tests/test_end_to_end.py` for the workflows that cross skill
boundaries. These tests use temporary vaults; do not substitute a user's live
vault for their fixtures.

Before distributing runtime changes, bump the version in the authored manifest
and run `python3 tools/build_plugin.py`, then
`python3 tools/build_plugin.py --check`. A Git push alone does not invalidate
an installed plugin whose explicit version has not changed. Do not edit users'
installed caches or reconfigure their marketplaces as part of a source edit.
