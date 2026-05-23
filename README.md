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

## CLI Commands

```bash
# Start server
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
```

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
| `proposals_csv` | `/home/hermes/proposals/proposals.csv` | Proposals CSV path |
| `projects_csv` | `/home/hermes/proposals/projects.csv` | Projects CSV path |
| `audit_log` | `/home/hermes/proposals/audit.log` | Audit log path |

---

## Testing

```bash
# Run full test suite (107 tests)
python3 -m pytest tests/ -v

# Run specific test file
python3 -m pytest tests/test_api.py -v
python3 -m pytest tests/test_storage.py -v
python3 -m pytest tests/test_models.py -v
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
│   ├── storage.py       # CSVStorage: flock + audit + validation
│   ├── server.py        # FastAPI server (9 endpoints)
│   ├── client.py        # APIClient: Unix socket HTTP client
│   └── cli.py           # CLI entry point
├── tests/
│   ├── test_models.py   # 37 tests
│   ├── test_storage.py  # 41 tests
│   └── test_api.py      # 29 tests
├── deploy/
│   ├── ai-superpower.service  # systemd unit
│   └── install.sh             # installer
└── pyproject.toml
```
