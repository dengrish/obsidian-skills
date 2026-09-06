# Knowledge

Seven skills for organizing sources and maintaining an Obsidian knowledge base
in Codex and Claude Code. This plugin works independently of `investments`;
both may use the same selected vault.

| Skill | Purpose |
|---|---|
| [knowledge:pdf-organize](skills/pdf-organize/SKILL.md) | Rename, file and split PDFs |
| [knowledge:figure-extract](skills/figure-extract/SKILL.md) | Extract source figures |
| [knowledge:paper-summarize](skills/paper-summarize/SKILL.md) | Write PDF reading notes |
| [knowledge:clipping-clean](skills/clipping-clean/SKILL.md) | Clean Web Clipper captures |
| [knowledge:wiki-build](skills/wiki-build/SKILL.md) | Build or enrich entries from new sources |
| [knowledge:wiki-add](skills/wiki-add/SKILL.md) | Research missing queued topics |
| [knowledge:wiki-lint](skills/wiki-lint/SKILL.md) | Maintain entries, links, parents and MOCs |

## Setup

Read [runtime setup](shared/RUNTIME.md) and [vault conventions](shared/CONVENTIONS.md).
Python 3.10+ is required. Wiki and clipping helpers use the standard library;
PDF workflows need the packages in [requirements.txt](requirements.txt),
installed into an isolated environment using the runtime guide. Install this
whole package so its relative skill and helper paths stay intact.

Use the vault already selected for the task. Sources and reading notes retain
their `Inbox/`, `Articles/` and `Sources/` routes; entries remain in `Wiki/`
and generated navigation stays in `MOCs/`. This plugin leaves `Investments/`
records outside its intake and repair scope. Open suggestions remain in
`Reviews/<skill>-suggestions.md` under the [shared protocol](shared/SUGGESTIONS.md).

## Developing and packaging

This runtime tree is built from the canonical `skills/` and `shared/` sources
in [obsidian-skills](https://github.com/dengrish/obsidian-skills). Edit those
sources in the repository and follow its contributor instructions. Rebuild
before releasing; do not edit an installed plugin cache or generated runtime
copies. The `knowledge` and `investments` versions advance independently.
