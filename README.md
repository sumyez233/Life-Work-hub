# Lifehub · 本地优先的个人中台

> **Local-First Personal Hub · 手机飞书是遥控器，本地 PC 是大脑**
>
> Lifehub turns your own Windows PC into a personal hub you can talk to from Feishu:
> capture todos / events / expenses in plain language, watch your Bitable tables,
> and shuttle files between phone and computer — all data stays on your machine.

> **Status**: 个人单用户项目（experimental / alpha），Windows + 飞书优先。核心功能在作者机器上真实运行，
> 但 API 与数据格式仍可能演进，暂不承诺向后兼容。欢迎 Issue / PR 共建。

你的待办、日程、账目散落在脑子里、聊天记录里、本地便签里。Lifehub 把它们收进一个**运行在你电脑上**的中台：飞书里发一句大白话即可录入，每天早晨自动收到晨报，事件发生前主动提醒，数据永远只在本地。

---

## 🎬 它长什么样

在飞书里跟机器人说话，就像发给一个朋友：

```text
你：明天下午3点开产品评审会
Lifehub：✓ 已记日程 #12：产品评审会（明天 15:00）

你：午饭 35
Lifehub：✓ 已记餐饮 35 元

你：买牛奶 买速溶咖啡
Lifehub：都记下了（待办 2 条）
  · 买牛奶
  · 买速溶咖啡

你：搞定 牛奶
Lifehub：✓ 已搞定：买牛奶，干得漂亮！
```

不需要打开网页、不需要记忆编号、不需要学习任何命令。想看全貌时发 `看看待办`，飞书会弹出一张原生交互卡片，按钮原地打卡。

---

## ✨ 核心特性 Features

### 💬 对话即一切 (Conversational Core)

- `买牛奶` → 待办；`明天下午3点开会` → 日程；`午饭 35` / `工资 8000` → 自动分类记账；
- `搞定 牛奶` / `会议开完了` → 模糊匹配打卡，标题里不用出现编号；
- 多行整段粘贴自动分节入库；高频短句本地规则解析（零延迟、零 Token 成本），复杂内容可选用 LLM 兜底。

### 🎴 Schema 2.0 原生交互卡片 (Native Interactive Cards)

- `看看待办` / `看账本` / `看安排` 按需召唤，不主动刷屏；
- 卡片内置打卡按钮，点击后**原地刷新**，无需刷新页面；
- 逾期变红、今日有事变橙、平静时清爽蓝绿——状态一眼可见。

### 📊 飞书多维表格联动 (Bitable Watchdog)

- 在 `config.toml` 绑定你自己的任意一张 Bitable；
- 飞书里发 `看大盘`：查看**记录总数**与**最近更新时间**；
- 分页拉取全量记录并缓存为本地 JSON 快照，供其他脚本与工作流联动取数；
- 业务语义完全由你的表格定义，代码不做任何字段假设。

### 📁 手机 ⇋ 电脑 全双工文件流 (Full-Duplex Files)

- **下行**：`传 调研报告` → 电脑在配置的目录里检索并把文件直接推回手机；
- **上行**：手机发来的文档 / 图片 → 毫秒级落盘本地收件箱，回执路径；
- 适合"手机当终端、电脑当仓库"的阅读、归档与后续处理流水线。

### 🧠 可选 Codex CLI 直通 (Agent Bridge)

- 飞书发 `codex <任务>`，本机 Codex 执行真实终端任务并回传结果；
- 支持话题级多轮续聊（自动 resume 上一次会话）；
- 默认 **read-only 沙箱 + 会话白名单**，无授权会话不可触发。

### ⏰ 被动唤醒，而不是主动打开

- 每日晨报（待办 / 今日日程 / 昨日支出 / 表格动态）；
- 日程开始前 N 分钟主动私聊提醒，带持久化去重，重启不重复打扰。

### 🔒 Local-First 数据主权

- SQLite 单文件存储（WAL），备份 = 拷贝一个文件；
- 配置、缓存、收件箱全部本地；飞书仅作为消息通道与卡片 UI；
- 基于飞书 WebSocket 长连接，**无需公网 IP / 端口映射**。

---

## 🏗️ 架构 Architecture

```text
             手机飞书（私聊 / 群聊 @机器人）
                       │  WebSocket 长连接
                       ▼
              lifehub.bot  (事件路由 / 解析 / 卡片 / 文件)
         ┌─────────────┬──────────────┬─────────────┐
         ▼             ▼              ▼             ▼
     本地 SQLite   飞书多维表格    本地磁盘检索    Codex CLI
   (todo/event/     (更新概况与     收件箱落盘      (可选,
     ledger)         数据快照)        / 文件回推      白名单)
         └─────────────┴──────────────┴─────────────┘
                       │
                       ▼
         lifehub.serve  (APScheduler + FastAPI，可选)
               每日晨报 · 提前提醒 · 8420 健康检查
```

### 解析引擎：规则优先，LLM 兜底

```text
一条消息
  ├─ 规则引擎（无网络、无 Token）：金额/日期/星期/口语动词……
  └─ 复杂或含换行 → 可选 LLM（OpenAI 兼容接口）→ 失败自动回退规则
            ↓
   结构化记录（todo / event / ledger）→ SQLite
```

---

## 🗂️ 项目结构 Project Layout

```text
lifehub/
├── config.example.toml      # 配置模板（复制为 config.toml 后填写）
├── requirements.txt
├── lifehub/
│   ├── cli.py               # 统一命令入口（bot / serve / add / todos / send...）
│   ├── bot.py               # 飞书长连接机器人、事件分发、卡片补丁
│   ├── cards.py             # Schema 2.0 交互卡片引擎
│   ├── parser.py            # 本地规则解析（单行 / 多行分节 / 时间 / 金额）
│   ├── ai.py                # 可选 LLM 兜底（OpenAI 兼容）
│   ├── db.py                # SQLite CRUD + 模糊打卡
│   ├── bitable.py           # 多维表格通用联动（更新概况 / 数据快照）
│   ├── transfer.py          # 文件检索、上传直传、收件箱落盘
│   ├── codex_runner.py      # 可选 Codex CLI 直通执行器
│   ├── report.py            # 晨报生成器
│   ├── reminders.py         # 日程提前提醒扫描与去重
│   ├── push.py              # 飞书 Webhook / OpenAPI 推送
│   └── api.py               # 可选 FastAPI 接口
├── scripts/                 # 一键启动 / 状态巡检 / 开机自启
├── docs/feishu-setup.md     # 飞书应用与权限配置指引
└── 启动.bat                 # Windows 双击启动
```

---

## 🚀 快速开始 Quick Start

### 0. 环境

- Windows 10 / 11（脚本面向 Windows 开发）
- Python 3.12+（3.13 亦可）

### 1. 克隆并安装

```powershell
git clone <your-repo-url> lifehub
cd lifehub
python -m venv .venv
python -m pip --python .venv\Scripts\python.exe install -r requirements.txt

# （可选）标准安装：额外获得全局 lifehub 命令
python -m pip --python .venv\Scripts\python.exe install -e ".[dev]"
```

> 若你的路径含中文导致 venv 失败，见下方"常见坑"。

### 2. 配置

```powershell
Copy-Item config.example.toml config.toml
notepad config.toml
```

至少填写：

```toml
[feishu]
app_id = "cli_xxxxxxxx"
app_secret = "xxxxxxxx"
```

飞书自建应用、权限、事件订阅的完整步骤见 [docs/feishu-setup.md](docs/feishu-setup.md)（约 10 分钟）。

### 3. 启动

**方式 A：双击 `启动.bat`**（静默拉起 bot + serve，日常使用推荐）。

**方式 B：命令行分开启动**

```powershell
.\.venv\Scripts\python -m lifehub.cli bot     # 飞书对话机器人（前台）
.\.venv\Scripts\python -m lifehub.cli serve   # 定时晨报 / 提醒 + API（前台）
```

### 4. 验收

在飞书里给机器人发：`帮助` → `买牛奶` → `看看待办` → `搞定 牛奶` → `午饭 35`。

---

## 📱 手机端指令速查 Command Cheat Sheet

| 输入 | 作用 |
| :--- | :--- |
| `买牛奶` / `周五交周报` | 录入待办（口语词自动清洗） |
| `明天下午3点开会` | 录入日程，开始前自动提醒 |
| `午饭 35` / `打车 23.5` / `工资 8000` | 记账，自动分类收支 |
| `搞定 牛奶` / `会议开完了` / `材料打印完了` | 模糊匹配打卡 |
| `删掉 牛奶` / `不要了 3` | 级联检索并删除（待办/日程/账目） |
| `看看待办` / `看账本` / `看安排` | 呼出对应交互卡片 |
| `今天` / `晨报` / `总览` | 立即生成今日总览 |
| `看大盘` | 查看已绑定多维表格的更新概况 |
| `传 调研报告` / `发 交接文档` | 电脑检索文件并推送手机 |
| *(直接发文件 / 图片)* | 自动存入收件箱并回执本地路径 |
| `codex 帮我看看 xxx` | 交给本机 Codex 执行（需配置白名单） |

---

## ⚙️ 配置参考 Configuration Reference

| 段 | 字段 | 说明 |
| :--- | :--- | :--- |
| `[feishu]` | `app_id` / `app_secret` | 飞书自建应用凭据（必填） |
| `[feishu]` | `report_chat` | 晨报推送目标群（`python -m lifehub.cli chats` 查询） |
| `[ai]` | `api_key` / `base_url` / `model` | 可选 LLM 兜底，任意 OpenAI 兼容接口 |
| `[hub]` | `db` | SQLite 路径，默认 `data/hub.db` |
| `[hub]` | `report_time` / `remind_before` | 晨报时间 / 提前提醒分钟数 |
| `[bitable]` | `app_token` / `table_id` | 多维表格绑定（可选） |
| `[bitable]` | `updated_field` | 记录更新时间的字段名（可选，用于展示） |
| `[transfer]` | `inbox_dir` | 手机上行文件收件箱（默认项目内 `inbox/`） |
| `[transfer]` | `search_dirs` | 下行文件检索目录列表 |
| `[codex]` | `enabled` / `allowed_chats` | Codex 直通开关与会话白名单 |
| `[codex]` | `sandbox` | `read-only` / `workspace-write` / `danger-full-access` |

---

## 🧪 开发与测试 Development

```powershell
# 安装项目（含开发依赖）
python -m pip install -e ".[dev]"

# 运行单元测试（无需 pytest，unittest 即可；CI 两者皆可）
python -m unittest discover -s tests -v
# 或
pytest
```

测试覆盖：解析规则、SQLite CRUD / 模糊打卡、卡片 Schema 2.0 结构、多维表格摘要、配置脱敏默认值。
CI（`.github/workflows/ci.yml`）会在 Python 3.12 / 3.13 上执行语法检查、单元测试与 CLI 冒烟。

---

## 🛠️ 运维 Operations

```powershell
# 状态巡检（进程 + 8420 健康检查）
powershell -ExecutionPolicy Bypass -File .\scripts\status.ps1

# 静默拉起全部服务（无黑框）
wscript .\scripts\start_all.vbs

# 安全停止 lifehub 进程（只杀本仓库的 Python，不误伤其他进程）
powershell -ExecutionPolicy Bypass -File .\scripts\stop_all.ps1

# 安装 / 卸载开机自启
powershell -ExecutionPolicy Bypass -File .\scripts\install_autostart.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall_autostart.ps1
```

### 备份

Lifehub 的一切数据都在 SQLite 单文件里：停服（或直接在线，WAL 模式下）拷贝 `data/hub.db` 即可。

---

## 🩹 常见坑 Troubleshooting

1. **控制台输出中文乱码 / UnicodeEncodeError**：代码入口已强制 UTF-8 输出；手动跑命令时先 `chcp 65001`。
2. **中文路径下 `python -m venv` 失败**：改用
   `python -m venv --without-pip .venv`，再用外部 Python 的 pip 跨环境安装：
   `python -m pip --python .venv\Scripts\python.exe install -r requirements.txt`。
3. **卡片按钮点击无反应（lark-oapi 已知 Bug）**：官方 SDK 在 WebSocket 长连接下会静默丢弃卡片回调帧；本项目内置 Monkey-Patch（`bot.py` 的 `_install_card_patch`），升级 SDK 时请保留该补丁。
4. **二进制消息回复失败（飞书 9499）**：内置"线程回贴失败自动降级为直接发消息"的双通道兜底。

---

## 🔐 安全须知 Security Notes

- `config.toml` 含你的真实密钥，已被 `.gitignore` 排除，**严禁提交**；仓库只提供 `config.example.toml`。
- `data/*.db`、缓存 JSON、收件箱均在 `.gitignore` 中，不会入库。
- **Codex 直通风险**：默认 `read-only` 且限 `allowed_chats`。若配置为 `danger-full-access`，飞书消息将能触发本机无沙箱执行——请仅在你完全信任且长期可控的会话中使用，README 与代码注释均不建议默认开启。
- 本项目是面向个人的本地工具，不是企业级多租户系统；请自行评估你所在环境的安全策略。

---

## 🗺️ Roadmap

- [ ] Web 仪表盘（基于已就绪的 FastAPI 与本地数据）
- [ ] 账单一键导入（微信 / 支付宝 CSV）
- [ ] 收件箱文件自动路由（按类型/关键词触发本地工作流）
- [ ] 更完善的多维表格字段映射与多表聚合
- [ ] macOS / Linux 适配

---

## 📄 License

MIT — 详见 [LICENSE](LICENSE)。作者署名：Sumyez。

如果你觉得这个项目有用，欢迎 ⭐ Star、提 Issue 或参与贡献。
