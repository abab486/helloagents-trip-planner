"""LLM 规划链路：带真实 Planner 的 DAG，没有假数据兜底。

图：
    load_dataset -> plan(LLM) -> validate -> budget -> render

这是 Day 3 的路径。Day 1 的走路骨架保留为确定性回归基线，但本链路在
LLM 产不出合法 PlanDraft 时直接失败，而不是返回一份编造的行程。
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


# 闭包工厂，闭包是最轻的适配器：把依赖在构造期捕获，对外只暴露标准签名。
# 换成 functools.partial 也行，但闭包能顺手做参数校验，planner=None 是合法输入
# 节点之间不通过返回值传数据，而是通过修改同一个 TripContext 实例
def make_llm_plan_node(planner: PlannerAgent | None):
    """把一个 PlannerAgent 绑成标准的 DAG 节点。"""

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


# graph 是静态的，DAGExecutor 只执行它，不修改它。节点之间不通过返回值传数据，而是通过修改同一个 TripContext 实例 
# 纯链路，没有并行，本类只提供一个plan节点，load_dataset / validate / budget / render 四个全部从 walking_skeleton.py 导入  
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


"""
消费者	期望的契约	为什么不同
Web 框架FastAPI	 async def,异常冒泡	不能阻塞事件循环；错误要靠 HTTP 状态码表达
脚本 / CLI	 同步、返回退出码、打印到 stdout	命令行没有事件循环，失败要给人看
测试	 同步、可断言、可注入替身	pytest 默认同步,planner 参数就是为了注入 FakePlanner
其他服务代码（评测）	异步 + 中间状态	要统计 token、attempts、facts
"""

# 1惰性构造，2异步执行，3失败时抛异常，4成功时返回 TripResult 和 TripContext
# 入口1：异步接口，API使用
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


# 入口2：返回TripResult，只要结果的类用 空跑，被下一个函数内部调用
async def run_llm_pipeline_async(
    request: TripRequest,
    planner: PlannerAgent | None = None,
) -> TripResult:
    result, _ = await run_llm_pipeline_context_async(request, planner)
    return result


# 入口3：同步接口，CLI/eval使用
def run_llm_pipeline(
    request: TripRequest,
    planner: PlannerAgent | None = None,
) -> TripResult:
    """给 CLI/冒烟脚本用的同步包装；API 走异步版本。"""
    return asyncio.run(run_llm_pipeline_async(request, planner))

# 入口4：主函数，用于 CLI 使用，打印JSON
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
