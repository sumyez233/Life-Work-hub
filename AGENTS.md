# AGENTS.md · Lifehub 协同开发与长期维护准则

> **致进入本工作区的所有 AI Agent（Codex / Claude / Cursor / Harness 等）：**  
> 本文件是本工作区的最高维护协议。任何新开的会话、子代理或后续维护者，必须严格遵守以下准则，持续保障和维护核心功能。

---

## 📌 一、项目定位与双仓库架构

Lifehub 是本地优先（Local-First）的个人中台系统。手机飞书是遥控器，宿主 PC 是大脑。

- **私有工作区**：`F:\电脑中台\lifehub`（当前仓库）
  - 运行真实的个人定时服务（Serve 端口 8420）与飞书长连接网关（Bot WebSocket）。
  - 包含用户私有配置 `config.toml`、个人数据库 `data/hub.db`、持久化日志 `data/bot.log`。
  - **绝对禁止**将私有配置、Token、群聊 ID 推送到任何公开仓库！
- **公开开源仓库**：`F:\电脑中台\lifehub-public`
  - 关联远端：`https://github.com/sumyez233/Life-Work-hub.git`（分支 `main`）。
  - 机械脱敏、纯净开源，含自动化测试流水线。代码核心变更必须经测试后同步推送。

---

## 🧠 二、核心旗舰功能：Codex CLI 直通（持续维护保障）

**此功能为 Lifehub 最核心的技术护城河之一，必须永久保持可用并持续迭代！**

### 1. 运行机制
- 移动端飞书发送 `codex <指令>`，Bot 捕获后交由 `lifehub.codex_runner`。
- 本地后台异步拉起原生 Codex CLI 进程：
  ```bash
  codex exec <prompt> --danger-full-access -C <workdir> [--resume <session_id>]
  ```
- 会话追踪：每个飞书 Thread / 单聊对应一个唯一的 Codex Session ID，保存在 `data/codex_sessions.json`。支持上下文多轮连续追问。
- 任务完成后通过飞书 API 自动异步推送执行总结与执行结果。

### 2. 白名单守则（重点排查项）
- `config.toml` 中包含 `[codex].allowed_chats`。
- **Agent 注意**：若用户反馈收到「🧠 Codex 直通未启用：请把本会话 ID 加入 config.toml...」提示：
  1. 打开 `data/bot.log`，查找最新收到消息的 `chat_id`（例如 `oc_b09bf1bf7d230b259f2d057ad151fda7`）；
  2. 立即将该 ID 追加至 `config.toml` 的 `allowed_chats` 列表中；
  3. 平滑重启后台 Bot 进程并通知用户。

### 3. 执行纪律
- 严禁随意更改 `codex_runner.py` 中的超时机制（默认 600s）和长文本智能切片规则（4000 字符限制）。
- 在 Windows 生产环境下，必须保持沙箱模式为 `danger-full-access`，避免临时目录权限陷阱。

---

## 🛡️ 三、服务稳定性与排错规范

### 1. 单实例互斥锁（Mutex）
- `lifehub.cli` 通过底层的 `os.open` + `msvcrt.locking`（Windows）持有 `data/bot.lock` 和 `data/serve.lock`。
- 启动新实例前，必须检查并清理旧残留进程，严禁强行绕过锁机制。

### 2. 消息去重（Deduplication）
- 飞书 WebSocket 断网重连时会重放历史消息。`bot.py` 维护了 5 分钟滑动窗口的 `_is_duplicate_message(msg_id)`，严禁删除此去重守卫。

### 3. SDK 回复判断
- 飞书 SDK（`lark-oapi`）响应必须使用 `resp.success()` 判定，严禁使用 `resp.code != 0`，否则会导致成功的消息被二次降级发送，引发群内刷屏。

### 4. 实时日志
- 所有消息接收与发送必须统一通过 `_log()` 写入 `data/bot.log`。排查问题时第一时间查看 `data/bot.log`。

---

## 🔄 四、双仓库同步规范

当你在 `F:\电脑中台\lifehub` 完成了代码改进或 Bug 修复：
1. 确认私有端测试通过，服务正常拉起；
2. 将脱敏的代码变动同步至 `F:\电脑中台\lifehub-public`；
3. 在 `F:\电脑中台\lifehub-public` 运行全量单元测试：
   ```powershell
   F:\电脑中台\lifehub\.venv\Scripts\python.exe -m unittest discover -s tests
   ```
4. 确保测试 100% 通过后，执行 git commit 并推送到 `origin main`。
