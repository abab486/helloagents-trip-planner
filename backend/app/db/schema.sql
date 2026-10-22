-- 预算价格库：建表 + 镇江种子数据
-- 使用方式：python -m app.db.init_db
-- 说明：脚本可重复执行；已存在的旧表会自动补唯一索引（见 init_db.py）

CREATE TABLE IF NOT EXISTS attraction_price (
  id INT NOT NULL AUTO_INCREMENT,
  city VARCHAR(50) NOT NULL COMMENT '城市',
  name VARCHAR(100) NOT NULL COMMENT '景点标准名称',
  price INT NOT NULL DEFAULT 0 COMMENT '门票价格(元)，0 表示免费',
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_city_name (city, name),
  KEY idx_city (city)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS attraction_alias (
  id INT NOT NULL AUTO_INCREMENT,
  city VARCHAR(50) NOT NULL,
  alias VARCHAR(100) NOT NULL COMMENT '模型可能写出的名字',
  name VARCHAR(100) NOT NULL COMMENT '对应标准名',
  PRIMARY KEY (id),
  UNIQUE KEY uk_city_alias (city, alias),
  KEY idx_name (city, name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS hotel_price (
  id INT NOT NULL AUTO_INCREMENT,
  city VARCHAR(50) NOT NULL,
  name VARCHAR(100) NOT NULL,
  tier VARCHAR(20) NOT NULL COMMENT '经济型/舒适型/豪华型',
  price_per_night INT NOT NULL COMMENT '每晚价格(元)',
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_city_name (city, name),
  KEY idx_city_tier (city, tier)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS meal_price (
  id INT NOT NULL AUTO_INCREMENT,
  city VARCHAR(50) NOT NULL DEFAULT '*' COMMENT '城市，* 为全国默认',
  meal_type VARCHAR(20) NOT NULL COMMENT 'breakfast/lunch/dinner',
  price INT NOT NULL,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_city_type (city, meal_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS transport_price (
  id INT NOT NULL AUTO_INCREMENT,
  city VARCHAR(50) NOT NULL DEFAULT '*' COMMENT '城市，* 为全国默认',
  mode VARCHAR(20) NOT NULL COMMENT '公共交通/打车/自驾/步行',
  price_per_day INT NOT NULL,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_city_mode (city, mode)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ---------- 镇江：景点 ----------
INSERT INTO attraction_price (city, name, price) VALUES
('镇江', '金山寺', 65),
('镇江', '西津渡', 0),
('镇江', '镇江博物馆', 0),
('镇江', '北固山', 40),
('镇江', '焦山', 50),
('镇江', '茅山', 70)
ON DUPLICATE KEY UPDATE price = VALUES(price);

-- ---------- 镇江：景点别名 ----------
INSERT INTO attraction_alias (city, alias, name) VALUES
('镇江', '金山公园', '金山寺'),
('镇江', '金山寺(金山公园内)', '金山寺'),
('镇江', '西津渡历史文化街区', '西津渡'),
('镇江', '西津渡古街', '西津渡'),
('镇江', '北固楼', '北固山'),
('镇江', '北固山风景区', '北固山')
ON DUPLICATE KEY UPDATE name = VALUES(name);

-- ---------- 镇江：酒店 ----------
INSERT INTO hotel_price (city, name, tier, price_per_night) VALUES
('镇江', '格林豪泰(镇江中央大街大润发店)', '经济型', 200),
('镇江', '汉庭酒店(镇江火车站店)', '经济型', 220),
('镇江', '锦江之星(镇江西津渡店)', '经济型', 240)
ON DUPLICATE KEY UPDATE price_per_night = VALUES(price_per_night), tier = VALUES(tier);

-- ---------- 餐饮：城市默认 ----------
INSERT INTO meal_price (city, meal_type, price) VALUES
('镇江', 'breakfast', 30),
('镇江', 'lunch', 50),
('镇江', 'dinner', 70),
('*', 'breakfast', 25),
('*', 'lunch', 45),
('*', 'dinner', 60)
ON DUPLICATE KEY UPDATE price = VALUES(price);

-- ---------- 交通：城市默认 ----------
INSERT INTO transport_price (city, mode, price_per_day) VALUES
('镇江', '公共交通', 20),
('镇江', '打车', 60),
('镇江', '自驾', 80),
('镇江', '步行', 0),
('*', '公共交通', 30),
('*', '打车', 80),
('*', '自驾', 100),
('*', '步行', 0)
ON DUPLICATE KEY UPDATE price_per_day = VALUES(price_per_day);
