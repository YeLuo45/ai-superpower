"""Backup scheduler — periodic and on-demand backup of db/ directory."""
import hashlib
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import APIConfig, load_config


class BackupScheduler:
    """Manages scheduled and on-demand backups."""

    def __init__(self, config: Optional[APIConfig] = None):
        self.config = config or load_config()
        self.local_path = self.config.backup_local_path
        self.max_copies = self.config.backup_max_copies
        self.remote_repo = self.config.backup_remote_repo
        self.remote_branch = self.config.backup_remote_branch or "backup"

    def backup(self) -> dict:
        """Perform a single backup. Returns dict with status info."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"db_backup_{ts}"
        backup_dir = Path(self.local_path) / backup_name

        result = {
            "success": False,
            "backup_dir": str(backup_dir),
            "local_done": False,
            "remote_done": False,
            "error": None,
        }

        # ── Local backup ────────────────────────────────────────────────────────
        try:
            Path(self.local_path).mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                self.config.data_dir,
                backup_dir,
                dirs_exist_ok=False,
            )
            result["local_done"] = True
            print(f"  Local backup: {backup_dir}")

            # Prune old backups
            self._prune_old()
            result["success"] = True
        except Exception as ex:
            result["error"] = str(ex)
            print(f"  Local backup failed: {ex}")
            return result

        # ── Remote backup (git push) ──────────────────────────────────────────
        if self.remote_repo and not self.remote_repo.startswith("git@"):
            # Convert HTTPS to SSH if needed
            remote = self.remote_repo
        elif self.remote_repo:
            remote = self.remote_repo
        else:
            remote = None

        if remote:
            try:
                self._git_push(backup_dir, remote)
                result["remote_done"] = True
                print(f"  Remote backup pushed to {remote}")
            except Exception as ex:
                print(f"  Remote backup failed (non-fatal): {ex}")
                result["error"] = str(ex)

        return result

    def list_backups(self) -> list[dict]:
        """List available local backups."""
        p = Path(self.local_path)
        if not p.exists():
            return []
        backups = []
        for d in sorted(p.iterdir()):
            if d.is_dir() and d.name.startswith("db_backup_"):
                stat = d.stat()
                backups.append({
                    "name": d.name,
                    "path": str(d),
                    "size": sum(f.stat().st_size for f in d.rglob("*") if f.is_file()),
                    "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
        return sorted(backups, key=lambda x: x["name"], reverse=True)

    def restore(self, backup_name: str) -> bool:
        """Restore db/ from a backup."""
        backup_dir = Path(self.local_path) / backup_name
        if not backup_dir.exists():
            print(f"Backup not found: {backup_dir}")
            return False

        # Backup current db first
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        emergency = Path(self.config.data_dir).parent / f"db_emergency_{ts}"
        shutil.copytree(self.config.data_dir, emergency)
        print(f"  Emergency backup of current db: {emergency}")

        # Restore
        target = Path(self.config.data_dir)
        shutil.rmtree(target)
        shutil.copytree(backup_dir, target)
        print(f"  Restored: {backup_name} → {target}")
        return True

    def _prune_old(self):
        """Delete oldest backups beyond max_copies."""
        backups = self.list_backups()
        if len(backups) <= self.max_copies:
            return
        for old in backups[self.max_copies:]:
            shutil.rmtree(Path(old["path"]))
            print(f"  Pruned: {old['name']}")

    def _git_push(self, backup_dir: Path, remote_repo: str):
        """Git add + commit + push a backup directory."""
        # Init a temp git repo in the backup dir
        git_dir = backup_dir / ".git"
        if not git_dir.exists():
            subprocess.run(["git", "init", "-q"], cwd=backup_dir, check=True)
            subprocess.run(
                ["git", "remote", "add", "origin", remote_repo],
                cwd=backup_dir, check=True,
            )

        # Configure credential helper for HTTPS token
        token = self.config.backup_api_key
        if token and remote_repo.startswith("https://"):
            subprocess.run(
                ["git", "config", "credential.helper", f"store --file {backup_dir}/.git/credentials"],
                cwd=backup_dir, check=False,
            )
            cred = f"https://oauth2:{token}@github.com"
            with open(backup_dir / ".git/credentials", "w") as f:
                f.write(cred)
            subprocess.run(
                ["git", "config", "http.version", "HTTP/1.1"],
                cwd=backup_dir, check=False,
            )

        subprocess.run(["git", "add", "-A"], cwd=backup_dir, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", f"Backup {backup_dir.name}"],
            cwd=backup_dir, check=True,
        )
        subprocess.run(
            ["git", "push", "-q", "origin", f"HEAD:{self.remote_branch}"],
            cwd=backup_dir, check=True,
        )
