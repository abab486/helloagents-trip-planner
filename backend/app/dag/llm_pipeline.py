"""LLM planning pipeline: DAG with a real Planner, no fake fallback.

Graph:
    load_dataset -> plan(LLM) -> validate -> budget -> render

This is the Day 3 path. The Day 1 walking skeleton remains available as a
deterministic regression baseline, but this pipeline fails loudly instead of
returning a fabricated plan when the LLM cannot produce a valid PlanDraft.
"""

from __future__ import annotations

import asyncio
import json

from ..agents.planner import PlannerAgent
from ..domain.models import TripRequest
from ..llm.client import create_llm_client
from .context import NodeResult, TripContext, TripResult
from .executor import DAGExecutor
from .graph import Graph
from .walking_skeleton import (
    budget_node,
    build_cli_parser,
    build_request_from_args,
    load_dataset_node,
    render_node,
    validate_node,
)


def make_llm_plan_node(planner: PlannerAgent | None):
    """Bind a PlannerAgent to a DAG node."""

    def plan_node(context: TripContext) -> NodeResult:
        if planner is None:
            raise RuntimeError("LLM planner 未配置")
        if context.facts is None:
            raise RuntimeError("LLM plan 节点需要 facts")
        result = planner.plan(context.request, context.facts)
        context.plan = result.plan
        return NodeResult.ok(
            {"days": len(result.plan.days)},
            planner_attempts=result.attempts,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
            model=result.model,
            prompt_version=result.prompt_version,
        )

    return plan_node


def build_llm_graph(planner: PlannerAgent | None) -> Graph:
    graph = Graph()
    graph.add("load_dataset", load_dataset_node)
    graph.add(
        "plan",
        make_llm_plan_node(planner),
        depends_on=("load_dataset",),
    )
    graph.add("validate", validate_node, depends_on=("plan",))
    graph.add("budget", budget_node, depends_on=("validate",))
    graph.add("render", render_node, depends_on=("budget",))
    return graph


async def run_llm_pipeline_context_async(
    request: TripRequest,
    planner: PlannerAgent | None = None,
) -> tuple[TripResult, TripContext]:
    planner = planner or PlannerAgent(create_llm_client())
    context = TripContext(request=request)
    execution = await DAGExecutor().run(build_llm_graph(planner), context)

    if not execution.success:
        errors = [event.error for event in execution.trace if event.error]
        raise RuntimeError(
            "LLM 规划失败: " + ("; ".join(errors) if errors else str(execution.failed))
        )

    result = execution.outputs.get("render")
    if not isinstance(result, TripResult):
        raise RuntimeError("render 节点没有返回 TripResult")

    result.trace = list(execution.trace)
    result.degraded = context.degraded
    return result, context


async def run_llm_pipeline_async(
    request: TripRequest,
    planner: PlannerAgent | None = None,
) -> TripResult:
    result, _ = await run_llm_pipeline_context_async(request, planner)
    return result


def run_llm_pipeline(
    request: TripRequest,
    planner: PlannerAgent | None = None,
) -> TripResult:
    """Synchronous wrapper for CLI/smoke scripts; API uses the async version."""
    return asyncio.run(run_llm_pipeline_async(request, planner))


def main(argv: list[str] | None = None) -> int:
    parser = build_cli_parser()
    args = parser.parse_args(argv)
    try:
        request = build_request_from_args(args)
        result = run_llm_pipeline(request)
    except Exception as exc:  # noqa: BLE001 - CLI should print a useful error
        print(f"[FAIL] {exc}")
        return 2
    print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
