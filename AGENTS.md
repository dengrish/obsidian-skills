# Project context

This repository, https://github.com/dengrish/obsidian-skills, is the source of
the `obsidian` plugin from the `obsidian-skills` marketplace. Its installed
skills appear in Codex with the `obsidian:` prefix.

The user's intended workflow is to edit the skills in this repository and
push the changes to that GitHub repository to update the plugin. Make lasting
skill changes here, rather than editing installed plugin cache copies.

Skill sources live in `skills/`; shared conventions and helpers live in
`shared/`. Plugin metadata is in `.claude-plugin/plugin.json`, and the
marketplace definition is in `.claude-plugin/marketplace.json`.

When editing skills, follow `shared/CONVENTIONS.md` and the validation guidance
in `README.md`, including `python3 tests/test_conventions.py` and any relevant
script self-tests.
