# Day 7 Log

## 今天完成

### README

- 重写根 [README.md](../README.md)
  - 从“HelloAgents 教程项目”改成“镇江旅行助手”case study
  - 问题定义 → 架构 → 评测 → 快速开始 → 关键取舍 → 边界
  - 放首页/结果页截图
  - 解释为什么不用 RAG / LangGraph / Java 重写
  - 数据/许可/致谢

### 架构文档

- `docs/architecture.md`
  - 系统总览 Mermaid
  - DAG 图
  - LLM 职责边界
  - 硬约束 vs 软偏好
  - 请求级状态 / 缓存 / 限流
  - 失败语义
  - 评测方法
  - Java 映射

### Demo 材料

- `docs/demo-script.md`
  - 3 分钟讲稿
  - 90 秒版本
  - 演示前检查
  - LLM/地图失败时的备用方案
  - 常见追问回答
  - 不要说的话
- `frontend/public/demo-trip.json`
  - 无需 API Key 的静态示例
  - 路由：`/result?demo=1`
- 首页增加“没有 API Key？先看一份示例行程 →”
- 结果页支持 `?demo=1` 读取静态示例

### 截图

- `docs/images/home.png`（1440×1600）
- `docs/images/result.png`（1440×1200）
- 使用 Edge headless 从 Vite preview 构建截图

### 历史基准

- 新增 `docs/benchmarks.md`
  - 464k → 24k → 当前平均 6.3k Token
  - 56.9s → 41s → 当前 P50 13.2s
  - LLM 预算 1315 → 代码重算 1035
  - 测试 28 → 50 → 64 → 100 → 105
- 删除根目录 scratch `base.md`

### 许可与清理

- 新增 `LICENSE`（MIT）
- `.gitignore` 增加 `.edge-screenshot-profile/`
- 保持 `TROUBLESHOOTING.md` 作为调试记录入口

## 验证结果

```text
后端测试: 105 passed
前端构建: 成功（3484 modules）
静态示例: TripPlanResponse schema 校验通过（2 天 / 690 元 / validation passed / 5 trace）
截图: home.png / result.png 已生成
```

## 已知边界

- 截图来自 headless Edge + Vite preview，地图底图可能未完全加载；点位/连线可见。
- Demo 静态 JSON 是离线快照，不代表实时数据。
- README 里的 26.7% 超预算是评测发现，不是失败；后续可做二次规划。
- Docker 仍未在本机实际跑（无 Docker），只做了 YAML 校验。

## 明天 Day 8 的输入

- 20 个面试问答
- 简历 bullet（Java 后端版 / Agent 版）
- 代码阅读笔记
- 3 分钟 Demo 控制到 4 分钟内
- 最终清理与提交
