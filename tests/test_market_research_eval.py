#!/usr/bin/env python3
"""Exercise the offline evaluator with hand-checked calculations and defects.

These are evaluator regression tests, not independent agent performance runs.
All files and CLI outputs used here stay in isolated temporary directories.
"""

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools/evaluate_market_research.py"
spec = importlib.util.spec_from_file_location("market_research_eval", SCRIPT)
evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)


def fact(reference):
    return {"fact": reference}


def operation(name, left, right):
    return {"op": name, "args": [left, right]}


def difference(current, first):
    return operation("subtract", fact(current), fact(first))


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.inputs = evaluator.read_json(evaluator.FIXTURES / "inputs.json")
        self.key = evaluator.read_json(evaluator.FIXTURES / "expected.json")

    def correct_run(self, label="baseline"):
        # Independently specify the financial derivations. Copying the key's
        # typed outputs is useful scaffolding, not a behavioral evaluation.
        expressions = {
            ("case01", "quarter_revenue"): difference("current.half_revenue", "current.first_revenue"),
            ("case01", "quarter_growth"): operation("pct_change",
                difference("current.half_revenue", "current.first_revenue"),
                difference("prior.half_revenue", "prior.first_revenue")),
            ("case02", "revenue_growth"): operation("pct_change",
                operation("multiply", fact("current.revenue"), {"constant": 1000}), fact("prior.revenue")),
            ("case02", "eps_growth"): operation("pct_change", fact("current.gaap_eps"), fact("prior.gaap_eps")),
            ("case03", "reported_eps"): fact("release.eps"),
            ("case04", "current_quote"): fact("prices.intraday"),
            ("case05", "operating_income_growth"): operation("pct_change", fact("current.operating_income"), fact("prior.operating_income")),
        }
        key = {case["case_id"]: {answer["question_id"]: answer for answer in case["answers"]}
               for case in self.key["cases"]}
        responses = []
        for case in self.inputs["cases"]:
            answers = []
            for question in case["questions"]:
                expected = key[case["case_id"]][question["question_id"]]
                answer = {name: copy.deepcopy(expected[name]) for name in
                          ("question_id", "status", "value", "reason_codes")}
                answer.update({name: question[name] for name in ("unit", "period", "basis")})
                answer["evidence"] = expected["evidence_alternatives"][0][:]
                answer["calculation"] = expressions.get((case["case_id"], question["question_id"]))
                answers.append(answer)
            responses.append({"case_id": case["case_id"], "answers": answers})
        return {"schema_version": 1, "suite_id": self.inputs["suite_id"],
                "input_sha256": evaluator.input_fingerprint(self.inputs), "run_id": label + "-run-1",
                "variant": {"label": label, "instructions_sha256": "a" * 64 if label == "baseline" else "b" * 64},
                "conditions": {"model": "synthetic-test", "tool_policy": "offline-packet-only",
                               "sampling": "deterministic-test", "context_policy": "isolated-test"},
                "responses": responses}

    @staticmethod
    def answer(run, case_id, question_id):
        return next(answer for case in run["responses"] if case["case_id"] == case_id
                    for answer in case["answers"] if answer["question_id"] == question_id)

    def grade(self, run):
        return evaluator.grade(self.inputs, self.key, run)

    def codes(self, run, case_id, question_id):
        result = self.grade(run)
        row = next(row for row in result["results"]
                   if row["case_id"] == case_id and row["question_id"] == question_id)
        return {error["code"] for error in row["errors"]}

    def test_hand_checked_positive_and_abstention_controls_pass(self):
        report = self.grade(self.correct_run())
        self.assertEqual(report["questions"], 17)
        self.assertEqual(report["passed_questions"], 17)
        self.assertEqual(report["errors_by_category"], {})
        self.assertEqual(len(self.inputs["cases"]), 7)
        self.assertNotIn("confidence", report)
        self.assertNotIn("expected_return", report)

    def test_quarter_is_350_and_growth_40_not_half_year_30(self):
        case = self.inputs["cases"][0]
        facts, _ = evaluator.source_facts(case)
        run = self.correct_run()
        quarter = self.answer(run, "case01", "quarter_revenue")
        growth = self.answer(run, "case01", "quarter_growth")
        self.assertEqual(evaluator.calculate(quarter["calculation"], facts)[0], 350)
        self.assertAlmostEqual(evaluator.calculate(growth["calculation"], facts)[0], 40)
        growth["value"] = 30
        growth["calculation"] = operation("pct_change", fact("current.half_revenue"), fact("prior.half_revenue"))
        self.assertTrue({"numeric_error", "calculation_error"} <= self.codes(run, "case01", "quarter_growth"))

    def test_million_billion_normalization_and_wrong_units(self):
        run = self.correct_run()
        answer = self.answer(run, "case02", "revenue_growth")
        answer["calculation"] = operation("pct_change", fact("current.revenue"), fact("prior.revenue"))
        answer["value"] = -99.875
        self.assertIn("numeric_error", self.codes(run, "case02", "revenue_growth"))
        run = self.correct_run()
        self.answer(run, "case02", "revenue_growth")["unit"] = "USD_million"
        self.assertIn("unit_error", self.codes(run, "case02", "revenue_growth"))

    def test_gaap_adjusted_mix_fails_value_basis_and_provenance(self):
        run = self.correct_run()
        answer = self.answer(run, "case02", "eps_growth")
        answer.update(value=200, basis="non-GAAP", evidence=["current.adjusted_eps", "prior.gaap_eps"],
                      calculation=operation("pct_change", fact("current.adjusted_eps"), fact("prior.gaap_eps")))
        self.assertTrue({"numeric_error", "basis_error", "evidence_error", "calculation_error"}
                        <= self.codes(run, "case02", "eps_growth"))

    def test_current_consensus_cannot_create_a_historical_beat(self):
        run = self.correct_run()
        answer = self.answer(run, "case03", "earnings_surprise")
        answer.update(status="answered", value=10, reason_codes=[],
                      evidence=["release.eps", "estimates.eps", "estimates.version"],
                      calculation=operation("pct_change", fact("release.eps"), fact("estimates.eps")))
        self.assertIn("unsupported_claim", self.codes(run, "case03", "earnings_surprise"))

    def test_consensus_provenance_alone_supports_abstention_but_missing_evidence_does_not(self):
        run = self.correct_run()
        answer = self.answer(run, "case03", "earnings_surprise")
        # The provenance fact itself explicitly establishes the unavailable
        # pre-announcement comparator; actual EPS is unnecessary to abstain.
        answer["evidence"] = ["estimates.version"]
        self.assertEqual(self.codes(run, "case03", "earnings_surprise"), set())
        for evidence in ([], ["release.eps"]):
            with self.subTest(evidence=evidence):
                answer["evidence"] = evidence
                self.assertIn("evidence_error", self.codes(run, "case03", "earnings_surprise"))

    def test_intraday_quote_does_not_confirm_later_regular_close(self):
        run = self.correct_run()
        answer = self.answer(run, "case04", "confirmation")
        answer.update(value=True, reason_codes=[])
        answer["evidence"].append("later_close")
        self.assertTrue({"assessment_error", "cutoff_error"} <= self.codes(run, "case04", "confirmation"))

    def test_rule_and_session_schedule_suffice_to_reject_early_confirmation(self):
        run = self.correct_run()
        answer = self.answer(run, "case04", "confirmation")
        answer["evidence"] = ["thesis.condition", "calendar.close_time"]
        self.assertEqual(self.codes(run, "case04", "confirmation"), set())
        # A quote alone does not establish which confirmation was required.
        answer["evidence"] = ["prices.intraday"]
        self.assertIn("evidence_error", self.codes(run, "case04", "confirmation"))

    def test_missing_revenue_cannot_create_operating_margin(self):
        run = self.correct_run()
        answer = self.answer(run, "case05", "operating_margin")
        answer.update(status="answered", value=10, reason_codes=[],
                      evidence=["current.operating_income", "prior.revenue"],
                      calculation=operation("multiply", operation("divide", fact("current.operating_income"), fact("prior.revenue")), {"constant": 100}))
        self.assertTrue({"unsupported_claim", "evidence_error", "calculation_error"}
                        <= self.codes(run, "case05", "operating_margin"))

    def test_missing_denominator_fact_alone_supports_margin_abstention(self):
        run = self.correct_run()
        answer = self.answer(run, "case05", "operating_margin")
        answer["evidence"] = ["current.revenue_gap"]
        self.assertEqual(self.codes(run, "case05", "operating_margin"), set())
        for evidence in ([], ["current.operating_income"], ["prior.revenue"]):
            with self.subTest(evidence=evidence):
                answer["evidence"] = evidence
                self.assertIn("evidence_error", self.codes(run, "case05", "operating_margin"))

    def test_theme_does_not_establish_material_issuer_exposure(self):
        run = self.correct_run()
        self.answer(run, "case06", "classification")["value"] = "verified_issuer_catalyst"
        self.assertIn("assessment_error", self.codes(run, "case06", "classification"))

    def test_correct_empty_ready_list_and_incorrect_promotions(self):
        run = self.correct_run()
        self.assertEqual(self.answer(run, "case07", "ready_candidates")["value"], [])
        self.answer(run, "case07", "ready_candidates")["value"] = ["Harbor", "Iris"]
        self.assertIn("assessment_error", self.codes(run, "case07", "ready_candidates"))

    def test_blanket_abstention_cannot_pass(self):
        run = self.correct_run()
        for case in run["responses"]:
            for answer in case["answers"]:
                answer.update(status="insufficient", value=None, calculation=None)
        report = self.grade(run)
        self.assertEqual(report["errors_by_category"]["unwarranted_abstention"], 14)
        self.assertEqual(report["passed_questions"], 3)

    def test_correct_number_requires_replayable_relevant_inputs(self):
        run = self.correct_run()
        answer = self.answer(run, "case01", "quarter_revenue")
        answer["calculation"] = {"constant": 350}
        self.assertIn("calculation_error", self.codes(run, "case01", "quarter_revenue"))
        answer["calculation"] = fact("current.half_revenue")
        self.assertIn("calculation_error", self.codes(run, "case01", "quarter_revenue"))

    def test_equivalent_arithmetic_is_accepted(self):
        run = self.correct_run()
        answer = self.answer(run, "case02", "eps_growth")
        answer["calculation"] = operation("multiply", operation("subtract",
            operation("divide", fact("current.gaap_eps"), fact("prior.gaap_eps")), {"constant": 1}), {"constant": 100})
        self.assertEqual(self.codes(run, "case02", "eps_growth"), set())

    def test_known_alternative_citations_and_array_order_are_accepted(self):
        run = self.correct_run()
        self.answer(run, "case03", "earnings_surprise")["evidence"].append("estimates.eps")
        self.answer(run, "case07", "next_checks")["value"].reverse()
        self.assertEqual(self.grade(run)["passed_questions"], 17)

    def test_shotgun_or_fabricated_citations_and_reason_codes_fail(self):
        run = self.correct_run()
        answer = self.answer(run, "case03", "reported_eps")
        answer["evidence"].append("invented.fact")
        answer["reason_codes"] = sorted(evaluator.REASONS)
        self.assertTrue({"evidence_error", "unknown_evidence", "reason_error"}
                        <= self.codes(run, "case03", "reported_eps"))

    def test_correct_value_cannot_hide_wrong_period(self):
        run = self.correct_run()
        self.answer(run, "case01", "quarter_revenue")["period"] = "FY2025-H1"
        self.assertIn("period_error", self.codes(run, "case01", "quarter_revenue"))

    def test_booleans_are_not_numbers(self):
        run = self.correct_run()
        self.answer(run, "case03", "reported_eps")["value"] = True
        self.assertIn("value_type_error", self.codes(run, "case03", "reported_eps"))

    def test_explanations_are_explicitly_unscored(self):
        run = self.correct_run()
        self.answer(run, "case03", "reported_eps")["explanation"] = "A deliberately wrong narrative is not mechanically graded."
        report = self.grade(run)
        self.assertEqual(report["passed_questions"], 17)
        self.assertIn("Explanations are unscored", report["scope"])

    def test_export_contains_tasks_not_keys_or_expected_answers(self):
        packet = evaluator.export_inputs(self.inputs)
        self.assertEqual(packet["input_sha256"], evaluator.input_fingerprint(self.inputs))
        self.assertEqual(packet["input_sha256"], evaluator.fingerprint({
            key: value for key, value in packet.items() if key != "input_sha256"}))
        self.assertEqual(packet["cases"], self.inputs["cases"])
        text = json.dumps(packet)
        self.assertNotIn("evidence_alternatives", text)
        self.assertNotIn("absolute_tolerance", text)
        self.assertNotIn('"expected"', text)
        self.assertNotIn('"passed"', text)

    def test_future_facts_are_rejected_before_export(self):
        future = self.inputs["cases"][3]["sources"][-1]
        future["facts"] = copy.deepcopy(self.inputs["cases"][3]["sources"][1]["facts"])
        with self.assertRaisesRegex(ValueError, "post-cutoff source must contain no facts"):
            evaluator.export_inputs(self.inputs)

    def test_timestamp_offsets_are_compared_as_instants(self):
        source = self.inputs["cases"][0]["sources"][0]
        source["available_at"] = "2025-08-08T15:30:00Z"
        evaluator.export_inputs(self.inputs)
        source["available_at"] = "2025-08-08T15:30:01Z"
        with self.assertRaisesRegex(ValueError, "post-cutoff"):
            evaluator.export_inputs(self.inputs)
        source["available_at"] = "2025-08-08T11:30:00"
        with self.assertRaisesRegex(ValueError, "explicit offset"):
            evaluator.export_inputs(self.inputs)

    def test_malformed_offsets_cannot_change_evaluation_availability(self):
        for offset in ('-04:99', '+00:60'):
            inputs = copy.deepcopy(self.inputs)
            inputs['cases'][0]['sources'][0]['available_at'] = '2025-08-08T07:00:00' + offset
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, 'explicit offset'):
                evaluator.export_inputs(inputs)

    def test_stale_inputs_or_key_cannot_be_silently_used(self):
        run = self.correct_run()
        self.inputs["cases"][0]["sources"][0]["facts"][0]["value"] = 999
        with self.assertRaisesRegex(ValueError, "answer key does not match"):
            self.grade(run)
        self.key["input_sha256"] = evaluator.input_fingerprint(self.inputs)
        with self.assertRaisesRegex(ValueError, "run does not match"):
            self.grade(run)

    def test_changed_agent_protocol_invalidates_the_key_and_run(self):
        run = self.correct_run()
        schema = copy.deepcopy(evaluator.RESPONSE_SCHEMA)
        schema["extra_instruction"] = "A changed response protocol."
        with patch.object(evaluator, "RESPONSE_SCHEMA", schema):
            with self.assertRaisesRegex(ValueError, "answer key does not match"):
                self.grade(run)

    def test_cherry_picked_cases_and_duplicate_answers_fail(self):
        run = self.correct_run()
        run["responses"].pop()
        with self.assertRaisesRegex(ValueError, "every case"):
            self.grade(run)
        run = self.correct_run()
        run["responses"][0]["answers"].append(copy.deepcopy(run["responses"][0]["answers"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.grade(run)
        run = self.correct_run()
        run["responses"][0]["answers"].pop()
        with self.assertRaisesRegex(ValueError, "every question"):
            self.grade(run)

    def test_key_roster_evidence_and_type_are_validated(self):
        self.key["cases"][0]["answers"][0]["evidence_alternatives"] = [["missing.fact"]]
        with self.assertRaisesRegex(ValueError, "known facts"):
            evaluator.validate_key(self.inputs, self.key)
        self.setUp()
        self.key["cases"][0]["answers"][0]["value"] = True
        with self.assertRaisesRegex(ValueError, "expected value type"):
            evaluator.validate_key(self.inputs, self.key)

    def test_same_input_comparison_reports_resolved_and_new_errors(self):
        baseline = self.correct_run()
        candidate = self.correct_run("candidate")
        self.answer(baseline, "case02", "draft_claim")["value"] = True
        self.answer(candidate, "case07", "harbor_state")["value"] = "ready"
        result = evaluator.compare(self.inputs, self.key, baseline, candidate)
        old = next(row for row in result["paired_results"] if row["case_id"] == "case02" and row["question_id"] == "draft_claim")
        new = next(row for row in result["paired_results"] if row["case_id"] == "case07" and row["question_id"] == "harbor_state")
        self.assertEqual(old["resolved_errors"], ["assessment_error"])
        self.assertEqual(new["introduced_errors"], ["assessment_error"])
        # An unchanged aggregate count must not conceal a newly broken case.
        self.assertEqual(result["error_count_delta_candidate_minus_baseline"]["assessment_error"], 0)

    def test_comparison_rejects_changed_conditions_and_identical_run_ids(self):
        baseline = self.correct_run()
        for field in evaluator.CONDITION_FIELDS - {"tool_policy"}:
            candidate = self.correct_run("candidate")
            candidate["conditions"][field] = "different"
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "conditions differ"):
                evaluator.compare(self.inputs, self.key, baseline, candidate)
        candidate = self.correct_run("candidate")
        candidate["run_id"] = baseline["run_id"]
        with self.assertRaisesRegex(ValueError, "run IDs must differ"):
            evaluator.compare(self.inputs, self.key, baseline, candidate)

    def test_arithmetic_rejects_zero_base_negative_base_code_and_depth(self):
        facts = {"s.x": {"value": 0}, "s.y": {"value": -1}}
        for expression in (operation("divide", {"constant": 1}, fact("s.x")),
                           operation("pct_change", {"constant": 1}, fact("s.y")),
                           {"eval": "__import__('os').remove('anything')"}):
            with self.subTest(expression=expression), self.assertRaises(ValueError):
                evaluator.calculate(expression, facts)
        expression = {"constant": 1}
        for _ in range(14):
            expression = operation("add", expression, {"constant": 1})
        with self.assertRaisesRegex(ValueError, "deep"):
            evaluator.calculate(expression, {})

    def test_duplicate_and_nonfinite_json_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="market-eval-json-") as tmp:
            path = Path(tmp) / "bad.json"
            for content in ('{"a": 1, "a": 2}', '{"a": NaN}', '{"a": Infinity}'):
                path.write_text(content, encoding="utf-8")
                with self.subTest(content=content), self.assertRaises(ValueError):
                    evaluator.read_json(path)

    def test_public_cli_export_grade_compare_and_error_exit_codes(self):
        with tempfile.TemporaryDirectory(prefix="market-eval-cli-") as tmp:
            temp = Path(tmp)
            paths = {name: temp / (name + ".json") for name in ("inputs", "expected", "baseline", "candidate")}
            objects = {"inputs": self.inputs, "expected": self.key,
                       "baseline": self.correct_run(), "candidate": self.correct_run("candidate")}
            for name, path in paths.items():
                path.write_text(json.dumps(objects[name]), encoding="utf-8")
            def invoke(*args):
                return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                                      cwd=temp, capture_output=True, text=True, encoding="utf-8", timeout=30)
            # No answer key needs to exist for an agent-facing export.
            expected_bytes = paths["expected"].read_bytes()
            paths["expected"].unlink()
            exported = invoke("export", "--inputs", paths["inputs"])
            self.assertEqual(exported.returncode, 0, exported.stderr)
            self.assertEqual(json.loads(exported.stdout)["cases"], self.inputs["cases"])
            paths["expected"].write_bytes(expected_bytes)
            common = ("--inputs", paths["inputs"], "--expected", paths["expected"])
            graded = invoke("grade", *common, "--run", paths["baseline"])
            self.assertEqual(graded.returncode, 0, graded.stderr)
            self.assertEqual(json.loads(graded.stdout)["passed_questions"], 17)
            objects["candidate"]["responses"][0]["answers"][0]["value"] = 999
            paths["candidate"].write_text(json.dumps(objects["candidate"]), encoding="utf-8")
            failed = invoke("grade", *common, "--run", paths["candidate"])
            self.assertEqual(failed.returncode, 1, failed.stderr)
            compared = invoke("compare", *common, "--baseline", paths["baseline"], "--candidate", paths["candidate"])
            self.assertEqual(compared.returncode, 1, compared.stderr)
            self.assertTrue(any(row["introduced_errors"] for row in json.loads(compared.stdout)["paired_results"]))
            paths["candidate"].write_text('{}', encoding="utf-8")
            malformed = invoke("grade", *common, "--run", paths["candidate"])
            self.assertEqual(malformed.returncode, 2)
            self.assertEqual(malformed.stdout, "")
            self.assertIn("evaluation error", malformed.stderr)
            self.assertEqual(set(temp.iterdir()), set(paths.values()))


class DocumentEvaluationTests(unittest.TestCase):
    def setUp(self):
        directory = evaluator.FIXTURES / "documents"
        self.inputs = evaluator.read_json(directory / "inputs.json")
        self.oracle = evaluator.read_json(directory / "oracle.json")
        self.key = evaluator.read_json(directory / "expected.json")

    def correct_run(self, condition="raw", label="baseline"):
        # These hand-specified formulas validate the evaluator, not an agent.
        # Oracle observations are used only to construct test responses.
        current = operation("subtract", operation("divide", fact("h1_current"), {"constant": 1000}), fact("q1_current"))
        prior = operation("subtract", operation("divide", fact("h1_prior"), {"constant": 1000}), fact("q1_prior"))
        expressions = {
            ("doc01", "quarter_revenue"): current,
            ("doc01", "quarter_growth"): operation("pct_change", current, prior),
            ("doc02", "reported_eps"): fact("gaap_current"),
            ("doc02", "eps_growth"): operation("pct_change", fact("gaap_current"), fact("gaap_prior")),
            ("doc02", "analytical_eps"): operation("subtract", fact("gaap_current"), fact("disposal_gain")),
            ("doc03", "operating_income"): fact("income"),
            ("doc04", "reported_revenue"): fact("revenue"),
        }
        responses = []
        curated = {case["case_id"]: {f["fact_id"]: f for f in case["facts"]} for case in self.oracle["cases"]}
        def raw(expression, case_id):
            if expression is None:
                return None
            if "fact" in expression:
                observation = curated[case_id][expression["fact"]]
                return {"extract": {key: copy.deepcopy(observation[key])
                                    for key in ("value", "unit", "period", "basis", "evidence")}}
            if "constant" in expression:
                return dict(expression)
            return operation(expression["op"], *[raw(arg, case_id) for arg in expression["args"]])
        for case, keyed in zip(self.inputs["cases"], self.key["cases"]):
            answers = []
            for question, expected in zip(case["questions"], keyed["answers"]):
                expression = copy.deepcopy(expressions.get((case["case_id"], question["question_id"])))
                answers.append({"question_id": question["question_id"], "status": expected["status"],
                                "value": copy.deepcopy(expected["value"]),
                                **{field: question[field] for field in ("unit", "period", "basis")},
                                "evidence": copy.deepcopy(expected["evidence_alternatives"][0]),
                                "reason_codes": expected["reason_codes"][:],
                                "calculation": raw(expression, case["case_id"]) if condition == "raw" else expression})
            responses.append({"case_id": case["case_id"], "answers": answers})
        packet = evaluator.export_documents(self.inputs, condition, self.oracle if condition == "oracle" else None)
        return {"schema_version": 2, "suite_id": self.inputs["suite_id"], "input_sha256": packet["input_sha256"],
                "document_sha256": packet["document_sha256"], "evidence_condition": condition,
                "run_id": label + "-" + condition, "variant": {"label": label, "instructions_sha256": "c" * 64},
                "conditions": {"model": "synthetic-test", "tool_policy": "offline-packet-only",
                               "sampling": "deterministic-test", "context_policy": "isolated-test"},
                "responses": responses}

    answer = staticmethod(EvaluationTests.answer)

    def grade(self, run):
        return evaluator.grade_documents(self.inputs, self.oracle, self.key, run)

    def codes(self, run, case_id, question_id):
        row = next(row for row in self.grade(run)["results"]
                   if row["case_id"] == case_id and row["question_id"] == question_id)
        return {issue["code"] for issue in row["errors"]}

    def compare(self, left, right, pairing="raw-oracle"):
        return evaluator.compare_documents(self.inputs, self.oracle, self.key, left, right, pairing)

    def test_document_positive_and_abstention_controls_pass_in_both_conditions(self):
        for condition in ("raw", "oracle"):
            run = self.correct_run(condition)
            result = self.grade(run)
            self.assertEqual(result["questions"], 11)
            self.assertEqual(result["passed_questions"], 11)
            self.assertEqual(result["errors_by_category"], {})
            self.assertIn("Explanations are unscored", result["scope"])
        raw, oracle = self.correct_run(), self.correct_run("oracle")
        self.assertEqual(raw["document_sha256"], oracle["document_sha256"])
        self.assertNotEqual(raw["input_sha256"], oracle["input_sha256"])
        self.assertTrue(all(row["baseline_passed"] and row["candidate_passed"]
                            for row in self.compare(raw, oracle)["paired_results"]))

    def test_raw_and_oracle_packets_are_separate_and_have_no_answers(self):
        raw = evaluator.export_documents(self.inputs)
        oracle = evaluator.export_documents(self.inputs, "oracle", self.oracle)
        self.assertEqual(raw["cases"], self.inputs["cases"])
        self.assertIn('<table id="consolidated-sales">', raw["cases"][0]["documents"][0]["content"])
        self.assertNotIn("facts", raw["cases"][0])
        self.assertNotIn("h1_current", json.dumps(raw))
        self.assertNotIn("content", oracle["cases"][0]["documents"][0])
        self.assertEqual(oracle["cases"][0]["facts"], self.oracle["cases"][0]["facts"])
        for packet in (raw, oracle):
            self.assertEqual(packet["input_sha256"], evaluator.fingerprint({key: value for key, value in packet.items()
                                                                         if key != "input_sha256"}))
            for key in ("numeric_fact_alternatives", "evidence_alternatives", "absolute_tolerance", "passed_questions",
                        "observation_rules", "permitted_context", "basis_aliases"):
                self.assertNotIn(key, json.dumps(packet))

    def test_raw_extractions_allow_verified_context_without_changing_observation(self):
        run = self.correct_run()
        for qid in ("quarter_revenue", "quarter_growth"):
            answer = self.answer(run, "doc01", qid)
            current = answer["calculation"] if qid == "quarter_revenue" else answer["calculation"]["args"][0]
            current["args"][1]["extract"]["evidence"].append("rill:L3")
            if qid == "quarter_growth":
                answer["calculation"]["args"][1]["args"][1]["extract"]["evidence"].append("rill:L3")
            self.assertEqual(self.codes(run, "doc01", qid), set())
        gain = self.answer(run, "doc02", "analytical_eps")["calculation"]["args"][1]["extract"]
        for context in (["northlamp:L2"], ["northlamp:L3"], ["northlamp:L2", "northlamp:L3"]):
            gain["evidence"] = ["northlamp:L7", *context]
            with self.subTest(context=context):
                self.assertEqual(self.codes(run, "doc02", "analytical_eps"), set())

    def test_extraction_context_cannot_replace_required_value_line_or_add_unrelated_header(self):
        for evidence in (["rill:L3"], ["rill:L3", "rill:L13", "rill:L9"]):
            run = self.correct_run()
            # L9 is valid for H1 and present in the answer, but not Q1 support.
            self.answer(run, "doc01", "quarter_revenue")["calculation"]["args"][1]["extract"]["evidence"] = evidence
            with self.subTest(evidence=evidence):
                self.assertIn("extraction_error", self.codes(run, "doc01", "quarter_revenue"))

    def test_component_basis_alias_is_local_and_final_analytical_basis_remains_required(self):
        run = self.correct_run()
        answer = self.answer(run, "doc02", "analytical_eps")
        gain = answer["calculation"]["args"][1]["extract"]
        gain["basis"] = "GAAP"
        self.assertEqual(self.codes(run, "doc02", "analytical_eps"), set())
        answer["basis"] = "GAAP"
        self.assertEqual(self.codes(run, "doc02", "analytical_eps"), {"basis_error"})
        answer["basis"] = "analytical_excluding_disposal_gain"
        for field, wrong in (("basis", "company_adjusted"), ("period", "FY2024-Q3"),
                             ("unit", "USD_million"), ("value", 0.5)):
            old = gain[field]
            gain[field] = wrong
            with self.subTest(field=field):
                self.assertIn("extraction_error", self.codes(run, "doc02", "analytical_eps"))
            gain[field] = old
        # A component label is not an alias for total reported GAAP EPS.
        answer["calculation"]["args"][0]["extract"]["basis"] = "GAAP_component"
        self.assertIn("extraction_error", self.codes(run, "doc02", "analytical_eps"))

    def test_contextual_citations_accept_minimal_or_supported_expanded_abstentions(self):
        for condition in ("raw", "oracle"):
            for case in self.key["cases"]:
                for expected in case["answers"]:
                    context = expected.get("permitted_context", {})
                    if not context:
                        continue
                    run = self.correct_run(condition)
                    answer = self.answer(run, case["case_id"], expected["question_id"])
                    # Every permitted contextual line can supplement the required support.
                    for refs in ([ref] for ref in context):
                        answer["evidence"] = expected["evidence_alternatives"][0] + refs
                        self.assertEqual(self.codes(run, case["case_id"], expected["question_id"]), set())
                    answer["evidence"] = expected["evidence_alternatives"][0] + list(context)
                    self.assertEqual(self.codes(run, case["case_id"], expected["question_id"]), set())
                    # All context together still cannot replace even one required line.
                    for required in expected["evidence_alternatives"][0]:
                        answer["evidence"] = [ref for ref in expected["evidence_alternatives"][0] if ref != required] + list(context)
                        self.assertIn("source_selection_error", self.codes(run, case["case_id"], expected["question_id"]))

    def test_optional_context_does_not_accept_citation_stuffing(self):
        for case_id, qid, irrelevant in (("doc01", "quarter_revenue", "rill:L1"),
                                         ("doc04", "revenue_surprise", "quote:L2"),
                                         ("doc04", "closing_breakout", "demonstration:L2")):
            run = self.correct_run()
            self.answer(run, case_id, qid)["evidence"].append(irrelevant)
            with self.subTest(question=qid):
                self.assertIn("source_selection_error", self.codes(run, case_id, qid))

    def test_private_rule_changes_preserve_packets_but_change_report_identity(self):
        run = self.correct_run()
        before = self.grade(run)
        packets = {condition: evaluator.export_documents(self.inputs, condition, self.oracle)
                   for condition in ("raw", "oracle")}
        # An older exact-evidence key remains supported without weakening defaults.
        for case in self.key["cases"]:
            case.pop("observation_rules", None)
            for answer in case["answers"]:
                answer.pop("permitted_context", None)
        after = self.grade(run)
        self.assertEqual(after["passed_questions"], 11)
        self.assertNotEqual(before["answer_key_sha256"], after["answer_key_sha256"])
        for condition in ("raw", "oracle"):
            self.assertEqual(packets[condition], evaluator.export_documents(self.inputs, condition, self.oracle))
        self.answer(run, "doc03", "operating_margin")["evidence"].append("fenbridge:L3")
        self.assertIn("source_selection_error", self.codes(run, "doc03", "operating_margin"))

    def test_private_context_rules_must_be_attributed_and_reference_valid_evidence(self):
        for context in ({"rill:L99": "Not a real line."}, {"rill:L3": ""}, ["rill:L3"]):
            self.key["cases"][0]["observation_rules"]["q1_current"]["permitted_context"] = context
            with self.subTest(context=context), self.assertRaisesRegex(ValueError, "context"):
                self.grade(self.correct_run())
        self.setUp()
        self.key["cases"][0]["observation_rules"]["invented"] = {
            "permitted_context": {}, "basis_aliases": {}}
        with self.assertRaisesRegex(ValueError, "observation rules"):
            self.grade(self.correct_run())
        self.setUp()
        self.key["cases"][1]["observation_rules"]["disposal_gain"]["basis_aliases"] = {"GAAP": ""}
        with self.assertRaisesRegex(ValueError, "basis aliases"):
            self.grade(self.correct_run())
        self.setUp()
        self.key["cases"][3]["answers"][0]["permitted_context"] = {"later_close:L1": "Future."}
        with self.assertRaisesRegex(ValueError, "existing document lines"):
            self.grade(self.correct_run())

    def test_wrong_table_column_is_extraction_error_not_arithmetic_error(self):
        run = self.correct_run()
        answer = self.answer(run, "doc01", "quarter_revenue")
        answer["calculation"]["args"][0]["args"][0]["extract"]["value"] = 700000
        answer["value"] = 330  # Correct arithmetic over the wrongly read column.
        codes = self.codes(run, "doc01", "quarter_revenue")
        self.assertTrue({"numeric_error", "extraction_error"} <= codes)
        self.assertNotIn("calculation_error", codes)
        paired = self.compare(run, self.correct_run("oracle"))
        row = paired["paired_results"][0]
        self.assertIn("extraction_error", row["resolved_errors"])

    def test_correct_extraction_with_wrong_arithmetic_is_separate(self):
        run = self.correct_run()
        self.answer(run, "doc01", "quarter_revenue")["value"] = 551
        codes = self.codes(run, "doc01", "quarter_revenue")
        self.assertEqual(codes, {"numeric_error", "calculation_error"})
        oracle = self.correct_run("oracle")
        self.answer(oracle, "doc01", "quarter_revenue")["value"] = 551
        row = self.compare(run, oracle)["paired_results"][0]
        self.assertFalse(row["baseline_passed"])
        self.assertFalse(row["candidate_passed"])
        self.assertEqual(row["resolved_errors"], [])

    def test_correctly_read_wrong_period_is_source_selection_not_extraction(self):
        run = self.correct_run()
        answer = self.answer(run, "doc01", "quarter_revenue")
        leaf = answer["calculation"]["args"][0]["args"][0]["extract"]
        leaf.update(value=700000, period="FY2024-H1")
        answer["value"] = 330
        self.assertEqual(self.codes(run, "doc01", "quarter_revenue"), {"numeric_error", "source_selection_error"})

    def test_correct_number_with_distractor_table_citation_still_fails(self):
        run = self.correct_run()
        answer = self.answer(run, "doc01", "quarter_revenue")
        answer["calculation"]["args"][0]["args"][0]["extract"]["evidence"] = ["rill:L3", "rill:L5", "rill:L6"]
        answer["evidence"] = ["rill:L3", "rill:L5", "rill:L6", "rill:L13"]
        self.assertTrue({"extraction_error", "source_selection_error"} <= self.codes(run, "doc01", "quarter_revenue"))

    def test_period_unit_and_footnote_errors_cannot_hide_behind_correct_values(self):
        for field, value in (("period", "FY2025-Q2"), ("unit", "USD_million"), ("basis", "non-GAAP")):
            run = self.correct_run()
            answer = self.answer(run, "doc01", "quarter_revenue")
            answer["calculation"]["args"][0]["args"][0]["extract"][field] = value
            with self.subTest(field=field):
                self.assertIn("extraction_error", self.codes(run, "doc01", "quarter_revenue"))
        run = self.correct_run()
        answer = self.answer(run, "doc02", "eps_growth")
        answer["calculation"]["args"][1]["extract"]["evidence"].remove("northlamp:L6")
        answer["evidence"].remove("northlamp:L6")
        self.assertTrue({"source_selection_error", "extraction_error"} <= self.codes(run, "doc02", "eps_growth"))

    def test_post_result_consensus_and_undefined_margin_are_not_verified(self):
        run = self.correct_run()
        self.answer(run, "doc04", "revenue_surprise").update(status="answered", value=1.694915,
                                                            calculation={"constant": 1}, reason_codes=[])
        self.assertIn("unsupported_claim", self.codes(run, "doc04", "revenue_surprise"))
        self.answer(run, "doc03", "margin_claim")["value"] = True
        self.assertIn("assessment_error", self.codes(run, "doc03", "margin_claim"))

    def test_blanket_abstention_fails_seven_numeric_and_two_boolean_controls(self):
        run = self.correct_run()
        for case in run["responses"]:
            for answer in case["answers"]:
                answer.update(status="insufficient", value=None, calculation=None)
        result = self.grade(run)
        self.assertEqual(result["passed_questions"], 2)
        self.assertEqual(result["errors_by_category"]["unwarranted_abstention"], 9)

    def test_future_document_content_rejected_and_future_citation_identified(self):
        self.inputs["cases"][3]["documents"][-1]["content"] = "Future close: 200."
        with self.assertRaisesRegex(ValueError, "post-cutoff document"):
            evaluator.export_documents(self.inputs)
        self.inputs["cases"][3]["documents"][-1]["content"] = ""
        run = self.correct_run()
        self.answer(run, "doc04", "closing_breakout")["evidence"].append("later_close:L1")
        self.assertTrue({"cutoff_error", "unknown_evidence"} <= self.codes(run, "doc04", "closing_breakout"))

    def test_oracle_must_bind_the_corpus_and_real_nonfuture_locations(self):
        self.oracle["document_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "does not match frozen documents"):
            evaluator.export_documents(self.inputs, "oracle", self.oracle)
        self.setUp()
        for ref in ("rill:L99", "later_close:L1", "invented:L1"):
            self.oracle["cases"][0]["facts"][0]["evidence"] = [ref]
            with self.subTest(ref=ref), self.assertRaisesRegex(ValueError, "existing document lines"):
                evaluator.export_documents(self.inputs, "oracle", self.oracle)

    def test_packet_source_and_protocol_changes_invalidate_old_runs(self):
        raw = self.correct_run()
        self.inputs["cases"][0]["documents"][0]["content"] += "A changed footnote.\n"
        with self.assertRaisesRegex(ValueError, "oracle evidence does not match"):
            self.grade(raw)
        self.setUp()
        original_schema = evaluator.document_response_schema
        def modified_schema(condition):
            result = original_schema(condition)
            result["extra_instruction"] = "A changed response protocol."
            return result
        with patch.object(evaluator, "document_response_schema", modified_schema):
            with self.assertRaisesRegex(ValueError, "answer key does not match frozen packets"):
                self.grade(raw)
        raw["input_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "run does not match frozen packet"):
            self.grade(raw)

    def test_future_citation_in_calculation_cannot_hide_outside_answer_evidence(self):
        run = self.correct_run()
        self.answer(run, "doc04", "reported_revenue")["calculation"]["extract"]["evidence"] = ["later_close:L1"]
        self.assertTrue({"cutoff_error", "unknown_evidence", "extraction_error"}
                        <= self.codes(run, "doc04", "reported_revenue"))

    def test_changed_oracle_requires_key_revision_even_for_raw_grading(self):
        run = self.correct_run()
        self.oracle["cases"][0]["facts"][0]["value"] = 999
        with self.assertRaisesRegex(ValueError, "answer key does not match frozen evidence"):
            self.grade(run)

    def test_raw_and_oracle_expression_forms_cannot_be_interchanged(self):
        raw, oracle = self.correct_run(), self.correct_run("oracle")
        for condition, run in (("raw", raw), ("oracle", oracle)):
            expression = fact("income") if condition == "raw" else {
                "extract": {key: self.oracle["cases"][2]["facts"][0][key]
                            for key in ("value", "unit", "period", "basis", "evidence")}}
            self.answer(run, "doc03", "operating_income")["calculation"] = expression
            with self.subTest(condition=condition):
                self.assertIn("calculation_error", self.codes(run, "doc03", "operating_income"))

    def test_complete_rosters_and_sane_keys_are_required(self):
        run = self.correct_run()
        run["responses"][0]["answers"].pop()
        with self.assertRaisesRegex(ValueError, "every question"):
            self.grade(run)
        self.key["cases"][0]["answers"][0]["numeric_fact_alternatives"] = [["invented"]]
        with self.assertRaisesRegex(ValueError, "known numeric"):
            self.grade(self.correct_run())

    def test_pairing_controls_refuse_confounded_comparisons(self):
        raw, oracle = self.correct_run(), self.correct_run("oracle")
        with self.assertRaisesRegex(ValueError, "same evidence condition"):
            self.compare(raw, oracle, "method")
        oracle["variant"]["instructions_sha256"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "identical research instructions"):
            self.compare(raw, oracle)
        for field in evaluator.CONDITION_FIELDS - {"tool_policy"}:
            oracle = self.correct_run("oracle")
            oracle["conditions"][field] = "different"
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "conditions differ"):
                self.compare(raw, oracle)
        oracle = self.correct_run("oracle")
        oracle["run_id"] = raw["run_id"]
        with self.assertRaisesRegex(ValueError, "run IDs must differ"):
            self.compare(raw, oracle)
        candidate = self.correct_run(label="candidate")
        candidate["variant"]["instructions_sha256"] = "d" * 64
        self.assertEqual(self.compare(raw, candidate, "method")["pairing"], "method")

    def test_document_cli_never_reads_oracle_for_raw_export_and_reports_exit_codes(self):
        with tempfile.TemporaryDirectory(prefix="market-doc-eval-cli-") as tmp:
            directory = Path(tmp)
            paths = {name: directory / (name + ".json") for name in ("inputs", "oracle", "expected", "raw", "curated")}
            objects = {"inputs": self.inputs, "oracle": self.oracle, "expected": self.key,
                       "raw": self.correct_run(), "curated": self.correct_run("oracle")}
            paths["inputs"].write_text(json.dumps(self.inputs), encoding="utf-8")
            def invoke(*args):
                return subprocess.run([sys.executable, "-B", str(SCRIPT), *map(str, args)], cwd=directory,
                                      capture_output=True, text=True, encoding="utf-8", timeout=30)
            exported = invoke("export-documents", "--inputs", paths["inputs"], "--oracle", paths["oracle"])
            self.assertEqual(exported.returncode, 0, exported.stderr)
            self.assertEqual(set(directory.iterdir()), {paths["inputs"]})
            self.assertEqual(json.loads(exported.stdout)["evidence_condition"], "raw")
            for name in ("oracle", "raw", "curated"):
                paths[name].write_text(json.dumps(objects[name]), encoding="utf-8")
            exported = invoke("export-documents", "--condition", "oracle", "--inputs", paths["inputs"], "--oracle", paths["oracle"])
            self.assertEqual(exported.returncode, 0, exported.stderr)
            self.assertFalse(paths["expected"].exists())
            paths["expected"].write_text(json.dumps(self.key), encoding="utf-8")
            common = ("--inputs", paths["inputs"], "--oracle", paths["oracle"], "--expected", paths["expected"])
            graded = invoke("grade-documents", *common, "--run", paths["raw"])
            self.assertEqual(graded.returncode, 0, graded.stderr)
            self.answer(objects["curated"], "doc02", "reported_eps")["value"] = 8
            paths["curated"].write_text(json.dumps(objects["curated"]), encoding="utf-8")
            compared = invoke("compare-documents", *common, "--pairing", "raw-oracle", "--baseline", paths["raw"], "--candidate", paths["curated"])
            self.assertEqual(compared.returncode, 1, compared.stderr)
            failed = invoke("grade-documents", *common, "--run", paths["curated"])
            self.assertEqual(failed.returncode, 1, failed.stderr)
            paths["raw"].write_text('{}', encoding="utf-8")
            malformed = invoke("grade-documents", *common, "--run", paths["raw"])
            self.assertEqual(malformed.returncode, 2, malformed.stderr)
            self.assertEqual(malformed.stdout, "")


if __name__ == "__main__":
    unittest.main()
