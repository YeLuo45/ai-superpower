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
    STATUS_DERIVE_RULES,
    STATUS_TRANSITIONS,
    derive_status_from_fields,
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

    @staticmethod
    def _normalize_repo_url(url: str) -> str:
        """Normalize a git repo URL for duplicate comparison.

        - Strip trailing slashes
        - Strip trailing ``.git``
        - Lower-case (GitHub URLs are case-insensitive on the path)
        - Strip surrounding whitespace
        """
        if not url:
            return ""
        s = url.strip().rstrip("/")
        if s.lower().endswith(".git"):
            s = s[:-4]
        return s.lower()

    def check_project_duplicate(
        self, name: str = "", git_repo: str = ""
    ) -> Optional[dict]:
        """Check whether a project with the same name (case-insensitive) or
        git_repo (trailing-slash + .git normalized) already exists.

        Returns ``None`` if no duplicate; otherwise a dict with::

            {
                "reason": "name" | "git_repo",
                "existing_id": "PRJ-...",
                "existing_value": "<the stored value>",
            }

        Empty ``name`` and empty ``git_repo`` are not considered duplicates
        of each other (a project with no git_repo is allowed to coexist with
        any number of other projects that also have no git_repo).
        """
        target_name = (name or "").strip().lower()
        target_repo = self._normalize_repo_url(git_repo)

        with self._lock_file(self.config.projects_csv, "shared"):
            with open(self.config.projects_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if target_name:
                        existing_name = (row.get("name") or "").strip().lower()
                        if existing_name and existing_name == target_name:
                            return {
                                "reason": "name",
                                "existing_id": row.get("id", ""),
                                "existing_value": row.get("name", ""),
                            }
                    if target_repo:
                        existing_repo = self._normalize_repo_url(row.get("git_repo", ""))
                        if existing_repo and existing_repo == target_repo:
                            return {
                                "reason": "git_repo",
                                "existing_id": row.get("id", ""),
                                "existing_value": row.get("git_repo", ""),
                            }
        return None

    def find_project_by_exact_name(self, name: str) -> Optional[Project]:
        """Find a project whose name matches ``name`` EXACTLY (case-sensitive,
        no stripping beyond trimming whitespace).

        Unlike ``check_project_duplicate`` which is case-INSENSITIVE, this
        is for the create_project flow where boss wants exact match:
        if a project named exactly ``"MyProject"`` exists, return it; if
        only ``"myproject"`` exists (case-different), return None and let
        the caller create a new one.

        Returns ``None`` if no exact match.
        """
        if not name:
            return None
        target = name.strip()
        if not target:
            return None
        with self._lock_file(self.config.projects_csv, "shared"):
            with open(self.config.projects_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    existing = (row.get("name") or "").strip()
                    if existing == target:
                        return Project(**row)
        return None

    def create_project(
        self,
        name: str,
        git_repo: str = "",
        local_path: str = "",
        description: str = "",
        prj_url: str = "",
        force: bool = False,
    ) -> Project:
        """Create a new project with auto-generated ID.

        When ``force`` is False (default) the new project is checked for
        duplicates by name (case-insensitive) and by git_repo (trailing slash
        and ``.git`` suffix normalized). A duplicate raises
        ``ValueError("Duplicate project: name=... existing_id=...")`` (or
        ``... git_repo=...``) and no CSV write or audit entry is produced.
        Pass ``force=True`` to bypass duplicate detection.

        For EXACT-name-match lookup before creation, use
        ``find_project_by_exact_name(name)`` first (or call the MCP
        ``create_project`` tool which does this for you).
        """
        if not force:
            dup = self.check_project_duplicate(name=name, git_repo=git_repo)
            if dup is not None:
                raise ValueError(
                    f"Duplicate project: {dup['reason']}={dup['existing_value']} "
                    f"existing_id={dup['existing_id']}"
                )

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

    def scan_duplicate_projects(
        self,
        case_insensitive: bool = True,
        min_count: int = 2,
    ) -> list[dict]:
        """Scan existing projects for duplicate names.

        Returns a list of duplicate groups. Each group has::

            {
                "key": "<normalized key (lowercase if case_insensitive)>",
                "name": "<the first-seen display name>",
                "count": <int>,
                "projects": [
                    {"id": "PRJ-...", "name": "...", "git_repo": "...",
                     "create_at": "...", "last_update": "...", "proposal_count": ...},
                    ...
                ]
            }

        Only groups with >= ``min_count`` projects are returned (default 2).
        Projects with empty/whitespace-only names are excluded from grouping.

        Use ``case_insensitive=False`` to detect exact-name duplicates only
        (case-sensitive). The default True is the typical "find typos" scan.
        """
        with self._lock_file(self.config.projects_csv, "shared"):
            with open(self.config.projects_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

        groups: dict[str, list[dict]] = {}
        first_seen_name: dict[str, str] = {}
        for row in rows:
            raw_name = (row.get("name") or "").strip()
            if not raw_name:
                continue
            key = raw_name.lower() if case_insensitive else raw_name
            if key not in groups:
                first_seen_name[key] = raw_name
            groups.setdefault(key, []).append(row)

        result = []
        for key, items in groups.items():
            if len(items) >= min_count:
                result.append({
                    "key": key,
                    "name": first_seen_name[key],
                    "count": len(items),
                    "projects": [
                        {
                            "id": r.get("id", ""),
                            "name": r.get("name", ""),
                            "git_repo": r.get("git_repo", ""),
                            "create_at": r.get("create_at", ""),
                            "last_update": r.get("last_update", ""),
                            "proposal_count": int(r.get("proposal_count") or 0),
                        }
                        for r in items
                    ],
                })
        # Sort by count desc, then by name for stable output
        result.sort(key=lambda g: (-g["count"], g["name"]))
        return result

    def merge_projects(
        self,
        target_id: str,
        source_id: str,
        delete_source: bool = True,
    ) -> dict:
        """Merge source_project into target_project.

        Steps (boss preference 2026-06-10):
        1. Validate both projects exist; target_id != source_id
        2. Move ALL proposals of source → target (rewrites project_id field,
           preserves all other fields including status, stage, notes)
        3. Audit each merged proposal's project_id change
        4. If delete_source=True: remove source row from projects.csv
           (safe because all proposals now point to target_id)
        5. Audit each field of the deleted source project

        Returns::
            {
                "target_id": "PRJ-...",
                "source_id": "PRJ-...",
                "merged_proposals": <int>,
                "merged_proposal_ids": ["P-...", ...],
                "deleted_source": <bool>,
            }

        Raises ``ValueError`` if:
        - target_id == source_id
        - target_id not found
        - source_id not found
        """
        if target_id == source_id:
            raise ValueError("target_id and source_id cannot be the same")

        target = self.get_project(target_id)
        if target is None:
            raise ValueError(f"Target project not found: {target_id}")
        source = self.get_project(source_id)
        if source is None:
            raise ValueError(f"Source project not found: {source_id}")

        # Step 1: Read all proposals
        with self._lock_file(self.config.proposals_csv, "shared"):
            with open(self.config.proposals_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

        merged_ids: list[str] = []
        today = datetime.now().strftime("%Y-%m-%d")
        for row in rows:
            if (row.get("project_id") or "") == source_id:
                row["project_id"] = target_id
                row["last_update"] = today
                merged_ids.append(row.get("id", ""))

        # Step 2: Write back proposals (only if anything changed)
        sha_after_proposals = None
        if merged_ids:
            with self._lock_file(self.config.proposals_csv, "exclusive"):
                with open(self.config.proposals_csv, "w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=PROPOSALS_CSV_HEADERS)
                    writer.writeheader()
                    writer.writerows(rows)
                sha_after_proposals = self._sha256(self.config.proposals_csv)

            # Audit each merged proposal
            for pid in merged_ids:
                self._audit(
                    "UPDATE", "proposal", pid,
                    field="project_id",
                    old=source_id, new=target_id,
                    checksum_after=sha_after_proposals,
                )

        # Step 3: Delete source project (now has 0 proposals because we moved them all)
        deleted_source = False
        if delete_source:
            # delete_project refuses if proposals exist — after our move it has 0
            deleted_source = self.delete_project(source_id)

        return {
            "target_id": target_id,
            "source_id": source_id,
            "merged_proposals": len(merged_ids),
            "merged_proposal_ids": merged_ids,
            "deleted_source": deleted_source,
        }

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
        valid_sort_keys = ["last_update", "create_at", "update_at", "title", "id", "status", "stage"]
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
        # Timestamps (V5 B4): ISO8601 UTC with Z suffix
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        new_row["create_at"] = now_iso
        new_row["update_at"] = now_iso
        for key, value in data.items():
            if key in PROPOSALS_CSV_HEADERS and value is not None:
                new_row[key] = str(value)

        # Auto-fill project_local_path from project's local_path if not explicitly set
        if not new_row.get("project_local_path"):
            with self._lock_file(self.config.projects_csv, "shared"):
                with open(self.config.projects_csv, "r", encoding="utf-8", newline="") as f:
                    reader = csv.DictReader(f)
                    for prow in reader:
                        if prow.get("id") == new_row.get("project_id", ""):
                            new_row["project_local_path"] = prow.get("local_path", "")
                            break

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

    def merge_proposals_by_project(
        self,
        target_project_id: str,
        source_project_name: str,
    ) -> dict:
        """Merge proposals from a source project (matched by name, case-insensitive)
        into a target project. Only proposals with status in
        {active, archived} are merged — intake / in-progress proposals stay where
        they are.

        Returns:
            {"merged_count": int, "merged_ids": [str, ...]}

        Raises:
            ValueError if target_project_id does not exist.
        """
        target = self.get_project(target_project_id)
        if target is None:
            raise ValueError(f"Target project not found: {target_project_id}")

        target_name_lower = (source_project_name or "").strip().lower()

        # Find source project by case-insensitive name match
        with self._lock_file(self.config.projects_csv, "shared"):
            with open(self.config.projects_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                source_project_id = None
                for row in reader:
                    if (row.get("name") or "").strip().lower() == target_name_lower:
                        source_project_id = row.get("id")
                        break

        if source_project_id is None:
            return {"merged_count": 0, "merged_ids": []}

        # Update proposals: project_id = target_project_id, where project_id =
        # source_project_id AND status IN {active, archived}
        with self._lock_file(self.config.proposals_csv, "shared"):
            with open(self.config.proposals_csv, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

        merged_ids = []
        today = datetime.now().strftime("%Y-%m-%d")
        for row in rows:
            if (row.get("project_id") == source_project_id
                    and row.get("status") in ("active", "archived")):
                row["project_id"] = target_project_id
                row["last_update"] = today
                merged_ids.append(row["id"])

        with self._lock_file(self.config.proposals_csv, "exclusive"):
            sha_before = self._sha256(self.config.proposals_csv)
            with open(self.config.proposals_csv, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=PROPOSALS_CSV_HEADERS)
                writer.writeheader()
                writer.writerows(rows)
            sha_after = self._sha256(self.config.proposals_csv)

        # Field-level audit per merged proposal
        for pid in merged_ids:
            self._audit(
                "UPDATE", "proposal", pid,
                field="project_id", old=source_project_id, new=target_project_id,
                checksum_after=sha_after,
            )

        # Sync proposal_count on both projects
        self._sync_project_proposal_count(source_project_id)
        self._sync_project_proposal_count(target_project_id)

        return {"merged_count": len(merged_ids), "merged_ids": merged_ids}

    def update_proposal(self, proposal_id: str, updates: dict) -> Optional[Proposal]:
        """Update proposal fields (partial update, field-level audit).

        Side effect: when ``status`` is NOT in ``updates`` and one of the
        business fields (stage / prd_confirmation / tech_expectations /
        acceptance) is being changed, the ``status`` field is automatically
        advanced to the value suggested by ``derive_status_from_fields()`` —
        BUT only if the current ``status`` can legally transition to the
        derived value per ``STATUS_TRANSITIONS``. Illegal transitions are
        silently skipped (status stays unchanged) so existing workflows
        that bypass the state machine still keep working.
        """
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
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        old_values = {}
        for key, value in updates.items():
            if key == "id" or value is None:
                continue
            if key in PROPOSALS_CSV_HEADERS:
                old_values[key] = rows[target_idx].get(key, "")
                rows[target_idx][key] = str(value)
        rows[target_idx]["last_update"] = today
        # V5 B4: bump update_at on every update; create_at is preserved.
        # project_local_path is also preserved unless explicitly included in updates.
        rows[target_idx]["update_at"] = now_iso

        # ─── Auto-derive status from business field changes ───
        # Skip if user explicitly set status in this update — they own the choice.
        # update_proposal_status() relies on this: it calls update_proposal with
        # {"status": new_status} and expects the state-machine check in
        # update_proposal_status() to be authoritative.
        #
        # Also skip if no business field actually changed in this update.
        # Without this guard, updating an unrelated field (e.g. notes, title)
        # would re-run derive_status_from_fields() and could *regress* the
        # status to an earlier state (e.g. stage=ideation stays ideation, so
        # a previously-promoted status=in_dev gets clobbered back to ideation).
        #
        # Note on legality: derived status is applied WITHOUT checking
        # STATUS_TRANSITIONS. Rationale: business fields (stage / acceptance /
        # deployment_url) are the ground truth written by the dev/PM pipeline;
        # they often jump multiple steps ahead of status (legacy data had 290+
        # intake proposals with stage=approved_for_dev or acceptance=accepted).
        # The status field exists to *report* the business state, not to gate
        # it — so auto-derive should sync status to whatever the business fields
        # already declare. Explicit status changes via update_proposal_status()
        # still go through the state machine.
        _BUSINESS_FIELDS = {"stage", "prd_confirmation", "tech_expectations", "acceptance", "deployment_url"}
        business_changed = bool(set(old_values.keys()) & _BUSINESS_FIELDS)
        if "status" not in updates and business_changed:
            derived = derive_status_from_fields(rows[target_idx])
            if derived:
                current_status = rows[target_idx].get("status", "")
                if derived != current_status:
                    old_values["status"] = current_status
                    rows[target_idx]["status"] = derived

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
