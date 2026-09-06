#!/usr/bin/env python3
"""Offline financial-evidence regression checks; never an investment-return score.

The export command reads inputs only. grade/compare also read the separately
held answer key. No network, model, vault, runtime plugin or external dependency
is used. See market-research-evals.md for independent behavioral runs.
"""

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/market_research"
REASONS = {
    "quarter_not_ytd", "basis_mismatch", "missing_preannouncement_consensus",
    "post_cutoff", "missing_denominator", "unproven_business_exposure",
    "missing_confirmation",
}
ANSWER_FIELDS = {
    "question_id", "status", "value", "unit", "period", "basis", "evidence",
    "reason_codes", "calculation",
}
CONDITION_FIELDS = {"model", "tool_policy", "sampling", "context_policy"}
OPERATIONS = {"add", "subtract", "multiply", "divide", "pct_change"}
CONSTANTS = {1, 100, 1000, 1000000}
RESPONSE_SCHEMA = {
    "run": {
        "schema_version": 1, "suite_id": "copy from this packet",
        "input_sha256": "copy from this packet", "run_id": "unique run label",
        "variant": {"label": "baseline or candidate", "instructions_sha256": "64 lowercase hex characters"},
        "conditions": {
            "model": "exact model/version", "tool_policy": "offline-packet-only",
            "sampling": "settings or unavailable", "context_policy": "fresh context, task packet and variant instructions only",
        },
        "responses": [{"case_id": "case ID", "answers": [{
            "question_id": "question ID", "status": "answered or insufficient",
            "value": "number/boolean/choice string/selection array; null when insufficient",
            "unit": "requested unit or null", "period": "requested period or null",
            "basis": "requested accounting basis or null",
            "evidence": ["source_id.fact_id used to support this answer"],
            "reason_codes": ["all applicable codes from reason_codes below"],
            "calculation": "numeric answered questions require an expression; otherwise null",
            "explanation": "optional, retained but not automatically graded",
        }]}],
    },
    "calculation": {
        "fact_reference": {"fact": "source_id.fact_id"},
        "constant": {"constant": "one of 1, 100, 1000, 1000000 for normalization"},
        "operation": {"op": "add/subtract/multiply/divide/pct_change", "args": ["expression", "expression"]},
        "pct_change": "100 * (first / second - 1); second must be positive",
    },
    "reason_codes": sorted(REASONS),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def read_json(path):
    def reject_constant(value):
        raise ValueError("nonfinite JSON number: " + value)
    return json.loads(Path(path).read_text(encoding="utf-8"),
                      object_pairs_hook=unique_object, parse_constant=reject_constant)


def fingerprint(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def timestamp(value):
    require(isinstance(value, str) and re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})", value),
        "timestamp requires ISO8601 seconds and explicit offset")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def index(items, field, label):
    require(isinstance(items, list) and items, label + " must be a nonempty list")
    result = {}
    for item in items:
        require(isinstance(item, dict), label + " items must be objects")
        key = item.get(field)
        require(isinstance(key, str) and re.fullmatch(r"[a-z0-9_-]+", key),
                label + " needs a simple nonempty " + field)
        require(key not in result, "duplicate " + label + ": " + key)
        result[key] = item
    return result


def strings(value, label):
    require(isinstance(value, list) and all(isinstance(v, str) for v in value),
            label + " must be an array of strings")
    require(len(set(value)) == len(value), label + " contains duplicates")
    return set(value)


def validate_inputs(inputs):
    require(isinstance(inputs, dict) and set(inputs) == {
        "schema_version", "suite_id", "description", "cases"}, "invalid input fields")
    require(type(inputs["schema_version"]) is int and inputs["schema_version"] == 1,
            "unsupported input schema")
    require(isinstance(inputs["suite_id"], str) and inputs["suite_id"], "missing suite_id")
    require(isinstance(inputs["description"], str), "description must be text")
    cases = index(inputs["cases"], "case_id", "cases")
    for case in cases.values():
        require(set(case) == {"case_id", "task", "cutoff", "sources", "questions"},
                "invalid case fields")
        require(isinstance(case["task"], str) and case["task"], "missing task")
        cutoff = timestamp(case["cutoff"])
        for source in index(case["sources"], "source_id", "sources").values():
            require(set(source) == {"source_id", "available_at", "facts"}, "invalid source fields")
            available = timestamp(source["available_at"])
            require(isinstance(source["facts"], list), "facts must be a list")
            # A future source can be represented by availability metadata only.
            # The task must never contain its realized financial facts/outcomes.
            require(available <= cutoff or source["facts"] == [],
                    "post-cutoff source must contain no facts")
            if not source["facts"]:
                continue
            for fact in index(source["facts"], "fact_id", "facts").values():
                require(set(fact) == {"fact_id", "description", "value", "unit", "period", "basis"},
                        "invalid fact fields")
                require(isinstance(fact["description"], str), "fact description must be text")
                value = fact["value"]
                require(isinstance(value, (str, bool)) or number(value), "invalid fact value")
                for field in ("unit", "period", "basis"):
                    require(fact[field] is None or isinstance(fact[field], str), "invalid fact " + field)
        for question in index(case["questions"], "question_id", "questions").values():
            require(set(question) == {"question_id", "prompt", "answer_type", "unit", "period", "basis", "options"},
                    "invalid question fields")
            require(isinstance(question["prompt"], str), "question prompt must be text")
            require(question["answer_type"] in {"number", "boolean", "choice", "selection"}, "invalid answer_type")
            options = strings(question["options"], "question options")
            require(bool(options) == (question["answer_type"] in {"choice", "selection"}), "unexpected question options")
            for field in ("unit", "period", "basis"):
                require(question[field] is None or isinstance(question[field], str), "invalid question " + field)
    return cases


def source_facts(case):
    facts, available = {}, {}
    for source in case["sources"]:
        available[source["source_id"]] = timestamp(source["available_at"])
        for fact in source["facts"]:
            reference = source["source_id"] + "." + fact["fact_id"]
            facts[reference] = fact
            available[reference] = available[source["source_id"]]
    return facts, available


def task_payload(inputs):
    """All agent-facing task material, before attaching its own hash."""
    return {
        "schema_version": 1, "suite_id": inputs["suite_id"],
        "instructions": (
            "Evaluate only the supplied synthetic evidence at each cutoff. Do not browse or read the answer key, "
            "evaluator, tests, other runs, or repository fixtures. Return one JSON run matching response_schema. "
            "Answer every question; insufficient is a valid result only where evidence cannot support the requested value. "
            "Use the requested units, periods and bases. Cite only relevant factual evidence. An unavailable later source "
            "has no usable facts. For a numeric answer provide a replayable calculation referring to the actual input facts. "
            "For an insufficient answer use null value/calculation but retain requested unit/period/basis. "
            "This is research-quality assessment, not a return prediction or a recommendation to trade."
        ),
        "description": inputs["description"], "response_schema": RESPONSE_SCHEMA, "cases": inputs["cases"],
    }


def input_fingerprint(inputs):
    # Include the task protocol and response contract, not just numerical data.
    # A changed instruction or schema must invalidate earlier comparisons too.
    return fingerprint(task_payload(inputs))


def export_inputs(inputs):
    validate_inputs(inputs)
    return dict(task_payload(inputs), input_sha256=input_fingerprint(inputs))


def validate_answers(answers, questions):
    indexed = index(answers, "question_id", "answers")
    require(set(indexed) == set(questions), "answers must include every question exactly once")
    for answer in indexed.values():
        require(ANSWER_FIELDS <= set(answer) <= ANSWER_FIELDS | {"explanation"}, "invalid answer fields")
        require(answer["status"] in {"answered", "insufficient"}, "invalid answer status")
        strings(answer["evidence"], "evidence")
        require(strings(answer["reason_codes"], "reason_codes") <= REASONS, "unknown reason code")
        if "explanation" in answer:
            require(isinstance(answer["explanation"], str), "explanation must be text")
        for field in ("unit", "period", "basis"):
            require(answer[field] is None or isinstance(answer[field], str), "invalid answer " + field)
        value = answer["value"]
        require(value is None or isinstance(value, (str, bool)) or number(value)
                or isinstance(value, list) and all(isinstance(v, str) for v in value), "invalid answer value")
        if isinstance(value, list):
            strings(value, "selection")
    return indexed


def validate_key(inputs, key):
    cases = validate_inputs(inputs)
    require(isinstance(key, dict) and set(key) == {"schema_version", "suite_id", "input_sha256", "cases"},
            "invalid answer-key fields")
    require(type(key["schema_version"]) is int and key["schema_version"] == 1,
            "unsupported answer-key schema")
    require(key["suite_id"] == inputs["suite_id"] and key["input_sha256"] == input_fingerprint(inputs),
            "answer key does not match the frozen inputs")
    keyed = index(key["cases"], "case_id", "answer-key cases")
    require(set(keyed) == set(cases), "answer key must cover every case")
    for case_id, case in cases.items():
        require(set(keyed[case_id]) == {"case_id", "answers"}, "invalid answer-key case")
        questions = index(case["questions"], "question_id", "questions")
        answers = index(keyed[case_id]["answers"], "question_id", "answer-key answers")
        require(set(answers) == set(questions), "answer key must cover every question")
        facts, available = source_facts(case)
        for question_id, expected in answers.items():
            require(set(expected) == {"question_id", "status", "value", "evidence_alternatives", "reason_codes", "absolute_tolerance"},
                    "invalid expected answer fields")
            require(expected["status"] in {"answered", "insufficient"}, "invalid expected status")
            require(strings(expected["reason_codes"], "expected reason_codes") <= REASONS, "unknown expected reason")
            tolerance = expected["absolute_tolerance"]
            require(number(tolerance) and 0 <= tolerance <= 0.01, "invalid absolute tolerance")
            question = questions[question_id]
            require(value_matches_type(expected["value"], question, expected["status"]), "invalid expected value type")
            alternatives = expected["evidence_alternatives"]
            require(isinstance(alternatives, list) and alternatives, "missing evidence alternatives")
            for evidence in alternatives:
                references = strings(evidence, "expected evidence")
                require(references <= set(facts), "expected evidence must cite known facts")
                require(all(available[ref] <= timestamp(case["cutoff"]) for ref in references), "answer key uses future evidence")
                if expected["status"] == "answered" and question["answer_type"] == "number":
                    require(any(number(facts[ref]["value"]) for ref in references), "numeric key requires numeric evidence")
    return keyed


def value_matches_type(value, question, status):
    if status == "insufficient":
        return value is None
    kind = question["answer_type"]
    if kind == "number":
        return number(value)
    if kind == "boolean":
        return type(value) is bool
    if kind == "choice":
        return isinstance(value, str) and value in question["options"]
    return (isinstance(value, list) and all(isinstance(v, str) for v in value)
            and len(set(value)) == len(value) and set(value) <= set(question["options"]))


def calculate(expression, facts, depth=0):
    """Replay a small arithmetic tree. No eval, executable expressions or imports."""
    require(depth <= 12 and isinstance(expression, dict), "invalid or overly deep calculation")
    if set(expression) == {"fact"}:
        ref = expression["fact"]
        require(isinstance(ref, str) and ref in facts and number(facts[ref]["value"]), "calculation needs a known numeric fact")
        return facts[ref]["value"], {ref}
    if set(expression) == {"constant"}:
        value = expression["constant"]
        require(number(value) and value in CONSTANTS, "unsupported calculation constant")
        return value, set()
    require(set(expression) == {"op", "args"} and expression["op"] in OPERATIONS,
            "invalid calculation operation")
    require(isinstance(expression["args"], list) and len(expression["args"]) == 2, "operation needs two arguments")
    left, left_refs = calculate(expression["args"][0], facts, depth + 1)
    right, right_refs = calculate(expression["args"][1], facts, depth + 1)
    operation = expression["op"]
    if operation in {"divide", "pct_change"}:
        require(right != 0, "zero denominator")
    if operation == "pct_change":
        require(right > 0, "conventional percentage change requires a positive base")
    if operation == "add":
        result = left + right
    elif operation == "subtract":
        result = left - right
    elif operation == "multiply":
        result = left * right
    elif operation == "divide":
        result = left / right
    else:
        result = 100 * (left / right - 1)
    require(number(result), "nonfinite calculation result")
    return result, left_refs | right_refs


def validate_run(inputs, run):
    cases = validate_inputs(inputs)
    require(isinstance(run, dict) and set(run) == {
        "schema_version", "suite_id", "input_sha256", "run_id", "variant", "conditions", "responses"}, "invalid run fields")
    require(type(run["schema_version"]) is int and run["schema_version"] == 1, "unsupported run schema")
    require(run["suite_id"] == inputs["suite_id"] and run["input_sha256"] == input_fingerprint(inputs),
            "run does not match the frozen inputs")
    require(isinstance(run["run_id"], str) and run["run_id"], "run_id is required")
    variant = run["variant"]
    require(isinstance(variant, dict) and set(variant) == {"label", "instructions_sha256"}, "invalid variant")
    require(isinstance(variant["label"], str) and variant["label"], "variant label is required")
    require(isinstance(variant["instructions_sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", variant["instructions_sha256"]), "invalid instruction hash")
    conditions = run["conditions"]
    require(isinstance(conditions, dict) and set(conditions) == CONDITION_FIELDS, "invalid comparison conditions")
    require(all(isinstance(v, str) and v.strip() for v in conditions.values()), "empty comparison condition")
    require(conditions["tool_policy"] == "offline-packet-only", "evaluation requires offline-packet-only access")
    responses = index(run["responses"], "case_id", "responses")
    require(set(responses) == set(cases), "run must include every case exactly once")
    for case_id, case in cases.items():
        require(set(responses[case_id]) == {"case_id", "answers"}, "invalid response fields")
        validate_answers(responses[case_id]["answers"], index(case["questions"], "question_id", "questions"))
    return responses


def close(left, right, tolerance):
    return number(left) and number(right) and abs(left - right) <= tolerance


def grade(inputs, key, run):
    keyed = validate_key(inputs, key)
    responses = validate_run(inputs, run)
    rows, errors = [], Counter()
    for case in inputs["cases"]:
        case_id = case["case_id"]
        expected_answers = index(keyed[case_id]["answers"], "question_id", "expected answers")
        answers = index(responses[case_id]["answers"], "question_id", "answers")
        facts, availability = source_facts(case)
        for question in case["questions"]:
            question_id = question["question_id"]
            answer, expected = answers[question_id], expected_answers[question_id]
            issues = []
            def issue(code, detail):
                issues.append({"code": code, "detail": detail})
            if answer["status"] != expected["status"]:
                issue("unsupported_claim" if answer["status"] == "answered" else "unwarranted_abstention", "incorrect answerability assessment")
            if not value_matches_type(answer["value"], question, answer["status"]):
                issue("value_type_error", "answer value does not match requested type/status")
            if question["answer_type"] == "number" and expected["status"] == "answered":
                matches = close(answer["value"], expected["value"], expected["absolute_tolerance"])
            elif question["answer_type"] == "selection" and isinstance(answer["value"], list):
                matches = set(answer["value"]) == set(expected["value"] or [])
            else:
                matches = type(answer["value"]) is type(expected["value"]) and answer["value"] == expected["value"]
            if not matches:
                issue("numeric_error" if question["answer_type"] == "number" else "assessment_error", "incorrect value")
            for field in ("unit", "period", "basis"):
                if answer[field] != question[field]:
                    issue(field + "_error", "answer uses incorrect " + field)
            evidence = set(answer["evidence"])
            if not any(evidence == set(option) for option in expected["evidence_alternatives"]):
                issue("evidence_error", "missing, irrelevant or unsupported factual citation")
            if evidence - set(facts):
                issue("unknown_evidence", "citation is not a supplied fact")
            if any(availability[ref] > timestamp(case["cutoff"]) for ref in evidence if ref in availability):
                issue("cutoff_error", "cited source was unavailable at cutoff")
            if set(answer["reason_codes"]) != set(expected["reason_codes"]):
                issue("reason_error", "missing or inapplicable reasoning category")
            if answer["status"] == "answered" and question["answer_type"] == "number":
                try:
                    value, references = calculate(answer["calculation"], facts)
                    require(close(value, answer["value"], expected["absolute_tolerance"]), "calculation does not reproduce answer")
                    eligible = [{ref for ref in option if number(facts[ref]["value"])}
                                for option in expected["evidence_alternatives"]]
                    require(references in eligible and references <= evidence and references,
                            "calculation does not use the relevant numeric evidence")
                except (ValueError, OverflowError) as exc:
                    issue("calculation_error", str(exc))
            elif answer["calculation"] is not None:
                issue("calculation_error", "calculation must be null for nonnumeric or insufficient answers")
            for code in {item["code"] for item in issues}:
                errors[code] += 1
            rows.append({"case_id": case_id, "question_id": question_id, "passed": not issues, "errors": issues})
    return {
        "schema_version": 1, "suite_id": inputs["suite_id"], "input_sha256": input_fingerprint(inputs),
        "answer_key_sha256": fingerprint(key), "run_id": run["run_id"],
        "evaluator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "variant": run["variant"], "conditions": run["conditions"],
        "scope": "Synthetic evidence/calculation regression only; no investment-edge or generalization claim. Explanations are unscored.",
        "questions": len(rows), "passed_questions": sum(row["passed"] for row in rows),
        "errors_by_category": dict(sorted(errors.items())), "results": rows,
    }


def compare(inputs, key, baseline, candidate):
    left, right = grade(inputs, key, baseline), grade(inputs, key, candidate)
    require(left["conditions"] == right["conditions"], "baseline/candidate conditions differ")
    require(left["run_id"] != right["run_id"], "baseline/candidate run IDs must differ")
    paired = []
    for before, after in zip(left["results"], right["results"]):
        before_codes = {item["code"] for item in before["errors"]}
        after_codes = {item["code"] for item in after["errors"]}
        paired.append({"case_id": before["case_id"], "question_id": before["question_id"],
                       "baseline_passed": before["passed"], "candidate_passed": after["passed"],
                       "resolved_errors": sorted(before_codes - after_codes),
                       "introduced_errors": sorted(after_codes - before_codes)})
    categories = set(left["errors_by_category"]) | set(right["errors_by_category"])
    return {
        "schema_version": 1, "scope": left["scope"], "baseline": left, "candidate": right,
        "error_count_delta_candidate_minus_baseline": {
            code: right["errors_by_category"].get(code, 0) - left["errors_by_category"].get(code, 0)
            for code in sorted(categories)}, "paired_results": paired,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("export", "grade", "compare"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--inputs", type=Path, default=FIXTURES / "inputs.json")
        if command != "export":
            command_parser.add_argument("--expected", type=Path, default=FIXTURES / "expected.json")
        if command == "grade":
            command_parser.add_argument("--run", type=Path, required=True)
        if command == "compare":
            command_parser.add_argument("--baseline", type=Path, required=True)
            command_parser.add_argument("--candidate", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        inputs = read_json(args.inputs)
        if args.command == "export":
            result = export_inputs(inputs)
        elif args.command == "grade":
            result = grade(inputs, read_json(args.expected), read_json(args.run))
        else:
            result = compare(inputs, read_json(args.expected), read_json(args.baseline), read_json(args.candidate))
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        # A valid report can contain research failures. Keep tool failure (2)
        # distinct from valid measured failures (1), including regressions.
        if args.command == "grade":
            return int(bool(result["errors_by_category"]))
        if args.command == "compare":
            return int(any(row["introduced_errors"] for row in result["paired_results"]))
        return 0
    except (OSError, ValueError, TypeError, KeyError, OverflowError) as exc:
        print("evaluation error: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
