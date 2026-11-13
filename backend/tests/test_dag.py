"""DAG graph/executor tests: ordering, parallel, retry, timeout, isolation."""

import asyncio
import time

import pytest

from app.dag.context import NodeResult, NodeStatus, TripContext
from app.dag.executor import DAGExecutor
from app.dag.graph import Graph, GraphValidationError
from app.dag.walking_skeleton import build_skeleton_graph
from app.domain.models import TripRequest


def make_context() -> TripContext:
    return TripContext(
        request=TripRequest(
            city="镇江",
            start_date="2026-11-01",
            end_date="2026-11-02",
            travel_days=2,
            transportation="公共交通",
            accommodation="经济型酒店",
            preferences=["历史文化"],
            budget_limit=800,
        )
    )


def ok_node(label: str):
    async def run(_context: TripContext) -> NodeResult:
        return NodeResult.ok(label)

    return run


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------
def test_layers_and_topological_order():
    graph = Graph()
    graph.add("a", ok_node("a"))
    graph.add("b", ok_node("b"), depends_on=("a",))
    graph.add("c", ok_node("c"), depends_on=("a",))
    graph.add("d", ok_node("d"), depends_on=("b", "c"))

    assert graph.topological_order() == ["a", "b", "c", "d"]
    assert graph.layers() == [["a"], ["b", "c"], ["d"]]


def test_cycle_is_rejected():
    graph = Graph()
    graph.add("x", ok_node("x"), depends_on=("y",))
    graph.add("y", ok_node("y"), depends_on=("x",))

    with pytest.raises(GraphValidationError, match="环"):
        graph.layers()


def test_unknown_dependency_is_rejected():
    graph = Graph()
    graph.add("a", ok_node("a"), depends_on=("missing",))

    with pytest.raises(GraphValidationError, match="不存在"):
        graph.validate()


def test_duplicate_node_is_rejected():
    graph = Graph()
    graph.add("a", ok_node("a"))

    with pytest.raises(GraphValidationError, match="重复"):
        graph.add("a", ok_node("a"))


def test_mermaid_contains_edges():
    graph = Graph()
    graph.add("a", ok_node("a"))
    graph.add("b", ok_node("b"), depends_on=("a",), required=False)

    mermaid = graph.to_mermaid()
    assert "flowchart LR" in mermaid
    assert "a --> b" in mermaid
    assert "optional" in mermaid


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------
def test_independent_nodes_run_in_parallel():
    async def slow_ok(_context: TripContext) -> NodeResult:
        await asyncio.sleep(0.2)
        return NodeResult.ok("done")

    graph = Graph()
    graph.add("a", slow_ok)
    graph.add("b", slow_ok)

    started = time.perf_counter()
    execution = asyncio.run(DAGExecutor().run(graph, make_context()))
    elapsed = time.perf_counter() - started

    assert execution.success is True
    assert execution.statuses == {"a": NodeStatus.ok, "b": NodeStatus.ok}
    # Serial would be >= 0.4s; parallel should be close to 0.2s.
    assert elapsed < 0.35


def test_required_failure_skips_downstream_but_not_independent():
    async def boom(_context: TripContext) -> NodeResult:
        raise RuntimeError("boom")

    graph = Graph()
    graph.add("boom", boom)
    graph.add("after", ok_node("after"), depends_on=("boom",))
    graph.add("independent", ok_node("independent"))

    execution = asyncio.run(DAGExecutor().run(graph, make_context()))

    assert execution.success is False
    assert execution.statuses["boom"] == NodeStatus.failed
    assert execution.statuses["after"] == NodeStatus.skipped
    assert execution.statuses["independent"] == NodeStatus.ok
    assert execution.outputs["independent"] == "independent"
    assert "boom" in execution.failed


def test_optional_failure_degrades_and_downstream_still_runs():
    async def soft_fail(_context: TripContext) -> NodeResult:
        raise RuntimeError("weather down")

    graph = Graph()
    graph.add("weather", soft_fail, required=False)
    graph.add("plan", ok_node("plan"), depends_on=("weather",))

    context = make_context()
    execution = asyncio.run(DAGExecutor().run(graph, context))

    assert execution.success is True
    assert execution.statuses["weather"] == NodeStatus.degraded
    assert execution.statuses["plan"] == NodeStatus.ok
    assert context.degraded is True


def test_optional_node_returning_failed_degrades():
    async def soft_failure_result(_context: TripContext) -> NodeResult:
        return NodeResult.failed("optional data unavailable")

    graph = Graph()
    graph.add("soft", soft_failure_result, required=False)

    execution = asyncio.run(DAGExecutor().run(graph, make_context()))

    assert execution.success is True
    assert execution.statuses["soft"] == NodeStatus.degraded
    assert any(event.error for event in execution.trace)


def test_condition_false_skips_node_but_downstream_runs():
    graph = Graph()
    graph.add("maybe", ok_node("maybe"), when=lambda _context: False)
    graph.add("after", ok_node("after"), depends_on=("maybe",))

    execution = asyncio.run(DAGExecutor().run(graph, make_context()))

    assert execution.success is True
    assert execution.statuses["maybe"] == NodeStatus.skipped
    assert execution.statuses["after"] == NodeStatus.ok
    assert "maybe" in execution.skipped


def test_timeout_marks_node_failed():
    async def too_slow(_context: TripContext) -> NodeResult:
        await asyncio.sleep(0.2)
        return NodeResult.ok("late")

    graph = Graph()
    graph.add("slow", too_slow, timeout_s=0.05)

    execution = asyncio.run(DAGExecutor().run(graph, make_context()))

    assert execution.success is False
    assert execution.statuses["slow"] == NodeStatus.failed
    assert any("超时" in (event.error or "") for event in execution.trace)


def test_retry_succeeds_on_second_attempt():
    attempts = {"count": 0}

    async def flaky(_context: TripContext) -> NodeResult:
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise RuntimeError("first attempt fails")
        return NodeResult.ok("recovered")

    graph = Graph()
    graph.add("flaky", flaky, retries=1)

    execution = asyncio.run(DAGExecutor().run(graph, make_context()))

    assert execution.success is True
    assert execution.statuses["flaky"] == NodeStatus.ok
    assert attempts["count"] == 2
    assert execution.trace[0].meta["attempts"] == 2


def test_trace_records_each_node():
    graph = Graph()
    graph.add("a", ok_node("a"))
    graph.add("b", ok_node("b"), depends_on=("a",))

    execution = asyncio.run(DAGExecutor().run(graph, make_context()))

    assert [event.node_id for event in execution.trace] == ["a", "b"]
    assert all(event.status == NodeStatus.ok for event in execution.trace)
    assert all(event.duration_ms >= 0 for event in execution.trace)


def test_skeleton_graph_has_five_layers():
    graph = build_skeleton_graph()
    assert graph.layers() == [
        ["load_dataset"],
        ["fake_plan"],
        ["validate"],
        ["budget"],
        ["render"],
    ]
