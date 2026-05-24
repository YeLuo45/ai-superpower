"""CSV storage layer with file locking and field-level audit logging."""
import csv
import fcntl
import hashlib
import json
import os
import re
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Generator, Optional

_ID_DATE_RE = re.compile(r"^(?:PRJ|P)-(\d{4})(\d{2})(\d{2})-\d{3}$")

from .config import APIConfig, load_config
from .models import (
    PROJECTS_CSV_HEADERS,
    PROPOSALS_CSV_HEADERS,
    Project,
    Proposal,
)


class CSVStorage:
    """Thread-safe CSV storage with field-level audit logging."""

    def __init__(self, config: Optional[APIConfig] = None, actor: str = "system"):
        self.config = config or load_config()
        self.actor = actor  # SHA256 first 8 chars of API key
        self._ensure_files_exist()

    def _ensure_files_exist(self):
        """Ensure CSV files and audit log exist."""
        for csv_path in [self.config.projects_csv, self.config.proposals_csv]:
            if not Path(csv_path).exists():
                with open(csv_path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.writer(f)
                    headers = PROJECTS_CSV_HEADERS if "projects" in csv_path else PROPOSALS_CSV_HEADERS
                    writer.writerow(headers)

        Path(self.config.audit_log).parent.mkdir(parents=True, exist_ok=True)
        if not Path(self.config.audit_log).exists():
            Path(self.config.audit_log).touch()

    def _sha256(self, path: str) -> str:
        """Compute SHA256 of a file."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            h.update(f.read())
        return h.hexdigest()

    @contextmanager
    def _lock_file(self, path: str, lock_type: str = "shared") -> Generator[None, None, None]:
        """Lock a file using flock. 'shared' for reads, 'exclusive' for writes."""
        fd = os.open(path, os.O_RDWR)
        try:
            lock_flag = fcntl.LOCK_SH if lock_type == "shared" else fcntl.LOCK_EX
            fcntl.flock(fd, lock_flag | fcntl.LOCK_NB)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _audit(
        self,
        op: str,
        entity: str,
        entity_id: str,
        field: Optional[str] = None,
        old: Optional[Any] = None,
        new: Optional[Any] = None,
        checksum_after: Optional[str] = None,
    ):
        """Write a JSON audit log entry (one JSON per line)."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "op": op,
            "entity": entity,
            "id": entity_id,
            "field": field,
            "old": old,
            "new": new,
            "actor": self.actor,
            "checksum_after": checksum_after,
        }
        with open(self.config.audit_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ─── Projects ──────────────────────────────────────────────────────────────

    def list_projects(
        self,
        page: int = 1,
        page_size: int = 50,
        search: Optional[str] = None,
        sort_by: Optional[str] = "last_update",
        sort_order: Optional[str] = "desc",
    ) -> tuple[list[Project], int]:
        """List projects with pagination."""
        with self._lock_file(self.config.projects_csv, "shared"):
            with open(self.config.projects_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                all_rows = list(reader)

        filtered = all_rows
        if search:
            search_lower = search.lower()
            filtered = [r for r in filtered if search_lower in r.get("name", "").lower()]

        # Sort
        valid_sort_keys = ["last_update", "create_at", "name", "id"]
        sort_field = sort_by if sort_by in valid_sort_keys else "last_update"
        reverse = sort_order == "desc"
        filtered.sort(key=lambda r: r.get(sort_field, ""), reverse=reverse)

        total = len(filtered)
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = filtered[start:end]

        projects = [Project(**row) for row in page_rows]
        return projects, total

    def get_project(self, project_id: str) -> Optional[Project]:
        """Get a single project by ID."""
        with self._lock_file(self.config.projects_csv, "shared"):
            with open(self.config.projects_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row["id"] == project_id:
                        return Project(**row)
        return None

    def create_project(
        self, name: str, git_repo: str = "", local_path: str = "", description: str = "", prj_url: str = ""
    ) -> Project:
        """Create a new project with auto-generated ID."""
        today = datetime.now().strftime("%Y-%m-%d")

        with self._lock_file(self.config.projects_csv, "shared"):
            with open(self.config.projects_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                existing = list(reader)

        # Generate next ID
        today_prefix = f"PRJ-{today.replace('-', '')}-"
        existing_ids = [r["id"] for r in existing if r["id"].startswith(today_prefix)]
        if existing_ids:
            nums = [int(r.split("-")[-1]) for r in existing_ids]
            next_num = max(nums) + 1
        else:
            next_num = 1
        new_id = f"{today_prefix}{next_num:03d}"

        new_project = Project(
            id=new_id,
            name=name,
            proposal_count=0,
            git_repo=git_repo,
            local_path=local_path,
            description=description,
            last_update=today,
            create_at=today,
            prj_url=prj_url,
        )

        with self._lock_file(self.config.projects_csv, "exclusive"):
            sha_before = self._sha256(self.config.projects_csv)
            with open(self.config.projects_csv, "a", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=PROJECTS_CSV_HEADERS)
                writer.writerow(new_project.model_dump(exclude_none=True))
            sha_after = self._sha256(self.config.projects_csv)

        self._audit("CREATE", "project", new_id, checksum_after=sha_after)
        return new_project

    def update_project(self, project_id: str, updates: dict) -> Optional[Project]:
        """Update project fields (partial update, field-level audit)."""
        with self._lock_file(self.config.projects_csv, "shared"):
            with open(self.config.projects_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

        target_idx = None
        for i, row in enumerate(rows):
            if row["id"] == project_id:
                target_idx = i
                break

        if target_idx is None:
            return None

        today = datetime.now().strftime("%Y-%m-%d")
        # Collect old values for audit
        old_values = {}
        for key, value in updates.items():
            if value is not None and key in PROJECTS_CSV_HEADERS:
                old_values[key] = rows[target_idx].get(key, "")
                rows[target_idx][key] = value
        rows[target_idx]["last_update"] = today

        with self._lock_file(self.config.projects_csv, "exclusive"):
            sha_before = self._sha256(self.config.projects_csv)
            with open(self.config.projects_csv, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=PROJECTS_CSV_HEADERS)
                writer.writeheader()
                writer.writerows(rows)
            sha_after = self._sha256(self.config.projects_csv)

        # Field-level audit entry per changed field
        for field, old_val in old_values.items():
            new_val = rows[target_idx].get(field, "")
            self._audit("UPDATE", "project", project_id, field=field, old=old_val, new=new_val, checksum_after=sha_after)

        return Project(**rows[target_idx])

    def delete_project(self, project_id: str) -> bool:
        """Delete a project. Fails if it has proposals."""
        # Check for proposals first
        proposals, _ = self.list_proposals(page=1, page_size=1, project_id=project_id)
        if proposals:
            raise ValueError(f"Project {project_id} has proposals, cannot delete")

        with self._lock_file(self.config.projects_csv, "shared"):
            with open(self.config.projects_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

        target_row = None
        for row in rows:
            if row["id"] == project_id:
                target_row = row
                break

        if target_row is None:
            return False

        new_rows = [r for r in rows if r["id"] != project_id]
        with self._lock_file(self.config.projects_csv, "exclusive"):
            sha_before = self._sha256(self.config.projects_csv)
            with open(self.config.projects_csv, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=PROJECTS_CSV_HEADERS)
                writer.writeheader()
                writer.writerows(new_rows)
            sha_after = self._sha256(self.config.projects_csv)

        # Audit each field as deleted
        for field, old_val in target_row.items():
            self._audit("DELETE", "project", project_id, field=field, old=old_val, new=None, checksum_after=sha_after)
        return True

    # ─── Proposals ────────────────────────────────────────────────────────────

    def list_proposals(
        self,
        page: int = 1,
        page_size: int = 50,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
        owner: Optional[str] = None,
        search: Optional[str] = None,
        stage: Optional[str] = None,
        sort_by: Optional[str] = "last_update",
        sort_order: Optional[str] = "desc",
    ) -> tuple[list[Proposal], int]:
        """List proposals with pagination and filters."""
        with self._lock_file(self.config.proposals_csv, "shared"):
            with open(self.config.proposals_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                all_rows = list(reader)

        project_map = {}
        with self._lock_file(self.config.projects_csv, "shared"):
            with open(self.config.projects_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    project_map[row["id"]] = row.get("name", "")

        filtered = all_rows
        if project_id:
            filtered = [r for r in filtered if r.get("project_id") == project_id]
        if status:
            filtered = [r for r in filtered if r.get("status") == status]
        if owner:
            filtered = [r for r in filtered if r.get("owner") == owner]
        if stage:
            filtered = [r for r in filtered if r.get("stage") == stage]
        if search:
            search_lower = search.lower()
            filtered = [r for r in filtered if search_lower in r.get("title", "").lower()]

        # Sort
        valid_sort_keys = ["last_update", "create_at", "title", "id", "status", "stage"]
        sort_field = sort_by if sort_by in valid_sort_keys else "last_update"
        reverse = sort_order == "desc"
        filtered.sort(key=lambda r: r.get(sort_field, ""), reverse=reverse)

        total = len(filtered)
        start = (page - 1) * page_size
        end = start + page_size
        page_rows = filtered[start:end]

        proposals = []
        for row in page_rows:
            row["project_name"] = project_map.get(row.get("project_id", ""), "")
            proposals.append(Proposal(**row))

        return proposals, total

    def get_proposal(self, proposal_id: str) -> Optional[Proposal]:
        """Get a single proposal by ID."""
        project_map = {}
        with self._lock_file(self.config.projects_csv, "shared"):
            with open(self.config.projects_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    project_map[row["id"]] = row.get("name", "")

        with self._lock_file(self.config.proposals_csv, "shared"):
            with open(self.config.proposals_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row["id"] == proposal_id:
                        row["project_name"] = project_map.get(row.get("project_id", ""), "")
                        return Proposal(**row)
        return None

    def create_proposal(self, data: dict) -> Proposal:
        """Create a new proposal with auto-generated ID."""
        today = datetime.now().strftime("%Y-%m-%d")

        with self._lock_file(self.config.proposals_csv, "shared"):
            with open(self.config.proposals_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                existing = list(reader)

        # Generate next ID
        today_prefix = f"P-{today.replace('-', '')}-"
        existing_ids = [r["id"] for r in existing if r["id"].startswith(today_prefix)]
        if existing_ids:
            nums = [int(r.split("-")[-1]) for r in existing_ids]
            next_num = max(nums) + 1
        else:
            next_num = 1
        new_id = f"{today_prefix}{next_num:03d}"

        new_row = {h: "" for h in PROPOSALS_CSV_HEADERS}
        new_row["id"] = new_id
        new_row["status"] = "intake"
        new_row["last_update"] = today
        for key, value in data.items():
            if key in PROPOSALS_CSV_HEADERS and value is not None:
                new_row[key] = str(value)

        project_map = {}
        with self._lock_file(self.config.projects_csv, "shared"):
            with open(self.config.projects_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    project_map[row["id"]] = row.get("name", "")
        new_row["project_name"] = project_map.get(new_row.get("project_id", ""), "")

        with self._lock_file(self.config.proposals_csv, "exclusive"):
            sha_before = self._sha256(self.config.proposals_csv)
            with open(self.config.proposals_csv, "a", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=PROPOSALS_CSV_HEADERS)
                writer.writerow(new_row)
            sha_after = self._sha256(self.config.proposals_csv)

        self._audit("CREATE", "proposal", new_id, checksum_after=sha_after)

        # Sync project proposal_count
        self._sync_project_proposal_count(new_row.get("project_id", ""))

        # Auto-backup trigger
        self._auto_backup_if_needed(new_row.get("project_id", ""))

        return Proposal(**new_row)

    def update_proposal(self, proposal_id: str, updates: dict) -> Optional[Proposal]:
        """Update proposal fields (partial update, field-level audit)."""
        with self._lock_file(self.config.proposals_csv, "shared"):
            with open(self.config.proposals_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

        target_idx = None
        for i, row in enumerate(rows):
            if row["id"] == proposal_id:
                target_idx = i
                break

        if target_idx is None:
            return None

        today = datetime.now().strftime("%Y-%m-%d")
        old_values = {}
        for key, value in updates.items():
            if key == "id" or value is None:
                continue
            if key in PROPOSALS_CSV_HEADERS:
                old_values[key] = rows[target_idx].get(key, "")
                rows[target_idx][key] = str(value)
        rows[target_idx]["last_update"] = today

        project_map = {}
        with self._lock_file(self.config.projects_csv, "shared"):
            with open(self.config.projects_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    project_map[row["id"]] = row.get("name", "")
        rows[target_idx]["project_name"] = project_map.get(rows[target_idx].get("project_id", ""), "")

        with self._lock_file(self.config.proposals_csv, "exclusive"):
            sha_before = self._sha256(self.config.proposals_csv)
            with open(self.config.proposals_csv, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=PROPOSALS_CSV_HEADERS)
                writer.writeheader()
                writer.writerows(rows)
            sha_after = self._sha256(self.config.proposals_csv)

        for field, old_val in old_values.items():
            new_val = rows[target_idx].get(field, "")
            self._audit("UPDATE", "proposal", proposal_id, field=field, old=old_val, new=new_val, checksum_after=sha_after)

        return Proposal(**rows[target_idx])

    def update_proposal_status(self, proposal_id: str, new_status: str) -> Optional[Proposal]:
        """Update proposal status with state machine validation."""
        proposal = self.get_proposal(proposal_id)
        if proposal is None:
            return None

        current_status = proposal.status
        from .models import STATUS_TRANSITIONS
        if new_status not in STATUS_TRANSITIONS.get(current_status, set()):
            raise ValueError(f"Invalid status transition: {current_status} → {new_status}")

        return self.update_proposal(proposal_id, {"status": new_status})

    def delete_proposal(self, proposal_id: str) -> bool:
        """Delete a proposal (field-level audit of deleted values)."""
        with self._lock_file(self.config.proposals_csv, "shared"):
            with open(self.config.proposals_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

        target_row = None
        for row in rows:
            if row["id"] == proposal_id:
                target_row = row
                break

        if target_row is None:
            return False

        new_rows = [r for r in rows if r["id"] != proposal_id]
        with self._lock_file(self.config.proposals_csv, "exclusive"):
            sha_before = self._sha256(self.config.proposals_csv)
            with open(self.config.proposals_csv, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=PROPOSALS_CSV_HEADERS)
                writer.writeheader()
                writer.writerows(new_rows)
            sha_after = self._sha256(self.config.proposals_csv)

        for field, old_val in target_row.items():
            self._audit("DELETE", "proposal", proposal_id, field=field, old=old_val, new=None, checksum_after=sha_after)

        self._sync_project_proposal_count(target_row.get("project_id", ""))
        return True

    def _sync_project_proposal_count(self, project_id: str):
        """Sync proposal_count for a project."""
        if not project_id:
            return
        with self._lock_file(self.config.proposals_csv, "shared"):
            with open(self.config.proposals_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                count = sum(1 for row in reader if row.get("project_id") == project_id)

        self.update_project(project_id, {"proposal_count": count})

    def _auto_backup_if_needed(self, project_id: str):
        """Trigger auto-backup if threshold reached for this project."""
        if not project_id:
            return
        threshold = getattr(self.config, "auto_backup_threshold", 0)
        if threshold <= 0:
            return  # disabled

        # Load counter from flag file
        counter_file = Path(self.config.data_dir) / f".backup_counter_{project_id}"
        try:
            count = int(counter_file.read_text().strip())
        except (FileNotFoundError, ValueError):
            count = 0

        count += 1
        counter_file.write_text(str(count))

        if count >= threshold:
            # Trigger backup
            try:
                from .backup import BackupScheduler
                bs = BackupScheduler(self.config)
                result = bs.backup()
                print(f"[AutoBackup] Project {project_id}: {result}")
                # Reset counter
                counter_file.write_text("0")
            except Exception as ex:
                print(f"[AutoBackup] Failed: {ex}")

    # ─── Stats ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _id_to_date(entity_id: str) -> Optional[str]:
        """Extract YYYY-MM-DD from PRJ-YYYYMMDD-NNN or P-YYYYMMDD-NNN."""
        m = _ID_DATE_RE.match(entity_id)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        return None

    @staticmethod
    def _project_created_date(row: dict) -> Optional[str]:
        create_at = (row.get("create_at") or "").strip()
        if create_at:
            return create_at
        return CSVStorage._id_to_date(row.get("id", ""))

    def get_stats(self, days: int = 30) -> dict:
        """Aggregate dashboard statistics from CSV data."""
        today = datetime.now().strftime("%Y-%m-%d")

        with self._lock_file(self.config.projects_csv, "shared"):
            with open(self.config.projects_csv, "r", encoding="utf-8", newline="") as f:
                projects = list(csv.DictReader(f))

        with self._lock_file(self.config.proposals_csv, "shared"):
            with open(self.config.proposals_csv, "r", encoding="utf-8", newline="") as f:
                proposals = list(csv.DictReader(f))

        project_dates = Counter(
            d for r in projects if (d := self._project_created_date(r))
        )
        proposal_dates = Counter(
            d for r in proposals if (d := self._id_to_date(r.get("id", "")))
        )
        by_status = Counter(r.get("status", "") for r in proposals if r.get("status"))

        start = datetime.now().date() - timedelta(days=days - 1)
        projects_by_date = []
        proposals_by_date = []
        for i in range(days):
            d = (start + timedelta(days=i)).strftime("%Y-%m-%d")
            projects_by_date.append({"date": d, "count": project_dates.get(d, 0)})
            proposals_by_date.append({"date": d, "count": proposal_dates.get(d, 0)})

        audit_entries, audit_total = self.list_audit(page=1, page_size=5)
        recent = list(reversed(audit_entries))

        return {
            "totals": {
                "projects": len(projects),
                "proposals": len(proposals),
                "audit_entries": audit_total,
            },
            "today": {
                "projects": project_dates.get(today, 0),
                "proposals": proposal_dates.get(today, 0),
            },
            "trends": {
                "days": days,
                "projects_by_date": projects_by_date,
                "proposals_by_date": proposals_by_date,
            },
            "by_status": dict(by_status),
            "recent_activity": recent,
        }

    # ─── Audit ────────────────────────────────────────────────────────────────

    def list_audit(
        self,
        page: int = 1,
        page_size: int = 100,
        entity_id: Optional[str] = None,
        op: Optional[str] = None,
        entity: Optional[str] = None,
    ) -> tuple[list[dict], int]:
        """List audit log entries (JSON lines) with pagination."""
        entries = []
        if not Path(self.config.audit_log).exists():
            return [], 0

        with open(self.config.audit_log, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entity_id and entry.get("id") != entity_id:
                    continue
                if op and entry.get("op") != op:
                    continue
                if entity and entry.get("entity") != entity:
                    continue
                entries.append(entry)

        total = len(entries)
        start = (page - 1) * page_size
        end = start + page_size
        return entries[start:end], total

    def validate_proposal(self, data: dict) -> list[str]:
        """Dry-run validation for a proposal. Returns list of errors."""
        errors = []
        from .models import VALID_ENUMS, PROJECT_ID_PATTERN, VALID_PROPOSAL_STAGES

        if not PROJECT_ID_PATTERN.match(data.get("project_id", "")):
            errors.append(f"Invalid project_id format: {data.get('project_id')}. Expected PRJ-YYYYMMDD-NNN")

        if data.get("stage") not in VALID_PROPOSAL_STAGES:
            errors.append(f"Invalid stage: {data.get('stage')}")

        for field, valid_values in VALID_ENUMS.items():
            val = data.get(field, "")
            if val and val not in valid_values:
                errors.append(f"Invalid {field}: {val}")

        if data.get("project_id"):
            project = self.get_project(data["project_id"])
            if project is None:
                errors.append(f"project_id does not exist: {data['project_id']}")

        return errors

    def validate_project(self, data: dict) -> list[str]:
        """Dry-run validation for a project. Returns list of errors."""
        errors = []
        from .models import PROJECT_ID_PATTERN

        if data.get("project_id") and not PROJECT_ID_PATTERN.match(data["project_id"]):
            errors.append(f"Invalid project_id format: {data['project_id']}. Expected PRJ-YYYYMMDD-NNN")

        if not data.get("name"):
            errors.append("Project name is required")

        return errors
