# Clawith 自定义修改记录

记录 Clawith 升级时需要保留的修改，避免被覆盖。

---

## 1. httpx 禁用系统代理

**文件**: `backend/app/services/llm_client.py`

**位置**: 4 个客户端类的 `_get_client()` 方法

- Line 215: `OpenAICompatibleClient._get_client()`
- Line 546: `GeminiClient._get_client()`
- Line 852: `AnthropicClient._get_client()`
- Line 1343: `OllamaClient._get_client()`

**问题**: httpx 默认读取系统代理设置，导致请求被拦截，LLM 调用返回 502。

**修改**: 在创建 `httpx.AsyncClient` 时添加 `trust_env=False`

```python
async def _get_client(self) -> httpx.AsyncClient:
    if self._client is None or self._client.is_closed:
        self._client = httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, trust_env=False)
    return self._client
```

> 搜索 `trust_env=False` 确认所有 4 处都已修改

---

## 2. Windows subprocess 支持 (Python 3.12)

**文件**: `backend/app/services/agent_tools.py`

### 2.1 模块级事件循环策略

**位置**: 文件开头，`from loguru import logger` 之后

**问题**: Python 3.12 在 Windows 上默认 `SelectorEventLoop` 不支持 subprocess，导致 `asyncio.create_subprocess_exec` 抛出 `NotImplementedError`。

**修改**:

```python
from loguru import logger

import sys as _sys
if _sys.platform == "win32":
    import asyncio as _asyncio
    _asyncio.set_event_loop_policy(_asyncio.WindowsProactorEventLoopPolicy())
```

### 2.2 subprocess 编码修复

**位置**: `_execute_code` 函数内，`await asyncio.wait_for(proc.communicate(), timeout=timeout)` 之后

**问题**: Windows subprocess 默认输出用 GBK 编码，但代码用 UTF-8 解码导致乱码。

**修改**:

```python
# 修改前
stdout_str = stdout.decode("utf-8", errors="replace")[:10000]
stderr_str = stderr.decode("utf-8", errors="replace")[:5000]

# 修改后
if _sys.platform == "win32":
    def _try_decode_win(data):
        if not data:
            return ""
        if len(data) >= 2 and data[:2] == b"\xff\xfe":
            return data[2:].decode("utf-16-le", errors="replace")
        null_count = sum(1 for i in range(1, min(len(data), 1000), 2) if data[i] == 0)
        if null_count / max(len(data) // 2, 1) > 0.3:
            return data.decode("utf-16-le", errors="replace")
        return data.decode("gbk", errors="replace")
    stdout_str = _try_decode_win(stdout)[:10000]
    stderr_str = _try_decode_win(stderr)[:5000]
else:
    stdout_str = stdout.decode("utf-8", errors="replace")[:10000]
    stderr_str = stderr.decode("utf-8", errors="replace")[:5000]
```

> 2026-03-21 更新：加了 UTF-16LE 检测，解决 PowerShell 输出的 UTF-16LE 编码问题。

### 2.3 bash 命令改用 PowerShell

**位置**: `_execute_code` 函数内，`if language == "bash"` 分支

**问题**: Windows 没有 `bash` 命令。Git Bash 会检测 WSL 环境，但 WSL 没有安装 Linux 分发版时会导致 `agent-browser` 等工具出错。

**修改**:

```python
# 修改前
elif language == "bash":
    ext = ".sh"
    import shutil as _shutil
    if _shutil.which("bash"):
        cmd_prefix = ["bash"]
    elif _shutil.which("cmd"):
        cmd_prefix = ["cmd", "/c"]
    else:
        cmd_prefix = ["powershell", "-Command"]

# 修改后
elif language == "bash":
    ext = ".bat"
    cmd_prefix = ["powershell", "-Command"]
```

> 2026-03-21 更新：删除了 bash/cmd 自动检测，直接固定用 PowerShell，避免 Git Bash 检测 WSL 导致的问题。

---

## 3. feishu tool_call 历史记录修复

**文件**: `backend/app/api/feishu.py`

**位置**: `_call_agent_llm` 函数内，历史记录构建部分（约 line 992）

**问题**: feishu 路由的消息在加载历史时跳过了 `role='tool_call'` 的消息，导致多轮工具调用对话中工具调用信息丢失，LLM 报错 "No tool output found for function call"。

**修改**: 将简单的列表推导式替换为循环，正确处理 `tool_call` 角色：

```python
# 修改前
_history = [{"role": m.role, "content": m.content} for m in reversed(_hist_r.scalars().all())]

# 修改后
_hist_list = list(reversed(_hist_r.scalars().all()))
_history = []
for m in _hist_list:
    if m.role == "tool_call":
        import json as _j_tc
        try:
            tc_data = _j_tc.loads(m.content)
            tc_name = tc_data.get("name", "unknown")
            tc_args = tc_data.get("args", {})
            tc_result = tc_data.get("result", "")
            tc_id = f"call_{m.id}"
            _history.append({
                "role": "assistant",
                "content": None,
                "tool_calls": [{
                    "id": tc_id,
                    "type": "function",
                    "function": {"name": tc_name, "arguments": _j_tc.dumps(tc_args, ensure_ascii=False)},
                }],
            })
            _history.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": str(tc_result)[:500],
            })
        except Exception:
            continue
    else:
        entry = {"role": m.role, "content": m.content}
        if hasattr(m, 'thinking') and m.thinking:
            entry["thinking"] = m.thinking
        _history.append(entry)
```

---

## 4. emoji 日志编码修复

**文件**: `backend/app/main.py`

**位置**: `migrate_enterprise_info()` 函数内的 print 语句

**问题**: Windows GBK 终端无法打印 emoji 字符，导致启动时异常退出。

**修改**: 将 emoji 替换为 ASCII 字符：

```python
# 修改前
print(f"[startup] ✅ Migrated enterprise_info → enterprise_info_{_tenant.id}", flush=True)
print(f"[startup] ℹ️ enterprise_info_{_tenant.id} already exists, skipping migration", flush=True)

# 修改后
print(f"[startup] [OK] Migrated enterprise_info -> enterprise_info_{_tenant.id}", flush=True)
print(f"[startup] [i] enterprise_info_{_tenant.id} already exists, skipping migration", flush=True)
```

---

## 5. 启动脚本路径修复

**文件**: `links.bat`、`clawith.bat`

**问题**: Windows 上 venv Scripts 路径为 `.venv\Scripts\` 而非 `.venv/bin/`。

**修改** (`links.bat`):
```bash
# 修改前
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port $BACKEND_PORT

# 修改后
.venv/Scripts/uvicorn app.main:app --host 0.0.0.0 --port $BACKEND_PORT
```

**修改** (`clawith.bat`):
```bat
REM 修改前
uv run uvicorn app.main:app --reload --port 8008

REM 修改后
.venv\Scripts\uvicorn app.main:app --port 8008
```

> 注意：移除了 `--reload` 参数，因为 watchfiles 子进程可能与 Windows 事件循环冲突。

---

## 6. 禁用 Agent Seeder

**文件**: `backend/app/main.py`

**位置**: `startup()` 函数（约 line 181-184）

**问题**: 每次重启服务都会运行 `seed_default_agents()`，覆盖用户自定义的 Agent。

**修改**: 注释掉相关调用：

```python
# await seed_default_agents()
# 如果以上命令报错，可能是重复的 agent name，执行以下命令解决：
# truncate_table("agents")
```

---

## 7. MCP 工具在 Agent Tools 分配页面不显示

**文件**: `backend/app/api/tools.py`

**位置**: `GET /api/tools/agents/{agent_id}/with-config` 端点（约 line 188 和 line 400）

**问题**: MCP 工具只有在 Agent 已有分配记录时才显示，用户从未分配过所以看不到，形成"先有鸡还是先有蛋"的问题。

**修改**: 删除两处 `if t.type == "mcp" and not at: continue` 检查

```python
# 修改前
tid = str(t.id)
at = assignments.get(tid)
# MCP tools only show for agents that have an explicit assignment
if t.type == "mcp" and not at:
    continue
enabled = at.enabled if at else t.is_default

# 修改后
tid = str(t.id)
at = assignments.get(tid)
enabled = at.enabled if at else t.is_default
```

两处均修改（line 188 和 line 400）。

两处均修改（line 188 和 line 400）。

## 8. 前端聊天输入框卡顿优化

**文件**: `frontend/src/pages/AgentDetail.tsx`

**问题**: 输入框打字延迟——每次按键触发 `setChatInput` 更新 state，导致整个父组件（4400+行）re-render。

**修改**:

1. 删除全部 `refetchInterval`（4处）：避免不必要的定时数据刷新触发 re-render。

2. 输入框改为 uncontrolled 模式，完全绕过 React state：
   - `ChatInput` 组件去掉 `value/onChange`，使用原生 `<input>`
   - `sendChatMsg` 直接从 `chatInputRef.current.value` 读取输入值
   - 发送后直接清空 DOM：`if (chatInputRef.current) chatInputRef.current.value = ''`
   - `sendChatMsg` 加上 `useCallback`

```tsx
// ChatInput 组件改为 uncontrolled
const ChatInput = React.memo(({ onKeyDown, onPaste, placeholder, disabled, autoFocus, inputRef }) => (
    <input ref={inputRef} className="chat-input" onKeyDown={onKeyDown} onPaste={onPaste}
        placeholder={placeholder} disabled={disabled} style={{ flex: 1 }} autoFocus={autoFocus} />
));

// sendChatMsg 读 DOM 而非 state
const _inputEl = chatInputRef.current;
if (!_inputEl) return;
const _inputVal = _inputEl.value.trim();
if (!_inputVal && attachedFiles.length === 0) return;
const userMsg = _inputVal;

// 发送后清空 DOM
if (chatInputRef.current) chatInputRef.current.value = '';

// 发送按钮禁用条件修复
<button onClick={sendChatMsg} disabled={!wsConnected}>Send</button>
```

## 9. 飞书群聊多 Agent 协作：注入群消息上下文

**文件**: `backend/app/api/feishu.py`

**位置**: `_feishu_event()` 函数内，`llm_user_text` 构建之后、流式卡片响应之前（约 line 580 之后）

**问题**: 飞书群聊中，用户 @ 机器人后只有被 @ 的机器人回复。但 AI 需要知道群里其他机器人的对话内容才能决定是否要回复（或协作）。

**修改**: 在 bot 被 mention 时，主动拉取群里最近 10 分钟的消息，过滤掉自己的消息和纯 @ 消息，将上下文拼接到 `llm_user_text` 前面传给 LLM。

```python
# ── Inject group chat context for multi-agent collaboration ──
if chat_type == "group" and chat_id:
    try:
        import time as _grp_time
        async def _fetch_group_context() -> str:
            _app_token = ""
            try:
                _resp = await feishu_service.get_tenant_access_token(config.app_id, config.app_secret)
                _app_token = _resp.get("tenant_access_token", "")
            except Exception:
                return ""
            if not _app_token:
                return ""
            _hdrs = {"Authorization": f"Bearer {_app_token}"}
            _params = {
                "container_id_type": "chat",
                "container_id": chat_id,
                "start_time": str(int(_grp_time.time()) - 600),
                "end_time": str(int(_grp_time.time())),
                "sort_type": "ByCreateTimeAsc",
                "page_size": 50,
            }
            _msgs_resp = feishu_service._sync_get(...)
            _items = (_msgs_resp.json().get("data") or {}).get("items", [])
            _parts = []
            for _m in _items:
                if _m["sender"]["id"] == _bot_open_id:
                    continue
                if _m["msg_type"] == "text":
                    _txt = re.sub(r"@_user_\d+", "", _txt).strip()
                    if _txt:
                        _parts.append(f"[群消息] {_txt}")
                elif _m["msg_type"] == "post":
                    # 解析富文本消息...
            return "\n".join(_parts)

        _grp_ctx = await _fetch_group_context()
        if _grp_ctx:
            llm_user_text = (
                f"[群聊上下文（最近消息）]\n{_grp_ctx}\n\n---\n当前用户的消息：\n{llm_user_text}"
            )
    except Exception as _grp_e:
        logger.error(f"[Feishu] Group context injection error: {_grp_e}")
```

---

## 10. 飞书群聊多 Agent @mention 过滤与上下文注入（2026-03-22）

**文件**: `backend/app/api/feishu.py`

### 10.1 @mention 过滤（按用户指定 bot 回复）

**问题**: 群里所有 bot 都收到消息并全部回复，用户 @ 某个 bot 时也如此。

**逻辑**:
- 有 mention 列表时：只有被 @ 的 bot 回复，其他 bot 跳过
- 没有 mention 时：所有 bot 回复（会议模式）

**关键代码**（在 `llm_user_text` 构建之前）:
```python
_mentioned_open_ids = []
_mention_list = message.get("mention", []) or message.get("mentions", [])
for _m in _mention_list:
    if isinstance(_m, dict):
        _id = _m.get("id", {})
        if isinstance(_id, dict):
            _mentioned_open_ids.append(_id.get("open_id", ""))

if _mentioned_open_ids:
    _bot_open_id = await _get_bot_open_id()  # httpx 调用 /bot/v3/info
    _other_mentions = [_m for _m in _mention_list
                       if (_m.get("id") or {}).get("open_id", "") != _bot_open_id]
    if _bot_open_id and _bot_open_id not in _mentioned_open_ids:
        return {"code": 0, "msg": "bot not mentioned"}
else:
    _other_mentions = []
```

### 10.2 Bot 发消息时自动 @ 其他被 @ 的 bot

**修改**: `feishu_service.send_message` 支持 `mentions` 参数；回复时如果有 `_other_mentions`，用 `post` 类型消息自动带上 @其他bot。

### 10.3 Bot-to-Bot 一轮限制

**问题**: Bot A @ Bot B → Bot B 回复 → Bot A 继续回复 → 无限循环。

**修改**: 模块级 `_bot_reply_count` 计数器，每 bot 每 chat 只允许回复其他 bot 一次。

```python
_bot_reply_count: dict[str, dict[str, int]] = {}  # {chat_id: {sender_bot_id: count}}

# 收到 bot 消息时检查
if _sender_type == "bot" and chat_type == "group" and _bot_open_id:
    if _bot_reply_count.get(chat_id, {}).get(_sender_open_id, 0) >= 1:
        return {"code": 0, "msg": "bot-to-bot round limit"}

# 回复成功后记录
if _sender_type == "bot" and _sender_open_id:
    _bot_reply_count.setdefault(chat_id, {})[_sender_open_id] = \
        _bot_reply_count[chat_id].get(_sender_open_id, 0) + 1
```

### 10.4 智能群上下文（按 bot 最后消息时间戳）

**问题**: 每次固定拉取 10 分钟上下文不科学，应该只拉取 bot 最后一条消息之后的新消息。

```python
_last_bot_msg_time: dict[str, float] = {}

# 获取上下文
_last_time = _last_bot_msg_time.get(str(agent_id), 0)
_params["start_time"] = str(int(_last_time) + 1) if _last_time else ""

# 回复成功后
_last_bot_msg_time[str(agent_id)] = time.time()
```

---

## 11. Fetch Feishu Group Messages 工具（2026-03-22）

**文件**: 
- `backend/app/services/tool_seeder.py`（工具定义，`is_default: True`）
- `backend/app/services/agent_tools.py`（函数实现 `_fetch_feishu_group_messages` + 分发注册）

**功能**: 让 Agent 可以主动获取飞书群的消息记录

**工具参数**:
- `chat_id`: 群 ID（必填）
- `limit`: 最大消息数（默认 10，最大 20）
- `start_time`: 向前秒数（默认 600）
- `include_own`: 是否包含 bot 消息（默认 true）

**使用**: 后端重启后，管理后台 → Agent → Tools → 安装 `Fetch Feishu Group Messages`。

**工具定义** (tool_seeder.py):
```python
def _FETCH_FEISHU_GROUP_MESSAGES():
    return {
        "name": "fetch_feishu_group_messages",
        "description": """Fetch recent messages from a Feishu group chat.\n\nParams:\n- chat_id: Group chat ID (oc_xxx format)\n- limit: Max messages to fetch (default 10, max 20)\n- start_time: Seconds ago to start from (default 600)\n- include_own: Include bot's own messages (default false)""",
        "parameters": {
            "type": "object",
            "properties": {
                "chat_id": {"type": "string", "description": "The Feishu group chat ID (oc_xxx format)"},
                "limit": {"type": "integer", "description": "Max messages to fetch (default 10, max 20)"},
                "start_time": {"type": "integer", "description": "Seconds ago to start from (default 600)"},
                "include_own": {"type": "boolean", "description": "Include bot's own messages (default false)"},
            },
            "required": ["chat_id"],
        },
        "is_default": True,
    }
```

**工具实现** (agent_tools.py): `_fetch_feishu_group_messages()` 函数

---

---

## 13. 数据库迁移（notifications 表）

**问题**: `notifications` 表缺少 `agent_id` 字段，heartbeat 事务失败。

**解决**: 运行 `alembic upgrade head`

---

## 14. 飞书 WebSocket 事件处理修复（2026-03-23）

### 14.1 _bot_open_id 未定义问题

**文件**: `backend/app/api/feishu.py`

**问题**: 第 276 行使用 `_bot_open_id` 时可能还未定义，导致 `UnboundLocalError`。

**修改**: 
- 初始化 `_bot_open_id = ""` 在判断之前
- 条件判断改为先检查 `_sender_type == "bot" and chat_type == "group" and chat_id`，再在块内获取 `_bot_open_id`

### 14.2 bot_p2p_chat_entered_v1 事件未注册

**文件**: `backend/app/services/feishu_ws.py`

**问题**: 日志报错 "processor not found, type: im.chat.access_event.bot_p2p_chat_entered_v1"

**修改**: 添加事件注册：
```python
.register_p2_customized_event("im.chat.access_event.bot_p2p_chat_entered_v1", handle_message)
```

### 14.3 fetch_feishu_group_messages 属性名错误

**文件**: `backend/app/services/agent_tools.py`

**问题**: 使用了不存在的 `feishu_app_id` 和 `feishu_app_secret` 属性

**修改**: 改为正确的 `app_id` 和 `app_secret`

### 14.4 write_file 的 enterprise_info 路径映射缺失

**文件**: `backend/app/services/agent_tools.py`

**问题**: `write_file("enterprise_info/产品经理/xxx.md")` 写到了 Agent 自己 workspace，而不是共享的 `enterprise_info_{tenant_id}` 目录。

**修改**: 给 `_write_file` 函数添加 `tenant_id` 参数，并添加与 `_list_files` 相同的 enterprise_info 路径映射逻辑。

### 14.5 Linux 硬编码路径修复（Windows 兼容）

**文件**: 
- `backend/app/services/agent_tools.py`
- `backend/app/api/feishu.py`

**问题**: 飞书联系人缓存路径硬编码为 `/data/workspaces/...`

**修改**: 全部改为使用 `WORKSPACE_ROOT`

### 14.6 SyntaxWarning escape sequence

**文件**: `backend/app/services/agent_tools.py`

**问题**: `\_` 语法警告

**修改**: 改为 `r"\_"` (raw string)

### 14.7 前端聊天输入框优化

**文件**: `frontend/src/pages/AgentDetail.tsx`

**修改**:
- 删除全部 `refetchInterval`（4处）
- ChatInput 改为 uncontrolled 模式
- `sendChatMsg` 从 `chatInputRef.current.value` 读取

### 14.8 数据库迁移：llm_models.temperature

**问题**: 新版本需要 `temperature` 字段

**修复**: 
```sql
ALTER TABLE llm_models ADD COLUMN temperature FLOAT DEFAULT 0.7;
```

### 15.1 bot_p2p_chat_entered_v1 事件注册

**文件**: `backend/app/services/feishu_ws.py`

**问题**: 飞书机器人加入私聊事件未注册

**修改**: 添加事件注册：
```python
.register_p2_customized_event("im.chat.access_event.bot_p2p_chat_entered_v1", handle_message)
```

### 15.2 Linux 硬编码路径修复（Windows 兼容）✅ 已实现

**文件**: 
- `backend/app/services/agent_tools.py`
- `backend/app/api/feishu.py`

**问题**: 飞书联系人缓存路径硬编码为 `/data/workspaces/...`

**修改**: 全部改为使用 `get_settings().AGENT_DATA_DIR`

### 15.3 SyntaxWarning escape sequence ✅ 已实现

**文件**: `backend/app/services/agent_tools.py`

**问题**: `\_` 语法警告

**修改**: 改为 `r"\_"` (raw string)

### 15.4 数据库迁移：llm_models.temperature ✅ 已实现

**问题**: 新版本需要 `temperature` 字段

**修复**: 
```sql
ALTER TABLE llm_models ADD COLUMN temperature FLOAT DEFAULT 0.7;
```

### 15.5 fetch_feishu_group_messages 工具优化 ✅ 新增

**文件**: `backend/app/services/agent_tools.py`

**功能**:
- 群号动态获取：`[From: {chat_id}]`
- 格式 `(发送者@目标)`，如 `(小美@赵光明)`
- Bot 消息默认 @赵光明
- 最多 10 条消息
- 每次拉取后保存最后一条消息时间到 `feishu_fetch_times.json`
- 下次只拉取该时间之后的消息（增量拉取）
- 验证 chat_id 必须以 `oc_` 开头（群号格式）

### 15.6 feishu.py 变量初始化修复 ✅ 新增

**文件**: `backend/app/api/feishu.py`

**问题**: `_other_mentions` 变量在闭包中未定义

**修改**: 在函数开头初始化 `_other_mentions = []` 和 `_mentioned_humans = []`

### 15.7 群上下文注入限制 ✅ 新增

**文件**: `backend/app/api/feishu.py`

**问题**: 私聊也会拉取群历史消息

**修改**: `_fetch_group_context()` 只在 `chat_type == "group"` 时调用

### 15.8 群聊天记录改用工具获取 ✅ 新增

**文件**: `backend/app/api/feishu.py`

**功能**:
- 群上下文获取改为调用 `_fetch_feishu_group_messages` 工具
- 复用工具的增量拉取、格式化为 `(发送者@目标)` 等功能
- 简化代码，删除约60行重复的 API 调用代码

### 15.9 sandbox_enabled 字段添加 ✅ 新增

**文件**: 
- `backend/app/schemas/schemas.py` - AgentUpdate schema 添加字段
- `frontend/src/pages/AgentDetail.tsx` - Settings 页面添加沙箱开关

**功能**: 允许前端保存沙箱开关设置

### 15.10 _execute_code 缺少 agent_id 参数修复 ✅ 新增

**文件**: `backend/app/services/agent_tools.py`

**问题**: 调用 `_execute_code()` 时缺少 `agent_id` 参数

**修改**: 添加 `agent_id` 参数传递

### 15.11 LLM 超时时间改为 10 分钟 ✅ 新增

**文件**: `backend/app/services/llm_client.py`

**修改**: `timeout` 默认值从 120 秒改为 600 秒

### 15.12 聊天输入框支持排队 ✅ 新增

**文件**: `frontend/src/pages/AgentDetail.tsx`

**问题**: 机器人回答问题时，输入框被禁用，无法输入

**修改**: 移除 `isWaiting || isStreaming` 禁用条件，只在 `!wsConnected` 时禁用

**效果**: 用户可以在机器人回答时输入消息，消息会自动排队处理

### 15.13 fetch_feishu_group_messages 修复 ✅ 新增

**文件**: `backend/app/services/agent_tools.py`

**修复内容**:
- 时间戳格式化为 `[dd/HH:mm:ss]`
- sender 显示为 `user:{open_id}`
- interactive 卡片消息解析（双重 JSON 编码）
- 默认获取 50 条，最大 100 条
- 默认时间范围改为 1 小时
