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
