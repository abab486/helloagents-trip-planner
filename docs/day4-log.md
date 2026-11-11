# Day 4 Log

## 今天完成

### API v1

- `POST /api/v1/trips`
  - 请求：`TripRequest`
  - 响应：`TripPlanResponse`（`data` + `trip_id` + `request_id` + `cached`）
  - 支持 `Idempotency-Key`
- `POST /api/v1/trips/{trip_id}/recalculate`
  - 编辑后的 `PlanDraft` 重新校验、重算预算
- `GET /api/v1/graph`
  - 返回 DAG Mermaid
- `GET /api/v1/health` + `GET /health`
  - 返回 cache backend、LLM 是否配置、模型名、图节点数
- 旧的 `/api/trip/plan` 保留可回滚，新前端走 `/api/v1`

### Redis / 缓存

- `app/infra/cache.py`
  - `REDIS_URL` / `REDIS_HOST` 配置时使用 Redis
  - **未配置或连接失败自动回退 MemoryCache**
  - 同一接口覆盖：计划缓存、幂等、限流、行程快照
- 计划缓存：`plan:{request_hash}`，默认 1h
- 幂等：`idem:{Idempotency-Key}`，默认 10min
- 限流：`rate:{ip}:{minute}`，默认 10 次/分钟
- 行程快照：`trip:{trip_id}`，用于 recalculate

### 并发与状态

- 每个请求独立 `TripContext`
- Planner 无 history；Tool/LLM 调用不带跨请求状态
- 并发测试：两个不同日期的请求同时执行，结果日期不串

### 日志与请求追踪

- `app/infra/logging.py`
  - UTF-8 输出，不使用 emoji
  - 格式含 `request_id`
- `app/api/middleware.py`
  - 生成/透传 `X-Request-ID`
  - 记录 method/path/status/耗时
- 响应头返回 `X-Request-ID`，CORS 已暴露该 header

### 依赖

- `requirements.txt` 增加 `redis>=5.0.0`
- `.env.example` 增加 `REDIS_URL`、`RATE_LIMIT_PER_MINUTE`、DB 配置

## 验证结果

```text
完整后端测试: 100 passed
```

真实 API 冒烟（DeepSeek）：

```text
POST /api/v1/trips -> 200
耗时约 9.7s
trip_id=trip_3ad24537dc0c
budget=645, over=0
tokens=5567
trace: load_dataset -> plan -> validate -> budget -> render
X-Request-ID 与响应体 request_id 一致
```

缓存/幂等/限流/重算/并发测试均通过，且测试不依赖 Redis：

```text
tests/test_cache.py
tests/test_trip_service.py
tests/test_api_v1.py
```

## 接口示例

```bash
curl -X POST http://localhost:8000/api/v1/trips \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: demo-001" \
  -d '{
    "city": "镇江",
    "start_date": "2026-11-14",
    "end_date": "2026-11-15",
    "travel_days": 2,
    "transportation": "公共交通",
    "accommodation": "经济型酒店",
    "preferences": ["历史文化"],
    "budget_limit": 800
  }'
```

## 已知边界

- 未配置 Redis 时使用单进程 MemoryCache；多 worker 部署需要配置 `REDIS_URL`。
- `recalculate` 依赖快照 TTL（默认 1h），过期后返回 404。
- 旧 `/api/trip/plan` 仍使用旧链路，前端迁移到 v1 后再删除。
- 预算超限目前只返回 `over_budget`，二次规划留给后续增强。

## 明天 Day 5 的输入

- 前端首页改为镇江场景
- 结果页接 `/api/v1/trips`
- 增加 Trace 时间线、预算来源 badge
- 编辑后调用 `/recalculate`
- 修硬编码 URL、XSS、假进度条
