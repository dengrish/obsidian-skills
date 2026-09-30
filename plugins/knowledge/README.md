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
| [knowledge:wiki-add](skills/wiki-add/SKILL.md) | Research missing queued or named topics |
| [knowledge:wiki-lint](skills/wiki-lint/SKILL.md) | Maintain entries, links, parents and MOCs |

## Setup

Read [runtime setup](shared/RUNTIME.md) once per task; each skill links the
[vault conventions](shared/CONVENTIONS.md) sections it needs.
Python 3.10+ is required. Wiki and clipping helpers use the standard library,
except the optional Lottie renderer, which needs Playwright with Chromium and
Pillow as [Lottie recovery](skills/clipping-clean/references/lottie-recovery.md)
describes. Parsing a PDF or image, including a Wiki skill reading a source
PDF, needs the packages in [requirements.txt](requirements.txt) in an
isolated environment and a passing `shared/scripts/check_parsers.py`, as the
runtime guide describes.
Install this whole package so its relative skill and helper paths stay intact.

Use the vault already selected for the task. Sources and reading notes retain
their `Inbox/`, `Articles/` and `Sources/` routes; entries remain in `Wiki/`
and generated navigation stays in `MOCs/`. This plugin leaves `Investments/`
records outside its intake and repair scope. Open and fixed suggestions are
kept in `Reviews/<skill>-suggestions.md` under the [shared protocol](shared/SUGGESTIONS.md).

## Reviewing flashcards

Wiki entries end with a flashcard for the Spaced Repetition community plugin
(`obsidian-spaced-repetition`), which you install and configure in the vault
yourself. Each entry has one reversed definition card, separated by `??` and
reviewed in both directions; a discipline root may have none. Keep the
plugin's multi-line reversed separator at `??` and its multi-line end marker
empty. Keep cloze conversion off (no highlight, bold or curly-bracket
conversion and no cloze patterns): the plugin reads the whole note, so it
would turn entry markup such as bold openers into extra cards. The plugin
reviews a note's card only when its *Flashcard tags* setting lists the note's
tag, unless folders-as-decks is on, so list every
[discipline tag](shared/CONVENTIONS.md#3-the-discipline-tag-enum) your Wiki
uses. wiki-lint reports unlisted tags, changed separators and active cloze
conversion but never edits the plugin's settings. To pause a card, change its
separator line to `!!`; restore `??` to resume it.

## Developing and packaging

This runtime tree is built from the canonical `skills/` and `shared/` sources
in [obsidian-skills](https://github.com/dengrish/obsidian-skills). Edit those
sources in the repository and follow its contributor instructions. Rebuild
before releasing; do not edit an installed plugin cache or generated runtime
copies. The `knowledge` and `investments` versions advance independently.
