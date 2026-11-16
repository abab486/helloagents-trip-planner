"""评测脚本测试：用例能加载、规则基线能离线跑通。"""

import asyncio

from app.eval.run import (
    CaseResult,
    build_request,
    load_cases,
    run_rule,
    summarize,
)


# 用例集固定 15 条且 id 不重复 —— 这个数字被 README 和报告引用，
# 改了就等于评测口径变了
def test_eval_cases_are_15_unique():
    cases = load_cases()
    assert len(cases) == 15
    assert len({case["id"] for case in cases}) == 15


# case 的字段要原样搬进 TripRequest，尤其 party（老人/亲子会直接影响校验）
def test_build_request_maps_case_fields():
    case = load_cases()[0]
    request = build_request(case)
    assert request.city == "镇江"
    assert request.travel_days == case["days"]
    assert request.preferences == case["preferences"]
    assert request.party == case["party"]


# 规则基线（fake_plan）一个 token 不花，也必须结构合法 + 预算恒等；
# 它的意义是证明"校验和计价链路本身通"，不是拿来和 LLM 比好坏
def test_rule_baseline_runs_without_llm():
    row = asyncio.run(run_rule(load_cases()[0]))
    assert row.mode == "rule"
    assert row.structure_pass is True
    assert row.budget_identity is True
    assert row.tokens == 0


# 手造两条 CaseResult 验汇总口径：通过率/覆盖率/幻觉率/超预算率按条数算，
# token 累加，P50 取中位数
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


# 关键口径：基础设施失败（断网/超时）要从质量分母里剔除 ——
# 否则一次断网就会把 structure_pass_rate 拉低，看起来像模型的问题
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
