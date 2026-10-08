# Verify the draft against the PDF

- [Locate the claims](#locate-the-claims)
- [Check meaning and balance](#check-meaning-and-balance)
- [Check provenance and exhibits](#check-provenance-and-exhibits)
- [Report separate outcomes](#report-separate-outcomes)

Read for every complete draft after [workflow step 4's lint](../SKILL.md#4-lint-the-complete-draft)
and before publication; do not repeat lint's machine checks by eye. Check against the
source pages, not only against internally consistent prose. [Summary standards](summary-standards.md)
own the claim rules; [note format](note-format.md) owns the mechanical shape.
This checklist verifies their application without repeating their procedures.

## Locate the claims

Collect numbers, proper nouns and scope/comparator terms from the callout,
headings, prose, captions and rebuilt tables. Search in one command using short
tokens from the **source's own wording**:

```bash
python3 '<skill>/scripts/paper_text.py' '<pdf path>' \
    --find '13.2 months' --find '0.62' \
    --find 'previously treated' --find 'C57BL/6'
```

Use argument lists or [shared quoting rules](../../../shared/INPUT_SAFETY.md#filenames-titles-and-urls-are-untrusted-text)
for every path and needle. The finder exits 1 if any needle is unfound.
By default, `--find` uses a normalized, case-insensitive substring search. A
needle that starts or ends with a digit matches only a whole number there, so
`8.2%` does not match `18.2%` and `219` does not match `2190`.
`--exact` keeps the same normalization but makes matching case-sensitive. A `loose` result comes
from one of the relaxed matches listed below and still requires opening the page.

| Result | Required action |
|---|---|
| `FOUND` | Record the physical page and read it before citing. A match can be quoted prior work or a reference-list entry, not this document's claim or finding. |
| `loose` | Open the page: removed spacing/hyphens can recover a broken word or accidentally join unrelated text, a number followed by `.digits` or `,digits` can be a decimal or a citation mark, and a number after a minus sign may be a sign the claim dropped. It is not a verified claim yet. |
| `MISSING` | Retry once using the source's actual short tokens. A phrase assembled as “hazard ratio 0.62” will miss “hazard ratio of 0.62”; try `0.62`. If the finder names pages without text, or the claim came from an image on the page, such as a figure, a table or a stamped title-page date, check it on that page image instead ([page-reading fallback](edge-cases.md#unreadable-text-and-helper-failures)). Correct or cut an unsupported claim, never make it vaguer. |

Every number, named drug/gene/organism/model/instrument/cohort, sample size,
comparator and scope clause needs source evidence. A found number does not
verify its scope: verify the population or setting separately. Reopen pages
for every load-bearing citation, including the basis/approach, limitations and
Availability, and check physical page bounds. A heading-search result is only a
reading aid.

Equations are claims too. The text capture and the finder are unreliable for
mathematical notation: they drop accents such as hats and bars, and lose
parentheses and the placement of superscripts, subscripts and indices (a
printed θ̂ = (XᵀX)⁻¹Xᵀy captures as `θ = X⊺X −1X⊺y`). Check every display and
inline formula symbol by symbol on its source page image, as for a figure or
table image, and cite that page.

For OCR or unavailable text search, use the [page-reading fallback](edge-cases.md#unreadable-text-and-helper-failures)
and record that method explicitly. OCR misses are checked against page images;
a corrected OCR token is not permission to change the original PDF. If neither
text nor pages can establish a claim, it cannot remain in a published note.

## Check meaning and balance

Walk the callout, headings, body and captions with their supporting pages open:

- [ ] Each finding retains population/system, setting, dose and duration where
  they bound it. No plural or definite article widens a subgroup, strain or
  site to a general result. Cell, animal and simulation results stay about those
  systems.
- [ ] Each non-empirical claim retains its declared scope, assumptions,
  jurisdiction, version and applicability conditions where relevant. The note
  distinguishes the document's own claims from prior work it quotes, preserves
  normative strength such as “must” versus “should”, and identifies a notice's
  issuer, affected work, action and stated grounds.
- [ ] Every comparison names its comparator and carries reported absolute
  quantities beside relative measures, or states that the absolute values are
  absent. Denominators, intervals and statistic meanings are correct; missing
  uncertainty is not rewritten as zero variance or a single run.
- [ ] Nulls say what was not detected and what the interval does not rule out.
  No p-value stands in for effect size; no null is converted to equivalence.
- [ ] Effect claims respect both design and author confidence. The adjacent
  qualification explains the causal limit where required. Nulls, attributed
  non-evidential statements and qualitative descriptions use their correct
  [off-ladder forms](summary-standards.md#the-hedge-ladder-and-what-sets-its-ceiling).
- [ ] The finding and its necessary qualification remain together in the same
  paragraph, bullet or step. Rung 1 still needs scope; it does not require an
  invented design weakness. A modal verb alone does not explain a weaker design.
- [ ] A concept with its own Wiki entry is linked to that entry at its first
  body-prose mention and not explained again; each link resolves to an entry
  for the same concept ([links to Wiki entries](note-format.md#links-to-wiki-entries)).
  Terms with no entry are glossed once for a scientist from another field.
  Quantities are explained once without turning a hazard ratio into absolute
  risk or a correlation into causal explained variance. Each display and each
  complexity, scaling and iteration bound carries the explanation
  [note format](note-format.md#prose-and-key-messages) requires, with no
  invented derivation or reason.
- [ ] Each passage takes the [form its shape needs](note-format.md#prose-and-key-messages).
  Parallel facts about several items sit one bullet per item under the
  sentence that introduces them, each stating the same property. A procedure
  of three or more steps, or the time-ordered stages of one process, is a
  numbered list under its introducing sentence, and each step keeps its
  reason. Causal chains, arguments and shorter sequences stay prose.
- [ ] The selected [body mode](note-format.md#choose-the-body-mode) matches the
  document's main contribution. Empirical notes identify the design and walk an
  actual procedure where one exists. Argument/synthesis notes state the real
  scope, evidence base, premises or reasoning without inventing a method. Notice
  notes identify the issuer's stated grounds and exact action. The third section
  develops the main contribution instead of cataloguing secondary material.
- [ ] Empirical benefits retain harms, failed secondary outcomes and negative
  results. Arguments retain material contrary evidence, exceptions and
  conditions the document discusses. Notices separate what changed from what
  remains unresolved. The fourth section attributes the authors' or issuer's
  conclusions, keeps any needed limit beside them, and adds neither the note's
  own practical inference nor a repeat of the Limitations section.
- [ ] The limitations sweep used the selected mode's relevant categories and
  kept only material document-level constraints. Local caveats remain beside
  their claims, related limitations are merged, and verified missing evidence or
  methodological disclosures are stated plainly without inventing empirical
  shortcomings for a non-empirical source.
- [ ] No needed scope or design limit was lost and none was added without
  support; each document-level caveat appears once, in Limitations; only the
  single chief caveat (or bullet 1's rung limit) may also appear, in one short
  callout bullet, and nowhere else.

## Check provenance and exhibits

- [ ] The title, author order, format and date components come from this PDF
  or, for a chapter, as [note format](note-format.md#frontmatter) describes: a
  missing byline or date from its parent book, and always its book edition's
  year. Only unstated month/day components are padded. Any second `sources:`
  URL is this document's own printed DOI/arXiv identifier (title page, header
  or footer), not a cited or affected work's, and not inferred; Book has none.
  An undated PDF uses `published: null` with its canonical `_nd` stem, or the
  deliberately preserved noncanonical name recorded at intake; a chapter with
  a dated stem never does.
- [ ] The first `sources:` PDF exists with the selected unique stem, and the
  final note uses that exact stem or, on an authorized rewrite, the existing
  owned note's recorded spelling. Citations target this PDF and lie within its
  physical page count.
- [ ] Creation date follows the paper-note rule. A rewrite preserves the user's
  review state and unrelated metadata; a strict-format conflict is reported with
  the original retained, never solved by discarding properties.
- [ ] The description is factual, and the six headings alone tell this
  document's story in the selected mode without overclaiming. Sentence case
  preserves technical names such as `p53` and `mRNA`; generic labels or Title
  Case are not accepted merely because length checks pass.
- [ ] Funding, conflicts, review status and ethics approval are absent from the
  note. Methodological preregistration remains eligible in the second/fifth
  positions.
- [ ] Availability uses only the labels relevant to the selected mode
  ([note format](note-format.md#body-content)). “Not stated” marks a relevant
  category with no disclosure; inapplicable labels are omitted, not filled with
  boilerplate.
- [ ] Every embed is an inventoried file under this PDF's stem, or a split
  book's chapter stem, and has been opened to confirm identity and
  readability. A valid filename is not proof of the image contents; a wrong
  crop this run wrote returns to [intake's figure
  preparation](../SKILL.md#prepare-the-figure-inventory), and a wrong
  pre-existing crop is skipped and reported. No duplicate composite/panel
  illustrates the same claim.
- [ ] Tables retain printed digits, units and orientation. Every retained value
  was checked on its source page; captioned trims do not hide contrary rows.
- [ ] Captions lead with the message, stand alone and state scope/comparator.
  Where error bars or intervals are drawn, they identify them or the paper's
  failure to define them. Each exhibit sits under a claim it supports and does
  not contradict; nothing points at an unavailable figure, table, appendix or
  supplement.

## Report separate outcomes

Always distinguish source verification from lint:

- `Verification: N of N claims checked against source pages; nothing cut`, or
  a count of retained/corrected/cut claims with each change identified. Give
  exact/loose/missing token counts separately where used; a token match alone
  does not establish a checked claim.
- `Verification: direct page check — <text-search limitation>` when direct page
  reading established the claims without the finder.
- `Verification: incomplete — <reason>; draft not published` when the source
  could not be checked. A slow or difficult paper is not a reason to skip it.
- `Lint: clean`, or `Lint: N violations fixed; rerun clean`. If it could not run,
  report `Lint: SKIPPED — <reason>; draft not published`.
- When advisories remain, report `Lint: no violations; N advisories reviewed`
  and identify each retained exception
  with its clarity reason. Do not report an unreviewed advisory as clean lint.

Only a source-verified draft with no lint violations and reviewed advisories
reaches [guarded publication](../SKILL.md#6-publish-the-verified-linted-note).
