-- 镇江旅行助手：Day 1 主数据表（新链路）
--
-- 设计原则：
--   1. 统一 zj_ 前缀，避免和旧链路的 attraction_price / hotel_price /
--      meal_price / transport_price / attraction_alias 冲突。
--   2. 显式主键 ID（A001 / H001 / R001），Planner 只输出这些 ID。
--   3. 每条数据保留 source_url + last_verified，价格是参考价，不承诺实时。
--   4. 本文件只建表 + 少量参考配置，不覆盖旧 schema.sql。
--
-- 用法：
--   mysql -u root -p < backend/app/db/schema_zhenjiang.sql
-- 或在 Day 4 由 app.db.init_zhenjiang 读取执行。

SET NAMES utf8mb4;

-- ---------------------------------------------------------------------------
-- 1. 景点
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS zj_attraction (
  id VARCHAR(16) NOT NULL COMMENT '稳定 ID，如 A001',
  name VARCHAR(100) NOT NULL COMMENT '标准名称',
  area VARCHAR(20) NOT NULL COMMENT '京口区/润州区/丹徒区/句容市/丹阳市/扬中市/镇江新区',
  category VARCHAR(20) NOT NULL COMMENT '寺庙/古街/博物馆/山岳/园林/工业旅游/名人故居/公园/红色景点',
  tags VARCHAR(255) NOT NULL DEFAULT '' COMMENT '竖线分隔，如 历史文化|摄影',
  ticket_price INT NOT NULL DEFAULT 0 COMMENT '参考门票价，元',
  price_note VARCHAR(100) NOT NULL DEFAULT '' COMMENT '如 参考价，出行前核实',
  duration_min INT NOT NULL DEFAULT 90 COMMENT '建议游览分钟',
  open_hours VARCHAR(50) NOT NULL DEFAULT '' COMMENT '如 08:00-17:00；未知留空',
  closed_days VARCHAR(20) NOT NULL DEFAULT '' COMMENT '0=周一...6=周日，竖线分隔；未知留空',
  indoor TINYINT NOT NULL DEFAULT 0 COMMENT '1=室内为主，雨天优先',
  walking_level TINYINT NOT NULL DEFAULT 2 COMMENT '1 低 / 2 中 / 3 高',
  must_see TINYINT NOT NULL DEFAULT 0 COMMENT '1=必去',
  season VARCHAR(50) NOT NULL DEFAULT '全年' COMMENT '春|夏|秋|冬|全年',
  lat DECIMAL(10,6) NOT NULL,
  lng DECIMAL(10,6) NOT NULL,
  description TEXT COMMENT '用于 Narrator 的事实/知识卡入口',
  source_url VARCHAR(500) NOT NULL,
  last_verified DATE NOT NULL,
  coord_source VARCHAR(20) NOT NULL DEFAULT 'manual' COMMENT 'amap / manual / unknown',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_zj_attraction_name (name),
  KEY idx_zj_attraction_area (area),
  KEY idx_zj_attraction_category (category),
  KEY idx_zj_attraction_must_see (must_see)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='镇江景点主数据';

-- ---------------------------------------------------------------------------
-- 2. 景点别名（用于导入/兼容旧数据；Planner 不依赖别名）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS zj_attraction_alias (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  attraction_id VARCHAR(16) NOT NULL,
  alias VARCHAR(100) NOT NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_zj_alias (attraction_id, alias),
  KEY idx_zj_alias_text (alias),
  CONSTRAINT fk_zj_alias_attraction
    FOREIGN KEY (attraction_id) REFERENCES zj_attraction (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='景点别名';

-- ---------------------------------------------------------------------------
-- 3. 酒店
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS zj_hotel (
  id VARCHAR(16) NOT NULL COMMENT '如 H001',
  name VARCHAR(100) NOT NULL,
  tier VARCHAR(20) NOT NULL COMMENT '经济型/舒适型/豪华型/民宿',
  area VARCHAR(20) NOT NULL,
  price_per_night INT NOT NULL COMMENT '参考价，元/晚',
  lat DECIMAL(10,6) NOT NULL,
  lng DECIMAL(10,6) NOT NULL,
  source_url VARCHAR(500) NOT NULL,
  last_verified DATE NOT NULL,
  note VARCHAR(255) NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_zj_hotel_name (name),
  KEY idx_zj_hotel_area_tier (area, tier)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='镇江酒店主数据';

-- ---------------------------------------------------------------------------
-- 4. 餐厅
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS zj_restaurant (
  id VARCHAR(16) NOT NULL COMMENT '如 R001',
  name VARCHAR(100) NOT NULL,
  meal_types VARCHAR(50) NOT NULL COMMENT 'breakfast|lunch|dinner',
  area VARCHAR(20) NOT NULL,
  avg_price INT NOT NULL COMMENT '参考人均，元',
  tags VARCHAR(255) NOT NULL DEFAULT '',
  lat DECIMAL(10,6) NOT NULL,
  lng DECIMAL(10,6) NOT NULL,
  source_url VARCHAR(500) NOT NULL,
  last_verified DATE NOT NULL,
  note VARCHAR(255) NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_zj_restaurant_name (name),
  KEY idx_zj_restaurant_area (area)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='镇江餐厅主数据';

-- ---------------------------------------------------------------------------
-- 5. 交通（站点/区域之间的参考路线；日预算见 zj_transport_price）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS zj_transport (
  id VARCHAR(16) NOT NULL COMMENT '如 T001',
  from_station VARCHAR(100) NOT NULL,
  to_area VARCHAR(50) NOT NULL,
  mode VARCHAR(20) NOT NULL COMMENT '公共交通/步行/打车/自驾',
  duration_min INT NOT NULL,
  price INT NOT NULL COMMENT '参考票价，元',
  source_url VARCHAR(500) NOT NULL,
  last_verified DATE NOT NULL,
  note VARCHAR(255) NOT NULL DEFAULT '',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_zj_transport_route (from_station, to_area, mode)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='镇江交通参考';

-- ---------------------------------------------------------------------------
-- 6. 知识卡（按 attraction_id 注入，不走向量检索）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS zj_knowledge_card (
  id VARCHAR(16) NOT NULL COMMENT '如 K001',
  attraction_id VARCHAR(16) NOT NULL,
  topic VARCHAR(100) NOT NULL,
  content TEXT NOT NULL,
  source_url VARCHAR(500) NOT NULL,
  last_verified DATE NOT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_zj_knowledge_topic (attraction_id, topic),
  CONSTRAINT fk_zj_knowledge_attraction
    FOREIGN KEY (attraction_id) REFERENCES zj_attraction (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='镇江本地知识卡';

-- ---------------------------------------------------------------------------
-- 7. 交通日预算（确定性预算用；CSV 中的 zj_transport 是路线参考）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS zj_transport_price (
  city VARCHAR(20) NOT NULL DEFAULT '镇江',
  mode VARCHAR(20) NOT NULL COMMENT '公共交通/步行/打车/自驾',
  price_per_day INT NOT NULL COMMENT '参考日预算，元',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (city, mode)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='交通方式日预算';

INSERT INTO zj_transport_price (city, mode, price_per_day) VALUES
  ('镇江', '公共交通', 30),
  ('镇江', '步行', 0),
  ('镇江', '打车', 80),
  ('镇江', '自驾', 100)
ON DUPLICATE KEY UPDATE price_per_day = VALUES(price_per_day);

-- ---------------------------------------------------------------------------
-- 8. 数据集元信息（缓存版本号 / 导入时间）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS zj_dataset_meta (
  meta_key VARCHAR(50) NOT NULL,
  meta_value VARCHAR(255) NOT NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (meta_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='镇江数据集元信息';

INSERT INTO zj_dataset_meta (meta_key, meta_value) VALUES
  ('data_version', '2026-10-27'),
  ('city', '镇江')
ON DUPLICATE KEY UPDATE meta_value = VALUES(meta_value);
