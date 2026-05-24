# ai-superpower 开发环境指南

本文档说明如何在**不影响生产实例**的前提下，使用独立的开发版 ai-superpower 进行功能开发与联调。

> 生产环境说明见 [README-zh.md](./README-zh.md)。

---

## 生产 vs 开发

| 维度 | 生产 | 开发 |
|------|------|------|
| 源码目录 | `/home/hermes/ai-superpower` | `/home/hermes/ai-superpower-dev` |
| Git 分支 | `master` | `dev-env`（worktree） |
| 配置 | `~/.ai-superpower/config.toml` | `~/.aisp-dev-home/.ai-superpower/config.toml` |
| 数据 | `/home/hermes/ai-superpower/db/` | `/home/hermes/ai-superpower-dev/db/` |
| HTTP 端口 | **8000** | **8100** |
| 允许删除 | `false` | `true` |
| 虚拟环境 | 系统全局 / 生产安装 | `/home/hermes/ai-superpower-dev/.venv` |

**隔离原理：** 开发实例通过 `HOME=/home/hermes/.aisp-dev-home` 读取独立配置，与生产的 `~/.ai-superpower` 完全分离；端口 8100 与生产的 8000/8001 互不冲突。

---

## 架构示意

```
/home/hermes/
├── ai-superpower/              ← 生产源码（master）
├── ai-superpower-dev/          ← 开发源码（dev-env worktree）
│   ├── .venv/                  ← 开发专用 Python 环境
│   ├── db/                     ← 开发 CSV 数据
│   └── backups/
├── .ai-superpower/             ← 生产配置（勿动）
│   └── config.toml
└── .aisp-dev-home/             ← 开发 HOME
    └── .ai-superpower/
        └── config.toml         ← 开发配置
```

---

## 快速开始

### 一键启动

```bash
# 首次运行会自动初始化；之后直接启动
bash ~/run-aisp-dev.sh
```

### 分步操作

```bash
# 1. 初始化（创建 worktree、venv、配置、空 CSV）
bash ~/ai-superpower/scripts/setup-dev-env.sh

# 2. 启动开发服务
bash ~/ai-superpower/scripts/run-dev.sh

# 3. 停止开发服务
bash ~/ai-superpower/scripts/stop-dev.sh
```

### 访问地址

| 用途 | 地址 |
|------|------|
| Web UI | http://localhost:8100 |
| 健康检查 | http://localhost:8100/health |
| API 基址 | http://localhost:8100/api/ |

Windows 浏览器可直接访问 WSL 中的 `localhost:8100`。

---

## 开发 CLI 用法

开发环境的 CLI 必须带上独立 `HOME`，否则会连到生产配置：

```bash
export AISP_DEV_HOME=/home/hermes/.aisp-dev-home
export AISP_CLI="$HOME/ai-superpower-dev/.venv/bin/ai-superpower"

# 项目管理
HOME=$AISP_DEV_HOME $AISP_CLI project list
HOME=$AISP_DEV_HOME $AISP_CLI project create --name "测试项目"

# 提案管理
HOME=$AISP_DEV_HOME $AISP_CLI proposal list
HOME=$AISP_DEV_HOME $AISP_CLI proposal create \
  --title "测试提案" --owner dev --project-id PRJ-xxx --stage ideation

# TUI
HOME=$AISP_DEV_HOME $AISP_CLI tui
```

也可通过环境变量覆盖 API Key（CLI 客户端优先读取 `SUPERPOWER_API_KEY`）：

```bash
export SUPERPOWER_API_KEY="$(grep '^key' ~/.aisp-dev-home/.ai-superpower/config.toml | cut -d'"' -f2)"
```

---

## API 调用示例

API Key 位于 `~/.aisp-dev-home/.ai-superpower/config.toml` 的 `[api].key` 字段。

```bash
DEV_KEY="$(grep '^key' ~/.aisp-dev-home/.ai-superpower/config.toml | cut -d'"' -f2)"

# 列出项目
curl -s "http://localhost:8100/api/projects" \
  -H "X-API-Key: $DEV_KEY" | python3 -m json.tool

# 统计信息
curl -s "http://localhost:8100/api/stats?days=7" \
  -H "X-API-Key: $DEV_KEY"

# Undo 操作（V4 新增）
curl -s -X POST "http://localhost:8100/api/replay/undo" \
  -H "X-API-Key: $DEV_KEY" \
  -H "Content-Type: application/json" \
  -d '{"entity": "proposal", "id": "P-20260526-001"}'
```

集成测试可指定基址：

```bash
AI_SUPERPOWER_BASE=http://localhost:8100 pytest tests/test_api_scenarios.py -v
```

---

## 初始化选项

### 从生产复制 CSV 快照

适合需要真实数据形态做联调，但**不要在 dev 中写回生产**：

```bash
COPY_PROD_DATA=1 bash ~/ai-superpower/scripts/setup-dev-env.sh
```

### 自定义端口

```bash
AISP_DEV_PORT=8200 bash ~/ai-superpower/scripts/setup-dev-env.sh
AISP_DEV_PORT=8200 bash ~/ai-superpower/scripts/run-dev.sh
```

同时需更新 `~/.aisp-dev-home/.ai-superpower/config.toml` 中的 `port` 与 `socket_path`。

### 自定义 worktree 分支名

```bash
AISP_DEV_BRANCH=my-feature bash ~/ai-superpower/scripts/setup-dev-env.sh
```

---

## 日常开发流程

```bash
# 1. 在开发目录改代码
cd ~/ai-superpower-dev
source .venv/bin/activate

# 2. 重装（代码变更后）
pip install -e ".[dev]"

# 3. 运行测试（不依赖 live server）
pytest tests/ -v

# 4. 重启开发服务
bash ~/ai-superpower/scripts/stop-dev.sh
bash ~/ai-superpower/scripts/run-dev.sh

# 5. 提交 — 在 dev worktree 提交，再合并到 master
git add -p && git commit -m "feat: ..."
# 回到生产目录合并（示例）
cd ~/ai-superpower && git merge dev-env
```

---

### 4. Undo 操作（V4 新增）

```bash
DEV_KEY="$(grep '^key' ~/.aisp-dev-home/.ai-superpower/config.toml | cut -d'"' -f2)"

# Undo API（Web UI 通过 /web/audit 页面按钮触发）
curl -X POST "http://localhost:8100/api/replay/undo" \
  -H "X-API-Key: $DEV_KEY" \
  -H "Content-Type: application/json" \
  -d '{"entity": "proposal", "id": "P-20260526-001"}'

# CLI 方式（等效）
export AISP_DEV_HOME=/home/hermes/.aisp-dev-home
HOME=$AISP_DEV_HOME $AISP_CLI replay --undo P-20260526-001 --dry-run
```

**V4 功能：**
- Web UI `/web/audit` 每条记录增加 Undo 按钮，点击触发 POST `/api/replay/undo`
- 支持 entity 类型：`project`、`proposal`
- dry-run 默认开启（预览变更，不实际写入）
- DELETE 操作 undo 返回警告但不阻止

---

## 日志与排错

| 项目 | 路径 |
|------|------|
| 运行日志 | `/tmp/ai-superpower-dev.log` |
| PID 文件 | `/tmp/ai-superpower-dev.pid` |
| 开发配置 | `~/.aisp-dev-home/.ai-superpower/config.toml` |
| 开发数据 | `~/ai-superpower-dev/db/` |

```bash
# 查看日志
tail -f /tmp/ai-superpower-dev.log

# 检查端口占用
ss -tlnp | grep -E ':8100|:8000'

# 健康检查
curl -s http://localhost:8100/health
```

**常见问题：**

| 现象 | 处理 |
|------|------|
| `开发环境未初始化` | 先运行 `setup-dev-env.sh` |
| 端口 8100 被占用 | `bash ~/ai-superpower/scripts/stop-dev.sh` |
| CLI 连到生产 | 确认命令前加了 `HOME=/home/hermes/.aisp-dev-home` |
| venv 创建失败 | 安装 `python3.12-venv`，或确保 `uv` 可用 |
| Web UI 401 | 在 Settings 页填入 dev 配置中的 API Key |

---

## 环境变量参考

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HERMES_HOME` | `/home/hermes` | 用户主目录 |
| `AISP_DEV_PORT` | `8100` | 开发 HTTP 端口 |
| `AISP_DEV_BRANCH` | `dev-env` | worktree 分支名 |
| `COPY_PROD_DATA` | `0` | 设为 `1` 时从生产复制 CSV |
| `AISP_DEV_LOG` | `/tmp/ai-superpower-dev.log` | 运行日志路径 |
| `AISP_DEV_PID` | `/tmp/ai-superpower-dev.pid` | PID 文件路径 |
| `SUPERPOWER_API_KEY` | — | CLI 客户端 API Key 覆盖 |
| `AI_SUPERPOWER_BASE` | `http://localhost:8000` | 集成测试 API 基址 |

---

## 脚本位置

开发脚本维护在生产仓库的 `scripts/` 目录（worktree 创建时若尚未包含，以生产目录为准）：

```
/home/hermes/ai-superpower/scripts/
├── setup-dev-env.sh    # 初始化 worktree + venv + 配置 + 数据
├── run-dev.sh          # 后台启动开发实例
└── stop-dev.sh         # 停止开发实例

/home/hermes/run-aisp-dev.sh   # 快捷入口（setup / run / stop）
```

---

## 注意事项

1. **不要修改生产配置** — 开发操作只涉及 `~/.aisp-dev-home/` 和 `ai-superpower-dev/`。
2. **端口隔离** — 开发脚本只清理 8100，不会停止 8000 上的生产实例。
3. **数据独立** — 开发 CSV 与生产完全分离；`COPY_PROD_DATA=1` 仅做一次性快照复制。
4. **删除权限** — 开发环境 `allow_delete = true`，便于测试删除与回滚，请勿在生产开启。
5. **Agent 联调** — 若有脚本写死 `http://127.0.0.1:8000`，开发时需改为 `8100` 或通过 `AI_SUPERPOWER_BASE` 覆盖。

---

## 相关文档

- [README-zh.md](./README-zh.md) — 项目功能、API、状态机、测试
- [README.md](./README.md) — English version
- 在线文档：https://yeluo45.github.io/ai-superpower/
