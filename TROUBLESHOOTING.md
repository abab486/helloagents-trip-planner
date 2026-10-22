# 问题记录与排查总结

本文档用于记录本项目在开发、部署和运行过程中遇到的问题，沉淀排查过程与解决方式，避免同类问题重复出现。

**记录约定**：每个问题单独一节，包含「现象 / 根因 / 关键证据 / 解决 / 验证 / 经验」六部分；新问题按编号追加，不要覆盖旧记录。

---

## 快速排查清单

| 检查项 | 怎么看 | 正常表现 |
| --- | --- | --- |
| MCP 工具是否展开 | 启动日志搜索 `已展开` | `✅ 工具 'amap' 已展开为 16 个独立工具` |
| Agent 工具数量 | 启动日志末尾 | 三个 Agent 各 `16 个工具` |
| `uvx` 是否可用 | 终端执行 `uvx --version` | 输出版本号，而不是「找不到命令」 |
| PyPI 是否可达 | 终端访问 `https://pypi.org/simple/` | 能打开；国内网络常超时，需换镜像 |
| 后端环境变量 | `backend/.env` 是否存在 | 含 `AMAP_API_KEY`、`LLM_API_KEY` 等 |
| 历史消息是否清空 | 连续请求两次，看第二次的 Prompt | 不含上一次的城市/行程；输入 Token 不随请求次数上涨 |
| 预算上限是否生效 | 表单填 1000 后生成计划 | 结果页显示「超出/结余」；后端日志有「预算上限: 1000 元」 |
| 子 Agent 是否并行 | 看日志里 `[景点]`/`[天气]`/`[酒店]` 的完成耗时 | 三者耗时接近，总耗时 ≈ 最大值而不是累加 |

---

## 001 高德 MCP 工具没有展开，Agent 工具调用全部失败

- **发现时间**：2026-10-19
- **影响范围**：多智能体旅行规划主流程（景点、天气、酒店三步）；`/api/map/*` 地图接口
- **状态**：已修复

### 现象

1. 启动日志里每个 Agent 只有 1 个工具：

   ```
   ✅ 工具 'amap' 已注册。
      景点搜索Agent: 1 个工具
      天气查询Agent: 1 个工具
      酒店推荐Agent: 1 个工具
   ```

   正常应该是 `已展开为 16 个独立工具`。

2. 景点步骤的模型输出不是真实工具调用，而是把调用格式当文本吐出来：

   ```
   [TOOL_CALL:amap:action=maps_text_search,keywords=历史文化,city=镇江]
   ```

3. 酒店步骤直接报「未找到工具」。

4. 最终生成的行程里残留 `[TOOL_CALL:...]` 原文，景点和天气数据都是编造的。

### 根因

**直接原因**：MCP 服务器进程根本没启动成功，但异常被依赖库静默吞掉了。

调用链：

```
MCPTool.__init__()
  └─ _discover_tools()            # 启动 uvx amap-mcp-server 并列出工具
       └─ except Exception:       # 任何异常都被吞掉
            self._available_tools = []
  └─ ToolRegistry.register_tool() # 发现 expandable=True，但 get_expanded_tools() 为空
       └─ 退化为普通注册，只注册一个通用工具 'amap'
```

关键代码位置（`hello_agents` 库）：

- `tools/builtin/protocol_tools.py:276-278` —— 工具发现失败被 `except Exception` 吞掉
- `tools/builtin/protocol_tools.py:314-337` —— `get_expanded_tools()` 依赖 `_available_tools`，为空则返回空
- `tools/registry.py:29-45` —— 展开列表为空时走普通注册分支

**为什么启动失败**（两层叠加，均已实测）：

| 层级 | 原因 | 表现 |
| --- | --- | --- |
| 网络 | 本机访问 `pypi.org` 的 TLS 握手超时（15s），清华镜像 0.5s 返回 200 | `uvx` 下载 `amap-mcp-server` 失败 |
| 依赖 | `amap-mcp-server==0.1.11` 钉死 `mcp==1.8.1`，而 mcp 1.8.1 在 `pydantic>=2.12` 下启动即崩 | `ImportError: cannot import name 'eval_type_backport'` |

**连锁反应**：

1. 只注册了通用 `amap` 工具，它的参数是 `action` / `tool_name` / `arguments`，`action` 必填。
2. 但提示词写的是 `[TOOL_CALL:amap_maps_text_search:...]`，该工具名并不存在。
3. 模型只好猜 `action=maps_text_search`，而 `MCPTool.run()` 只认 `list_tools` / `call_tool` / `list_resources` 等，返回「不支持的操作」。
4. 模型重试耗尽后，把 `[TOOL_CALL:...]` 原文写进了回答。

### 关键证据

- `https://pypi.org/simple/amap-mcp-server/` → 15s TLS handshake timeout；`https://pypi.tuna.tsinghua.edu.cn/simple/amap-mcp-server/` → HTTP 200、0.5s。
- uv 缓存中只有 `simple-v26\pypi\amap-mcp-server.lock`（0 字节，12:52 创建），没有包体 —— 说明包从未下载成功。
- uvx 临时环境解析结果为 `mcp 1.8.1` + `pydantic 2.14.1`，服务器启动报 `eval_type_backport` 缺失。
- 加镜像后报错消失，工具能正常发现。

### 解决

在创建 `MCPTool` 时锁定版本并指定镜像（`server_command` + `env` 两处改动）：

```python
server_command=[
    "uvx", "--from", "amap-mcp-server==0.1.11",
    "--with", "pydantic<2.12", "amap-mcp-server"
],
env={
    "AMAP_MAPS_API_KEY": settings.amap_api_key,
    "UV_DEFAULT_INDEX": "https://pypi.tuna.tsinghua.edu.cn/simple"
},
```

涉及两个文件（两处配置相同，必须同时改，否则地图接口仍会失败）：

- `backend/app/agents/trip_planner_agent.py`
- `backend/app/services/amap_service.py`

### 验证

用项目自身的初始化代码运行，输出：

```
✅ 工具 'amap' 已展开为 16 个独立工具   # ×3（三个 Agent）
available_tools = 16
expanded_tools = 16
agent_tools = [16, 16, 16]
```

展开后的工具名为 `amap_maps_text_search`、`amap_maps_weather`、`amap_maps_geo`、`amap_maps_direction_*` 等，与提示词中的调用格式一致。

### 经验

1. **`已注册` ≠ `已展开`**：日志里出现 `工具 'amap' 已注册` 就说明展开失败，不要只看「初始化成功」。
2. **`expandable=True` 必须保留**：`MCPTool.__init__` 调用 `super().__init__(name, description)` 时没有传 `expandable`，基类默认 `False`；不手动置真，即使工具发现成功也不会展开。
3. **`uvx` 必须在 PATH 上**：本项目已把 `F:\agent\env313\Scripts` 加入用户 PATH。若在 IDE 里直接运行，确认解释器所在环境的 `Scripts` 目录在 PATH 中，否则会报 `WinError 2`。
4. **首次启动会联网**：第一次跑会下载 `amap-mcp-server` 及依赖，之后走 uv 缓存；首次启动慢是正常的。
5. **静默降级最危险**：依赖库把连接失败变成「没有工具」，表现为模型乱编工具名，容易误判成提示词问题。排查时应优先确认 `_available_tools` 是否为空。










----------------------------------------------------------------------------------------------------------------------------

## 002 单次请求的 Token 越跑越高（历史消息累积）

- **发现时间**：2026-10-19
- **影响范围**：所有 `/api/trip/plan` 请求；后端进程持续运行越久，单次请求越慢、越贵
- **状态**：已修复

### 现象

1. 控制台上的用量明显偏高（累计达到几十万 Token），但代码里看不出哪里在重复烧 Token。
2. 同一个后端进程，请求次数越多，单次请求的输入 Token 越大；重启后端后恢复正常，跑十几次又开始变慢。
3. 请求 A 城市之后紧接着请求 B 城市，生成结果可能带上 A 城市的景点、价格或酒店。

### 根因

Agent 是**单例**，而 `_history` **只增不清**，每次请求都把全部历史重新发给模型。

调用链（`hello_agents` 库）：

```
SimpleAgent.run()
  ├─ messages = [system] + self._history + [本次用户输入]   # 历史全量重放
  ├─ while 循环：最多 max_tool_iterations=3 轮
  └─ 结束时 add_message(user) + add_message(assistant)        # 每次多 2 条
```

叠加项目侧的两个事实：

- `get_trip_planner_agent()` 返回单例，进程不重启，Agent 就一直在（`backend/app/api/routes/trip.py`）；
- 项目里从未调用过 `clear_history()`，`Config.max_history_length` 只有定义、库并未实现裁剪。

**所以 46 万 Token 不是单次请求内部循环造成的**：单次最多 3 轮工具调用，量级只有几万；真正的原因是历史跨请求累积，且每次都整段重放。

### 关键证据

- 实测同一个 Agent 连续跑 5 次：历史变成 10 条，每次调用发送的消息数为 `2 → 4 → 6 → 8 → 10`，线性增长。
- 每次请求往历史里写入约 **4239 Token**，其中最大头是 Planner 自己的 JSON 输出（约 **2853 Token**）——下一次请求会把它原样带上。
- 按此增长，第 10 次请求 Planner 输入约 2.6 万 Token，第 20 次约 5.5 万 Token；累计 20 次请求约 55 万 Token。

### 解决

在 `plan_trip()` 开头清空四个 Agent 的历史，让每次请求都是干净上下文：

```python
for agent in (
    self.attraction_agent,
    self.weather_agent,
    self.hotel_agent,
    self.planner_agent,
):
    agent.clear_history()
```

### 验证

用假 LLM 连续发两次不同城市的请求（镇江 → 苏州）：

```
RUN1 planner_msgs = 2   history = 2
RUN2 planner_msgs = 2   history = 2
RUN2 contains_zhenjiang = False
RUN2 contains_suzhou = True
```

第二次请求的消息数仍是 2（system + 本次输入），历史没有累积，Prompt 里也不再有上一个城市的内容。修复前第二次会是 4 条消息且包含「镇江」。

### 经验

1. **单例 + 有状态 Agent 必须显式 reset**：库不会自动清理，`clear_history()` 要自己调。
2. **不要用 Prompt 限制代替代码修复**：在提示词里写「禁止多轮搜索」只能影响单次循环的 3 轮，压不住历史回放，还会降低数据覆盖。
3. **滑动窗口在这个项目里不划算**：窗口最小单位是一轮对话（约 2800+ Token），比压缩后的上下文（约 320 Token）大近 10 倍，而且仍会把上一个城市的行程带进来。
4. **多发散问句先量再说**：判断「是不是循环爆炸」要看单次 run 的调用上限，判断「是不是历史累积」要看连续请求的消息数。
5. **将来若做对话式改行程**，用 `session_id + 结构化状态（当前 TripPlan + 约束）`，不要复用 `agent._history`。










----------------------------------------------------------------------------------------------------------------------------
## 003 预算靠模型随口编：金额不可复现、明细对不上、超支无提示

- **发现时间**：2026-10-21
- **影响范围**：`/api/trip/plan` 返回的 `budget` 与所有明细金额、结果页预算卡片
- **状态**：已修复

### 现象

1. 行程里的 `budget` 四项（门票/酒店/餐饮/交通）全部由 LLM 在 JSON 里写，代码直接 `TripPlan(**data)` 收下，没有任何校验。
2. 同样的行程重新生成一次，金额会变；门票价、房价来自模型记忆，不是真实价格。
3. 明细里的 `ticket_price`、`estimated_cost` 和汇总的 `budget` 可能对不上，前端展示「明细相加 ≠ 总费用」。
4. 用户把预算写进「额外要求」自由文本（例如 `预算1500元`），系统不解析，超支也照样返回「成功」。

### 根因

- **把「算钱」交给了生成模型**：LLM 擅长选景点、排行程，但不适合做确定性计算，也不会实时查价。
- **没有价格数据源**：高德 `maps_text_search` 只返回名称、地址、坐标，不返回门票价；模型只能靠记忆报数。
- **`budget` 是模型的输出，而不是明细的推导结果**：它和 `ticket_price` / `estimated_cost` 是两套独立生成的数字，天然可能不一致。
- **用户预算没有契约字段**：只存在于自由文本里，既无法校验，也无法回传前端。

### 解决：新增 BudgetCalculator

核心思路是**LLM 只负责「选哪些景点、哪家酒店、吃什么」，金额全部交给代码算**。

**1. MySQL 价格库**（`backend/app/db/schema.sql`）

| 表 | 用途 |
|---|---|
| `attraction_price` | 景点标准名 + 门票价 |
| `attraction_alias` | 别名映射（金山公园 → 金山寺、北固楼 → 北固山） |
| `hotel_price` | 酒店名 + 档位 + 每晚价格 |
| `meal_price` | 城市 + 餐型价格，`*` 为全国默认 |
| `transport_price` | 城市 + 交通方式日预算，`*` 为全国默认 |

初始化用 `python -m app.db.init_db`，幂等；旧表缺少唯一索引时会先按最小 id 去重再补索引。

**2. 数据访问分层**（`db/pool.py` + `db/repository.py`）

- 连接池懒加载，数据库不可用时自动降级，不阻塞请求；
- 门票匹配顺序：别名 → 精确 → 模糊（库名被输入包含，取最长匹配）；
- 酒店：名称 → 城市+档位均价；餐饮/交通：城市 → 全国默认。

**3. 名称归一化**（`services/price_normalizer.py`）

模型输出的名字很脏，先清洗再查库：去括号内容、去子景点后缀、去「风景区/景区」、去「城市+市」前缀。

**4. 确定性计算**（`services/budget_calculator.py`）

| 项 | 规则 | 兜底顺序 |
|---|---|---|
| 门票 | 逐个景点查库 | 库 → 计划内 `ticket_price` → 0 |
| 酒店 | 单价 × `max(天数-1, 1)` 晚 | 库(名称) → 库(档位) → 计划值 → 200 |
| 餐饮 | 按 `meal_type` 查库，逐餐累加 | 库(城市) → 库(`*`) → 计划值 → 30/50/70 |
| 交通 | 日预算 × 天数 | 库(城市) → 库(`*`) → 默认 |

计算完成后：

- **回写明细**：`attraction.ticket_price`、`hotel.estimated_cost`、`meal.estimated_cost` 全部改成算出来的值；
- **汇总恒等**：`total = 四项之和`，由代码保证；
- **来源日志**：每类金额打印 `db/alias/fuzzy/plan/default` 的命中分布。

**5. 预算上限（同一改动的延伸）**

- `TripRequest.budget_limit` → `TripPlan.over_budget = max(total - limit, 0)`；
- 前端首页新增可选预算输入，结果页显示「结余 / 超出」标签与降本建议；
- 超支时接口 `message` 也会带上「超出预算 X 元」。

### 验证

**真实行程重算**（用之前生成的那份镇江 3 天行程）：

| 项目 | 重算前（LLM） | 重算后（价格库） |
|---|---|---|
| 门票 | 115 | 125（北固楼 30 → 40） |
| 酒店 | 600 | 400（3 天 2 晚 × 200） |
| 餐饮 | 480 | 450（30/50/70 × 3 天） |
| 交通 | 120 | 60（20 元/天 × 3 天） |
| **合计** | **1315** | **1035** |

来源分布：门票 `alias 4 / db 2 / fuzzy 1 / plan 1`，酒店 `db 2`，餐饮 `db 9`，交通 `db 1`。明细全部被回写，`total = 125 + 400 + 450 + 60 = 1035`。

**测试与构建**：

- 后端 25 个测试通过（归一化 9、预算计算 9、数据库集成 7）；
- 冒烟测试：总额 1035、上限 1000、超出 35；
- 前端 `vue-tsc --noEmit` 无报错，`npm run build` 成功（3478 modules）。

### 经验

1. **LLM 负责「选」，代码负责「算」**：生成模型适合做取舍和表达，不适合做算术和查价；把两者分开，预算才可复现、可解释。
2. **兜底顺序要讲究**：`库 → 计划内模型值 → 默认值`。把「默认 30 元」放在模型估算之前是错的——免费景点会被算成收费，误差反而更大。
3. **名称归一化比 SQL 模糊查询更重要**：`LIKE '%金山寺(金山公园内)%'` 永远匹配不到库里的「金山寺」，方向反了；别名表 + 归一化才是正解。
4. **明细和汇总必须同源**：只改 `budget.total_attractions` 而不回写 `ticket_price`，页面就会出现「明细相加对不上总数」。
5. **参数与结论分层**：`budget_limit` 是用户输入，`over_budget` 是系统结论；混成一个字段，前端就分不清谁负责。
6. **提示要可行动**：只说「超支 35 元」不够，还要告诉用户「换景点 / 调住宿 / 减正餐」。
7. **先量再做**：改造前先用真实行程跑一遍，记录 1315 与各项来源，改造后才能用同一份数据证明 1035 和命中率——面试时这比「我加了数据库」有说服力得多。

---

## 004 三个子 Agent 串行执行，还把事件循环堵了 57 秒

- **发现时间**：2026-10-22
- **影响范围**：`/api/trip/plan` 全链路；请求期间整个服务不可用
- **状态**：已修复

### 现象

1. 一次规划端到端 **56.9 秒**，日志严格按「步骤1 → 步骤2 → 步骤3」顺序输出，后一步必须等前一步结束。
2. 请求进行中，其他接口（包括 `/health`）完全没有响应——整个进程像卡死一样。
3. 三个子 Agent 的任务其实互不依赖：景点、天气、酒店都只需要城市和偏好，没有先后关系。

### 根因

两层问题叠加：

**第一层：同步执行**

```python
def plan_trip(self, request):          # 普通 def
    attraction = self.attraction_agent.run(...)   # 串行
    weather = self.weather_agent.run(...)
    hotel = self.hotel_agent.run(...)
```

**第二层：异步路由里跑同步重活**

```python
async def plan_trip(request):          # async 路由
    trip_plan = agent.plan_trip(request)  # 同步调用，阻塞事件循环
```

FastAPI 的 `async def` 路由跑在事件循环上。里面调用一个耗时 57 秒的同步函数，等于把整个事件循环锁死 57 秒——期间所有请求都排队，`/health` 也会超时。

### 解决

**1. `plan_trip` 改为 `async def`，三个子 Agent 并行**

```python
results = await asyncio.gather(
    self._run_agent_async("景点", self.attraction_agent, ...),
    self._run_agent_async("天气", self.weather_agent, ...),
    self._run_agent_async("酒店", self.hotel_agent, ...),
    return_exceptions=True,
)
```

**2. 同步 Agent 放进线程池，并加超时**

```python
async def _run_agent_async(self, label, agent, query):
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(agent.run, query),
            timeout=AGENT_TIMEOUT_SECONDS,   # 90s
        )
        print(f"   [{label}] 完成，耗时 {time.perf_counter() - started:.1f}s")
        return result
    except asyncio.TimeoutError:
        print(f"   [{label}] 超时（>{AGENT_TIMEOUT_SECONDS}s）")
        raise
```

**3. 失败隔离**

`return_exceptions=True` + `_normalize_agent_result`：某个 Agent 超时或异常时降级为空字符串，ContextBuilder 会把对应段落写成「未获取到数据」，整体请求仍能返回计划。

**4. Planner 也放进线程池，路由改为 `await`**

```python
planner_response = await asyncio.to_thread(self.planner_agent.run, planner_query)
...
trip_plan = await agent.plan_trip(request)
```

同时把 `get_trip_planner_agent()` 也改成 `await asyncio.to_thread(...)`，避免首次请求初始化 MCP 时再次阻塞事件循环。

### 验证

真实请求（镇江 3 天，公共交通，经济型酒店）的日志：

```
   [天气] 完成，耗时 5.1s
   [景点] 完成，耗时 6.3s
   [酒店] 完成，耗时 7.4s
✅ 三路并行完成，耗时 7.4s
   规划耗时 22.1s
   总耗时 29.6s（并行阶段 7.4s）
```

| 指标 | 改造前 | 改造后 |
|---|---|---|
| 端到端 | 56.9s | **29.6s（-48%）** |
| 三个子 Agent | 串行累计约 18.8s | **并行 7.4s** |
| 事件循环 | 全程被阻塞 | 全程不阻塞 |

并行段实测 7.4s，正好等于三者最大值，说明确实是并发执行而非排队。

测试新增 3 个用例（`tests/test_plan_trip_parallel.py`）：

1. 三个各耗时 0.3s 的 Agent，总耗时 < 0.75s（串行需要 0.9s 以上）；
2. 天气 Agent 抛异常，整体仍返回计划，且三个 Agent 都被调用；
3. Planner 收到的上下文同时包含景点、天气、酒店数据。

全量 **28 个测试通过**。

### 经验

1. **`async def` 里不能跑同步重活**：这是最容易忽略的性能坑。要么用 `asyncio.to_thread`，要么把路由改成普通 `def` 让 FastAPI 自己丢线程池。
2. **并行前先画依赖图**：这三个 Agent 都只依赖城市，所以可以并行；如果酒店要按景点位置做周边搜索，那它就必须排在景点之后——**能不能并行取决于依赖，不取决于数量**。
3. **`gather` 默认会短路**：一个任务抛异常，其余结果拿不到。要 `return_exceptions=True` 再逐项降级。
4. **超时和降级必须成对出现**：只加 `wait_for` 不加降级，超时会让整个请求失败。
5. **提速后瓶颈会转移**：并行后三个 Agent 只占 7.4s，Planner 的 22.1s 成了新大头，下一步优化要盯着它，而不是继续优化已经很快的部分。
6. **用 `max` 而不是 `sum` 校验并行**：看日志时，并行段的耗时应该接近单个最慢任务，而不是三者之和；对不上就说明其实还在串行。

---

## 模板：新增问题记录

```markdown
## 编号 标题

- **发现时间**：
- **影响范围**：
- **状态**：排查中 / 已修复 / 已规避

### 现象

### 根因

### 关键证据

### 解决

### 验证

### 经验
```
