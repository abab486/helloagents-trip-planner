"""Async DAG executor with per-node timeout, retry and failure isolation.

Semantics:
    - required node failure  -> node failed; downstream nodes are skipped
    - optional node failure  -> node degraded; downstream nodes still run
    - condition false        -> node skipped; downstream nodes still run
    - skipped dependencies   -> downstream still runs (intentional branch skip)

This is a static DAG executor, not a workflow engine. It intentionally has no
persistence/checkpointing; that keeps the control plane small and testable.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .context import NodeResult, NodeStatus, TraceEvent, TripContext
from .graph import Graph, NodeSpec


class ExecutionResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    success: bool
    statuses: dict[str, NodeStatus] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    trace: list[TraceEvent] = Field(default_factory=list)
    failed: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    elapsed_ms: float = 0.0


class DAGExecutor:
    """Execute a Graph against a TripContext."""

    async def run(self, graph: Graph, context: TripContext) -> ExecutionResult:
        graph.validate()
        started = time.perf_counter()
        trace_start = len(context.trace)

        statuses: dict[str, NodeStatus] = {}
        outputs: dict[str, Any] = {}
        failed: list[str] = []
        skipped: list[str] = []

        for layer in graph.layers():
            runnable: list[NodeSpec] = []

            for name in layer:
                spec = graph.get(name)

                if spec.when is not None and not spec.when(context):
                    result = NodeResult(
                        status=NodeStatus.skipped,
                        meta={"reason": "condition_false"},
                    )
                    self._record(context, spec, result, 0.0)
                    statuses[name] = result.status
                    outputs[name] = None
                    skipped.append(name)
                    continue

                blocked_by = [
                    dep
                    for dep in spec.depends_on
                    if statuses.get(dep) == NodeStatus.failed
                ]
                if blocked_by:
                    result = NodeResult(
                        status=NodeStatus.skipped,
                        meta={
                            "reason": "dependency_failed",
                            "blocked_by": blocked_by,
                        },
                    )
                    self._record(context, spec, result, 0.0)
                    statuses[name] = result.status
                    outputs[name] = None
                    skipped.append(name)
                    continue

                runnable.append(spec)

            if not runnable:
                continue

            results = await asyncio.gather(
                *(self._execute_node(spec, context) for spec in runnable)
            )
            for spec, (result, duration_ms) in zip(runnable, results):
                statuses[spec.name] = result.status
                outputs[spec.name] = result.data
                self._record(context, spec, result, duration_ms)
                if result.status == NodeStatus.failed:
                    failed.append(spec.name)
                elif result.status == NodeStatus.skipped:
                    skipped.append(spec.name)

        success = not any(
            graph.get(name).required and status == NodeStatus.failed
            for name, status in statuses.items()
        )

        return ExecutionResult(
            success=success,
            statuses=statuses,
            outputs=outputs,
            trace=list(context.trace[trace_start:]),
            failed=failed,
            skipped=skipped,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    async def _execute_node(
        self,
        spec: NodeSpec,
        context: TripContext,
    ) -> tuple[NodeResult, float]:
        started = time.perf_counter()
        attempts = spec.retries + 1
        last_result = NodeResult.failed(f"{spec.name} 未执行")

        for attempt in range(1, attempts + 1):
            try:
                call = self._invoke(spec, context)
                if spec.timeout_s is not None:
                    result = await asyncio.wait_for(call, timeout=spec.timeout_s)
                else:
                    result = await call
            except asyncio.TimeoutError:
                result = NodeResult.failed(
                    f"{spec.name} 超时（>{spec.timeout_s}s）"
                )
            except Exception as exc:  # noqa: BLE001 - node failure is data
                result = NodeResult.failed(f"{type(exc).__name__}: {exc}")

            if not isinstance(result, NodeResult):
                result = NodeResult.failed(
                    f"{spec.name} 返回了 {type(result).__name__}，不是 NodeResult"
                )

            result.meta["attempts"] = attempt
            if result.status in {
                NodeStatus.ok,
                NodeStatus.degraded,
                NodeStatus.skipped,
            }:
                return result, (time.perf_counter() - started) * 1000

            last_result = result
            if attempt < attempts:
                await asyncio.sleep(spec.retry_delay_s)

        if not spec.required:
            return (
                NodeResult.degraded(
                    data=last_result.data,
                    error=last_result.error or f"{spec.name} 可选节点失败",
                    original_status="failed",
                    attempts=attempts,
                ),
                (time.perf_counter() - started) * 1000,
            )

        last_result.meta["attempts"] = attempts
        return last_result, (time.perf_counter() - started) * 1000

    async def _invoke(self, spec: NodeSpec, context: TripContext) -> Any:
        func = spec.func
        is_async = inspect.iscoroutinefunction(func) or inspect.iscoroutinefunction(
            getattr(func, "__call__", None)
        )
        if is_async:
            return await func(context)  # type: ignore[misc]

        # Sync node: keep the event loop responsive. Note: asyncio.wait_for
        # cannot stop a thread that already started; a timed-out sync node may
        # continue in the background. Async nodes are preferred for IO.
        result = await asyncio.to_thread(func, context)  # type: ignore[arg-type]
        if inspect.isawaitable(result):
            return await result
        return result

    @staticmethod
    def _record(
        context: TripContext,
        spec: NodeSpec,
        result: NodeResult,
        duration_ms: float,
    ) -> None:
        context.record(
            spec.name,
            result,
            duration_ms=duration_ms,
            required=spec.required,
        )
