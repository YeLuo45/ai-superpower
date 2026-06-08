# ai-superpower

**Proposal system API engine — the only gateway for all mutations on `projects.csv` and `proposals.csv`.**

All data changes go through the FastAPI server. Direct CSV manipulation is blocked at the architectural level: no path exists to modify data without passing through the API's validation layer.

---

## Why

The `projects.csv` and `proposals.csv` files are the source of truth for the entire proposal system. Direct edits (scripts, `execute_code`, manual patches) bypass validation, corrupt enum fields, and silently break referential integrity.

ai-superpower solves this by making the API the **only** write path:

```
Direct edit (bypassed)     →  No validation, no audit, no rollback
API write (required)       →  Pydantic校验 + 状态机 + flock锁 + SHA256审计
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    ai-superpower                     │
│                                                      │
│  ┌──────────────┐    ┌─────────────────────────────┐ │
│  │   CLI        │    │       FastAPI Server        │ │
│  │  (Unix Socket)│───→│  ─────────────────────────  │ │
│  └──────────────┘    │  Pydantic Validation        │ │
│                      │  Status State Machine        │ │
│  ┌──────────────┐    │  flock File Locking        │ │
│  │  API Clients │    │  SHA256 Audit Trail        │ │
│  │  (HTTP UDS)  │────→│  Referential Integrity     │ │
│  └──────────────┘    └──────────────┬──────────────┘ │
│                                     │                │
│                          ┌──────────▼──────────┐    │
│                          │   CSVStorage          │    │
│                          │  ┌────────────────┐  │    │
│                          │  │ projects.csv   │  │    │
│                          │  │ proposals.csv   │  │    │
│                          │  │ audit.log      │  │    │
│                          │  └────────────────┘  │    │
│                          └──────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

---

## Features

| Feature | Description |
|---------|-------------|
| **API-only writes** | All mutations go through the API — direct CSV edits are structurally impossible via the CLI |
| **Pydantic validation** | Every field is validated on write: ID format, enum values, string lengths |
| **Status state machine** | Proposal status transitions are enforced — no illegal state jumps |
| **flock file locking** | Concurrent reads are safe; writes are serialized with exclusive locks |
| **SHA256 audit log** | Every write logs before/after checksums to `audit.log` |
| **Referential integrity** | Cannot create a proposal for a non-existent project; project delete blocked if proposals exist |
| **Unix socket transport** | API server binds to a Unix socket — no network exposure |
| **API Key auth** | Every request requires `X-API-Key` header |
| **Pagination** | All list endpoints return `{items, total, page, page_size}` |
| **sync-to-index** | CLI command to regenerate `proposal-index.md` from API data |
| **Web UI** | FastAPI + Jinja2 — project/proposal management, audit viewer, settings |
| **Replay / Undo** | Field-level rollback from JSON audit log — dry-run by default |
| **Scheduled Backup** | APScheduler — hourly local + optional Git remote push, max 48 copies |
| **MCP server (NEW)** | 20 tools exposing projects/proposals/audit/sync — stdio + Streamable HTTP transports |

---

## API Endpoints

### Health
| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check (no auth) |

### Projects
| Method | Path | Description |
|--------|------|-------------|
| POST | `/projects` | Create project |
| GET | `/projects` | List projects (paginated) |
| GET | `/projects/{id}` | Get project |
| PUT | `/projects/{id}` | Update project (partial) |
| DELETE | `/projects/{id}` | Delete project |

### Proposals
| Method | Path | Description |
|--------|------|-------------|
| POST | `/proposals` | Create proposal |
| GET | `/proposals` | List proposals (paginated, filterable) |
| GET | `/proposals/{id}` | Get proposal |
| PUT | `/proposals/{id}/status` | Update status (state machine enforced) |
| PUT | `/proposals/{id}/fields` | Update fields (partial) |
| DELETE | `/proposals/{id}` | Delete proposal |

### Utility
| Method | Path | Description |
|--------|------|-------------|
| POST | `/validate` | Dry-run validation |
| GET | `/audit` | Query audit log |

---

## Status State Machine

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

Each status allows specific transitions (see `models.py` `STATUS_TRANSITIONS`).

---

## Three Ways to Use

### 1. CLI

```bash
# Start API server
ai-superpower run

# Projects
ai-superpower project create --name "My Project"
ai-superpower project list
ai-superpower project get PRJ-20250523-001
ai-superpower project delete PRJ-20250523-001

# Proposals
ai-superpower proposal create --title "New Feature" --owner alice --project-id PRJ-20250523-001 --stage ideation
ai-superpower proposal list
ai-superpower proposal list --project-id PRJ-20250523-001 --status intake
ai-superpower proposal get P-20250523-001
ai-superpower proposal update-status P-20250523-001 --status clarifying
ai-superpower proposal update-fields P-20250523-001 --field title="Updated Title"
ai-superpower proposal delete P-20250523-001

# Utility
ai-superpower validate --data '{"project_id":"PRJ-20250523-001","stage":"ideation"}'
ai-superpower audit --page 1 --page-size 100
ai-superpower sync-to-index

# Replay / Undo
ai-superpower replay --last 10 --dry-run    # view last 10 operations
ai-superpower replay --undo P-20250523-001  # rollback last op on an entity

# Backup
ai-superpower backup           # trigger immediate backup
ai-superpower backup --list    # list all backups
ai-superpower backup --restore db_backup_20260523_120000  # restore
```

### 2. Web UI (Browser)

```bash
ai-superpower run
# Open http://localhost:8000
```

| Route | Description |
|-------|-------------|
| `/` | Dashboard (project/proposal/audit stats) |
| `/web/projects` | Project list + create/edit |
| `/web/proposals` | Proposal list + filters + create |
| `/web/audit` | Audit log timeline |
| `/web/settings` | Configuration page |

### 3. TUI (Interactive Terminal)

```bash
ai-superpower tui
```

Full-screen interactive interface: browse projects/proposals, search, create, update status, view audit log.

### 4. MCP (Model Context Protocol)

ai-superpower ships with a built-in **MCP server** that exposes 20 tools (19 main + 1 auth helper) covering the full CRUD surface, audit log, stats, and sync. Two transports are supported:

- **stdio** — for local AI agents and CLI integrations (subprocess / JSON-RPC)
- **Streamable HTTP** — for browsers and remote consumers, mounted at `/mcp` on the FastAPI app

#### Start the MCP server (stdio)

```bash
# Set the API key in env (same key as ~/.ai-superpower/config.toml [api].key)
export AI_SUPERPOWER_API_KEY="<your-32-char-hex-key>"

# Start the stdio MCP server (blocks, reads JSON-RPC from stdin)
ai-superpower mcp --transport=stdio
```

Quick smoke test — initialize and list tools over stdio (full handshake):

```bash
# 1) Initialize
{ echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0.0.1"}}}'; \
  sleep 0.2; \
  echo '{"jsonrpc":"2.0","method":"notifications/initialized"}'; \
  sleep 0.2; \
  echo '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'; \
  sleep 0.5; } \
  | ai-superpower mcp --transport=stdio
# → server returns 20 tools (set_api_key + 19 main)
```

#### Start the MCP server (Streamable HTTP)

```bash
# Start the MCP HTTP server on port 8765 (avoid 8000/8001 — reserved for ai-superpower run)
ai-superpower mcp --transport=http --host 127.0.0.1 --port 8765
# Server listens at http://127.0.0.1:8765/mcp
```

Quick smoke test — initialize + list tools:

```bash
# 1) Initialize
curl -X POST http://127.0.0.1:8765/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'

# 2) tools/list (use the mcp-session-id returned from step 1)
curl -X POST http://127.0.0.1:8765/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "mcp-session-id: <id-from-step-1>" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

#### Use the MCP server alongside the Web UI

The MCP HTTP endpoint is also mounted on the main FastAPI app at `/mcp`. So you can run `ai-superpower run` (which starts the Web UI + REST API on port 8000) and the MCP HTTP server becomes available at the same port automatically:

```bash
ai-superpower run --port 8000
# Web UI:     http://localhost:8000/
# REST API:   http://localhost:8000/api/*  (legacy)
# MCP HTTP:   http://localhost:8000/mcp    (new)
```

> The legacy `/api/*` REST endpoints are still mounted for the Web UI and existing integrations; future iterations will migrate the Web UI to MCP and remove the REST surface.

#### MCP tools reference

| Tool | Purpose |
|------|---------|
| `set_api_key` | Set the API key in env var (stdio auth bootstrap) |
| `list_projects` / `get_project` / `create_project` / `update_project` / `delete_project` | Project CRUD |
| `check_project_duplicate` | Pre-flight duplicate check by name or git_repo |
| `list_proposals` / `get_proposal` / `create_proposal` | Proposal CRUD (read + create) |
| `update_proposal_status` | Status transitions (state machine enforced) |
| `update_proposal_fields` | Partial field update |
| `delete_proposal` | Delete (requires `allow_delete=true`) |
| `merge_proposals_by_project` | Bulk move proposals by source project name |
| `get_audit` | Audit log query (page + filter) |
| `get_stats` | Aggregate statistics (projects/proposals/audit counts) |
| `get_sync_config` / `update_sync_config` | Sync configuration read/write |
| `export_sync` | Trigger GitHub Pages sync export |
| `get_sync_status` | Sync enabled / last-run / target repo |

All tools require authentication. Pass `api_key` as a tool argument (stdio) or `X-API-Key` header (HTTP).

---

## Installation

```bash
# Install from source
cd ai-superpower
pip install -e . --break-system-packages

# Or use the install script (generates API key, fixes CSV headers)
bash deploy/install.sh

# Configure API key manually
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

## Running the Server

```bash
# Manual
ai-superpower run

# Or via systemd
sudo cp deploy/ai-superpower.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ai-superpower
```

---

## Configuration

| Field | Default | Description |
|-------|---------|-------------|
| `key` | (required) | API key — 32-char hex string |
| `socket_path` | `/var/run/ai-superpower/api.sock` | Unix socket path |
| `data_dir` | `/home/hermes/ai-superpower/db` | Directory for projects.csv, proposals.csv, audit.log |
| `allow_delete` | `false` | Allow DELETE operations (default 403 disabled) |

### Backup Configuration

```toml
[backup]
enabled = true                    # enable scheduled backup
frequency = "1h"                # 1h / 6h / 1d
max_copies = 48
local_path = "/home/hermes/ai-superpower/backups"
remote_repo = ""                 # git remote URL (optional)
remote_branch = "backup"          # branch for remote push (optional)
api_key = ""                      # backup-specific API key (optional)
```

---

## Web UI

Start `ai-superpower run` then open `http://localhost:8000`:

- `/` — Dashboard (project/proposal/audit statistics)
- `/web/projects` — Project list + create/edit
- `/web/proposals` — Proposal list + filters + create
- `/web/audit` — Audit log timeline
- `/web/settings` — Configuration page

---

## Testing

```bash
# Run full test suite (465+ tests across 16 test files)
python3 -m pytest tests/ -v

# Run specific test file
python3 -m pytest tests/test_api.py -v
python3 -m pytest tests/test_storage.py -v
python3 -m pytest tests/test_models.py -v

# Run MCP tests with coverage (target: 100% on mcp_server.py)
python3 -m pytest tests/test_mcp_server.py -v --cov=ai_superpower.mcp_server --cov-report=term-missing
```

---

## Data Flow

```
CLI Command
    ↓
APIClient (Unix socket HTTP)
    ↓
FastAPI (Header auth: X-API-Key)
    ↓
CSVStorage (flock lock)
    ↓
  ├─ Pydantic validation (field formats, enums)
  ├─ State machine validation (status transitions)
  ├─ Referential integrity (project_id exists)
  └─ SHA256 audit log write
    ↓
CSV file (projects.csv / proposals.csv)
    ↓
audit.log (sha_before → sha_after)
```

---

## Anti-tampering Design

1. **No direct file path exposed** — `CSVStorage` is internal; clients only talk to the API
2. **flock exclusive lock on every write** — concurrent writers are serialized; no partial writes
3. **SHA256 checksum in audit** — every write logs the file hash before and after; tampering is detectable
4. **State machine enforced at API layer** — even if someone bypasses the CLI, they cannot call the API with an invalid status transition
5. **Pydantic model validation** — invalid enum values, bad ID formats, and missing required fields are rejected before touching the CSV

---

## Project Structure

```
ai-superpower/
├── src/ai_superpower/
│   ├── models.py        # Pydantic models, status machine, enums
│   ├── config.py        # Config loading from ~/.ai-superpower/config.toml
│   ├── storage.py       # CSVStorage: flock + JSON audit + validation
│   ├── server.py        # FastAPI server (9 endpoints + Web UI)
│   ├── client.py        # APIClient: Unix socket HTTP client
│   ├── cli.py           # CLI entry point (project/proposal/audit/replay/backup/mcp)
│   ├── mcp_server.py    # MCP server: 20 tools, stdio + Streamable HTTP
│   ├── tui.py           # Curses TUI (interactive management)
│   ├── replay.py        # Audit log replay / field-level undo
│   ├── backup.py        # BackupScheduler: local + Git remote
│   ├── templates/       # Jinja2 HTML templates (Web UI)
│   └── static/          # CSS + JS (Web UI)
├── tests/
│   ├── test_models.py   # 37 tests
│   ├── test_storage.py  # 41 tests
│   ├── test_api.py      # 39 tests
│   └── test_client.py   # 10 tests (mock-based)
├── deploy/
│   ├── ai-superpower.service  # systemd unit
│   └── install.sh             # installer
└── pyproject.toml
```
