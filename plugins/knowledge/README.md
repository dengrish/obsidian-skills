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
| [knowledge:wiki-lint](skills/wiki-lint/SKILL.md) | Repair, merge and split entries, add missing ones, and maintain links, parents and MOCs |

A default wiki-lint run fixes what it finds. It checks every entry and repairs
content from the sources each entry already cites, removing information they
do not give, however accurate. It settles conflicting claims against standard
references read online, consolidates duplicated explanations, merges duplicate
entries, splits entries that define several subjects, retitles ambiguous titles
and creates missing entries the wiki needs, then maintains links, parents and
MOCs. New and merged
entries are marked unread. It also resolves the issues you flag in entries and
works through the open items in `Reviews/wiki-notes-suggestions.md`. Deleting
an entry needs an explicit request.

## Setup

Read [runtime setup](shared/RUNTIME.md) once per task; each skill links the
[vault conventions](shared/CONVENTIONS.md) sections it needs.
Python 3.10+ is required. Wiki and clipping helpers, and pdf-organize's
renaming and filing commands, use the standard library, except the optional
Lottie renderer, which needs Playwright with Chromium and Pillow as
[Lottie recovery](skills/clipping-clean/references/lottie-recovery.md)
describes. Parsing a PDF or image, including splitting a book or a Wiki skill
reading a source PDF, needs the packages in [requirements.txt](requirements.txt)
in an isolated environment and a passing `shared/scripts/check_parsers.py`, as
the runtime guide describes.
Install this whole package so its relative skill and helper paths stay intact.

Use the vault already selected for the task. Sources and reading notes retain
their `Inbox/`, `Articles/` and `Sources/` routes; entries remain in `Wiki/`
and generated navigation stays in `MOCs/`. When a skill renames a file, such
as pdf-organize filing a PDF or clipping-clean reprocessing a clipping under a
new name, it repairs every link to that file in the same run, as Obsidian
does, Obsidian Canvas boards included. This
plugin leaves `Investments/` records outside its intake and repair scope,
apart from clipping-clean respelling a link or embed to a clipping or
image it renames; dated research records are never edited. Open and fixed
suggestions are kept in `Reviews/<skill>-suggestions.md` under the
[shared protocol](shared/SUGGESTIONS.md).
wiki-lint also keeps its settled link decisions, private run state rather
than a suggestion log, in `Reviews/.wiki-lint-settled.json`.

## Flagging issues in a note

Every Wiki entry has an `issues` property after `read`, blank as `issues: ""`;
the next wiki-lint run adds it to older entries. When you notice a problem
while reviewing a note, describe it there on one line; several issues may
share the line. The next wiki-lint run treats each issue as your request for
that note: it fixes the issue, or checks it and explains in the report why it
does not hold, then removes the resolved issues and unchecks `read` so you
review the note again. An issue it cannot act on, such as one needing a
deletion or a source the entry does not cite, stays in the field, and the
report says why. In Obsidian, set the `issues` property's type to Text, or
to List if you prefer one issue per item. The
[field's rules](shared/CONVENTIONS.md#2d-issues--the-users-issue-inbox) own
the details.

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
uses. Reading notes in `Articles/` carry the same tags, so add `Articles/`
to the plugin's *Folders to ignore*: otherwise a `::` or a line that is only
`?` in an article becomes a card. wiki-lint reports unlisted tags, changed
separators, active cloze conversion and an `Articles/` folder the plugin does
not ignore, but never edits the plugin's settings. To pause a card, change its
separator line to `!!`; restore `??` to resume it. wiki-lint may reword a
card to make it clearer, keeping its review schedule, and wiki-lint and
wiki-build remove any further card from an entry, along with its review
schedule, quoting both in the run report.

## Developing and packaging

This runtime tree is built from the canonical `skills/` and `shared/` sources
in [obsidian-skills](https://github.com/dengrish/obsidian-skills). Edit those
sources in the repository and follow its contributor instructions. Rebuild
before releasing; do not edit an installed plugin cache or generated runtime
copies. The `knowledge` and `investments` versions advance independently.
