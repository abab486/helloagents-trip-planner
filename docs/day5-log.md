# Day 5 Log

## 今天完成

### 首页

- 标题改为「镇江旅行助手」，副标题强调确定性 DAG / 单城市深度
- 目的地固定为镇江（当前版本只支持单城市）
- 新增：
  - 同行人：solo / couple / family / elderly
  - 行程节奏：relaxed / normal / packed
  - 主题：历史文化、美食、自然、亲子、摄影、宗教、休闲
- 日期最多 7 天；超出会提示
- 移除假进度百分比，改为：
  - 真实等待计时
  - 阶段提示（加载数据 → Planner → 校验/预算 → 整理）
  - 明确写“预计 10–20 秒”
- 请求改走 `POST /api/v1/trips`
- 结果写入 `sessionStorage.tripResponse`

### 结果页

- 改为消费 API v1 的 `TripResult`
- 新增 [TraceTimeline.vue](frontend/src/components/TraceTimeline.vue)
  - 节点耗时、状态、缓存、Token、Planner 重试次数、错误
- 新增 [BudgetPanel.vue](frontend/src/components/BudgetPanel.vue)
  - 四项分类汇总
  - 每条费用的来源 badge（价格库/默认价/模型估值）
  - 超预算/结余提示
- 新增天气参考卡片（后端 `TripResult.weather`）
- 地图改用后端返回的 `lat/lng`
- 编辑模式：
  - 可删除景点
  - 「保存并重算」调用 `/recalculate`
  - 重算后更新预算与 Trace
- 修复：
  - 硬编码 `http://localhost:8000` → `API_BASE_URL`
  - 地图 InfoWindow 对 LLM 文本做 HTML 转义（XSS）
  - 编辑后预算不重算
  - 侧边导航/移动端布局
- 导出图片/PDF 合并为共享 `createExportCanvas()`

### 后端小改动

- `AttractionView` / `HotelView` 增加 `lat/lng`
- 新增 `WeatherView`
- `TripResult` 增加 `weather`
- `render_trip()` 填充坐标和天气

## 验证结果

```text
后端测试: 100 passed
前端 vue-tsc: 通过
前端生产构建: 成功（3484 modules）
```

构建命令需要 esbuild 子进程，沙箱下会 EPERM；使用完整权限后成功：

```text
dist/index.html
dist/assets/index-*.css
dist/assets/index-*.js
✓ built in 16.74s
```

产物提示主 chunk 约 2.19 MB（gzip 676 KB），后续可做路由懒加载/按需引入 Ant Design。

## 已知边界

- 地图需要 `VITE_AMAP_WEB_JS_KEY`；未配置时给出 warning，不影响文字行程。
- 图片仍走旧 `/api/poi/photo`，未配置 Unsplash 时使用渐变占位图。
- 编辑模式当前只支持删除景点；换酒店/换餐厅留给后续。
- 导出图片/PDF 是 DOM 截图，地图 canvas 可能因跨域/权限失败，失败时省略地图。

## 明天 Day 6 的输入

- 15 条评测 case + `eval/report.md`
- 单次 LLM / 规则保底基线
- Docker Compose（api + web + mysql + redis 可选）
- GitHub Actions：pytest + vue-tsc + build
- 评测指标：结构合法率、ID 幻觉率、约束通过率、超预算率、P50/P95、Token/成本
