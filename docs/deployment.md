# 部署上线清单

> 目标：让面试官打开一个 HTTPS 域名就能看，同时不把 API Key、Redis、MySQL 暴露到公网。
>
> 推荐顺序：**Linux VM + Docker Compose + Cloudflare Tunnel（或 Caddy）**。  
> WSL 里的 Redis 只建议本机开发用，不建议跨 Windows/WSL/Linux VM 当生产依赖。

---

## 1. 先选拓扑

### 方案 A：Linux VM + Cloudflare Tunnel（最推荐个人作品）

```text
浏览器 -> https://trip.example.com
  -> Cloudflare（TLS / DDoS / 域名）
  -> cloudflared 出站隧道
  -> VM 127.0.0.1:8080（web/nginx）
  -> /api -> api:8000
```

优点：

- 不需要公网 IP，不需要路由器端口映射；
- 自动 HTTPS；
- 只允许出站连接，攻击面小；
- 适合家里 VM / 学校实验室机器。

### 方案 B：云服务器 + Caddy

```text
浏览器 -> https://trip.example.com
  -> VM:443 Caddy（自动 Let's Encrypt）
  -> 127.0.0.1:8080 web
  -> /api -> api:8000
```

安全组只开：

- `22`（限制你的 IP）
- `80` / `443`
- **不要**开 `8000` / `8080` / `6379` / `3306`

### 方案 C：直接端口映射

不推荐。家庭宽带上线需要公网 IP + 端口转发 + DDNS，还要自己处理 TLS 和扫描；面试作品没必要。

---

## 2. 上线前必须配置

### 2.1 后端 `.env`

在 VM 上创建 `backend/.env`（不要提交）：

```env
# LLM：服务端专用，绝不能出现在前端
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL_ID=deepseek-flash
LLM_TIMEOUT=60

# 生产域名（替换成你的域名）
CORS_ORIGINS=https://trip.example.com

# Redis：建议和 api 在同一个 compose 网络
REDIS_URL=redis://redis:6379/0
RATE_LIMIT_PER_MINUTE=3

# 高德：v1 镇江链路不依赖；旧地图/MCP 路由才需要
AMAP_API_KEY=

# MySQL：v1 目前用 CSV，不用可以不配；保留则只在内网
DB_ENABLED=true
DB_HOST=mysql
DB_PORT=3306
DB_USER=root
DB_PASSWORD=change-me
DB_NAME=trip_agent
```

关键点：

- `LLM_API_KEY` 只在后端；前端构建产物里不能出现；
- `CORS_ORIGINS` 写真实 HTTPS 域名，不要 `*`；
- 公网 Demo 把 `RATE_LIMIT_PER_MINUTE` 调到 **2–5**；
- 如果只做展示，`AMAP_API_KEY` 可以留空（我已在代码里把 v1 的 AMap 依赖改为 warning）。

### 2.2 前端构建

Dockerfile 已经用：

```text
VITE_API_BASE_URL=/
```

前端请求 `/api/v1/...`，由 web 容器里的 nginx 代理到 `api:8000`。  
这样前后端同源，不需要跨域。

地图 Key：

```env
VITE_AMAP_WEB_JS_KEY=你的高德 JS Key
```

高德 JS Key 会出现在浏览器里，这是正常的，但要在高德控制台配置 **域名白名单**：

```text
https://trip.example.com
```

不要把高德 **Web 服务 API Key** 放到前端。

### 2.3 域名与 HTTPS

#### Cloudflare Tunnel

```bash
# VM 上
cloudflared tunnel login
cloudflared tunnel create trip
```

`~/.cloudflared/config.yml`：

```yaml
tunnel: <tunnel-id>
credentials-file: /home/<user>/.cloudflared/<tunnel-id>.json
ingress:
  - hostname: trip.example.com
    service: http://localhost:8080
  - service: http_status:404
```

```bash
cloudflared tunnel route dns trip trip.example.com
sudo cloudflared service install
sudo systemctl enable --now cloudflared
```

#### Caddy（VPS 方案）

`/etc/caddy/Caddyfile`：

```caddyfile
trip.example.com {
    encode gzip
    reverse_proxy 127.0.0.1:8080
}
```

```bash
sudo systemctl reload caddy
```

Caddy 自动申请/续期证书。web 容器内 nginx 继续把 `/api` 转到 `api:8000`。

---

## 3. Redis / WSL 怎么处理

### 推荐：Redis 和 api 在同一个 Docker Compose

`docker-compose.yml` 已经包含 `redis` 服务，`api` 用：

```env
REDIS_URL=redis://redis:6379/0
```

这是最稳的：

- 不暴露 `6379`；
- 容器重启后自动恢复；
- 多 worker 共享缓存/限流。

### 如果后端跑在 Windows 本机，Redis 在 WSL

WSL2 的 `localhost` 通常会转发到 Windows：

```powershell
wsl redis-cli ping
# PONG
```

后端 `.env`：

```env
REDIS_URL=redis://127.0.0.1:6379/0
```

这只适合本机开发。

### 如果后端跑在单独的 Linux VM，Redis 在 WSL

**不要跨 VM 去连 Windows/WSL 的 Redis。**  
原因：

- WSL IP 每次重启可能变化；
- Windows 防火墙/端口转发复杂；
- 延迟和稳定性不可控；
- 公网部署不应该依赖你的个人电脑。

正确做法：

```bash
# 在 Linux VM 里
sudo apt install redis-server
# 或直接用 docker compose 的 redis 服务
```

---

## 4. 启动与验证

```bash
cd helloagents-trip-planner
cp backend/.env.example backend/.env
# 编辑 backend/.env

docker compose up -d --build
docker compose ps
docker compose logs -f api
```

验证：

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8080/health
```

然后：

```text
https://trip.example.com/
https://trip.example.com/result?demo=1
```

如果没有 API Key，先看 `?demo=1`，它不需要后端/LLM。

---

## 5. 公网 Demo 的成本与滥用保护

当前一次请求：

- P50 约 13 秒；
- 平均约 6.3k Token；
- 15 条评测总 Token 约 94k。

公开 Demo 必须做：

1. `RATE_LIMIT_PER_MINUTE=2~5`
2. LLM 提供商后台设置**每月/每日预算上限**
3. 用便宜模型；不要用最贵的模型做公网 Demo
4. 计划缓存已经存在（同参数命中缓存）
5. 可选：Cloudflare Access / 访问码
6. 可选：每日全局请求上限（当前未实现，可加 Redis 计数器）

如果不想承担公网 LLM 成本：

- 只开放 `?demo=1` 静态示例；
- 真实生成加访问码；
- 或者录 Demo 视频，不公开调用。

---

## 6. 安全清单

- [ ] `.env` 不在 Git 里；`chmod 600 backend/.env`
- [ ] 只暴露 80/443；8000/8080/6379/3306 绑定 `127.0.0.1` 或仅 Docker 内网
- [ ] `CORS_ORIGINS` 写真实域名，不使用 `*`
- [ ] 高德 JS Key 配域名白名单；Web 服务 Key 只在服务端
- [ ] Redis 不暴露公网；如必须远程访问，启用密码 + 防火墙
- [ ] MySQL 不暴露公网；root 密码强随机
- [ ] 反向代理只允许受信任入口访问 API
- [ ] `X-Forwarded-For` 只在可信代理后面使用；直接暴露 API 时当前 `_client_ip` 可被伪造绕过限流
- [ ] 日志不打印完整 Prompt / API Key
- [ ] 定期轮换 LLM Key；Demo 结束可撤销
- [ ] 给 `/health` 加 UptimeRobot / Better Stack 监控
- [ ] Docker 日志配置轮转（`json-file` max-size/max-file）

> 当前 `docker-compose.yml` 已把 `8000`/`8080` 绑定到 `127.0.0.1`，适合放在 Caddy/Cloudflare Tunnel 后面。

---

## 7. 更新与回滚

更新：

```bash
cd helloagents-trip-planner
git pull
docker compose up -d --build
```

回滚：

```bash
git checkout <previous-commit>
docker compose up -d --build
```

数据：

- CSV 在镜像/仓库里，更新数据要重建；
- Redis 是缓存，可丢；
- MySQL 如果启用，备份 volume；
- `eval/`、`docs/` 不参与运行时。

---

## 8. 部署后检查

- [ ] `https://域名/` 首页正常
- [ ] `https://域名/result?demo=1` 示例正常
- [ ] 真实生成一次，看到 Trace / 预算
- [ ] `/health` 返回 `cache=redis`（如果配了 Redis）
- [ ] 连续请求触发 429
- [ ] 编辑后重算返回 200
- [ ] 手机宽度下页面可用
- [ ] 地图 Key 域名白名单生效
- [ ] LLM 提供商预算告警已设置
- [ ] README 截图/链接可访问

---

## 9. 最小上线版本

如果时间有限，优先：

```text
Cloudflare Tunnel -> web:8080 -> api:8000
Redis 用 compose 内的 redis
MySQL 可以暂时不接
只开放真实生成 + demo 示例
```

先把「HTTPS 可访问 + 不泄露 Key + 限流」做对，再考虑 MySQL/多 worker/监控。
