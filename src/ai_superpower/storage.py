"""CSV storage layer with file locking and audit logging."""
import csv
import fcntl
import hashlib
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator, Optional

from .config import APIConfig, load_config
from .models import (
    PROJECTS_CSV_HEADERS,
    PROPOSALS_CSV_HEADERS,
    Project,
    Proposal,
)


class CSVStorage:
    """Thread-safe CSV storage with file locking and audit logging."""

    def __init__(self, config: Optional[APIConfig] = None):
        self.config = config or load_config()
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

    def _audit_log(self, action: str, target: str, details: str = ""):
        """Write an audit log entry."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] {action} | {target} | {details}\n"
        with open(self.config.audit_log, "a", encoding="utf-8") as f:
            f.write(entry)

    # ─── Projects ──────────────────────────────────────────────────────────────

    def list_projects(
        self,
        page: int = 1,
        page_size: int = 50,
        search: Optional[str] = None,
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

    def create_project(self, name: str, git_repo: str = "", local_path: str = "", description: str = "") -> Project:
        """Create a new project with auto-generated ID."""
        today = datetime.now().strftime("%Y-%m-%d")

        with self._lock_file(self.config.projects_csv, "shared"):
            with open(self.config.projects_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                existing = list(reader)

        # Generate next ID
        today_prefix = f"PRJ-{today.replace('-', '')}-";
        existing_ids = [r["id"] for r in existing if r["id"].startswith(today_prefix)]
        if existing_ids:
            nums = [int(r.split("-")[-1]) for r in existing_ids]
            next_num = max(nums) + 1
        else:
            next_num = 1
        new_id = f"{today_prefix}{next_num:03d}"

        # Also create a project_name entry in proposals_csv lookup
        new_project = Project(
            id=new_id,
            name=name,
            proposal_count=0,
            git_repo=git_repo,
            local_path=local_path,
            description=description,
            last_update=today,
        )

        with self._lock_file(self.config.projects_csv, "exclusive"):
            sha_before = self._sha256(self.config.projects_csv)
            with open(self.config.projects_csv, "a", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=PROJECTS_CSV_HEADERS)
                writer.writerow(new_project.model_dump(exclude_none=True))
            sha_after = self._sha256(self.config.projects_csv)

        self._audit_log("CSV_WRITE", self.config.projects_csv, f"{len(existing) + 1} rows, {len(PROJECTS_CSV_HEADERS)} fields | sha {sha_before[:8]}→{sha_after[:8]}")
        return new_project

    def update_project(self, project_id: str, updates: dict) -> Optional[Project]:
        """Update project fields (partial update)."""
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
        for key, value in updates.items():
            if value is not None and key in PROJECTS_CSV_HEADERS:
                rows[target_idx][key] = value
        rows[target_idx]["last_update"] = today

        with self._lock_file(self.config.projects_csv, "exclusive"):
            sha_before = self._sha256(self.config.projects_csv)
            with open(self.config.projects_csv, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=PROJECTS_CSV_HEADERS)
                writer.writeheader()
                writer.writerows(rows)
            sha_after = self._sha256(self.config.projects_csv)

        self._audit_log("CSV_WRITE", self.config.projects_csv, f"{len(rows)} rows | sha {sha_before[:8]}→{sha_after[:8]}")
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

        new_rows = [r for r in rows if r["id"] != project_id]
        if len(new_rows) == len(rows):
            return False

        with self._lock_file(self.config.projects_csv, "exclusive"):
            sha_before = self._sha256(self.config.projects_csv)
            with open(self.config.projects_csv, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=PROJECTS_CSV_HEADERS)
                writer.writeheader()
                writer.writerows(new_rows)
            sha_after = self._sha256(self.config.projects_csv)

        self._audit_log("CSV_WRITE", self.config.projects_csv, f"delete {project_id} | {len(rows)}→{len(new_rows)} rows | sha {sha_before[:8]}→{sha_after[:8]}")
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
    ) -> tuple[list[Proposal], int]:
        """List proposals with pagination and filters."""
        with self._lock_file(self.config.proposals_csv, "shared"):
            with open(self.config.proposals_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                all_rows = list(reader)

        # Also load projects for project_name lookup
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
        new_row["last_update"] = today
        for key, value in data.items():
            if key in PROPOSALS_CSV_HEADERS and value is not None:
                new_row[key] = str(value)

        # Get project_name
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

        self._audit_log("CSV_WRITE", self.config.proposals_csv, f"{len(existing) + 1} rows, {len(PROPOSALS_CSV_HEADERS)} fields | sha {sha_before[:8]}→{sha_after[:8]}")

        # Update project proposal_count
        self._sync_project_proposal_count(new_row.get("project_id", ""))

        return Proposal(**new_row)

    def update_proposal(self, proposal_id: str, updates: dict) -> Optional[Proposal]:
        """Update proposal fields (partial update, excluding id)."""
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
        for key, value in updates.items():
            if key == "id" or value is None:
                continue
            if key in PROPOSALS_CSV_HEADERS:
                rows[target_idx][key] = str(value)
        rows[target_idx]["last_update"] = today

        # Refresh project_name
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

        self._audit_log("CSV_WRITE", self.config.proposals_csv, f"{len(rows)} rows | sha {sha_before[:8]}→{sha_after[:8]}")
        return Proposal(**rows[target_idx])

    def update_proposal_status(self, proposal_id: str, new_status: str) -> Optional[Proposal]:
        """Update proposal status with state machine validation."""
        proposal = self.get_proposal(proposal_id)
        if proposal is None:
            return None

        current_status = proposal.status
        allowed = {
            current_status: {
                "intake": {"clarifying"},
                "clarifying": {"prd_pending_confirmation"},
                "prd_pending_confirmation": {"approved_for_dev"},
                "approved_for_dev": {"in_tdd_test", "in_dev"},
                "in_tdd_test": {"in_dev"},
                "in_dev": {"in_test_acceptance", "needs_revision"},
                "in_test_acceptance": {"accepted", "test_failed"},
                "test_failed": {"in_dev"},
                "needs_revision": {"in_dev"},
                "accepted": {"deployed"},
                "deployed": {"delivered"},
                "deploying": {"deployed"},
                "research_direction_pending": {"intake"},
                "active": {"active"},
                "archived": {"archived"},
                "delivered": {"delivered"},
            }
        }

        from .models import STATUS_TRANSITIONS
        if new_status not in STATUS_TRANSITIONS.get(current_status, set()):
            raise ValueError(f"Invalid status transition: {current_status} → {new_status}")

        return self.update_proposal(proposal_id, {"status": new_status})

    def delete_proposal(self, proposal_id: str) -> bool:
        """Delete a proposal."""
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

        self._audit_log("CSV_WRITE", self.config.proposals_csv, f"delete {proposal_id} | {len(rows)}→{len(new_rows)} rows | sha {sha_before[:8]}→{sha_after[:8]}")

        # Update project proposal_count
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

    # ─── Audit ────────────────────────────────────────────────────────────────

    def list_audit(
        self,
        page: int = 1,
        page_size: int = 100,
        target: Optional[str] = None,
        action: Optional[str] = None,
    ) -> tuple[list[dict], int]:
        """List audit log entries with pagination."""
        with open(self.config.audit_log, "r", encoding="utf-8") as f:
            all_lines = f.readlines()

        entries = []
        for line in all_lines:
            line = line.strip()
            if not line:
                continue
            # Parse: [timestamp] action | target | details
            parts = line.split(" | ", 2)
            if len(parts) == 3:
                ts = parts[0].lstrip("[")
                act = parts[1].strip()
                det = parts[2].strip()
                if target and target != det.split()[0] if det else False:
                    continue
                if action and action != act:
                    continue
                entries.append({"timestamp": ts, "action": act, "target": det})

        total = len(entries)
        start = (page - 1) * page_size
        end = start + page_size
        return entries[start:end], total

    def validate_proposal(self, data: dict) -> list[str]:
        """Dry-run validation for a proposal. Returns list of errors."""
        errors = []
        from .models import VALID_ENUMS, PROJECT_ID_PATTERN, VALID_PROPOSAL_STAGES

        # project_id format
        if not PROJECT_ID_PATTERN.match(data.get("project_id", "")):
            errors.append(f"Invalid project_id format: {data.get('project_id')}. Expected PRJ-YYYYMMDD-NNN")

        # stage enum
        if data.get("stage") not in VALID_PROPOSAL_STAGES:
            errors.append(f"Invalid stage: {data.get('stage')}")

        # enum fields
        for field, valid_values in VALID_ENUMS.items():
            val = data.get(field, "")
            if val and val not in valid_values:
                errors.append(f"Invalid {field}: {val}")

        # project_id exists
        if data.get("project_id"):
            project = self.get_project(data["project_id"])
            if project is None:
                errors.append(f"project_id '{data['project_id']}' does not exist")

        return errors

    def validate_project(self, data: dict) -> list[str]:
        """Dry-run validation for a project. Returns list of errors."""
        errors = []
        if not data.get("name", "").strip():
            errors.append("name is required")
        return errors
