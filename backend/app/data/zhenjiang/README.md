# 镇江数据集（Day 1）

这份数据是“确定性 DAG”的事实层。原则是：**宁可标“待核实”，也不要编造。**

## 文件

| 文件 | 内容 | 冻结数量 |
|---|---|---:|
| `attractions.csv` | 景点主数据 | 18 |
| `hotels.csv` | 酒店 | 10 |
| `restaurants.csv` | 餐厅 | 12 |
| `transports.csv` | 站点/区域交通参考 | 8 |
| `knowledge_cards.csv` | 按景点挂载的知识卡 | 12 |
| `manifest.json` | 数据版本、数量、质量说明 | — |

## 景点字段

| 字段 | 说明 |
|---|---|
| `id` | 稳定 ID，Planner 只认这个；`A001–A018` |
| `name` / `aliases` | 标准名 + 别名（竖线分隔） |
| `area` | 京口区/润州区/丹徒区/句容市/丹阳市/扬中市/镇江新区 |
| `category` | 寺庙/古街/古建/博物馆/山岳/园林/工业旅游/名人故居/公园/红色景点 |
| `tags` | 主题标签，竖线分隔 |
| `ticket_price` / `price_note` | 参考门票价 + 说明；“0”表示免费或待核实 |
| `duration_min` | 建议游览分钟 |
| `open_hours` | 开放时间；未知留空 |
| `closed_days` | 0=周一…6=周日，竖线分隔；未知留空，不默认周一闭馆 |
| `indoor` | 1=室内为主，用于雨天筛选 |
| `walking_level` | 1 低 / 2 中 / 3 高，用于带父母/亲子 |
| `must_see` | 1=必去 |
| `season` | 春/夏/秋/冬/全年 |
| `lat` / `lng` | 坐标，当前 `manual`，Day 2 用高德校准 |
| `description` | 给 Narrator 的短事实，不写价格/时间承诺 |
| `source_url` / `last_verified` | 来源与核实日期 |
| `coord_source` | `amap` / `manual` / `unknown` |

## 数据质量规则

- 所有行必须有 `source_url` 和 `last_verified`。
- 不确定的价格写 `price_note=参考价，出行前核实` 或 `待核实`。
- 标注“示例”的酒店/餐厅是占位数据，Day 3 前替换。
- 价格是参考价，不是实时库存/实时票价。
- 坐标是人工估算，Day 2 用高德 POI 校准后把 `coord_source` 改成 `amap`。

## 校验

```powershell
cd backend
$env:PYTHONIOENCODING="utf-8"
F:\agent\env313\Scripts\python.exe -m app.data.validate_zhenjiang
```

校验通过后再进入 `TripContext` / walking skeleton / MySQL 导入。
