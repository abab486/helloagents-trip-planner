# 历史基准与优化记录

> 这些是开发过程中的真实测量，不是受控 benchmark。  
> 当前正式评测见 [eval/report.md](../eval/report.md)，问题排查见 [TROUBLESHOOTING.md](../TROUBLESHOOTING.md)。

---

## 1. Token：464,170 → 24,052

早期版本把 Agent 当成长会话使用，单例 Agent 的 `_history` 跨请求累积，导致第 N 次请求把前面所有对话重新发给模型。

| 阶段 | 单次请求 Token（记录值） | 说明 |
|---|---:|---|
| 修复前 | 464,170 | 历史跨请求累积 |
| 清空 history + ContextBuilder | 25,407 | 每次请求干净上下文 |
| 预算重算版本 | 24,052 | 进一步压缩 |
| 当前 DAG + 15 条评测 | 平均 6,285 | 只给候选 ID，不给长 Markdown |

关键点：

- 最大头不是单次循环，而是 Planner 的 JSON 输出被下一次请求重放；
- 修复不是“改 prompt”，而是 `clear_history()` + 结构化上下文；
- 当前版本把“数据获取”从 3 个 LLM 子 Agent 改成工具层/代码，Token 进一步下降。

---

## 2. 端到端耗时

| 阶段 | 记录值 | 说明 |
|---|---:|---|
| 串行 3 个子 Agent | 56.9s | 景点 → 天气 → 酒店 |
| 三路并行 | 约 41–46s | 并行 + 预算重算 |
| 当前 DAG + 15 条评测 P50 | 13.2s | Planner + 校验 + 预算 + render |
| 当前 DAG + 15 条评测 P95 | 19.2s | 长 case / 模型波动 |

当前耗时主要花在 Planner LLM 调用；工具层是毫秒级 CSV 读取。

---

## 3. 预算：LLM 估值 → 代码计算

早期行程：

```text
total_attractions: 115
total_hotels: 600
total_meals: 480
total_transportation: 120
total: 1315
```

这些数字由 LLM 在 JSON 里直接写，重新生成会变；而且明细与汇总可能对不上。

加入 BudgetCalculator + 价格库后：

| 项目 | LLM 估值 | 代码重算 |
|---|---:|---:|
| 门票 | 115 | 125 |
| 酒店 | 600 | 400（3 天 2 晚 × 200） |
| 餐饮 | 480 | 450（30/50/70 × 3 天） |
| 交通 | 120 | 60（20 元/天 × 3 天） |
| **合计** | **1315** | **1035** |

当前 DAG 版本进一步把 Planner 输出改成 ID：

- Planner 不写价格；
- Budget 按 ID 查数据；
- `total = sum(lines)` 由 `BudgetReport` validator 强制；
- 25 条测试（后续扩展到 105 条）覆盖命中、兜底、晚数、预算恒等。

---

## 4. 测试与评测

| 阶段 | 测试数 | 说明 |
|---|---:|---|
| 初始 | 28 | 预算/归一化/DB/并行 |
| 数据 + 契约 + skeleton | 50 | 镇江数据/领域模型/walking skeleton |
| DAG | 64 | 拓扑/并行/超时/重试/失败隔离 |
| LLM + API | 100 | Planner/Validator/Budget/API/Redis/并发 |
| 当前 | 105 | 加 eval harness 测试 |

正式评测（2026-11-11，DeepSeek）：

- 15 条当前系统：结构 100%，must-see 100%，ID 幻觉 0%，平均 6.3k Token；
- 15 条规则保底：结构 100%，must-see 54.4%，0 Token；
- 5 条单次 LLM：结构 100%，must-see 100%，P95 23.1s。

---

## 5. 这些数字怎么用

面试里建议这样讲：

> “我不只讲‘接了大模型’，我记录了三个可验证的变化：  
> 1）Token 从 46 万降到平均 6k，靠的是去掉历史累积、结构化候选和工具层；  
> 2）预算从 LLM 估值改成代码计算，明细恒等；  
> 3）用 15 条 case 对比规则保底和单次 LLM，而不是凭感觉说效果更好。”

不要把历史数字包装成受控 benchmark；说清楚“单机、单城市、个人项目、参考价”。
