# The verification pass

**Read this every time you reach step 10.** The trigger is a step number, not a circumstance — every note reaches it. It stays a separate file for length, not for conditionality.

**This pass is run against the PDF, not against the draft.** That is the whole design. A summary that has drifted wider than its source is internally consistent, fluent and self-confirming; re-reading it cannot surface the drift, because nothing inside it disagrees. The only thing that catches it is going back to the page.

Work the four blocks in order. The first is a command whose exit code is the answer; the rest are things no command can decide.

---

## 1. The mechanical sweep

Collect every number, every proper noun and every scope clause out of the draft — the callout and the body both — and put them through the finder in **one** command:

```bash
python3 '<skill>/scripts/paper_text.py' '<pdf path>' \
    --find '13.2 months' --find '0.62' \
    --find 'previously treated' --find 'C57BL/6'
```

Single-quote every needle and every path: they came off the paper and off the user's disk (`CONVENTIONS.md` §1b). It **exits 1** if any needle is unfound.

Read the three verdicts as three different instructions:

- **`FOUND`** with a page number — good, and note the page; the load-bearing ones become superscript `<sup>[[<stem>.pdf#page=N|N]]</sup>` citations in the body — *Results* most of all, but the design in *Methods*, the authors' own caveat in *Limitations* and the availability line all take one too (SKILL.md step 9a).
- **`loose`** — matched only after spacing and hyphens were stripped, which is how a word the PDF broke across a line is recovered. **Open that page and read it** before citing it: the same relaxation can join two things the paper kept apart.
- **`MISSING`** — the claim is not in the paper. **Cut it or correct it. Do not soften it.** Rewriting an unverifiable "13.2 months" into a vaguer "around a year" keeps a fabrication and removes the evidence that it was one. If the number is real but phrased differently in the source, re-run with the source's phrasing; if it is not there at all, it goes.

**What to feed it:** every figure with a digit in it; every drug, gene, organism, model, instrument and cohort name; the sample size; the comparator; and the words of each scope clause. A claim you did not put through the finder has not been verified, whatever else was.

**Feed it the paper's own tokens, kept short.** The finder is a substring search: a needle you reassembled — `'hazard ratio 0.62'` against a paper that wrote "a hazard ratio of 0.62" — comes back `MISSING` for a reason that has nothing to do with the claim, and the squashed retry does not bridge an inserted word. Prefer `'0.62'`. Re-run any `MISSING` needle once in the source's own wording before concluding the number is absent; if it misses twice, it is absent, and the rule is cut or correct.

**The count goes in the report.** "Verification: 14 of 14 claims located" is a result the user can check; silence is not.

**What this command cannot see, and what to do instead.** It is a substring search over the whole document, which leaves two gaps that block 2 below has to close by hand:

- **Widening a claim removes no token.** Delete the population from a finding and every needle still verifies. So **each scope clause goes in as its own needle** — `'previously treated'`, `'C57BL/6'`, `'at least two prior recurrences'` — and a scope clause you cannot needle is a scope clause you invented.
- **A `FOUND` page is where the string is, not where the finding is.** A number the paper quotes from prior work, or prints in its introduction or its reference list, verifies exactly like its own result. **Open every page before it becomes a citation.** `--sections` gives the pages the results occupy; a load-bearing number found only outside that range is the one to read first.

---

## 2. Claim-by-claim, against the rules

No command can see these. Walk the callout and each body section once.

**Scope**

- [ ] Every finding names the population, system or setting it holds for.
- [ ] No plural or definite article has quietly widened a specific result — "in mice" from one strain, "patients" from one hospital, "the effect" from one subgroup.
- [ ] Dose, duration and setting appear wherever they bound the result.
- [ ] An animal, cell or simulation finding is stated **as a claim about that system**, not as a hedged claim about people.

**Numbers**

- [ ] Every relative figure has an absolute one beside it — or an explicit note that the paper does not report one.
- [ ] Hazard ratios, odds ratios and risk ratios keep their own meanings; none is rewritten as a count or absolute risk without the required data. A missing uncertainty estimate is reported as missing, not as a single run or zero variance.
- [ ] Denominators are given for anything small.
- [ ] Intervals are carried on the results the note leans on, and on **every** null.
- [ ] No p-value is doing the work of an effect size.

**Comparators**

- [ ] Every comparative claim names what it was compared against.
- [ ] No bare "better", "effective" or "outperforms" with the comparator left implied.

**Nulls**

- [ ] No null is written as "no effect", "no difference" or "as good as".
- [ ] Every null carries its interval and says what that interval does not rule out.

**Hedging**

- [ ] Every claim sits on a rung from the closed ladder, and the rung is the lower of what the design supports and what the authors claim.
- [ ] The design constraint on causation is stated **as its own sentence** somewhere in the note, not carried only by the verb. Swapping a causal verb for an associational one does not, on its own, stop a reader drawing a causal conclusion.
- [ ] Nothing lets peer-review status do the work a design should have done — and neither the venue nor the review status appears in the note at all (SKILL.md step 7).
- [ ] Non-evidential statements are attributed, not graded.

**Readability** — the audience is a scientist from another field (SKILL.md step 7a)

- [ ] Every claim is a plain sentence followed by its qualifier, not one sentence carrying both. **A plain sentence with no qualifier behind it is an overstatement**, and it is the failure this shape can introduce that the old one could not.
- [ ] The **limit sentence follows immediately**, in the same paragraph and the same bullet. A reader who stops at the first sentence of a pair must not be left with a result and no statement of what it does not show.
- [ ] Every term the paper's own subfield would use freely is glossed on first use, once, and used bare afterwards. Read the note as someone who has never met the method: the first unexplained term is where they stop.
- [ ] No term is glossed twice, and no term appears with a gloss longer than the sentence it serves — that one should have been written in plain words instead.
- [ ] Every ratio, fold change, correlation or benchmark score has its size named in words once, beside the figures.
- [ ] **(lint)** No sentence runs over 25 words, and no numbered step over 20 — captions and callout bullets included.
- [ ] **(lint)** No paragraph holds more than six sentences.
- [ ] Confidence is carried by a **sentence pair** — what the study shows, then what it does not show — rather than by a modal verb alone.
- [ ] *Methods* walks the experiment as three to eight numbered steps in the simple past, unless the paper has no procedure.
- [ ] Active voice and simple tenses throughout, so the reader can tell who did what.
- [ ] **(lint)** *Results* holds no more than 2,400 characters of prose, exhibits excluded.
- [ ] *Results* develops **one** finding. A secondary experiment has at most a sentence, and the mechanism sub-study is in *Interpretation* unless it is itself the paper's result.

**Balance**

- [ ] Harms and negative results appear wherever benefits do.
- [ ] **(lint)** *Limitations* holds two to four bullets.
- [ ] Every limitation clears the bar: **would a reader do something different if they knew this?** If not, cut it — a padded list buries the one that matters.
- [ ] No bullet says an item "does not apply"; a considered-and-rejected item is simply absent.
- [ ] A caveat about one specific number is beside that number in *Results* or its exhibit caption, not in *Limitations*.
- [ ] The secondary outcomes that failed are in the note, not only the ones that worked.
- [ ] Every sentence in *Interpretation* is either something the authors concluded, or is explicitly marked as not.

---

## 3. Structure and frontmatter

**Run the linter first — it settles most of this block mechanically:**

```bash
python3 '<skill>/scripts/note_lint.py' '<drafted note>' --images '<vault>/Sources/Images'
```

Exit 0 means every item below with a **(lint)** tag is already satisfied and needs no eye. Exit 1 prints one line per violation; fix them and re-run rather than reading past them. The unmarked items are judgment and the linter cannot see them.

- [ ] **(lint)** Frontmatter is the source-note schema in order, nothing added, nothing reordered (`CONVENTIONS.md` §2b).
- [ ] **(lint)** `format` is one of `Paper`, `Book`, `Report` — this note's enum. The `Article`/`Post`/`Video` set belongs to a web clipping and is wrong here.
- [ ] **(lint)** `sources` item 1 is a **quoted** wikilink to a `.pdf`. That the PDF exists under that name is yours to confirm.
- [ ] A second `sources` item is present **only** if the document prints a DOI or an arXiv id (URL-normalised, double-quoted), never on `format: Book`, and never blank — a one-item list is a complete note. *(The linter checks the shape and the position, not whether the document prints one.)*
- [ ] **(lint)** `published` is a full `YYYY-MM-DD`, with any component the document does not print padded to `01` — never a bare year, and never a day invented from somewhere other than this PDF.
- [ ] `created` is today. *(Not linted — the check would fail every time an existing note is re-linted later.)*
- [ ] **(lint: length only)** `description` is 110 characters or fewer. That it is **one sentence**, and that it leads with the specifics, is yours.
- [ ] **(lint)** `tags` values are from the 27-value enum (`CONVENTIONS.md` §3), block-form, `#`-prefixed and **double-quoted**. An unquoted `#` starts a YAML comment and the discipline disappears with no error.
- [ ] **(lint)** `read` is a bare boolean, last in the schema, unquoted; write `false` on creation and preserve its existing value on a rewrite. A quoted `"false"` is a string, which renders in a checkbox property as permanently ticked.
- [ ] On a rewrite, `read` carries the existing note's value rather than resetting to `false`. *(The linter cannot know what the old note said.)*
- [ ] **(lint)** The `> [!Summary]` callout opens on the line immediately after the closing `---`, with no blank line above it, and holds three to seven single-line `> - ` bullets.
- [ ] **(lint)** One `___` rule, with a blank line either side, and no other horizontal rule in the note.
- [ ] **(lint)** Six `##` sections, in the role order of SKILL.md step 7, none empty.
- [ ] **(lint)** Every heading is 20 to 90 characters, three or more words, does not start lower-case, is not in capitals, has no full stop, and is not a bare role label like `Results` or `Background`.
- [ ] Every heading is in **sentence case** and is about **this paper**. The linter catches capitals and a lower-case opening; Title Case and a heading that could sit on any paper are yours.
- [ ] Read the six headings on their own, in order. **Do they tell the paper's story?** If they read as a table of contents rather than an argument, they are labels wearing sentences. *(Nothing mechanical can check this; it is the whole point of the rule.)*
- [ ] No heading overstates. The four claim rules bind in a heading exactly as in a sentence, and a heading is the most-read line in its section.
- [ ] **(lint)** Every page reference is a superscript `<sup>[[<stem>.pdf#page=N|N]]</sup>` whose display text equals the page it opens and whose target is this note's own `sources:` PDF, attached to the preceding character with no space, in body prose only — not in the front matter, the callout or a caption.
- [ ] **(lint)** No footnote syntax and no reference list; the note ends at *Availability*.
- [ ] The note's filename is the PDF's stem exactly.
- [ ] Nothing in the note reports funding, competing interests, peer-review status or ethics approval. *(Out of scope — SKILL.md step 7. The linter cannot read prose for this; it is the one structural rule you check by eye.)* **Preregistration is not in that list**: it is methodological, and its identifier belongs in *Methods* where the paper has one.

## 4. Figures and rebuilt tables

- [ ] **(lint, with `--images`)** Every embed names a file that exists in `Sources/Images/`.
- [ ] **(lint)** Every figure is filed under this note's PDF stem. Open it to confirm it is the intended exhibit; filenames and existence do not verify contents.
- [ ] **(lint)** Every embed has an italic caption on the line **immediately** below it, no blank line between.
- [ ] **(lint)** No figure or table number **anywhere in the note** — not `Figure 2 —` at the head of a caption, not "as Figure 2 shows", not "Table 5 reports", in any spelling.
- [ ] **(lint)** Four embeds and four rebuilt tables at most, all of them inside *Results*.
- [ ] **(lint)** Every rebuilt table is markdown, in *Results*, with an italic caption on the very next line.
- [ ] Every rebuilt table's values are verbatim from the paper — nothing rounded, converted or recomputed. *(Block 1's finder is what actually proves this: needle each number.)*
- [ ] A trimmed table says in its caption that it was trimmed, and to what. *(A trimmed table that looks complete is the most misleading object the note can hold.)*
- [ ] Nothing in the note points at a figure, table, appendix or supplement the reader does not have.
- [ ] Every caption leads with the message, not with what the axes are, and stands alone.
- [ ] Every caption obeys the claim rules — the hedge is the first thing to go missing in a caption.
- [ ] Error bars are identified, or their absence from the paper is stated.
- [ ] Each figure sits under the claim it supports.

---

## The verdict line

The pass **always** produces one, in the report:

- `Verification: N of N claims located; nothing cut` — it ran and everything held.
- `Verification: N of M claims located; K cut, J corrected` — with each cut and each correction on its own line, quoting the claim.
- `Verification: SKIPPED — <reason>` — and the only valid reasons are that the PDF has no extractable text, or that neither PDF backend could be installed. **A slow or awkward paper is not a reason.** A note that ships without a verdict line is incomplete, and the absence should be the first thing the report says.

**And a second verdict, from block 3:** `Lint: clean`, or `Lint: N violations, fixed` with what they were, or `Lint: SKIPPED — <reason>`. The two are separate results and a clean one of either says nothing about the other: the linter cannot tell whether a claim is in the paper, and the finder cannot tell whether the note is shaped like every other note in `Articles/`.
