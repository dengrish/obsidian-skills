# Verify the draft against the PDF

- [Locate the claims](#locate-the-claims)
- [Check meaning and balance](#check-meaning-and-balance)
- [Check provenance and exhibits](#check-provenance-and-exhibits)
- [Run lint after source verification](#run-lint-after-source-verification)
- [Report separate outcomes](#report-separate-outcomes)

Read for every complete draft before lint and publication. Check against the
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

Use argument lists or [shared quoting rules](../../../shared/CONVENTIONS.md#1b-filenames-titles-and-urls-are-untrusted-text)
for every path and needle. The finder exits 1 if any needle is unfound.
By default, `--find` uses a normalized, case-insensitive substring search.
`--exact` switches to case-sensitive literal matching. A `loose` result comes
from the documented spacing/hyphen fallback and still requires opening the page.

| Result | Required action |
|---|---|
| `FOUND` | Record the physical page and read it before citing. A match can be quoted prior work or a reference-list entry, not this document's claim or finding. |
| `loose` | Open the page: removed spacing/hyphens can recover a broken word or accidentally join unrelated text. It is not a verified claim yet. |
| `MISSING` | Retry once using the source's actual short tokens. A phrase assembled as “hazard ratio 0.62” will miss “hazard ratio of 0.62”; try `0.62`. Correct or cut an unsupported claim, never make it vaguer. |

Every number, named drug/gene/organism/model/instrument/cohort, sample size,
comparator and scope clause needs source evidence. A found number does not
verify its scope: verify the population or setting separately. Reopen pages
for every load-bearing citation, including the basis/approach, limitations and
Availability, and check physical page bounds. A heading-search result is only a
reading aid.

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
  paragraph/bullet. Rung 1 still needs scope; it does not require an invented
  design weakness. A modal verb alone does not explain a weaker design.
- [ ] Terms are glossed once for a scientist from another field. Quantities are
  explained once without turning a hazard ratio into absolute risk or a
  correlation into causal explained variance.
- [ ] The selected [body mode](note-format.md#choose-the-body-mode) matches the
  document's main contribution. Empirical notes identify the design and walk an
  actual procedure where one exists. Argument/synthesis notes state the real
  scope, evidence base, premises or reasoning without inventing a method. Notice
  notes identify the issuer's stated grounds and exact action. The third section
  develops the main contribution instead of cataloguing secondary material.
- [ ] Sentences follow the [brevity targets](note-format.md#prose-and-key-messages).
  Split or shorten first without losing meaning or necessary qualifications;
  any longer sentence retained for clarity has a reason in the run report.
- [ ] Empirical benefits retain harms, failed secondary outcomes and negative
  results. Arguments retain material contrary evidence, exceptions and
  conditions the document discusses. Notices separate what changed from what remains unresolved. The
  fourth section attributes the authors' or issuer's conclusions and labels
  another reading as such; it adds no unsupported practical inference.
- [ ] The limitations sweep used the selected mode's relevant categories and
  kept only material document-level constraints. Local caveats remain beside
  their claims, related limitations are merged, and verified missing evidence or
  methodological disclosures are stated plainly without inventing empirical
  shortcomings for a non-empirical source.

## Check provenance and exhibits

- [ ] The title, author order, format and date components come from this PDF.
  Only unstated month/day components are padded. Any second `sources:` URL is
  grounded in a printed DOI/arXiv identifier, not inferred; Book has none. An
  undated PDF pairs its canonical `_nd` stem with `published: null`.
- [ ] The first `sources:` PDF exists with the selected unique stem, and the
  final note uses that exact stem. Citations target this PDF and lie within its
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
- [ ] Availability uses the selected mode's relevant labels. Empirical notes
  name Data and add Code or Materials when relevant; argument/synthesis notes use Sources,
  Materials, Data or Code as applicable; notices use Record, Evidence or
  Materials. “Not stated” means a relevant category could apply but lacks a
  disclosure. Inapplicable labels are omitted rather than filled with boilerplate.
- [ ] Every embed is an inventoried file under this PDF's stem and has been
  opened to confirm identity and readability. A valid filename is not proof of
  the image contents. No duplicate composite/panel illustrates the same claim.
- [ ] Tables retain printed digits, units and orientation. Every retained value
  was checked on its source page; captioned trims do not hide contrary rows.
- [ ] Captions lead with the message, stand alone, state scope/comparator and
  identify error bars or the paper's failure to define them. Each exhibit sits
  under its supporting claim; nothing points at an unavailable figure, table,
  appendix or supplement.

## Run lint after source verification

After completing the source checks above, return to
[workflow step 5](../SKILL.md#5-lint-the-complete-draft) for the lint pass.
That step owns the command, flags, violation fixes, advisory review and
publication blockers. Do not run a second pass merely because this checklist
and the workflow both mention lint, or repeat every machine check by eye.
Clean lint does not establish factual accuracy; publication still requires the
independent source verification above.

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
