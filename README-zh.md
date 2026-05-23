# ai-superpower

**提案系统 API 引擎 — `projects.csv` 和 `proposals.csv` 所有变更的唯一入口。**

所有数据变更必须通过 FastAPI 服务器。直接编辑 CSV（脚本、`execute_code`、手动 patch）在架构层面被阻断：不存在任何绕过 API 验证层的修改路径。

---

## 背景问题

| 变更方式 | 风险 |
|---------|------|
| 直接 patch CSV | 绕过校验、污染枚举字段、破坏引用完整性 |
| 通过 API 写入 | Pydantic校验 + 状态机 + flock锁 + SHA256审计 |

---

## 架构图

```
┌─────────────────────────────────────────────────────┐
│                    ai-superpower                     │
│                                                      │
│  ┌──────────────┐    ┌─────────────────────────────┐ │
│  │   CLI        │    │       FastAPI 服务器          │ │
│  │  (Unix Socket)│───→│  ─────────────────────────  │ │
│  └──────────────┘    │  Pydantic 字段校验            │ │
│                      │  状态机转换校验                │ │
│  ┌──────────────┐    │  flock 文件锁                 │ │
│  │  API 客户端   │────→│  SHA256 审计日志            │ │
│  │  (HTTP UDS) │    │  引用完整性检查               │ │
│  └──────────────┘    └──────────────┬──────────────┘ │
│                                     │                │
│                          ┌──────────▼──────────┐    │
│                          │   CSVStorage         │    │
│                          │  ┌────────────────┐  │    │
│                          │  │ projects.csv   │  │    │
│                          │  │ proposals.csv  │  │    │
│                          │  │ audit.log     │  │    │
│                          │  └────────────────┘  │    │
│                          └──────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

---

## 核心防护机制

| 机制 | 作用 |
|------|------|
| **API 唯一写入路径** | 所有数据变更必须经过 API，CLI 是 API 的封装，直接改 CSV 没有路径 |
| **Pydantic 校验** | 写入前校验：ID 格式、枚举值、字符串长度、必填字段 |
| **状态机转换校验** | `intake→clarifying→prd_pending_confirmation→...→deployed→delivered` 每一步转换都在 API 层校验 |
| **flock 文件锁** | 读并发、写串行化，避免并发写入导致 CSV 部分写入 |
| **SHA256 审计日志** | 每次写入记录文件校验和（写前+写后），篡改可检测 |
| **引用完整性** | 创建 proposal 前检查 project_id 是否存在；删除 project 前检查是否有关联 proposal |
| **Unix Socket 传输** | 服务器绑定 Unix socket，不暴露网络端口 |
| **API Key 认证** | 每次请求必须带 `X-API-Key` Header |

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

## CLI 命令

```bash
# 启动服务器
ai-superpower run

# 项目
ai-superpower project create --name "我的项目"
ai-superpower project list
ai-superpower project get PRJ-20250523-001
ai-superpower project delete PRJ-20250523-001

# 提案
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
proposals_csv = "/home/hermes/proposals/proposals.csv"
projects_csv = "/home/hermes/proposals/projects.csv"
audit_log = "/home/hermes/proposals/audit.log"
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
| `proposals_csv` | `/home/hermes/proposals/proposals.csv` | 提案 CSV 路径 |
| `projects_csv` | `/home/hermes/proposals/projects.csv` | 项目 CSV 路径 |
| `audit_log` | `/home/hermes/proposals/audit.log` | 审计日志路径 |

---

## 测试

```bash
# 运行全部测试（107 个）
python3 -m pytest tests/ -v

# 运行单个测试文件
python3 -m pytest tests/test_api.py -v
python3 -m pytest tests/test_storage.py -v
python3 -m pytest tests/test_models.py -v
```

---

## 数据流

```
CLI 命令
    ↓
APIClient（Unix Socket HTTP）
    ↓
FastAPI（Header 认证：X-API-Key）
    ↓
CSVStorage（flock 文件锁）
    ↓
  ├─ Pydantic 字段校验（格式、枚举、长度）
  ├─ 状态机转换校验（不允许非法跳转）
  ├─ 引用完整性检查（project_id 必须存在）
  └─ SHA256 审计日志（写入前+写入后校验和）
    ↓
CSV 文件（projects.csv / proposals.csv）
    ↓
audit.log（记录 sha_before → sha_after）
```

---

## 防篡改设计要点

1. **无直接文件写入路径** — `CSVStorage` 是内部模块，外部客户端只能通过 API 操作数据
2. **flock 独占锁** — 所有写操作获取排他锁，并发写入被串行化，不存在部分写入
3. **SHA256 校验和** — 每次写操作在 audit.log 记录文件哈希前后值，篡改可检测
4. **状态机校验** — 即使绕过 CLI，也无法通过 API 进行非法的状态转换
5. **Pydantic 模型校验** — 非法枚举值、错误 ID 格式、缺失必填字段在写入前被拒绝

---

## 项目结构

```
ai-superpower/
├── src/ai_superpower/
│   ├── models.py        # Pydantic 模型、状态机、枚举定义
│   ├── config.py        # 从 ~/.ai-superpower/config.toml 加载配置
│   ├── storage.py       # CSVStorage：flock + 审计 + 校验
│   ├── server.py        # FastAPI 服务器（9 个端点）
│   ├── client.py        # APIClient：Unix socket HTTP 客户端
│   └── cli.py           # CLI 入口
├── tests/
│   ├── test_models.py   # 37 个测试
│   ├── test_storage.py  # 41 个测试
│   └── test_api.py      # 29 个测试
├── deploy/
│   ├── ai-superpower.service  # systemd 服务单元
│   └── install.sh             # 安装脚本
└── pyproject.toml
```
