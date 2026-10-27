# Day 1 Log

## 今天完成

- 冻结范围：`docs/scope-freeze.md`
- ADR-001 草稿：`docs/adr/001-deterministic-dag.md`
- 镇江数据集：18 景点 / 10 酒店 / 12 餐厅 / 8 交通 / 12 知识卡
- 数据校验器：`app/data/validate_zhenjiang.py`
- 数据说明：`app/data/zhenjiang/README.md`
- 新表 DDL：`app/db/schema_zhenjiang.sql`（`zj_` 前缀，避免旧表冲突）
- 测试：`tests/test_zhenjiang_dataset.py`

## 验证结果

```text
[OK] 镇江数据集校验通过
  - attractions.csv: 18 条
  - hotels.csv: 10 条
  - restaurants.csv: 12 条
  - transports.csv: 8 条
  - knowledge_cards.csv: 12 条
  - must_see: 已满足 >= 8

schema OK
tables: zj_attraction, zj_attraction_alias, zj_dataset_meta,
        zj_hotel, zj_knowledge_card, zj_restaurant,
        zj_transport, zj_transport_price
```

完整测试：31 passed。

## 数据边界

- 价格是参考价，`price_note` 标注“参考价/待核实”；不承诺实时。
- 标注“示例”的酒店/餐厅是占位数据，Day 3 前替换。
- 坐标当前 `manual`，Day 2 用高德 POI 校准。
- 闭馆日只填已核实的条目，不默认周一闭馆。

## 明天 Day 2 的输入

- 用 `TripContext` / `NodeResult` / `PlanDraft` 承接 CSV。
- 把 walking skeleton 的 load/plan/validate/budget/render 改成 DAG 节点。
- 加并行、超时、重试、失败隔离、Trace 测试。

## 面试可讲的一句话

“我先用 18 条镇江数据和一套可校验的 CSV 契约把事实层固定下来，
再在这个契约上做 DAG 和 LLM；这样模型出错时，我能判断是数据、契约还是生成的问题。”
