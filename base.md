question：镇江 3 天，预算 1500 元，喜欢历史文化，公共交通
────────────────────────────
端到端耗时：56.9 秒（看终端日志或者浏览器 Network 里的等待时间）
LLM 总 Token：__464170token__（这次请求大概消耗了多少 Token）
花费 0.05
工具调用序列（看后端终端）：
  1. 搜景点调用的工具名：amap_maps_text_search
  2. 查天气调用的工具名：amap_maps_weather
  3. 搜酒店调用的工具名：amap_maps_text_search
────────────────────────────
最关键的一项：预算是不是 LLM 编的？
打开返回的 JSON，找到 "budget": { ... }
total_attractions: 115
total_hotels: 600
total_meals: 480
total_transportation: 120
total: 1315
请用计算器算一下：前四项加起来等不等于 total？（115 + 600 + 480 + 120 = 1315，等于 total，本次一致）
────────────────────────────
行程是否包含：金山寺 [是]；西津渡 [是]；镇江博物馆 [是]
────────────────────────────

---------------------------------------------------------------------------------------------------------------------------
改了什么
1. 精简模型 — 新建 mini.py

python

class MiniAttraction(BaseModel):
    name: str
    address: Optional[str] = ""
    visit_duration: int = 60

class MiniHotel(BaseModel):
    name: str
    price_range: Optional[str] = ""

class MiniWeather(BaseModel):
    date / weather / temp

2. ContextBuilder — 新建 context_builder.py
build_planner_context()：P0 需求固定 → P1 数据清洗 → P2 组装控预算
超预算按 酒店 → 天气 → 景点 顺序降级，最后才硬截断（max_token_budget=4000）
提取器按优先级尝试：JSON → Markdown 表格 → **加粗**（地址） → 列表项
额外做了两件你示例里没有、但这个项目很需要的事：
过滤失败文本：子 Agent 工具失败时会写一大段「抱歉/错误/建议」，检测到这类内容直接替换成 （未获取到景点数据），不让它污染 Planner
去重 + 剔除子景点：比如 西津渡历史文化街区-凉亭 会被父景点吸收
3. 接入 — trip_planner_agent.py

python

planner_query = self.context_builder.build_planner_context(
    request, attraction_response, weather_response, hotel_response
)
删除了原来的 _build_planner_query（无其他引用），并加了一行日志： 上下文压缩: 734 -> 323 tokens（景点 5 / 天气 3 / 酒店 2）


代码块

PLAN_OK city=镇江 days=3 budget={'total_attractions': 175, 'total_hotels': 440, 'total_meals': 440, 'total_transportation': 200, 'total': 1255}
效果边界（免得预期过高）
省的是 Planner 的输入；三个子 Agent 各自的调用、以及 Planner 那段很长的系统提示（JSON 模板）都没有变，那部分才是固定的大头。
Token 数是按「汉字≈1、其他≈0.3」估算的，实际值以接口返回的 usage 为准。
预算兜底目前按估算值判断，如果真实 tokenizer 偏差大，可以把 max_token_budget 调小一点。

4.每次 plan_trip() 开头 clear_history()，把 Agent 当无状态函数用

plan_trip() 开头新增：
python


for agent in (
    self.attraction_agent,
    self.weather_agent,
    self.hotel_agent,
    self.planner_agent,
):
    agent.clear_history()

question：镇江 3 天，预算 1500 元，喜欢历史文化，公共交通
────────────────────────────
端到端耗时：46 秒（看终端日志或者浏览器 Network 里的等待时间）
LLM 总 Token：__25407token__（这次请求大概消耗了多少 Token）
花费 0.05
工具调用序列（看后端终端）：
  1. 搜景点调用的工具名：amap_maps_text_search
  2. 查天气调用的工具名：amap_maps_weather
  3. 搜酒店调用的工具名：amap_maps_text_search
────────────────────────────
最关键的一项：预算是不是 LLM 编的？
打开返回的 JSON，找到 "budget": { ... }
total_attractions: 115
total_hotels: 460
total_meals: 355
total_transportation: 60
total: 990
请用计算器算一下：前四项加起来等不等于 total？（等于 total，本次一致）
────────────────────────────
行程是否包含：金山寺 [是]；西津渡 [是]；镇江博物馆 [是]

---------------------------------------------------------------------------------------------------------------------------
新增 BudgetCalculator

BudgetCalculator 规则
项	计算方式	兜底顺序
门票	遍历 plan.days[].attractions，按归一化名查库	DB → 计划内 ticket_price → 0
酒店	晚数 = max(travel_days - 1, 1)；单价查库	DB(名称) → DB(城市+档位) → 计划内 estimated_cost
餐饮	遍历所有 meals，按 meal_type 查库	DB(城市) → DB(*) → 计划内 estimated_cost
交通	price_per_day × travel_days，mode 取自 request.transportation	DB(城市) → DB(*) → 40/天
要点：

回写明细：算完必须把 attraction.ticket_price、hotel.estimated_cost、meal.estimated_cost 改掉，否则明细和汇总对不上。
汇总恒等式：total = 四项之和，由代码保证，不信任 LLM。
幂等：同一份 plan 重复计算结果一致，便于测试。
调用次数：8 个景点 + 3 晚 + 9 餐 + 1 交通 ≈ 21 次查询，全部主键/唯一索引命中，耗时毫秒级。

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

示例
MySQL 连接池已创建: 127.0.0.1:3306/trip_agent
   预算重算: 门票 165(alias 4/db 2/plan 1) 酒店 600(plan 2) 餐饮 450(db 9) 交通 60(db 1) | 合计 1275
   预算上限: 1500 元，未超预算

 端到端耗时：41.2 秒（看终端日志或者浏览器 Network 里的等待时间）
LLM 总 Token：__24052token__（这次请求大概消耗了多少 Token）
花费 0.03
工具调用序列（看后端终端）：
  1. 搜景点调用的工具名：amap_maps_text_search
  2. 查天气调用的工具名：amap_maps_weather
  3. 搜酒店调用的工具名：amap_maps_text_search
────────────────────────────
采用BudgetCalculator
total_attractions: 165
total_hotels: 600
total_meals: 450
total_transportation: 60
total: 1275
save：225
请用计算器算一下：前四项加起来等于 total
────────────────────────────
行程是否包含：金山寺 [是]；西津渡 [是]；镇江博物馆 [是]  