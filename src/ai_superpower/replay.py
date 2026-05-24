"""Audit log replay — reverse operations from JSON audit log."""
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import load_config
from .storage import CSVStorage


class Replay:
    """Replay audit log entries to undo/replay operations."""

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.config = load_config()
        self.storage = CSVStorage(self.config, actor="replay")
        self.undo_stack: list[dict] = []

    def replay_from_file(
        self,
        log_path: Optional[str] = None,
        from_time: Optional[str] = None,
        last_n: Optional[int] = None,
        entity_id: Optional[str] = None,
    ):
        """Read audit log and apply operations in order."""
        path = log_path or self.config.audit_log
        if not Path(path).exists():
            print(f"Audit log not found: {path}")
            return

        entries = self._load_entries(path, from_time, last_n, entity_id)
        if not entries:
            print("No entries to replay.")
            return

        print(f"Replaying {len(entries)} entries (dry_run={self.dry_run})")
        for entry in entries:
            self._apply_entry(entry)

    def undo_last(self, entity_id: str, entity: Optional[str] = None) -> dict:
        """Undo the last operation on a given entity.

        Args:
            entity_id: The ID of the entity to undo.
            entity: Optional entity type filter ("project" or "proposal").

        Returns a structured dict:
            {"found": bool, "entry": dict|None, "message": str, "success": bool, "warning": bool}
        """
        path = self.storage.config.audit_log
        if not Path(path).exists():
            return {"found": False, "entry": None, "message": f"Audit log not found: {path}", "success": False, "warning": False}

        # Find last entry for this entity (optionally filtered by entity type)
        entry = None
        with open(path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        for line in reversed(lines):
            try:
                e = json.loads(line)
                if e.get("id") == entity_id:
                    # If entity filter provided, skip entries that don't match
                    if entity and e.get("entity") != entity:
                        continue
                    entry = e
                    break
            except json.JSONDecodeError:
                continue

        if not entry:
            filter_note = f" (entity={entity})" if entity else ""
            return {"found": False, "entry": None, "message": f"No entry found for {entity_id}{filter_note}", "success": False, "warning": False}

        op = entry.get("op", "")
        is_delete_undo = op == "DELETE"

        if is_delete_undo:
            return {
                "found": True,
                "entry": entry,
                "message": f"[SKIP] Cannot undo DELETE for {entry.get('entity')}:{entry.get('id')} — data lost",
                "success": False,
                "warning": True,
            }

        if self.dry_run:
            return {
                "found": True,
                "entry": entry,
                "message": f"[DRY] Would undo: {op} on {entry.get('entity')}:{entry.get('id')} field={entry.get('field')}",
                "success": True,
                "warning": False,
            }

        # Actually apply the reverse
        self._apply_reverse(entry)
        return {
            "found": True,
            "entry": entry,
            "message": f"Undone: {op} on {entry.get('entity')}:{entry.get('id')}",
            "success": True,
            "warning": False,
        }

    def _load_entries(
        self,
        path: str,
        from_time: Optional[str],
        last_n: Optional[int],
        entity_id: Optional[str],
    ) -> list[dict]:
        entries = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entity_id and e.get("id") != entity_id:
                    continue
                if from_time:
                    ts = datetime.fromisoformat(e["ts"].replace("Z", "+00:00"))
                    from_dt = datetime.fromisoformat(from_time.replace("Z", "+00:00"))
                    if ts < from_dt:
                        continue
                entries.append(e)

        if last_n:
            entries = entries[-last_n:]

        return entries

    def _apply_entry(self, entry: dict):
        """Apply a single audit log entry (forward)."""
        op = entry["op"]
        entity = entry["entity"]
        eid = entry["id"]
        field = entry["field"]
        old = entry.get("old")
        new = entry.get("new")

        label = f"{op} {entity}:{eid}"
        if field:
            label += f" [{field}]"

        if self.dry_run:
            if new is not None:
                print(f"  [DRY] Would set {label} = {new!r}")
            elif old is not None:
                print(f"  [DRY] Would restore {label} = {old!r}")
            else:
                print(f"  [DRY] Would {op.lower()} {label}")
            return

        try:
            if entity == "project":
                if op == "UPDATE" and field:
                    self.storage.update_project(eid, {field: new})
                    print(f"  [OK] Updated project {eid} {field} = {new!r}")
                elif op == "DELETE":
                    # Re-create is complex — log warning
                    print(f"  [SKIP] DELETE replay for projects not yet implemented")
            elif entity == "proposal":
                if op == "UPDATE" and field:
                    self.storage.update_proposal(eid, {field: new})
                    print(f"  [OK] Updated proposal {eid} {field} = {new!r}")
                elif op == "DELETE":
                    print(f"  [SKIP] DELETE replay for proposals not yet implemented")
        except Exception as ex:
            print(f"  [ERROR] {ex}")

    def _apply_reverse(self, entry: dict):
        """Apply the reverse of a single entry (undo)."""
        op = entry["op"]
        entity = entry["entity"]
        eid = entry["id"]
        field = entry["field"]
        old = entry.get("old")
        new = entry.get("new")

        try:
            if op == "UPDATE":
                if old is not None:
                    if entity == "project":
                        self.storage.update_project(eid, {field: old})
                    elif entity == "proposal":
                        self.storage.update_proposal(eid, {field: old})
                    print(f"  [OK] Reverted {entity}:{eid} {field} = {old!r}")
            elif op == "CREATE":
                # Undo create = delete
                if entity == "project":
                    self.storage.delete_project(eid)
                elif entity == "proposal":
                    self.storage.delete_proposal(eid)
                print(f"  [OK] Undid CREATE of {entity}:{eid}")
            elif op == "DELETE":
                print(f"  [SKIP] Cannot undo DELETE for {entity}:{eid} — data lost")
        except Exception as ex:
            print(f"  [ERROR] {ex}")
