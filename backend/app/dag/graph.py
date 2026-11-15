"""最小化的、用代码定义的 DAG。

刻意不做一个框架：
    - 节点/边都在 Python 里声明
    - 图是静态的、无环的
    - 条件节点是作用在 TripContext 上的谓词，由代码求值
    - 并行/超时/重试归执行器（见 executor.py）

保持这么小，是为了让控制面能在面试里讲清楚，也方便移植到 Java
（CompletableFuture / StateMachine）。
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from .context import NodeResult, TripContext

NodeFunc = Callable[[TripContext], NodeResult | Awaitable[NodeResult]]
NodePredicate = Callable[[TripContext], bool]

_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class GraphValidationError(ValueError):
    """图结构写错时抛的异常（重名 / 未知依赖 / 成环）。"""


# 不可变的节点规格，图构建完成后节点配置不能改
@dataclass(frozen=True)
class NodeSpec:
    name: str
    func: NodeFunc
    depends_on: tuple[str, ...] = ()
    required: bool = True
    timeout_s: float | None = None
    retries: int = 0
    retry_delay_s: float = 0.0
    when: NodePredicate | None = None
    
    # 简单校验
    def __post_init__(self) -> None:
        if not _NAME_RE.match(self.name):
            raise ValueError(f"非法节点名: {self.name!r}（只允许字母/数字/下划线）")
        if self.timeout_s is not None and self.timeout_s <= 0:
            raise ValueError(f"{self.name}: timeout_s 必须 > 0")
        if self.retries < 0:
            raise ValueError(f"{self.name}: retries 不能为负")
        if self.retry_delay_s < 0:
            raise ValueError(f"{self.name}: retry_delay_s 不能为负")
        object.__setattr__(self, "depends_on", tuple(self.depends_on))

# 可变的节点容器
@dataclass
class Graph:
    """按插入顺序保存 NodeSpec 的 DAG 容器。"""

    _nodes: dict[str, NodeSpec] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    def add(
        self,
        name: str,
        func: NodeFunc,
        *,
        depends_on: tuple[str, ...] | list[str] = (),
        required: bool = True,
        timeout_s: float | None = None,
        retries: int = 0,
        retry_delay_s: float = 0.0,
        when: NodePredicate | None = None,
    ) -> NodeSpec:
        spec = NodeSpec(
            name=name,
            func=func,
            depends_on=tuple(depends_on),
            required=required,
            timeout_s=timeout_s,
            retries=retries,
            retry_delay_s=retry_delay_s,
            when=when,
        )
        self.add_node(spec)
        return spec

    def add_node(self, spec: NodeSpec) -> None:
        if spec.name in self._nodes:
            raise GraphValidationError(f"节点重复: {spec.name}")
        self._nodes[spec.name] = spec

    def get(self, name: str) -> NodeSpec:
        try:
            return self._nodes[name]
        except KeyError as exc:
            raise GraphValidationError(f"未知节点: {name}") from exc

    @property
    def nodes(self) -> tuple[NodeSpec, ...]:
        return tuple(self._nodes.values())

    def __len__(self) -> int:
        return len(self._nodes)

    # ------------------------------------------------------------------
    # Validation / ordering
    # ------------------------------------------------------------------
    # 四个检查：空图 → 依赖存在 → 自依赖 → 环
    def validate(self) -> None:
        if not self._nodes:
            raise GraphValidationError("图为空")

        for spec in self._nodes.values():
            for dep in spec.depends_on:
                if dep not in self._nodes:
                    raise GraphValidationError(
                        f"节点 {spec.name} 依赖不存在的节点: {dep}"
                    )
                if dep == spec.name:
                    raise GraphValidationError(f"节点 {spec.name} 依赖自己")

        # Kahn's algorithm: if not all nodes are emitted, there is a cycle.
        # 这就是"排班"：谁入度为 0 谁先上，上一个就把它下游的入度减一。
        # 复杂度 O(V·E)（没有邻接表，每次扫全表），5 个节点完全够用。
        indegree = {name: len(spec.depends_on) for name, spec in self._nodes.items()}
        ready = deque(name for name in self._nodes if indegree[name] == 0)
        emitted = 0
        while ready:
            name = ready.popleft()
            emitted += 1
            for candidate in self._nodes.values():
                if name in candidate.depends_on:
                    indegree[candidate.name] -= 1
                    if indegree[candidate.name] == 0:
                        ready.append(candidate.name)
        if emitted != len(self._nodes):
            remaining = [name for name, degree in indegree.items() if degree > 0]
            raise GraphValidationError(f"图存在环: {remaining}")
    
    #同一个算法
    def topological_order(self) -> list[str]:
        self.validate()
        indegree = {name: len(spec.depends_on) for name, spec in self._nodes.items()}
        ready = deque(name for name in self._nodes if indegree[name] == 0)
        order: list[str] = []
        while ready:
            name = ready.popleft()
            order.append(name)
            for candidate in self._nodes.values():
                if name in candidate.depends_on:
                    indegree[candidate.name] -= 1
                    if indegree[candidate.name] == 0:
                        ready.append(candidate.name)
        return order

    # 最长路径分层，[["load_dataset"], ["plan"], ["validate"], ["budget"], ["render"]]
    # 同样的图构建代码永远产出同样的执行顺序——这是"可复现"的基础，评测依赖它
    def layers(self) -> list[list[str]]:
        """把节点切成"可并行的批次"。

        第 n 层只依赖更早的层；同一层内的节点互不依赖，可以并发执行。
        """
        order = self.topological_order()
        level: dict[str, int] = {}
        for name in order:
            deps = self._nodes[name].depends_on
            level[name] = max((level[dep] + 1 for dep in deps), default=0)
        max_level = max(level.values(), default=-1)
        return [
            [name for name in order if level[name] == current]
            for current in range(max_level + 1)
        ]

    # ------------------------------------------------------------------
    # Visualization
    # ------------------------------------------------------------------
    # 图转换为文档，提供前端渲染
    def to_mermaid(self) -> str:
        self.validate()
        lines = ["flowchart LR"]
        for spec in self._nodes.values():
            suffix = "" if spec.required else " (optional)"
            if spec.when is not None:
                label = f"{spec.name}?{suffix}"
                shape = f'{{{{"{label}"}}}}'
            else:
                label = f"{spec.name}{suffix}"
                shape = f'["{label}"]'
            lines.append(f"  {spec.name}{shape}")
        for spec in self._nodes.values():
            for dep in spec.depends_on:
                lines.append(f"  {dep} --> {spec.name}")
        return "\n".join(lines)
