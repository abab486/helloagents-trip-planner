# Day 6 Log

## 今天完成

### 评测集

- `eval/cases.json`：15 条镇江 case
  - 1/2/3 天
  - 历史文化、美食、自然、亲子、摄影、宗教、休闲
  - solo/couple/family/elderly
  - 公共交通/打车/自驾
  - 预算 300–2000
  - 每条 case 声明期望的 `must_see` ID

### 评测器

- `backend/app/eval/run.py`
  - 当前系统：DAG + LLM Planner（repair=1）
  - 规则保底：`run_walking_skeleton`，零 LLM、零 Token
  - 单次 LLM：Planner repair=0，用于对比“一次生成”的稳定性
  - 指标：结构合法率、must-see 覆盖、ID 幻觉率、预算恒等、超预算率、P50/P95、Token
  - 输出：`eval/report.md`、`eval/report.json`
- 支持 `--single-only` 复用已有 current/rule 结果，只重跑单次基线
- 网络/超时等基础设施失败单独统计，不计入模型质量分母

### 评测结果

| 系统 | 用例 | 结构合法率 | must-see 覆盖 | ID 幻觉率 | 预算恒等 | 超预算率 | P50 | P95 | 平均 Token |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 当前 DAG + LLM | 15 | 100% | 100% | 0% | 100% | 26.7% | 13.2s | 19.2s | 6285 |
| 规则保底 | 15 | 100% | 54.4% | 0% | 100% | 6.7% | 12.6ms | 14.5ms | 0 |
| 单次 LLM（无 repair） | 5 | 100% | 100% | 0% | 100% | 0% | 6.9s | 23.1s | 5656 |

结论：

- 当前系统 15/15 结构合法、must-see 覆盖 100%、ID 幻觉 0；LLM 的偏好匹配明显优于规则保底（54.4%）。
- 规则保底证明“校验 + 预算”链路本身是通的，但它不懂偏好。
- 26.7% 的 case 超预算，说明下一阶段需要“预算内二次规划/替换建议”。
- P50 13.2s、P95 19.2s；主要成本在 Planner 调用。

### 关于本轮出现的 FAIL

第一次评测时有两类失败，均已修复/归类：

1. **规则基线失败**：`run_walking_skeleton()` 内部调用 `asyncio.run()`，而评测器本身已经在事件循环中，触发 “asyncio.run() cannot be called from a running event loop”。
   - 修复：在评测器里用 `asyncio.to_thread(run_walking_skeleton, request)` 执行规则基线。

2. **单次 LLM 基线 2 条 FAIL**：关闭 repair 后，DeepSeek 出现 `Connection error`，被记录为结构失败。
   - 这是基础设施失败，不是模型输出错误；已在评测器中增加 `infra_error` 分类，不计入质量分母。
   - 增加 `--single-delay 2` 后重跑，单次基线 5/5 通过。
   - 最终报告基础设施失败 = 0。

### Docker

- `backend/Dockerfile`
- `frontend/Dockerfile` + `frontend/nginx.conf`
- `docker-compose.yml`
  - `api` + `web` + `mysql` + `redis`
  - web 端口 `8080`，API 端口 `8000`
  - nginx 代理 `/api` 与 `/health`
  - MySQL 初始化挂载 `schema_zhenjiang.sql`

本机未安装 Docker，因此只做了 YAML 语法校验（PyYAML 通过），未实际 `docker compose up`。

### CI

- `.github/workflows/ci.yml`
  - backend：Python 3.11 + pip install + pytest
  - frontend：Node 20 + npm ci + vue-tsc + build
  - 使用 fake LLM 环境变量，不访问真实 API
  - 触发：main / feature/** / PR

## 验证结果

```text
后端测试: 105 passed
前端 vue-tsc: 通过
前端生产构建: 成功（3484 modules）
YAML: docker-compose.yml / ci.yml 解析通过
真实评测: 15 current + 15 rule + 5 single 完成
```

## 复现

```powershell
cd backend
$env:PYTHONIOENCODING="utf-8"

# 完整评测（会调用真实 LLM）
F:\agent\env313\Scripts\python.exe -m app.eval.run --limit 15 --single-limit 5

# 只重跑单次 LLM 基线，复用已有 current/rule
F:\agent\env313\Scripts\python.exe -m app.eval.run --single-only --single-limit 5 --single-delay 2
```

Docker（需要安装 Docker Desktop）：

```powershell
$env:LLM_API_KEY="..."
docker compose up --build
# 前端 http://localhost:8080
# API  http://localhost:8000/docs
```

## 明天 Day 7 的输入

- README 改成 case study
- 架构图 / DAG 图 / 评测表
- 截图 + 90 秒 Demo 视频
- 3 分钟讲稿
- 清理旧代码/旧文档入口
- LICENSE、docs 目录整理
