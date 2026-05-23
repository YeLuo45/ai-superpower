"""Configuration loader for ai-superpower."""
import os
import tomllib
from pathlib import Path
from dataclasses import dataclass, field

CONFIG_PATH = Path.home() / ".ai-superpower" / "config.toml"

# 包内默认数据目录
_DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "db"


@dataclass
class APIConfig:
    key: str
    socket_path: str = "/var/run/ai-superpower/api.sock"
    data_dir: str = ""  # 如果设置，则优先用于 projects_csv / proposals_csv / audit_log
    proposals_csv: str = ""
    projects_csv: str = ""
    audit_log: str = ""
    allow_delete: bool = False

    def __post_init__(self):
        # 如果 data_dir 设置了，则覆盖三个路径
        if self.data_dir:
            dd = Path(self.data_dir)
            self.proposals_csv = str(dd / "proposals.csv")
            self.projects_csv = str(dd / "projects.csv")
            self.audit_log = str(dd / "audit.log")
        else:
            # 兜底默认值（保持向前兼容）
            if not self.proposals_csv:
                self.proposals_csv = str(_DEFAULT_DATA_DIR / "proposals.csv")
            if not self.projects_csv:
                self.projects_csv = str(_DEFAULT_DATA_DIR / "projects.csv")
            if not self.audit_log:
                self.audit_log = str(_DEFAULT_DATA_DIR / "audit.log")


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
    return APIConfig(
        key=api_section.get("key", ""),
        socket_path=api_section.get("socket_path", "/var/run/ai-superpower/api.sock"),
        data_dir=api_section.get("data_dir", ""),
        proposals_csv=api_section.get("proposals_csv", ""),
        projects_csv=api_section.get("projects_csv", ""),
        audit_log=api_section.get("audit_log", ""),
        allow_delete=api_section.get("allow_delete", False),
    )
