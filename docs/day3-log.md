# Day 3 Log

## 今天完成

- LLM Gateway：`app/llm/client.py`
  - OpenAI-compatible（OpenAI / DeepSeek / Qwen / 本地）
  - JSON mode，失败自动降级为普通 chat
  - 记录 prompt/completion/total tokens、latency、finish_reason
- Planner：`app/agents/planner.py`
  - 只输出 ID，不输出名称/地址/价格/坐标
  - 严格 JSON + `PlanDraft` Pydantic 校验
  - 非法 JSON / 未知 ID / 闭馆日 → 带错误反馈重试 1 次
  - 仍失败抛 `PlannerError`，**不返回假行程**
- LLM DAG：`app/dag/llm_pipeline.py`
  - `load_dataset -> plan -> validate -> budget -> render`
  - 失败时整体失败，不降级为 fake planner
- Validator/Budget 节点复用：
  - `validate_plan` 已覆盖 ID、闭馆日、每日时长、三餐、酒店、重复景点、预算恒等
  - `budget_plan` 保持 `total == sum(lines)` 与 `over_budget`
- 真实请求冒烟：`app/eval/smoke_llm.py`
- 测试：
  - `tests/test_llm_planner.py`
  - `tests/test_plan_validation.py`
- 依赖：`requirements.txt` 增加 `openai`、`requests`

## 真实请求结果（DeepSeek，2026-11-11）

```text
[OK] 2d-history-800: 2d, budget=645, over=0,  tokens=6718, attempts=1
[OK] 1d-food-600:    1d, budget=500, over=0,  tokens=4609, attempts=1
[OK] 3d-nature-1500: 3d, budget=1515, over=15, tokens=8818, attempts=1
[OK] 2d-family-1000: 2d, budget=1020, over=20, tokens=4623, attempts=1
[OK] 2d-elderly-1200: 2d, budget=1000, over=0, tokens=6235, attempts=1

summary: 5/5 passed
```

说明：

- 5 条请求都通过了 Validator，且预算明细相加等于总额。
- 2 条略超预算（15/20 元），这是 Day 4 “预算内二次规划”的输入，不是数据造假。
- Token 约 4.6k–8.8k，仍低于旧链路的约 24k。
- 真实请求不放进 pytest；CI 只用 FakeLLM。

## 测试结果

```text
完整后端测试: 79 passed
```

## 设计要点

- **Planner 不碰事实**：候选景点/酒店/餐厅以 `brief()` 形式给出，Planner 只选 ID。
- **早失败、可修复**：Planner 内部先查 ID / 闭馆日 / 三餐，发现问题带错误重试。
- **最终失败就报错**：LLM 两次都失败时抛 `PlannerError`，不生成“城市景点1”。
- **Trace 带 LLM 成本**：plan 节点记录 `planner_attempts / prompt_tokens / completion_tokens / total_tokens / model / prompt_version`。
- **DAG 不变**：Day 2 的并行/超时/重试/降级/Trace 直接复用。

## 明天 Day 4 的输入

- 把 LLM DAG 接到 FastAPI：`POST /api/v1/trips`、`/recalculate`、`/graph`、`/health`
- Redis：节点缓存、计划缓存、幂等键、限流
- 并发隔离：每个请求独立 `TripContext`，禁止共享 Agent history
- 日志：UTF-8、request_id、node trace
- 预算内二次规划（可选，优先做 API/Redis）
