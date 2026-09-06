# Project context

This repository, https://github.com/dengrish/obsidian-skills, is the source of
the `knowledge` and `investments` plugins for Codex and Claude Code. The
marketplace remains `obsidian-skills`. Both hosts use `knowledge:` for the
seven knowledge skills and `investments:market-research` for finance. Both
plugins can use the same selected Obsidian vault.

Keep shared contributor instructions in this file. `CLAUDE.md` imports it with
`@AGENTS.md`; do not maintain a second copy or require a filesystem symlink.
These files guide work on this repository, not installed-plugin execution.
Runtime guidance belongs in the skills and `shared/RUNTIME.md`.

The user's intended workflow is to edit the skills in this repository and
push the changes to that GitHub repository to update the plugins. Make lasting
skill changes here, rather than editing installed plugin cache copies.

An explicit request to review or improve this plugin authorizes fixing source
issues during that task, with relevant validation and Git history as the
durable record. Do not leave an actionable authorized fix merely as a proposal
or create dated `obsidian-plugin-review-*` or `wiki-review-*` reports by default.
Leave existing reports untouched unless their migration or removal is requested.
Routine installed-skill runs never edit skill sources; all suggestion-log
attribution, formatting, verified-resolution cleanup, and migration rules live
in `shared/SUGGESTIONS.md`.

Canonical skill sources live in `skills/`; shared conventions and helpers live
in `shared/`. Author each manifest in
`plugins/<name>/.claude-plugin/plugin.json`, along with its README and any
plugin-specific requirements file. All other files under `plugins/` are
generated: edit their canonical inputs, never the generated copies.
`tools/build_plugin.py` builds both self-contained plugin trees, their Codex
manifests, and `knowledge.plugin` / `investments.plugin`. The shared marketplace
definition remains `.claude-plugin/marketplace.json`.

`tools/package-files.json` maps each plugin's package-relative destinations to
exact repository-relative source files. Keep one editable copy of shared
runtime code; build copies it into each consuming distribution. Every
intentional skill/shared file must be mapped. The build refuses missing inputs
and unexpected generated files; inspect and remove an obsolete generated asset
when deliberately removing its map entry. Neither installed plugin may depend
on the other plugin or the repository checkout.

When editing skills, follow `shared/CONVENTIONS.md` and the validation guidance
in `README.md`, including `python3 tests/test_conventions.py` and any relevant
script self-tests. Install `requirements-dev.txt` in an isolated Python environment
first; use that same interpreter for validation. Run
`python3 tests/test_compatibility.py` for packaging and portability checks.
Run `python3 tests/test_end_to_end.py` for the workflows that cross skill
boundaries. These tests use temporary vaults; do not substitute a user's live
vault for their fixtures.

Before distributing runtime changes, bump each affected plugin's authored version
and commit the authored inputs first. Then run `python3 tools/build_plugin.py`,
`python3 tools/build_plugin.py --check`, and the relevant validation; commit the
generated distributions separately and push both commits together. This lets
bundled provenance identify the exact source commit without a self-referential
commit hash. Do not amend that source commit without rebuilding. Development
builds may report uncommitted or unavailable source provenance; do not label
them with an unrelated clean commit. A Git push alone does not invalidate
an installed plugin whose explicit version has not changed. A shared input
change requires a bump in every consuming plugin; plugin-specific changes do
not force a release of the other plugin. Do not edit users'
installed caches or reconfigure their marketplaces as part of a source edit.
