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