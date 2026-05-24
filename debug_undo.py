"""Debug script to test undo_last behavior."""
import json, tempfile, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ai_superpower.storage import CSVStorage

tmp = tempfile.mkdtemp()
audit_log = os.path.join(tmp, "audit.log")
projects_csv = os.path.join(tmp, "projects.csv")
proposals_csv = os.path.join(tmp, "proposals.csv")

class FakeConfig:
    projects_csv = projects_csv
    proposals_csv = proposals_csv
    audit_log = audit_log
    key = "test-key-456"
    socket_path = os.path.join(tmp, "api.sock")
    allow_delete = True
    data_dir = tmp
    sync_target_repo = None
    sync_api_key = None
    backup_api_key = None
    sync_enabled = False
    sync_last_run = ""

cfg = FakeConfig()

# Create storage
storage = CSVStorage(cfg, actor="test")

# Create project
proj = storage.create_project(name="Test Project")
print(f"Created project: {proj.id}")

# Create proposal
prop = storage.create_proposal({
    "title": "Undo Me Proposal",
    "project_id": proj.id,
    "status": "draft",
    "stage": "ideation",
})
print(f"Created proposal: {prop.id}")

# Read and print audit log
print("\n=== Audit log contents ===")
with open(audit_log, "r") as f:
    for i, line in enumerate(f):
        if line.strip():
            entry = json.loads(line)
            print(f"  [{i}] op={entry['op']} entity={entry['entity']} id={entry['id']}")
            if entry['id'] == prop.id:
                print(f"      *** MATCHING ENTRY for {prop.id} ***")

print("\n=== Testing undo_last with entity filter ===")

# Now test undo_last with entity filter
from ai_superpower.replay import Replay
replay = Replay(dry_run=False)
replay.storage = storage  # Use same storage

# First without entity filter (should work)
result_no_filter = replay.undo_last(prop.id)
print(f"undo_last({prop.id}) [no filter]: {result_no_filter}")

# With entity filter (the failing case)
result_with_filter = replay.undo_last(prop.id, entity="proposal")
print(f"undo_last({prop.id}, entity='proposal'): {result_with_filter}")

# With entity filter that doesn't match
result_wrong_entity = replay.undo_last(prop.id, entity="project")
print(f"undo_last({prop.id}, entity='project'): {result_wrong_entity}")

# Now test the _load_entries directly
print("\n=== Testing _load_entries ===")
# The issue might be in the line scanning
entries = replay._load_entries(audit_log, None, None, prop.id)
print(f"_load_entries for {prop.id}: {len(entries)} entries")
for e in entries:
    print(f"  op={e['op']} entity={e['entity']} id={e['id']}")

# Test if the issue is in the actual file reading
print("\n=== Manual file scan ===")
with open(audit_log, "r") as f:
    lines = [l.strip() for l in f if l.strip()]
print(f"Total lines in audit log: {len(lines)}")

# Look specifically for the proposal entries
for line in reversed(lines):
    try:
        e = json.loads(line)
        if e.get("id") == prop.id:
            print(f"  Found entry: op={e['op']} entity={e['entity']} id={e['id']}")
            print(f"  Entity matches 'proposal': {e.get('entity') == 'proposal'}")
            break
    except json.JSONDecodeError as ex:
        print(f"  JSON error: {ex}")