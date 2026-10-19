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
