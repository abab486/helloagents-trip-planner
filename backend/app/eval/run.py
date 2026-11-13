"""Day 6 evaluation harness.

Run from backend/ with a real LLM:

    python -m app.eval.run --limit 15 --single-limit 5

Outputs:
    eval/report.md
    eval/report.json

The harness is intentionally separate from pytest: real LLM calls cost money.
CI only runs the deterministic unit/API tests.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ..agents.planner import PlannerAgent
from ..dag.llm_pipeline import run_llm_pipeline_context_async
from ..dag.walking_skeleton import run_walking_skeleton
from ..domain.models import TripRequest
from ..llm.client import create_llm_client

ROOT = Path(__file__).resolve().parents[3]
CASES_PATH = ROOT / "eval" / "cases.json"
REPORT_MD = ROOT / "eval" / "report.md"
REPORT_JSON = ROOT / "eval" / "report.json"


@dataclass
class CaseResult:
    case_id: str
    mode: str
    ok: bool
    structure_pass: bool
    must_see_coverage: float
    id_hallucinations: int
    budget_identity: bool
    over_budget: bool
    latency_ms: float
    tokens: int
    planner_attempts: int
    budget_total: int
    error: str = ""
    error_kind: str = ""
    infra_error: bool = False
    issues: list[str] = field(default_factory=list)


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_request(case: dict[str, Any]) -> TripRequest:
    start = date.fromisoformat(case["start"])
    end = start + timedelta(days=int(case["days"]) - 1)
    return TripRequest(
        city="镇江",
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        travel_days=int(case["days"]),
        transportation=case["transportation"],
        accommodation=case["accommodation"],
        preferences=case["preferences"],
        free_text_input=case.get("free_text_input", ""),
        budget_limit=case["budget"],
        party=case["party"],
        pace=case["pace"],
        must_see_ids=case.get("must_see", []),
    )


def _id_hallucinations(issues) -> int:
    codes = {
        "UNKNOWN_ATTRACTION",
        "UNKNOWN_HOTEL",
        "UNKNOWN_RESTAURANT",
    }
    return sum(1 for issue in issues if issue.code in codes)


def _selected_attraction_ids(result) -> set[str]:
    return {
        attraction.id
        for day in result.days
        for attraction in day.attractions
    }


def _tokens(result) -> int:
    for event in result.trace:
        if event.node_id == "plan":
            value = event.meta.get("total_tokens", 0)
            return int(value or 0)
    return 0


def _planner_attempts(result) -> int:
    for event in result.trace:
        if event.node_id == "plan":
            value = event.meta.get("planner_attempts", 0)
            return int(value or 0)
    return 0


def evaluate_result(
    case: dict[str, Any],
    mode: str,
    result,
    latency_ms: float,
) -> CaseResult:
    expected = set(case.get("must_see", []))
    selected = _selected_attraction_ids(result)
    coverage = (
        len(expected & selected) / len(expected) if expected else 1.0
    )
    issues = [issue.code for issue in result.validation.issues]
    identity = result.budget.total == sum(
        line.amount for line in result.budget.lines
    )
    return CaseResult(
        case_id=case["id"],
        mode=mode,
        ok=result.validation.passed and identity,
        structure_pass=result.validation.passed,
        must_see_coverage=round(coverage, 3),
        id_hallucinations=_id_hallucinations(result.validation.issues),
        budget_identity=identity,
        over_budget=result.budget.over_budget > 0,
        latency_ms=round(latency_ms, 2),
        tokens=_tokens(result),
        planner_attempts=_planner_attempts(result),
        budget_total=result.budget.total,
        issues=issues,
    )


def error_result(case: dict[str, Any], mode: str, error: Exception, latency_ms: float) -> CaseResult:
    message = f"{type(error).__name__}: {error}"
    lowered = message.lower()
    infra_markers = (
        "connection error",
        "connection reset",
        "timeout",
        "timed out",
        "rate limit",
        "apiconnection",
        "network",
        "temporarily unavailable",
    )
    infra = any(marker in lowered for marker in infra_markers)
    return CaseResult(
        case_id=case["id"],
        mode=mode,
        ok=False,
        structure_pass=False,
        must_see_coverage=0.0,
        id_hallucinations=0,
        budget_identity=False,
        over_budget=False,
        latency_ms=round(latency_ms, 2),
        tokens=0,
        planner_attempts=0,
        budget_total=0,
        error=message,
        error_kind="infra" if infra else "quality",
        infra_error=infra,
    )


async def run_current(case: dict[str, Any], planner: PlannerAgent) -> CaseResult:
    request = build_request(case)
    started = time.perf_counter()
    try:
        result, _ = await run_llm_pipeline_context_async(request, planner)
        elapsed = (time.perf_counter() - started) * 1000
        return evaluate_result(case, "current", result, elapsed)
    except Exception as exc:  # noqa: BLE001 - eval should record failures
        elapsed = (time.perf_counter() - started) * 1000
        return error_result(case, "current", exc, elapsed)


async def run_rule(case: dict[str, Any]) -> CaseResult:
    request = build_request(case)
    started = time.perf_counter()
    try:
        # run_walking_skeleton uses asyncio.run internally; run it in a thread
        # so the eval event loop stays free.
        result = await asyncio.to_thread(run_walking_skeleton, request)
        elapsed = (time.perf_counter() - started) * 1000
        return evaluate_result(case, "rule", result, elapsed)
    except Exception as exc:  # noqa: BLE001
        elapsed = (time.perf_counter() - started) * 1000
        return error_result(case, "rule", exc, elapsed)


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((p / 100) * (len(ordered) - 1)))))
    return round(ordered[index], 2)


def summarize(rows: list[CaseResult]) -> dict[str, Any]:
    if not rows:
        return {
            "cases": 0,
            "valid_cases": 0,
            "infra_failures": 0,
            "structure_pass_rate": 0.0,
            "must_see_coverage": 0.0,
            "id_hallucination_rate": 0.0,
            "budget_identity_rate": 0.0,
            "over_budget_rate": 0.0,
            "p50_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "total_tokens": 0,
            "avg_tokens": 0.0,
        }
    # Infrastructure failures (network/timeout) are not model-quality failures.
    # Exclude them from quality denominators, but report them separately.
    valid = [row for row in rows if not row.infra_error]
    denom = len(valid) or 1
    latencies = [row.latency_ms for row in valid]
    return {
        "cases": len(rows),
        "valid_cases": len(valid),
        "infra_failures": len(rows) - len(valid),
        "structure_pass_rate": round(
            sum(row.structure_pass for row in valid) / denom, 3
        ),
        "must_see_coverage": round(
            statistics.mean(row.must_see_coverage for row in valid), 3
        ) if valid else 0.0,
        "id_hallucination_rate": round(
            sum(row.id_hallucinations > 0 for row in valid) / denom, 3
        ),
        "budget_identity_rate": round(
            sum(row.budget_identity for row in valid) / denom, 3
        ),
        "over_budget_rate": round(
            sum(row.over_budget for row in valid) / denom, 3
        ),
        "p50_latency_ms": _percentile(latencies, 50),
        "p95_latency_ms": _percentile(latencies, 95),
        "total_tokens": sum(row.tokens for row in valid),
        "avg_tokens": round(statistics.mean(row.tokens for row in valid), 1)
        if valid
        else 0.0,
    }


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def write_report(
    rows: list[CaseResult],
    single_rows: list[CaseResult],
    model: str,
) -> None:
    groups = {
        "current": [row for row in rows if row.mode == "current"],
        "rule": [row for row in rows if row.mode == "rule"],
        "single": single_rows,
    }
    summaries = {name: summarize(items) for name, items in groups.items()}

    lines: list[str] = [
        "# 镇江旅行助手评测报告",
        "",
        f"- 生成时间：{date.today().isoformat()}",
        f"- 模型：`{model}`",
        f"- 评测集：`eval/cases.json`（{len(groups['current'])} 条）",
        "- 指标均由代码计算；`must_see` 为 case 中声明的期望景点 ID。",
        "",
        "## 汇总",
        "",
        "| 系统 | 用例 | 有效 | 基础设施失败 | 结构合法率 | must-see 覆盖 | ID 幻觉率 | 预算恒等 | 超预算率 | P50 | P95 | 总 Token | 平均 Token |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    labels = {
        "current": "当前 DAG + LLM Planner",
        "rule": "规则保底（无 LLM）",
        "single": f"单次 LLM（无 repair，{len(single_rows)} 条）",
    }
    for name in ("current", "rule", "single"):
        summary = summaries[name]
        if summary["cases"] == 0:
            continue
        lines.append(
            "| {label} | {cases} | {valid} | {infra} | {structure} | {coverage} | {hallucination} | {identity} | {over} | {p50}ms | {p95}ms | {tokens} | {avg} |".format(
                label=labels[name],
                cases=summary["cases"],
                valid=summary.get("valid_cases", summary["cases"]),
                infra=summary.get("infra_failures", 0),
                structure=_fmt_pct(summary["structure_pass_rate"]),
                coverage=_fmt_pct(summary["must_see_coverage"]),
                hallucination=_fmt_pct(summary["id_hallucination_rate"]),
                identity=_fmt_pct(summary["budget_identity_rate"]),
                over=_fmt_pct(summary["over_budget_rate"]),
                p50=summary["p50_latency_ms"],
                p95=summary["p95_latency_ms"],
                tokens=summary["total_tokens"],
                avg=summary["avg_tokens"],
            )
        )

    lines.extend(
        [
            "",
            "## 逐条结果",
            "",
            "| case | 系统 | 结构 | must-see | 幻觉 | 超预算 | 预算合计 | 耗时 | Token | Planner 尝试 | 错误 |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in rows + single_rows:
        error = row.error.replace("|", "/") if row.error else ""
        if row.infra_error:
            error = f"[INFRA] {error}"
        lines.append(
            "| {case} | {mode} | {structure} | {coverage} | {hallucination} | {over} | {budget} | {latency}ms | {tokens} | {attempts} | {error} |".format(
                case=row.case_id,
                mode=row.mode,
                structure="✅" if row.structure_pass else "❌",
                coverage=f"{row.must_see_coverage * 100:.0f}%",
                hallucination=row.id_hallucinations,
                over="是" if row.over_budget else "否",
                budget=row.budget_total,
                latency=row.latency_ms,
                tokens=row.tokens,
                attempts=row.planner_attempts,
                error=error,
            )
        )

    lines.extend(
        [
            "",
            "## 观察",
            "",
            "- 当前系统把「选点」交给 LLM，把「校验 + 算钱」交给代码；结构合法率与预算恒等应优先看。",
            "- `rule` 是完全确定性、零 Token 的基线；它不懂偏好，但能证明预算/约束链路本身是通的。",
            "- `single` 是关闭 Planner repair 的单次 LLM 基线，用于观察一次输出失败时的损失。",
            "- `基础设施失败` 单列统计：网络/超时不计入模型质量分母，但会降低可用性。",
            "- 超预算的 case 不是失败：它应被 `over_budget` 标记，后续可接二次规划。",
            "- 本报告中的价格是 CSV 参考价，不是实时票价；数据边界见 `backend/app/data/zhenjiang/README.md`。",
            "",
            "## 复现",
            "",
            "```powershell",
            "cd backend",
            '$env:PYTHONIOENCODING="utf-8"',
            "F:\\agent\\env313\\Scripts\\python.exe -m app.eval.run --limit 15 --single-limit 5",
            "```",
            "",
        ]
    )

    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    REPORT_JSON.write_text(
        json.dumps(
            {
                "model": model,
                "summaries": summaries,
                "rows": [row.__dict__ for row in rows],
                "single_rows": [row.__dict__ for row in single_rows],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


async def main_async(args: argparse.Namespace) -> int:
    cases = load_cases()[: args.limit]
    model = os.getenv("LLM_MODEL_ID", "unknown")

    if args.single_only:
        if not REPORT_JSON.exists():
            print(f"[FAIL] 找不到已有报告: {REPORT_JSON}")
            return 1
        existing = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
        rows = [CaseResult(**row) for row in existing.get("rows", [])]
        model = existing.get("model", model)
        print(f"single-only: reuse {len(rows)} current/rule rows")
    else:
        planner = PlannerAgent(create_llm_client(), max_retries=1)
        rows = []
        print(f"running {len(cases)} cases with {model}")
        for index, case in enumerate(cases, start=1):
            current = await run_current(case, planner)
            rule = await run_rule(case)
            rows.extend([current, rule])
            print(
                f"[{index:02d}/{len(cases)}] {case['id']}: "
                f"current={'OK' if current.ok else 'FAIL'} "
                f"({current.latency_ms:.0f}ms, {current.tokens}t), "
                f"rule={'OK' if rule.ok else 'FAIL'}"
            )

    single_rows: list[CaseResult] = []
    if args.single_limit > 0:
        single_planner = PlannerAgent(
            create_llm_client(),
            max_retries=0,
        )
        for index, case in enumerate(cases[: args.single_limit], start=1):
            row = await run_current_for_mode(case, single_planner, "single")
            single_rows.append(row)
            print(
                f"[single {index}/{args.single_limit}] {case['id']}: "
                f"{'OK' if row.ok else 'FAIL'}"
                + (f" ({row.error_kind})" if row.error else "")
            )
            if index < args.single_limit and args.single_delay > 0:
                await asyncio.sleep(args.single_delay)

    write_report(rows, single_rows, model)
    print(f"\nwrote {REPORT_MD}")
    print(f"wrote {REPORT_JSON}")
    return 0


async def run_current_for_mode(
    case: dict[str, Any], planner: PlannerAgent, mode: str
) -> CaseResult:
    request = build_request(case)
    started = time.perf_counter()
    try:
        result, _ = await run_llm_pipeline_context_async(request, planner)
        elapsed = (time.perf_counter() - started) * 1000
        row = evaluate_result(case, mode, result, elapsed)
        return row
    except Exception as exc:  # noqa: BLE001
        elapsed = (time.perf_counter() - started) * 1000
        return error_result(case, mode, exc, elapsed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Day 6 evaluation harness")
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--single-limit", type=int, default=5)
    parser.add_argument(
        "--single-only",
        action="store_true",
        help="复用现有 report.json 的 current/rule 行，只重跑 single 基线",
    )
    parser.add_argument(
        "--single-delay",
        type=float,
        default=1.0,
        help="single 基线每个 case 之间的间隔秒数，降低触发限流的概率",
    )
    args = parser.parse_args(argv)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
