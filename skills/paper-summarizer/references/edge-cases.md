# Special paper types and reading exceptions

Use the relevant section when the design or input needs it. These cases keep
[the same note roles](note-format.md#section-roles-and-headings). The
[confidence ladder and design ceilings](summary-standards.md#the-hedge-ladder-and-what-sets-its-ceiling)
remain the single owner of confidence; this reference adds reading and Methods
requirements, not a second ladder.

## Methods for less common designs

| Design | What Methods must make visible |
|---|---|
| Preprint | Name the actual design and analysis stage, such as a planned interim analysis. Venue is not a design or a confidence adjustment. Use the date printed on this version, without adding venue/review status to the note. |
| Systematic review / meta-analysis | Give the number and designs of studies, total participants, search cut-off and pooling model. Do not let pooled *n* look like one primary study. Keep evidence limitations separate from review-process limitations using the [design taxonomy](summary-standards.md#the-limitations-taxonomy-by-design). |
| Model / simulation | Name the model class, calibration/fitting data, assumptions and scenarios, including the counterfactual comparator. Carry sensitivity ranges with estimates. Scope findings to the model, not the real population it represents; fit is not external validation. |
| Machine-learning benchmark | Name systems, benchmark version/split, number of runs, fixed data/compute/prompt budgets and dated baselines. Separate the measured score from the capability it is a proxy for. |
| Case report / series | State the count, lack of control group, and whether cases were consecutive or selected. Describe what happened in those cases, not its frequency in a population or a causal effect. |
| Qualitative work | Name the interview/focus-group/observation method, participants, recruitment and analysis method. Attribute descriptions/typologies to those studied; neither a vivid quotation nor a purposive sample establishes population frequency. |

## Missing sections or figures

- **No abstract heading:** read the first page before deciding the abstract is
  absent. `--sections` searches headings, not all abstract content. Do not
  change `format` because the search missed it; write description from results.
- **No Methods heading:** inspect the last pages and variants such as
  “Experimental procedures”; methods may follow references or live in an
  unavailable supplement. If the design remains unstated, say what is known and
  what is missing. Do not invent a design to support a stronger claim; use the
  conservative confidence the text supports and name the methodological gap.
- **No figure files:** follow [intake](../SKILL.md#1-select-and-inventory-the-work).
  A `--cites` miss does not prove a figureless paper: inspect unnumbered,
  non-English and image-only exhibits. Re-scan after permitted extraction.
- **Needed figure still absent:** follow [missing exhibits](figures.md#when-the-figure-you-need-is-not-there).
  A source-supported prose claim or rebuilt result table can remain; an invented
  file, another paper's image or a pointer to the missing exhibit cannot.

## Notices and non-English sources

A retraction, correction or comment is itself the note's subject. State what
changed, by whom, on what grounds and when, identifying the affected article by
its printed title/DOI where supplied. The first `sources:` item remains **this
notice's PDF**, not the affected paper. Do not retell withdrawn findings as if
the notice established them. Attribute the notice's statements rather than
forcing them onto an effect rung. If an affected paper has its own note, report
it; do not rewrite that other note as part of this summary.

Write summaries of non-English papers in English while preserving the printed
`title`. Verification needles remain in the source's language and typography,
including a decimal comma (`--find '13,2 meses'`). A translated needle's failure
says nothing about the original claim. Check numbers, units and names on the
page; report low-confidence translations of scope instead of treating a
familiar-looking word as proof.

## Unreadable text and helper failures

`paper_text.py` exits distinguish different problems:

| Exit | Meaning / action |
|---|---|
| 1 | At least one finder needle is missing; apply [claim verification](review-checklist.md#locate-the-claims). |
| 2 | Bad path or empty needle; fix the command. |
| 3 | Neither PDF backend is available; repair the permitted environment or read pages directly. It has not inspected the PDF. |
| 4 | No extractable text; inspect page images or OCR to unique scratch outside the vault. |
| 5 | Unreadable/corrupt or zero-page PDF; stop this note and report the need for a readable source. |
| 6 | Encrypted/password-protected PDF; decrypt to a unique scratch directory outside the vault, preserve the organized source unchanged, and rerun the reader on the scratch copy. If a figure tool will use that copy, retain the source's exact basename inside the unique directory. |

Do not place an OCR copy beside the original in `Sources/PDFs/`: that creates a
second source identity with no matching figures. Keep the original PDF
unchanged. Verify OCR digits against page images; a failed needle may be OCR
damage, not proof that the source lacks the claim. Correct from the page or cut
an unsupported claim, never soften it into vague prose.

If source-page reading is impossible, leave the summary unpublished. If only the
finder is unavailable but the pages are readable, record manual page
verification explicitly. Lint remains a separate required gate; its absence is
not waived by a readable PDF or an available checklist.

## Byline and duplicate-document cases

For a long or collective byline use [frontmatter](note-format.md#frontmatter).
Do not compensate for a shortened author list by promoting an omitted author
elsewhere or adding an unsupported “led by” claim. A many-site population belongs
in the finding's scope, not an invented byline.

Two different stems can contain the same paper: the scan checks stem identity,
not content. If reading reveals matching title/results, summarize one, skip the
other and report both filenames. Do not create two summaries merely because
both scans said `new`, and do not delete either PDF. Organization of source
files belongs to `pdf-organizer`; a suffix used for distinct papers must not be
treated as proof these contents are distinct.
