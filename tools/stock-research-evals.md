# Offline stock-research evidence evaluation

This developer tool checks whether a research method handles specific financial
evidence correctly. It does not fetch prices, call a model, place trades, modify
a vault or measure investment returns. It is not shipped in either plugin.

The original normalized-evidence suite has seven public synthetic cases and
17 questions: standalone-quarter versus
year-to-date figures, units and earnings bases, missing pre-announcement consensus,
an intraday cutoff, a missing denominator, an unproven thematic beneficiary, and a
shortlist where no idea has met its readiness conditions. Seven numerical positive
controls require correct fact-based arithmetic. Three questions require abstaining
from an unsupported number; other questions require rejecting claims, distinguishing
a hypothesis from a confirmed fact, and retaining a plausible unconfirmed watch.
Always abstaining fails the answerable questions.

A separate document suite has four original synthetic HTML/text cases and
11 questions. It tests finding the correct table, period, unit and footnote before
calculating, with distractor tables, missing or ambiguous evidence, a post-result
consensus page and a metadata-only future source. It has seven numerical positive
controls, two justified numerical abstentions and two boolean assessments.
The original suite, commands and response hashes remain unchanged.

These are visible regression cases, not permanently held-out evidence of general
reasoning ability or investment edge. The unit tests check the evaluator using
constructed responses. They are not a substitute for running an independent agent.

## Prepare an independent behavioral run

From the repository, using the isolated development interpreter:

```sh
.venv/py310/bin/python tools/evaluate_market_research.py export > /private/tmp/stock-research-eval-input-only.json
```

`export` reads only `tests/fixtures/market_research/inputs.json`. It never reads
`expected.json`. Its output contains the actual evidence and questions, the full
response contract, and a hash covering all exported material except that hash
field itself. Response-protocol changes therefore invalidate old comparisons too.
No expected values, evidence answer sets or grader results are exported.

Give a fresh independent agent **only** this exported packet and the exact baseline
or candidate research instructions being assessed. Do not give it this guide, the
evaluator source, answer key, tests, other responses or grading feedback. Disable
network access and repository browsing, or isolate the accessible filesystem to
these inputs. A request not to read answers is weaker than actual access isolation.
The evaluator validates declared conditions; it cannot establish which files or
tools an agent actually accessed. The orchestrator must preserve that evidence.

Ask the agent to answer all questions in one JSON run. Assign its metadata before
the run; the orchestrator may attach that metadata to the unchanged responses
afterward if the agent cannot observe exact model settings. Preserve the original
response too. Do not repair substantive answers to make them grade successfully.
Schema failures are visible integration failures, not zero-score research answers.

Use separate fresh contexts for baseline and candidate. Keep the exact model,
sampling settings, packet, tool restrictions and surrounding task prompt the same;
only the assessed research instructions should vary. Record unsupported model
settings as unavailable, not guessed values. If they cannot be held constant,
describe that limitation instead of claiming a controlled experiment. Hash the
exact instruction bytes supplied to each agent, not a convenient file that omits
included references or extra instructions. Freeze both responses before grading
either; otherwise feedback can contaminate the second run. Retain rejected or
failed runs and do not select the best of several attempts without reporting them.

## Response contract

The exported `response_schema` is authoritative. A run has these fields:

- `schema_version`: integer `1`.
- `suite_id` and `input_sha256`: copied unchanged from the packet.
- `run_id`: unique per attempt.
- `variant`: `label` and the 64-character lowercase `instructions_sha256`.
- `conditions`: nonempty strings for `model`, `tool_policy` (exactly
  `offline-packet-only`), `sampling`, and `context_policy`.
- `responses`: every `case_id`, each containing an `answers` array with every
  `question_id` exactly once. Ordering does not affect assessment.

Each answer has `status` (`answered` or `insufficient`), a typed `value`, the
question's `unit`, `period` and `basis` (including nulls), `evidence` fact references,
`reason_codes`, and `calculation`. Optional `explanation` text is retained in the
submitted run but **not automatically graded**. The task describes which limitation
codes belong in each question. This controlled vocabulary makes a small regression
test reproducible; it is not a required format for normal Obsidian research notes.

An `answered` value matches the question type: a number, boolean, choice string or
selection array. An empty selection can correctly mean no candidate is ready.
`insufficient` means the requested value is not supported: use null for both value
and calculation, but keep the requested unit/period/basis and cite the evidence
that establishes the limitation. Unsupported quantitative claims are not replaced
with an invented zero.

Evidence entries are `source_id.fact_id`, limited to facts actually used to support
the answer. Citing every source or listing every limitation does not satisfy the
rubric. A metadata-only future source is not usable factual evidence. Numeric
answers also need an arithmetic tree using supplied numeric facts:

```json
{
  "op": "pct_change",
  "args": [
    {"fact": "current.revenue"},
    {"fact": "prior.revenue"}
  ]
}
```

Allowed binary operations are `add`, `subtract`, `multiply`, `divide`, and
`pct_change`. The last means `100 * (first / second - 1)` and requires a positive
base. A direct numeric observation uses just `{"fact": "source.fact"}`. Constants
1, 100, 1000 and 1000000 support normalization. Arbitrary formula text is never
executed. The evaluator replays the arithmetic and checks that its inputs are the
relevant cited facts, not merely that the final number resembles the answer key.
Equivalent arithmetic arrangements and specified alternative evidence sets work.
This does not prove every possible expression is financially meaningful; also
check the submitted reasoning, using an independent agent when useful. No human
approval gate is required.

## Grade and compare frozen runs

Save separate run files outside the agent's accessible inputs, then run:

```sh
.venv/py310/bin/python tools/evaluate_market_research.py grade --run /private/tmp/baseline-response.json
.venv/py310/bin/python tools/evaluate_market_research.py grade --run /private/tmp/candidate-response.json
.venv/py310/bin/python tools/evaluate_market_research.py compare --baseline /private/tmp/baseline-response.json --candidate /private/tmp/candidate-response.json
.venv/py310/bin/python tests/test_market_research_eval.py
```

Reports go to standard output; redirect them to new files if retention is needed.
The tool never edits inputs, responses or notes. It reports each case/question,
numerical and calculation errors, unit/period/basis errors, unsupported claims,
unwarranted abstentions, evidence errors, cutoff violations and limitation codes.
It includes input, answer-key and evaluator hashes. There is no opaque weighted
score, model-confidence score, profit estimate or automatic declaration of a winner.

Comparison requires identical input hashes and declared conditions plus complete
case and question rosters. It reports errors resolved and introduced in each
question as well as category-count differences. Equal aggregate counts can conceal
a newly broken question, so inspect the paired results. Different instruction
hashes are expected when comparing methods; the remaining conditions must match.

Exit status is 0 for a clean grade, 1 for a valid grade containing research errors,
and 2 for invalid inputs or a malformed run. A comparison returns 1 when any question
introduces an error category, even if another question improves; it returns 0 when
none are introduced. A successful comparison can still contain unresolved errors.

Read the original answers alongside the report. The strict evidence alternatives
can omit a valid new citation combination, and unscored prose can contradict a
correct structured response. Label those limitations explicitly. Do not quietly
change the key after seeing which method benefits: retain the original reports,
record the correction, and regrade both methods under the same revised key. A
passed 17-question packet does not establish discovery breadth, source quality in
the wild, long-run judgment, writing quality or superior future returns. Outcome
tracking remains the separate runtime process in `outcomes-and-learning.md`.

The first independent paired run exposed one overly strict evidence requirement
in `case03/earnings_surprise`: `estimates.version` explicitly establishes that no
pre-announcement consensus snapshot exists, so that fact alone supports abstention
without also citing actual EPS. The key now accepts that citation alone; empty
evidence and actual EPS alone still fail. Both unchanged development responses
were regraded: baseline and current each pass 17/17. The initial 16/17 versus 17/17 difference was a rubric error,
not a demonstrated research improvement.

The key also accepts the explicit missing-denominator fact alone for margin
abstention, and the frozen confirmation rule plus session schedule for rejecting
a close-based confirmation before the close. The actual numerator and an intraday
quote are unnecessary to establish those limitations. These citation alternatives
do not change the expected financial answers; reports retain the answer-key hash
so results from different rubrics remain distinguishable.

## Compare document reading with curated evidence

The document suite uses three separate files under
`tests/fixtures/market_research/documents/`:

- `inputs.json`: original raw document text, source availability, cutoff and
  questions. HTML stays unrendered data. Citation IDs are `document_id:Lnumber`,
  using one-based physical lines in the unchanged content.
- `oracle.json`: curated observations with values, reported units, periods,
  accounting bases and supporting document lines. It contains no question
  answers or derived results. Its document hash binds it to the exact corpus.
- `expected.json`: typed answers, required line-evidence alternatives, narrowly
  permitted contextual citations, relevant numeric observations, limitation codes
  and tolerances. It binds both the document
  and oracle hashes and both complete packet hashes, including their protocols.
  This file belongs only to the evaluator.

Export two different packets for the **same** research instructions:

```sh
.venv/py310/bin/python -B tools/evaluate_market_research.py export-documents --condition raw > /private/tmp/market-doc-raw.json
.venv/py310/bin/python -B tools/evaluate_market_research.py export-documents --condition oracle > /private/tmp/market-doc-oracle.json
```

Raw export reads only `inputs.json`; it works when neither the oracle nor answer
key exists. Oracle export reads the documents and curated observations, never the
answer key. The oracle packet replaces raw content with those observations and
their citations. It does not require searching distractor tables or interpreting
the original layout. Both packets preserve the same questions and document hash;
their different payloads and response protocols have different `input_sha256`
values. Neither packet includes accepted answers or citation alternatives.

Use two fresh, separately isolated agents under the independent-run procedure
above. Supply each only its assigned packet and the same exact research-method
instructions. Neither agent may see the other condition, oracle file, key,
responses or feedback. Freeze both original responses before grading. Keep model,
sampling, tool policy and surrounding task instructions fixed. The external
research instructions have one identical `instructions_sha256`; each packet's
own instructions and response protocol are independently covered by its input
hash. Retain failed attempts and unavailable settings instead of selecting the
best run or implying stronger isolation than actually enforced.

Document runs use `schema_version: 2`, adding `document_sha256` and
`evidence_condition` (`raw` or `oracle`) to the original run metadata. Copy all
three identifiers from the assigned packet. The exported response schema remains
authoritative. Answers use precise line evidence in both conditions, including
the table headers and footnotes needed to interpret the values. Do not cite a
whole document, a guessed line, or every line as a substitute for locating support.

Raw numeric calculations use extracted observations as leaves, before any unit
normalization. For example, the current H1 table value in the public case is:

```json
{"extract":{"value":920000,"unit":"USD_thousand","period":"FY2025-H1","basis":"GAAP","evidence":["rill:L3","rill:L9","rill:L10","rill:L11"]}}
```

Use the existing bounded arithmetic operations around these leaves; normalize
thousands versus millions explicitly. Oracle calculations instead use
`{"fact":"h1_current"}`. The modes cannot exchange leaf formats. An answer's
top-level evidence must include the observations' relevant line citations.
Nonnumeric and insufficient answers still use null calculation. The document
suite adds `ambiguous_evidence` to its reason vocabulary without changing the
original suite's protocol.

Grade and compare frozen responses:

```sh
.venv/py310/bin/python -B tools/evaluate_market_research.py grade-documents --run /private/tmp/raw-response.json
.venv/py310/bin/python -B tools/evaluate_market_research.py grade-documents --run /private/tmp/oracle-response.json
.venv/py310/bin/python -B tools/evaluate_market_research.py compare-documents --pairing raw-oracle --baseline /private/tmp/raw-response.json --candidate /private/tmp/oracle-response.json
```

The grader reports **source-selection errors**, **extraction errors** and
**calculation errors** separately. Correct arithmetic on a wrongly read column
is an extraction failure; correct extraction followed by a wrong reported result
is an arithmetic failure. A correct final number with irrelevant table/footnote
citations still fails. Unit, period, basis, answerability and cutoff checks also
apply. Reports retain document, oracle, key, packet, evaluator and instruction
identities. Exit codes remain 0 for a clean report, 1 for valid research errors
or newly introduced comparison errors, and 2 for malformed/incompatible inputs.

The private document key distinguishes **required support** from **permitted
context**. Each answer's `evidence_alternatives` contains the required line sets;
optional `permitted_context` maps additional relevant line IDs to their rationale.
An answer must contain every line in one required set and may supplement it only
with those contextual lines. An old key without context retains exact-set
behavior. Context cannot replace a required unit, period, value, footnote or
limitation statement. Unrelated price evidence, for example, cannot pad a
consensus-surprise answer merely because it is in the same case.

Each case may also have `observation_rules`, keyed by curated observation ID.
Each rule contains `permitted_context` and `basis_aliases`, both maps with a
nonempty explanation for every entry. A raw extraction still needs all of the
observation's original evidence and its exact value, unit and period. An alias
applies only to that observation's accounting-basis label; it never changes the
requested final answer basis. For example, the disclosed disposal gain is a
component of GAAP EPS, so its extracted basis may be `GAAP` or `GAAP_component`.
The resulting EPS after excluding that gain must still be labeled analytical.
All extraction citations must also appear in the answer's accepted evidence.
These rules stay in the private key, never either agent packet. Their corrections
change the answer-key hash without rewriting frozen input or protocol hashes.

`--pairing raw-oracle` requires a raw baseline, oracle candidate, identical
research-instruction hashes and otherwise identical declared run conditions.
`--pairing method` is the default: it compares two research methods only within
the same evidence condition and allows different instruction hashes. Both require
the same frozen corpus, complete question roster and distinct run IDs. Per-question
resolved/introduced errors prevent aggregate counts from concealing regressions.

A raw failure with an oracle success identifies a useful **document-reading
diagnostic**, not proof that retrieval alone caused the difference. The conditions
also differ in context length and presentation. Shared failures warrant inspecting
reasoning, the response contract and the answer key; they do not mechanically
establish one cause. Explanations remain unscored. Required/context rules can
still omit legitimate support, and the curated values are trusted,
independently reviewed fixtures, not machine-proven interpretations of filings.
Retain rubric corrections and regrade both frozen responses together.

The first independent document pair initially scored raw **5/11** and oracle
**9/11**. Reading the unchanged responses against the raw documents identified
rubric errors in all eight failed question-level judgments: relevant global
GAAP/period context in extracted observations, a legitimate GAAP component label,
and additional evidence explaining missing denominators, post-release estimates
or an incomplete trading session. The required/context rules above corrected
those false positives; no financial answers were changed. Both frozen responses
then passed **11/11**, and their explanations had no identified contradiction
on this manual audit. This does not establish a retrieval advantage or investment
edge. Initial and revised reports must both be retained. The run conditions
reported unavailable exact model/sampling settings and instruction-based context
separation, not filesystem-enforced isolation; this was a public development
smoke test, not a private held-out comparison. Its original packets, instructions,
conditions, responses, and both grading rounds are retained in
[`documents/forward-run/`](../tests/fixtures/market_research/documents/forward-run/).
These are development artifacts, not bundled plugin files or live-vault reports.

These short public cases are development regressions. They do not measure long
filing retrieval, PDF/OCR accuracy, live research coverage or investment returns.
No FinanceBench or other upstream document corpus is vendored.

## Prepare a private held-out evaluation

Create new `inputs.json` and `expected.json` files in a private evaluator location,
using the same schema as these fixtures. Independently verify the financial answer
key before any agent run; an agent can perform this check. Use different companies,
values and combinations of pitfalls, with both positive and abstention controls. The existing
reason vocabulary is deliberately bounded; extending it is a versioned evaluation
change, not a way to quietly adjust a result. Do not copy these cases and call
their already-visible answers held out.

Use synthetic evidence or a data-only historical snapshot whose facts were
available at the chosen cutoff. Retain source provenance and availability evidence
privately. Do not include later returns, revised fundamentals, later commentary or
an answer inferred from the subsequent stock outcome. A later source may appear
only as `source_id`, `available_at` and an empty `facts` array; export rejects
post-cutoff facts. This timestamp check trusts the fixture author's attribution,
so independently audit real historical availability rather than using download
time as a proxy. Announced future plans are available facts; realized future
outcomes are not.

Use `export --inputs /private/evaluator/inputs.json` to make the agent packet. Copy
the packet's `suite_id` and `input_sha256` into the private key, then use `grade` or
`compare` with both `--inputs` and `--expected` paths. The key gives each question's
expected status/value, acceptable exact evidence sets, applicable reason codes,
and absolute numeric tolerance (at most 0.01 in the requested unit). It is never an
agent input. Freeze and retain the source snapshot, key, exported packet, exact
instruction bytes, run conditions, original responses and reports before looking
at comparative performance. Once a held-out case is used to revise instructions,
treat it as a development regression and obtain new unseen cases for the next
generalization check.

For private **document** evaluations, create new `inputs.json`, `oracle.json` and
`expected.json` files using the document schemas above, with unfamiliar companies,
values, layouts and combinations of pitfalls. Independently check each curated
observation against its original table headers, units, period and footnotes before
writing the answer key. Specify required support and justify any permitted
context or observation-local basis synonyms before collecting responses; do not
permit entire unrelated tables to accommodate a preferred answer. Preserve
original bytes and source availability evidence.
Keep the oracle and key outside the raw agent's accessible directory. A document
available after the cutoff must have empty content, not later facts hidden in an
HTML comment or an unused table; raw export rejects any nonempty future content.
The timestamp declaration itself still needs independent verification.

Use `export-documents --inputs /private/evaluator/inputs.json --condition raw`
for the raw packet. Oracle export additionally takes
`--oracle /private/evaluator/oracle.json --condition oracle`. Supply the same
`--inputs`, `--oracle` and `--expected` paths to `grade-documents` and
`compare-documents`. Freeze the corpus, curated evidence, key, both packets,
research instructions and run conditions before collecting either response.
Once a case influences implementation or prompting, move it into development
coverage and obtain genuinely unseen cases for the next generalization check.
