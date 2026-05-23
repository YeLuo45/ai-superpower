"""Configuration loader for ai-superpower."""
import os
import tomllib
from pathlib import Path
from dataclasses import dataclass

CONFIG_PATH = Path.home() / ".ai-superpower" / "config.toml"


@dataclass
class APIConfig:
    key: str
    socket_path: str = "/var/run/ai-superpower/api.sock"
    proposals_csv: str = "/home/hermes/proposals/proposals.csv"
    projects_csv: str = "/home/hermes/proposals/projects.csv"
    audit_log: str = "/home/hermes/proposals/audit.log"
    allow_delete: bool = False


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
        proposals_csv=api_section.get("proposals_csv", "/home/hermes/proposals/proposals.csv"),
        projects_csv=api_section.get("projects_csv", "/home/hermes/proposals/projects.csv"),
        audit_log=api_section.get("audit_log", "/home/hermes/proposals/audit.log"),
        allow_delete=api_section.get("allow_delete", False),
    )
