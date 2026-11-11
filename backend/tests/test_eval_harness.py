"""Eval harness tests: cases are loadable and the rule baseline works offline."""

import asyncio

from app.eval.run import (
    CaseResult,
    build_request,
    load_cases,
    run_rule,
    summarize,
)


def test_eval_cases_are_15_unique():
    cases = load_cases()
    assert len(cases) == 15
    assert len({case["id"] for case in cases}) == 15


def test_build_request_maps_case_fields():
    case = load_cases()[0]
    request = build_request(case)
    assert request.city == "镇江"
    assert request.travel_days == case["days"]
    assert request.preferences == case["preferences"]
    assert request.party == case["party"]


def test_rule_baseline_runs_without_llm():
    row = asyncio.run(run_rule(load_cases()[0]))
    assert row.mode == "rule"
    assert row.structure_pass is True
    assert row.budget_identity is True
    assert row.tokens == 0


def test_summarize_metrics():
    rows = [
        CaseResult(
            case_id="a",
            mode="current",
            ok=True,
            structure_pass=True,
            must_see_coverage=1.0,
            id_hallucinations=0,
            budget_identity=True,
            over_budget=False,
            latency_ms=100.0,
            tokens=1000,
            planner_attempts=1,
            budget_total=500,
        ),
        CaseResult(
            case_id="b",
            mode="current",
            ok=False,
            structure_pass=False,
            must_see_coverage=0.5,
            id_hallucinations=1,
            budget_identity=False,
            over_budget=True,
            latency_ms=300.0,
            tokens=2000,
            planner_attempts=2,
            budget_total=900,
        ),
    ]
    summary = summarize(rows)
    assert summary["cases"] == 2
    assert summary["valid_cases"] == 2
    assert summary["structure_pass_rate"] == 0.5
    assert summary["must_see_coverage"] == 0.75
    assert summary["id_hallucination_rate"] == 0.5
    assert summary["over_budget_rate"] == 0.5
    assert summary["total_tokens"] == 3000
    assert summary["p50_latency_ms"] in {100.0, 300.0}


def test_infra_failure_is_excluded_from_quality_denominator():
    rows = [
        CaseResult(
            case_id="ok",
            mode="single",
            ok=True,
            structure_pass=True,
            must_see_coverage=1.0,
            id_hallucinations=0,
            budget_identity=True,
            over_budget=False,
            latency_ms=100.0,
            tokens=1000,
            planner_attempts=1,
            budget_total=500,
        ),
        CaseResult(
            case_id="net",
            mode="single",
            ok=False,
            structure_pass=False,
            must_see_coverage=0.0,
            id_hallucinations=0,
            budget_identity=False,
            over_budget=False,
            latency_ms=100.0,
            tokens=0,
            planner_attempts=0,
            budget_total=0,
            error="Connection error",
            error_kind="infra",
            infra_error=True,
        ),
    ]
    summary = summarize(rows)
    assert summary["cases"] == 2
    assert summary["valid_cases"] == 1
    assert summary["infra_failures"] == 1
    assert summary["structure_pass_rate"] == 1.0
    assert summary["budget_identity_rate"] == 1.0
