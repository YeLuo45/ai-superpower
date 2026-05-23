#!/bin/bash
# Install ai-superpower

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$SCRIPT_DIR/src"

echo "=== ai-superpower installer ==="

# 1. Install Python package
echo "[1/4] Installing package..."
pip install -e "$SCRIPT_DIR" --break-system-packages -q 2>/dev/null || \
pip install -e "$SCRIPT_DIR" --user -q 2>/dev/null || \
echo "  (pip install skipped, run manually)"

# 2. Create config directory
echo "[2/4] Creating config..."
mkdir -p ~/.ai-superpower
if [ ! -f ~/.ai-superpower/config.toml ]; then
    API_KEY=$(openssl rand -hex 32)
    cat > ~/.ai-superpower/config.toml << EOF
[api]
key = "$API_KEY"
socket_path = "/var/run/ai-superpower/api.sock"
proposals_csv = "/home/hermes/proposals/proposals.csv"
projects_csv = "/home/hermes/proposals/projects.csv"
audit_log = "/home/hermes/proposals/audit.log"
EOF
    echo "  Config created at ~/.ai-superpower/config.toml"
    echo "  API Key: $API_KEY"
else
    echo "  Config already exists"
fi

# 3. Fix projects.csv header (remove prj_url if present)
echo "[3/4] Checking CSV headers..."
python3 -c "
import csv
from pathlib import Path

# Fix projects.csv
pc = Path('/home/hermes/proposals/projects.csv')
if pc.exists():
    with open(pc, 'r') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
    if 'prj_url' in headers:
        print('  Fixing projects.csv: removing prj_url column')
        rows = []
        with open(pc, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        TARGET = ['id', 'name', 'proposal_count', 'git_repo', 'local_path', 'description', 'last_update']
        with open(pc, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=TARGET, extrasaction='ignore')
            writer.writeheader()
            writer.writerows([{k: r.get(k, '') for k in TARGET} for r in rows])
        print(f'  Fixed {len(rows)} project rows')
    else:
        print('  projects.csv header OK')

# Fix proposals.csv: add status column if missing
prc = Path('/home/hermes/proposals/proposals.csv')
if prc.exists():
    with open(prc, 'r') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
    if 'status' not in headers:
        print('  Fixing proposals.csv: adding status column')
        rows = []
        with open(prc, 'r') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        TARGET = ['id', 'title', 'owner', 'status', 'project_id', 'project_name', 'stage',
                  'prd_path', 'tech_solution_path', 'project_path', 'git_repo', 'deployment_url',
                  'prd_confirmation', 'tech_expectations', 'acceptance', 'last_update',
                  'engine', 'target', 'game_type', 'notes']
        with open(prc, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=TARGET, extrasaction='ignore')
            writer.writeheader()
            for r in rows:
                clean = {k: r.get(k, '') for k in TARGET}
                if not clean.get('status'):
                    clean['status'] = 'intake'
                writer.writerow(clean)
        print(f'  Fixed {len(rows)} proposal rows')
    else:
        print('  proposals.csv header OK')
"

# 4. Create symlink for CLI
echo "[4/4] Done."
echo ""
echo "Start server: ai-superpower run"
echo "Or install systemd service: sudo cp deploy/ai-superpower.service /etc/systemd/system/"
echo ""
echo "Config at: ~/.ai-superpower/config.toml"
