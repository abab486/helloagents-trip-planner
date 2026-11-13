# Day 2 Log

## 今天完成

- DAG 图契约：`app/dag/graph.py`
  - `NodeSpec`：name / func / depends_on / required / timeout / retries / retry_delay / when
  - `Graph`：节点注册、依赖校验、拓扑排序、分层、循环检测、`to_mermaid()`
- DAG 执行器：`app/dag/executor.py`
  - 同层节点并行
  - 节点级超时、重试、失败隔离
  - `required` 失败 → 下游 skipped
  - `optional` 失败 → degraded，下游继续
  - `when=False` → skipped，下游继续
  - 每个节点写入 `TripContext.trace`
- Walking skeleton 改为 DAG：
  - `load_dataset -> fake_plan -> validate -> budget -> render`
  - `build_skeleton_graph()` 可直接生成 Mermaid
- 测试：`tests/test_dag.py`

## 验证结果

```text
tests/test_dag.py + tests/test_walking_skeleton.py: 22 passed
完整后端测试: 64 passed
```

Walking skeleton 输出保持不变：

```text
2026-11-01 ['A001', 'A002']
2026-11-02 ['A005', 'A006']
budget 690 over 0
validation passed
trace: load_dataset -> fake_plan -> validate -> budget -> render
```

## 设计要点

- **控制面是代码**：节点、边、条件、并行/超时/重试/降级全部由代码决定。
- **LLM 不在 Day 2**：当前节点都是确定性代码；Day 3 只替换 `fake_plan`。
- **失败语义**：
  - required 失败：整体失败，下游 skip；
  - optional 失败：整体继续，节点标记 degraded；
  - 条件 false：节点 skip，视为分支未选中，下游仍可执行。
- **Trace 是一等公民**：每个节点有 status / duration_ms / attempts / required / error。
- **可视化**：`Graph.to_mermaid()` 输出 README/接口可用的图。

## 已知边界

- `asyncio.wait_for(to_thread(...))` 取消不了已经启动的同步线程；超时后线程可能继续跑。
  Day 3+ 的 IO 节点优先用 async；同步节点只用于纯 CPU/快速逻辑。
- 条件谓词目前是同步函数；如果未来需要异步条件，再扩展。

## 明天 Day 3 的输入

- 用 LLM Planner 替换 `fake_plan` 节点。
- 保留 `PlanDraft` 只含 ID 的契约。
- 加 Validator 的 blocking/warning 规则与重试。
- 加 Budget 节点（Day 3 仍可用 CSV 价格，Day 4 接 MySQL）。
- 目标：5 条真实请求跑通，不返回假行程。
