#!/bin/bash
# Install ai-superpower

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$SCRIPT_DIR/src"
DATA_DIR="$SCRIPT_DIR/db"
OLD_DATA_DIR="/home/hermes/proposals"

echo "=== ai-superpower installer ==="

# 1. Install Python package
echo "[1/5] Installing package..."
pip install -e "$SCRIPT_DIR" --break-system-packages -q 2>/dev/null || \
pip install -e "$SCRIPT_DIR" --user -q 2>/dev/null || \
echo "  (pip install skipped, run manually)"

# 2. Create db directory and migrate data
echo "[2/5] Setting up database directory..."
mkdir -p "$DATA_DIR"

# Migrate data from old location if db/ is empty
if [ ! -s "$DATA_DIR/projects.csv" ] && [ -f "$OLD_DATA_DIR/projects.csv" ]; then
    echo "  Migrating projects.csv from $OLD_DATA_DIR..."
    cp "$OLD_DATA_DIR/projects.csv" "$DATA_DIR/projects.csv"
fi
if [ ! -s "$DATA_DIR/proposals.csv" ] && [ -f "$OLD_DATA_DIR/proposals.csv" ]; then
    echo "  Migrating proposals.csv from $OLD_DATA_DIR..."
    cp "$OLD_DATA_DIR/proposals.csv" "$DATA_DIR/proposals.csv"
fi
touch "$DATA_DIR/audit.log"

# 3. Create config directory
echo "[3/5] Creating config..."
mkdir -p ~/.ai-superpower
if [ ! -f ~/.ai-superpower/config.toml ]; then
    API_KEY=$(openssl rand -hex 32)
    cat > ~/.ai-superpower/config.toml << EOF
[api]
key = "$API_KEY"
socket_path = "/var/run/ai-superpower/api.sock"
data_dir = "$DATA_DIR"
allow_delete = false
EOF
    echo "  Config created at ~/.ai-superpower/config.toml"
    echo "  API Key: $API_KEY"
else
    echo "  Config already exists"
fi

# 4. Fix CSV headers
echo "[4/5] Checking CSV headers..."
python3 -c "
import csv
from pathlib import Path

DATA_DIR = '$DATA_DIR'

def fix_csv(path, target_headers, id_col='id', status_col=None):
    p = Path(path)
    if not p.exists():
        print(f'  {p.name}: file not found, skipping')
        return
    with open(p, 'r') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        rows = list(reader)
    dirty = any(h not in target_headers for h in headers)
    if dirty or len(headers) != len(target_headers):
        print(f'  Fixing {p.name}: headers mismatch')
        with open(p, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=target_headers, extrasaction='ignore')
            writer.writeheader()
            for r in rows:
                clean = {k: r.get(k, '') for k in target_headers}
                if status_col and not clean.get(status_col):
                    clean[status_col] = 'intake'
                writer.writerow(clean)
        print(f'    Fixed {len(rows)} rows')
    else:
        print(f'  {p.name}: header OK ({len(rows)} rows)')

PROJ_TARGET = ['id', 'name', 'proposal_count', 'git_repo', 'local_path', 'description', 'last_update']
fix_csv(f'{DATA_DIR}/projects.csv', PROJ_TARGET)

PROP_TARGET = ['id', 'title', 'owner', 'status', 'project_id', 'project_name', 'stage',
               'prd_path', 'tech_solution_path', 'project_path', 'git_repo', 'deployment_url',
               'prd_confirmation', 'tech_expectations', 'acceptance', 'last_update',
               'engine', 'target', 'game_type', 'notes']
fix_csv(f'{DATA_DIR}/proposals.csv', PROP_TARGET, status_col='status')
"

# 5. Create symlink for CLI
echo "[5/5] Done."
echo ""
echo "Start server: ai-superpower run"
echo "Or install systemd service: sudo cp deploy/ai-superpower.service /etc/systemd/system/"
echo ""
echo "Config at: ~/.ai-superpower/config.toml"
echo "Data at: $DATA_DIR"
