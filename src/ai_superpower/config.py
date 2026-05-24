"""Configuration loader for ai-superpower."""
import os
import tomllib
from pathlib import Path
from dataclasses import dataclass

CONFIG_PATH = Path.home() / ".ai-superpower" / "config.toml"

# 包内默认数据目录
_DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "db"


@dataclass
class APIConfig:
    key: str
    socket_path: str = "/var/run/ai-superpower/api.sock"
    host: str = "0.0.0.0"
    port: int = 8000
    data_dir: str = ""
    proposals_csv: str = ""
    projects_csv: str = ""
    audit_log: str = ""
    allow_delete: bool = False

    # Backup
    backup_enabled: bool = False
    backup_frequency: str = "1h"   # 1h / 6h / 1d
    backup_max_copies: int = 48
    backup_local_path: str = ""
    backup_remote_repo: str = ""
    backup_remote_branch: str = "backup"
    backup_api_key: str = ""
    auto_backup_threshold: int = 5  # 0=disabled

    # Sync
    sync_target_repo: str = ""
    sync_enabled: bool = False
    sync_api_key: str = ""
    sync_interval_minutes: int = 0  # 0=disabled
    sync_last_run: str = ""

    def __post_init__(self):
        if self.data_dir:
            dd = Path(self.data_dir)
            self.proposals_csv = str(dd / "proposals.csv")
            self.projects_csv = str(dd / "projects.csv")
            self.audit_log = str(dd / "audit.log")
        else:
            if not self.proposals_csv:
                self.proposals_csv = str(_DEFAULT_DATA_DIR / "proposals.csv")
            if not self.projects_csv:
                self.projects_csv = str(_DEFAULT_DATA_DIR / "projects.csv")
            if not self.audit_log:
                self.audit_log = str(_DEFAULT_DATA_DIR / "audit.log")

        if not self.backup_local_path:
            self.backup_local_path = str(_DEFAULT_DATA_DIR.parent / "backups")


def load_config() -> APIConfig:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"Config not found at {CONFIG_PATH}. "
            "Create it with: mkdir -p ~/.ai-superpower && "
            "echo '[api]' >> ~/.ai-superpower/config.toml && "
            "echo 'key = \"$(openssl rand -hex 32)\"' >> ~/.ai-superpower/config.toml && "
            "echo 'socket_path = \"/var/run/ai-superpower/api.sock\"' >> ~/.ai-superpower/config.toml"
        )

    with open(CONFIG_PATH, "rb") as f:
        data = tomllib.load(f)

    api_section = data.get("api", {})
    backup_section = data.get("backup", {})
    server_section = data.get("server", {})

    return APIConfig(
        key=api_section.get("key", ""),
        socket_path=api_section.get("socket_path", "/var/run/ai-superpower/api.sock"),
        host=server_section.get("host", "0.0.0.0"),
        port=server_section.get("port", 8000),
        data_dir=api_section.get("data_dir", ""),
        proposals_csv=api_section.get("proposals_csv", ""),
        projects_csv=api_section.get("projects_csv", ""),
        audit_log=api_section.get("audit_log", ""),
        allow_delete=api_section.get("allow_delete", False),
        backup_enabled=backup_section.get("enabled", False),
        backup_frequency=backup_section.get("frequency", "1h"),
        backup_max_copies=backup_section.get("max_copies", 48),
        backup_local_path=backup_section.get("local_path", ""),
        backup_remote_repo=backup_section.get("remote_repo", ""),
        backup_remote_branch=backup_section.get("remote_branch", "backup"),
        backup_api_key=backup_section.get("api_key", ""),
        auto_backup_threshold=backup_section.get("auto_backup_threshold", 5),
    )
