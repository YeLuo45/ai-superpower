# ai-superpower

**提案系统 API 引擎 — `projects.csv` 和 `proposals.csv` 所有变更的唯一入口。**

所有数据变更必须通过 FastAPI 服务器。直接编辑 CSV（脚本、`execute_code`、手动 patch）在架构层面被阻断：不存在任何绕过 API 验证层的修改路径。

---

## 背景问题

| 变更方式 | 风险 |
|---------|------|
| 直接 patch CSV | 绕过校验、污染枚举字段、破坏引用完整性 |
| 通过 API 写入 | Pydantic校验 + 状态机 + flock锁 + JSON 审计 |

---

## 架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        ai-superpower                         │
│                                                              │
│  ┌──────────────┐    ┌──────────────────────────────────┐   │
│  │  CLI (run)   │───→│          FastAPI 服务器            │   │
│  └──────────────┘    │  ─────────────────────────────────  │   │
│                       │  Pydantic 字段校验                   │   │
│  ┌──────────────┐    │  状态机转换校验                     │   │
│  │  Web UI      │───→│  flock 文件锁                      │   │
│  │  (浏览器)     │    │  JSON 字段级审计日志                │   │
│  └──────────────┘    │  引用完整性检查                      │   │
│                       └──────────────┬───────────────────┘   │
│  ┌──────────────┐                   │                        │
│  │  TUI         │───────────────────┘                        │
│  │  (交互终端)   │                                              │
│  └──────────────┘                                              │
│                              ┌──────────▼──────────┐           │
│                              │    CSVStorage        │           │
│                              │  ┌───────────────┐  │           │
│                              │  │ projects.csv  │  │           │
│                              │  │ proposals.csv│  │           │
│                              │  │ audit.log    │  │           │
│                              │  └───────────────┘  │           │
│                              └─────────────────────┘           │
└──────────────────────────────────────────────────────────────┘
```

---

## 核心防护机制

| 机制 | 作用 |
|------|------|
| **API 唯一写入路径** | 所有数据变更必须经过 API，CLI/TUI/Web UI 都是 API 的封装 |
| **Pydantic 校验** | 写入前校验：ID 格式、枚举值、字符串长度、必填字段 |
| **状态机转换校验** | `intake→clarifying→prd_pending_confirmation→...→deployed→delivered` |
| **flock 文件锁** | 读并发、写串行化，避免并发写入导致 CSV 部分写入 |
| **JSON 审计日志** | 字段级变更追踪 + 精确回滚（Replay） |
| **引用完整性** | project_id 存在性检查 + 级联删除保护 |
| **Unix Socket 传输** | 服务器绑定 Unix socket，不暴露网络端口 |
| **API Key 认证** | 每次请求必须带 `X-API-Key` Header |

---

## 三种使用方式

### 1. CLI（命令行）

```bash
# 启动 API 服务器
ai-superpower run

# 项目管理
ai-superpower project create --name "我的项目"
ai-superpower project list
ai-superpower project get PRJ-20250523-001
ai-superpower project delete PRJ-20250523-001

# 提案管理
ai-superpower proposal create --title "新功能" --owner alice --project-id PRJ-20250523-001 --stage ideation
ai-superpower proposal list
ai-superpower proposal list --project-id PRJ-20250523-001 --status intake
ai-superpower proposal get P-20250523-001
ai-superpower proposal update-status P-20250523-001 --status clarifying
ai-superpower proposal update-fields P-20250523-001 --field title="新标题"
ai-superpower proposal delete P-20250523-001

# 工具
ai-superpower validate --data '{"project_id":"PRJ-20250523-001","stage":"ideation"}'
ai-superpower audit --page 1 --page-size 100
ai-superpower sync-to-index

# 审计回滚（Replay / Undo）
ai-superpower replay --last 10 --dry-run    # 查看最近 10 条操作（不执行）
ai-superpower replay --undo P-20250523-001  # 回滚该实体的最后一次操作

# 备份
ai-superpower backup           # 立即备份
ai-superpower backup --list    # 列出所有备份
ai-superpower backup --restore db_backup_20260523_120000  # 恢复备份
```

### 2. Web UI（浏览器）

```bash
# 启动服务器
ai-superpower run
# 然后浏览器打开 http://localhost:8000
```

| 路由 | 说明 |
|------|------|
| `/` | 仪表盘（项目/提案/审计统计） |
| `/web/projects` | 项目列表 + 新建/编辑 |
| `/web/proposals` | 提案列表 + 筛选 + 新建 |
| `/web/audit` | 审计日志时间线 |
| `/web/settings` | 配置页面 |

### 3. TUI（交互终端）

```bash
# 启动交互式终端界面
ai-superpower tui
```

TUI 提供全屏交互界面：项目/提案浏览、搜索、创建、状态更新、审计日志查看。

---

## API 端点

### 健康检查
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 健康检查（无需认证） |

### 项目
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/projects` | 创建项目 |
| GET | `/projects` | 列出项目（分页） |
| GET | `/projects/{id}` | 获取单个项目 |
| PUT | `/projects/{id}` | 更新项目（部分更新） |
| DELETE | `/projects/{id}` | 删除项目 |

### 提案
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/proposals` | 创建提案 |
| GET | `/proposals` | 列出提案（分页+过滤） |
| GET | `/proposals/{id}` | 获取单个提案 |
| PUT | `/proposals/{id}/status` | 更新状态（状态机校验） |
| PUT | `/proposals/{id}/fields` | 更新字段（部分更新） |
| DELETE | `/proposals/{id}` | 删除提案 |

### 工具
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/validate` | 干跑校验（不写入） |
| GET | `/audit` | 查询审计日志 |
| POST | `/replay` | 回滚操作（dry-run/undo） |
| POST | `/backup` | 立即备份 |

---

## 状态机

```
intake → clarifying → prd_pending_confirmation → approved_for_dev
                                                       ↓
             in_tdd_test ←────────────────────── in_dev
                  ↓                                   ↓
         in_test_acceptance ←──────────────── needs_revision
                ↓      ↓
          accepted   test_failed
              ↓
          deployed → delivered
```

---

## 安装

```bash
# 从源码安装
cd ai-superpower
pip install -e . --break-system-packages

# 或使用安装脚本（自动生成 API Key、修复 CSV 表头）
bash deploy/install.sh

# 手动配置 API Key
mkdir -p ~/.ai-superpower
cat > ~/.ai-superpower/config.toml << 'EOF'
[api]
key = "your-32-char-hex-key"
socket_path = "/var/run/ai-superpower/api.sock"
data_dir = "/home/hermes/ai-superpower/db"
allow_delete = false
EOF
```

---

## 启动服务器

```bash
# 手动启动
ai-superpower run

# systemd 部署
sudo cp deploy/ai-superpower.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ai-superpower
```

---

## 配置项

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `key` | （必填） | API Key — 32位十六进制字符串 |
| `socket_path` | `/var/run/ai-superpower/api.sock` | Unix socket 路径 |
| `data_dir` | `/home/hermes/ai-superpower/db` | 数据目录（projects.csv、proposals.csv、audit.log） |
| `allow_delete` | `false` | 是否允许 DELETE 操作（默认 403 拒绝） |

### 备份配置

```toml
[backup]
enabled = false                 # 设为 true 启用定时备份
frequency = "1h"              # 1h / 6h / 1d
max_copies = 48
local_path = "/home/hermes/ai-superpower/backups"
remote_repo = ""               # Git 远程仓库（可选）
remote_branch = "backup"       # 远程分支（可选）
api_key = ""                   # 备用 API Key（可选）
```

---

## 测试

```bash
# 运行全部测试（117 个）
python3 -m pytest tests/ -v

# 运行单个测试文件
python3 -m pytest tests/test_api.py -v
python3 -m pytest tests/test_storage.py -v
python3 -m pytest tests/test_models.py -v
```

---

## 项目结构

```
ai-superpower/
├── src/ai_superpower/
│   ├── models.py        # Pydantic 模型、状态机、枚举定义
│   ├── config.py       # 从 ~/.ai-superpower/config.toml 加载配置
│   ├── storage.py      # CSVStorage：flock + JSON 审计 + 校验
│   ├── server.py      # FastAPI 服务器（9 个端点 + Web UI）
│   ├── client.py       # APIClient：Unix socket HTTP 客户端
│   ├── cli.py          # CLI 入口（project/proposal/audit/replay/backup）
│   ├── tui.py          # Curses TUI（交互终端界面）
│   ├── replay.py       # 审计日志回滚 / 字段级 undo
│   ├── backup.py       # 备份调度器：本地 + Git 远程
│   ├── templates/      # Jinja2 HTML 模板（Web UI）
│   └── static/         # CSS + JS（Web UI）
├── tests/
│   ├── test_models.py  # 37 个测试
│   ├── test_storage.py # 41 个测试
│   ├── test_api.py     # 39 个测试
│   └── test_client.py  # 10 个测试（mock 方式）
├── deploy/
│   ├── ai-superpower.service  # systemd 服务单元
│   └── install.sh              # 安装脚本
└── pyproject.toml
```

---

## 防篡改设计要点

1. **无直接文件写入路径** — `CSVStorage` 是内部模块，外部客户端只能通过 API 操作数据
2. **flock 独占锁** — 所有写操作获取排他锁，并发写入被串行化，不存在部分写入
3. **JSON 字段级审计** — 每次写入记录每个字段的变更前后值，可精确回滚
4. **状态机校验** — 即使绕过 CLI，也无法通过 API 进行非法的状态转换
5. **Pydantic 模型校验** — 非法枚举值、错误 ID 格式、缺失必填字段在写入前被拒绝

---

## 在线文档

GitHub Pages: https://yeluo45.github.io/ai-superpower/
