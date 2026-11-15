"""DAG 图/执行器测试：顺序、并发、重试、超时、失败隔离。

图（graph）和执行器（executor）分开测：前者只管"画得对不对"，
后者只管"跑得对不对"，出问题时一眼定位到是哪一层。
"""

import asyncio
import time

import pytest

from app.dag.context import NodeResult, NodeStatus, TripContext
from app.dag.executor import DAGExecutor
from app.dag.graph import Graph, GraphValidationError
from app.dag.walking_skeleton import build_skeleton_graph
from app.domain.models import TripRequest


# 最小可用的请求，只为了把 TripContext 构造出来（多数节点并不读它）
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


# 造一个立刻成功、把 label 原样返回的异步节点，当"万能零件"用
def ok_node(label: str):
    async def run(_context: TripContext) -> NodeResult:
        return NodeResult.ok(label)

    return run


# ---------------------------------------------------------------------------
# Graph：图的构建与校验（只讨论结构，不执行）
# ---------------------------------------------------------------------------
# 菱形依赖 a -> (b, c) -> d：拓扑序只有一种，
# 分层必须把互不依赖的 b、c 塞进同一层
def test_layers_and_topological_order():
    graph = Graph()
    graph.add("a", ok_node("a"))
    graph.add("b", ok_node("b"), depends_on=("a",))
    graph.add("c", ok_node("c"), depends_on=("a",))
    graph.add("d", ok_node("d"), depends_on=("b", "c"))

    assert graph.topological_order() == ["a", "b", "c", "d"]
    assert graph.layers() == [["a"], ["b", "c"], ["d"]]


# x 等 y、y 等 x：成环必须在校验期就拒绝，否则执行时永远开不了工
def test_cycle_is_rejected():
    graph = Graph()
    graph.add("x", ok_node("x"), depends_on=("y",))
    graph.add("y", ok_node("y"), depends_on=("x",))

    with pytest.raises(GraphValidationError, match="环"):
        graph.layers()


# 依赖一个不存在的节点：属于写错代码，不是运行时失败，构造完就该报
def test_unknown_dependency_is_rejected():
    graph = Graph()
    graph.add("a", ok_node("a"), depends_on=("missing",))

    with pytest.raises(GraphValidationError, match="不存在"):
        graph.validate()


# 同名节点：字典里后加的会悄悄覆盖前一个，所以直接报错更安全
def test_duplicate_node_is_rejected():
    graph = Graph()
    graph.add("a", ok_node("a"))

    with pytest.raises(GraphValidationError, match="重复"):
        graph.add("a", ok_node("a"))


# 导出的 Mermaid 要能表达边和 optional 标记——GET /api/v1/graph 直接返回它，
# 所以这张"图文档"不会和代码漂移
def test_mermaid_contains_edges():
    graph = Graph()
    graph.add("a", ok_node("a"))
    graph.add("b", ok_node("b"), depends_on=("a",), required=False)

    mermaid = graph.to_mermaid()
    assert "flowchart LR" in mermaid
    assert "a --> b" in mermaid
    assert "optional" in mermaid


# ---------------------------------------------------------------------------
# Executor：调度、并发与容错（这里才开始真的"跑图"）
# ---------------------------------------------------------------------------
# 两个各睡 0.2s 的独立节点：并发总耗时接近 0.2s，
# 串行必然 ≥0.4s，所以 0.35 是能区分两者的阈值
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
    # 串行要 ≥0.4s，并行应该贴着 0.2s
    assert elapsed < 0.35


# required 节点炸了：下游 skipped、无关节点照跑、success=False。
# 这三条一起断言，才能证明"隔离"而不是"整张图停了"
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


# optional 节点炸了：转 degraded，下游照跑，success 仍为 True，
# 同时 context.degraded 被置位（前端据此显示"部分内容不可用"）
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


# 另一种降级来源：optional 节点没抛异常，主动返回了 failed，
# 执行器也要把它包装成 degraded，并把错误留在 trace 里
def test_optional_node_returning_failed_degrades():
    async def soft_failure_result(_context: TripContext) -> NodeResult:
        return NodeResult.failed("optional data unavailable")

    graph = Graph()
    graph.add("soft", soft_failure_result, required=False)

    execution = asyncio.run(DAGExecutor().run(graph, make_context()))

    assert execution.success is True
    assert execution.statuses["soft"] == NodeStatus.degraded
    assert any(event.error for event in execution.trace)


# when 为假只跳过自己，下游照跑——这就是"跳过不阻塞"，
# 用来支持条件分支；代价是下游要自己处理"上游没给数据"
def test_condition_false_skips_node_but_downstream_runs():
    graph = Graph()
    graph.add("maybe", ok_node("maybe"), when=lambda _context: False)
    graph.add("after", ok_node("after"), depends_on=("maybe",))

    execution = asyncio.run(DAGExecutor().run(graph, make_context()))

    assert execution.success is True
    assert execution.statuses["maybe"] == NodeStatus.skipped
    assert execution.statuses["after"] == NodeStatus.ok
    assert "maybe" in execution.skipped


# 0.2s 的节点配 0.05s 超时 -> failed，trace 里留下"超时"字样。
# 注意：这里用的是 async 节点，wait_for 能真正取消它；
# 生产里五个节点都是同步函数，走线程池，超时后线程仍在跑
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


# retries=1 表示最多跑 2 次：第一次抛、第二次成，
# meta.attempts 要如实记 2（这是排查"到底重试了没"的唯一证据）
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


# 每个节点跑完由执行器记一条 trace：顺序=执行顺序，状态全 ok，耗时非负
def test_trace_records_each_node():
    graph = Graph()
    graph.add("a", ok_node("a"))
    graph.add("b", ok_node("b"), depends_on=("a",))

    execution = asyncio.run(DAGExecutor().run(graph, make_context()))

    assert [event.node_id for event in execution.trace] == ["a", "b"]
    assert all(event.status == NodeStatus.ok for event in execution.trace)
    assert all(event.duration_ms >= 0 for event in execution.trace)


# 骨架图是纯链：五层各一个节点。
# 这条同时是"并行能力存在、但当前图没有可并行分支"的证据
def test_skeleton_graph_has_five_layers():
    graph = build_skeleton_graph()
    assert graph.layers() == [
        ["load_dataset"],
        ["fake_plan"],
        ["validate"],
        ["budget"],
        ["render"],
    ]
