# Investments

[investments:market-research](skills/market-research/SKILL.md) finds buying
opportunities in liquid U.S.-listed stocks for a 3–12 month momentum horizon.
It records concise decision briefs, detailed research, and later evaluations
of earlier recommendations in an Obsidian vault. Holdings reviews, sell
recommendations and trade execution are outside this skill's scope.

## Setup

Read [runtime setup](shared/RUNTIME.md) and the skill's
[data-access guide](skills/market-research/references/data-access.md).
Core helpers use Python 3.10+ and the standard library, including system timezone
data. The offline screener calculates consistent momentum, relative strength,
trend and liquidity-proxy measurements from saved provider responses. Optional
SEC filing/section extraction uses pinned EdgarTools; its setup is in the
data-access guide. PDF/image packages and the `knowledge` plugin are not required.
Install the whole package to preserve its local helper paths.

Credentials remain outside the repository, plugin and vault. An explicitly
selected private JSON credentials file can be passed to the bundled data
script with `--credentials-file`; otherwise it uses configured environment
variables. Read-only data access covers SEC, Nasdaq, Alpaca, Alpha Vantage and
FRED, subject to account access and coverage limits. Credentials are never
included in plugin installation or publication.

Use the same selected Obsidian vault as `knowledge` if desired. Published
`Investments/` records remain immutable. Scheduled runs create one daily edition;
user-requested fresh reviews create timestamped manual editions under the
[note format](skills/market-research/references/note-format.md#editions-and-retries).
Both share the same thesis and outcome history.
`Reviews/market-research-suggestions.md` keeps its existing name under the
[shared protocol](shared/SUGGESTIONS.md).

Scheduling is separate from installation. When requested, invoke
`investments:market-research` daily at 08:30 `America/Los_Angeles` (11:30
`America/New_York`), following daylight saving time. Preserve the selected
vault and credentials configuration in the host's task; installing this plugin
does not create or change a schedule.

This product uses the FRED® API but is not endorsed or certified by the Federal
Reserve Bank of St. Louis. Use of its FRED integration is subject to the
[FRED API Terms of Use](https://fred.stlouisfed.org/docs/api/terms_of_use.html).

## Developing and packaging

Canonical sources are maintained in
[obsidian-skills](https://github.com/dengrish/obsidian-skills). Edit the source
skill and shared helpers there, rebuild, and release this plugin independently.
Do not edit generated runtime copies or installed caches.
