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


if __name__ == "__main__":
    unittest.main()
