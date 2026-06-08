"""CLI entry point for ai-superpower."""
import argparse
import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ai_superpower.client import APIClient
from ai_superpower.config import load_config


def cmd_run(args):
    """Start the API server."""
    import uvicorn

    config = load_config()
    sock_dir = Path(config.socket_path).parent
    sock_dir.mkdir(parents=True, exist_ok=True)

    # Bind to TCP so Windows can access via browser
    host = args.host or config.host
    port = args.port or config.port

    # Check if port is already in use
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        sock.close()
    except OSError as e:
        if e.errno == 98:  # address already in use
            import subprocess
            # Try multiple commands to find the process using the port
            cmds = [
                ["ss", "-tlnp"],
                ["netstat", "-tlnp"],
                ["fuser", f"{port}/tcp"],
            ]
            info = ""
            for cmd in cmds:
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
                    lines = [l for l in r.stdout.splitlines() if f":{port}" in l or str(port) in l]
                    if lines:
                        info += "\n".join(lines) + "\n"
                except Exception:
                    pass
            print(f"ERROR: Port {port} is already in use.", file=sys.stderr)
            if info:
                print(f"Current listener:\n{info}", file=sys.stderr)
            else:
                print("Run 'ss -tlnp' or 'netstat -tlnp' to find the process.", file=sys.stderr)
            return
        raise

    print(f"Web UI: http://{host}:{port}")
    print(f"Web UI (Windows): http://localhost:{port}")
    print(f"API socket: {config.socket_path}")
    print("Press Ctrl+C to stop")

    try:
        uvicorn.run(
            "ai_superpower.server:app",
            host=host,
            port=port,
            log_level="info",
            reload=False,
        )
    except KeyboardInterrupt:
        pass


def cmd_project_create(args):
    client = APIClient()
    client.create_project(
        name=args.name,
        git_repo=args.git_repo or "",
        local_path=args.local_path or "",
        description=args.description or "",
        prj_url=args.prj_url or "",
    )


def cmd_project_list(args):
    client = APIClient()
    client.list_projects(page=args.page, page_size=args.page_size, search=args.search,
                         sort_by=args.sort_by, sort_order=args.sort_order)


def cmd_project_get(args):
    client = APIClient()
    client.get_project(args.id)


def cmd_project_delete(args):
    client = APIClient()
    client.delete_project(args.id)


def _cmd_project_sync_status(args):
    client = APIClient()
    result = client._do_request("GET", f"/projects/{args.id}/sync-status")
    print(f"Project: {result['project_id']}")
    print(f"Sync enabled: {result['sync_enabled']}")
    print(f"Last sync: {result['sync_last_run'] or 'never'}")


def _cmd_project_sync_enable(args, enabled: bool):
    client = APIClient()
    result = client._do_request("PUT", f"/projects/{args.id}/sync-enabled?enabled={enabled}")
    print(f"Sync enabled: {result['sync_enabled']} for project {result['id']}")


def cmd_proposal_create(args):
    data = {
        "title": args.title,
        "owner": args.owner,
        "project_id": args.project_id,
        "stage": args.stage,
    }
    if args.prd_path:
        data["prd_path"] = args.prd_path
    if args.tech_solution_path:
        data["tech_solution_path"] = args.tech_solution_path
    if args.project_path:
        data["project_path"] = args.project_path
    if args.git_repo:
        data["git_repo"] = args.git_repo
    if args.deployment_url:
        data["deployment_url"] = args.deployment_url
    if args.engine:
        data["engine"] = args.engine
    if args.target:
        data["target"] = args.target
    if args.game_type:
        data["game_type"] = args.game_type
    if args.notes:
        data["notes"] = args.notes

    client = APIClient()
    client.create_proposal(**data)


def cmd_proposal_list(args):
    client = APIClient()
    client.list_proposals(
        page=args.page,
        page_size=args.page_size,
        project_id=args.project_id,
        status=args.status,
        owner=args.owner,
        search=args.search,
        stage=args.stage,
        sort_by=args.sort_by,
        sort_order=args.sort_order,
    )


def cmd_proposal_get(args):
    client = APIClient()
    client.get_proposal(args.id)


def cmd_proposal_update_status(args):
    client = APIClient()
    client.update_proposal_status(args.id, args.status)


def cmd_proposal_update_fields(args):
    # Parse --field key=value pairs
    fields = {}
    if args.fields:
        for f in args.fields:
            if "=" in f:
                k, v = f.split("=", 1)
                fields[k.strip()] = v.strip()

    client = APIClient()
    client.update_proposal_fields(args.id, **fields)


def cmd_proposal_delete(args):
    client = APIClient()
    client.delete_proposal(args.id)


def cmd_validate(args):
    import json
    import ast
    data = json.loads(args.data) if args.data.startswith("{") else ast.literal_eval(args.data)
    client = APIClient()
    client.validate(data)


def cmd_audit(args):
    client = APIClient()
    client.get_audit(page=args.page, page_size=args.page_size, entity_id=args.entity_id, op=args.op, entity=args.entity)


def cmd_replay(args):
    from ai_superpower.replay import Replay
    r = Replay(dry_run=args.dry_run)
    if args.undo:
        r.undo_last(args.undo)
    else:
        r.replay_from_file(
            from_time=args.from_time,
            last_n=args.last,
            entity_id=args.entity_id,
        )


def cmd_backup(args):
    from ai_superpower.backup import BackupScheduler
    bs = BackupScheduler()
    if args.list_backups:
        backups = bs.list_backups()
        print(f"{'Name':<40} {'Size':>10}  Modified")
        print("-" * 65)
        for b in backups:
            size_kb = b["size"] / 1024
            print(f"{b['name']:<40} {size_kb:>9.1f}KB  {b['mtime']}")
        return
    if args.restore:
        bs.restore(args.restore)
        return
    result = bs.backup()
    if result["success"]:
        print(f"Backup complete: {result['backup_dir']}")
        if result["remote_done"]:
            print("Remote push: OK")
    else:
        print(f"Backup failed: {result['error']}")


def cmd_sync_to_index(args):
    """Sync proposal-index.md from API data."""
    client = APIClient()
    # Get all proposals
    all_proposals = []
    page = 1
    while True:
        result = client._do_request("GET", f"/proposals?page={page}&page_size=500")
        items = result.get("items", [])
        all_proposals.extend(items)
        if page >= result.get("total", 0) // 500 + 1:
            break
        page += 1

    # Get all projects
    all_projects = []
    page = 1
    while True:
        result = client._do_request("GET", f"/projects?page={page}&page_size=500")
        items = result.get("items", [])
        all_projects.extend(items)
        if page >= result.get("total", 0) // 500 + 1:
            break
        page += 1

    project_map = {p["id"]: p for p in all_projects}

    # Generate markdown
    from datetime import datetime
    lines = ["# Proposal Index", "", f"Last updated: {datetime.now().strftime('%Y-%m-%d')}",
             f"Total: {len(all_proposals)} proposals, {len(all_projects)} projects", ""]

    # Sort by last_update descending
    sorted_proposals = sorted(all_proposals, key=lambda p: p.get("last_update", ""), reverse=True)

    current_project_id = None
    for p in sorted_proposals:
        pid = p.get("project_id", "")
        if pid != current_project_id:
            current_project_id = pid
            proj = project_map.get(pid, {})
            if proj:
                lines.extend([
                    f"## {proj['id']}: {proj['name']}",
                    "",
                    f"- **Description**: {proj.get('description', '')}",
                    f"- **Git Repo**: {proj.get('git_repo', '')}",
                    f"- **Local Path**: {proj.get('local_path', '')}",
                    "",
                ])

        # Format entry
        status_badge = f"[{p.get('status', '')}]"
        lines.append(f"- **{p['id']}** {status_badge} {p.get('title', '')} — {p.get('owner', '')} | {p.get('stage', '')}")

    content = "\n".join(lines)
    index_path = Path("/home/hermes/proposals/proposal-index.md")
    index_path.write_text(content, encoding="utf-8")
    print(f"Synced {len(all_proposals)} proposals to {index_path}")


def cmd_tui(args):
    """Launch the interactive TUI."""
    import curses
    from ai_superpower.tui import main as tui_main
    curses.wrapper(tui_main)


def cmd_mcp(args):
    """Start the MCP server (stdio or Streamable HTTP)."""
    from ai_superpower.mcp_server import main_stdio, main_http
    if args.transport == "stdio":
        main_stdio()
    elif args.transport == "http":
        host = args.host or "0.0.0.0"
        port = args.port or 8765
        main_http(host=host, port=port)
    else:
        raise ValueError(f"Unknown transport: {args.transport}")


def main():
    parser = argparse.ArgumentParser(prog="aisp", description="aisp (ai-superpower) API CLI")
    subparsers = parser.add_subparsers(dest="command")

    # run
    p_run = subparsers.add_parser("run", help="Start API server")
    p_run.add_argument("--host", default=None, help="Bind host (default: 0.0.0.0)")
    p_run.add_argument("--port", type=int, default=None, help="Bind port (default: 8000)")

    # project
    p_proj = subparsers.add_parser("project", help="Project commands")
    proj_sub = p_proj.add_subparsers(dest="project_cmd")

    p_proj_create = proj_sub.add_parser("create", help="Create project")
    p_proj_create.add_argument("--name", required=True)
    p_proj_create.add_argument("--git-repo", default="")
    p_proj_create.add_argument("--prj-url", dest="prj_url", default="")
    p_proj_create.add_argument("--local-path", dest="local_path", default="")
    p_proj_create.add_argument("--description", default="")
    p_proj_create.set_defaults(func=cmd_project_create)

    p_proj_list = proj_sub.add_parser("list", help="List projects")
    p_proj_list.add_argument("--page", type=int, default=1)
    p_proj_list.add_argument("--page-size", dest="page_size", type=int, default=50)
    p_proj_list.add_argument("--search", default=None)
    p_proj_list.add_argument("--sort-by", default="last_update")
    p_proj_list.add_argument("--sort-order", default="desc")
    p_proj_list.set_defaults(func=cmd_project_list)

    p_proj_get = proj_sub.add_parser("get", help="Get project")
    p_proj_get.add_argument("id")
    p_proj_get.set_defaults(func=cmd_project_get)

    p_proj_delete = proj_sub.add_parser("delete", help="Delete project")
    p_proj_delete.add_argument("id")
    p_proj_delete.set_defaults(func=cmd_project_delete)

    # project sync
    p_proj_sync_status = proj_sub.add_parser("sync-status", help="Get sync status of a project")
    p_proj_sync_status.add_argument("id")
    p_proj_sync_status.set_defaults(func=lambda args: _cmd_project_sync_status(args))

    p_proj_sync_enable = proj_sub.add_parser("sync-enable", help="Enable sync for a project")
    p_proj_sync_enable.add_argument("id")
    p_proj_sync_enable.set_defaults(func=lambda args: _cmd_project_sync_enable(args, True))

    p_proj_sync_disable = proj_sub.add_parser("sync-disable", help="Disable sync for a project")
    p_proj_sync_disable.add_argument("id")
    p_proj_sync_disable.set_defaults(func=lambda args: _cmd_project_sync_enable(args, False))

    # proposal
    p_prop = subparsers.add_parser("proposal", help="Proposal commands")
    prop_sub = p_prop.add_subparsers(dest="proposal_cmd")

    p_prop_create = prop_sub.add_parser("create", help="Create proposal")
    p_prop_create.add_argument("--title", required=True)
    p_prop_create.add_argument("--owner", "-o", required=True)
    p_prop_create.add_argument("--project-id", dest="project_id", required=True)
    p_prop_create.add_argument("--stage", required=True)
    p_prop_create.add_argument("--prd-path", dest="prd_path", default="")
    p_prop_create.add_argument("--tech-solution-path", dest="tech_solution_path", default="")
    p_prop_create.add_argument("--project-path", dest="project_path", default="")
    p_prop_create.add_argument("--git-repo", dest="git_repo", default="")
    p_prop_create.add_argument("--deployment-url", dest="deployment_url", default="")
    p_prop_create.add_argument("--engine", default="")
    p_prop_create.add_argument("--target", default="")
    p_prop_create.add_argument("--game-type", dest="game_type", default="")
    p_prop_create.add_argument("--notes", default="")
    p_prop_create.set_defaults(func=cmd_proposal_create)

    p_prop_list = prop_sub.add_parser("list", help="List proposals")
    p_prop_list.add_argument("--page", type=int, default=1)
    p_prop_list.add_argument("--page-size", dest="page_size", type=int, default=50)
    p_prop_list.add_argument("--project-id", dest="project_id", default=None)
    p_prop_list.add_argument("--status", default=None)
    p_prop_list.add_argument("--owner", default=None)
    p_prop_list.add_argument("--search", default=None)
    p_prop_list.add_argument("--stage", default=None)
    p_prop_list.add_argument("--sort-by", default="last_update")
    p_prop_list.add_argument("--sort-order", default="desc")
    p_prop_list.set_defaults(func=cmd_proposal_list)

    p_prop_get = prop_sub.add_parser("get", help="Get proposal")
    p_prop_get.add_argument("id")
    p_prop_get.set_defaults(func=cmd_proposal_get)

    p_prop_upd_status = prop_sub.add_parser("update-status", help="Update proposal status")
    p_prop_upd_status.add_argument("id")
    p_prop_upd_status.add_argument("--status", "-s", required=True)
    p_prop_upd_status.set_defaults(func=cmd_proposal_update_status)

    p_prop_upd_fields = prop_sub.add_parser("update-fields", help="Update proposal fields")
    p_prop_upd_fields.add_argument("id")
    p_prop_upd_fields.add_argument("--field", "-f", action="append", dest="fields")
    p_prop_upd_fields.set_defaults(func=cmd_proposal_update_fields)

    p_prop_delete = prop_sub.add_parser("delete", help="Delete proposal")
    p_prop_delete.add_argument("id")
    p_prop_delete.set_defaults(func=cmd_proposal_delete)

    # validate
    p_validate = subparsers.add_parser("validate", help="Validate proposal data")
    p_validate.add_argument("--data", required=True, help="JSON data to validate")
    p_validate.set_defaults(func=cmd_validate)

    # audit
    p_audit = subparsers.add_parser("audit", help="Query audit log")
    p_audit.add_argument("--page", type=int, default=1)
    p_audit.add_argument("--page-size", dest="page_size", type=int, default=100)
    p_audit.add_argument("--entity-id", dest="entity_id", default=None)
    p_audit.add_argument("--op", default=None, help="Filter by op: CREATE/UPDATE/DELETE")
    p_audit.add_argument("--entity", default=None, help="Filter by entity: project/proposal")
    p_audit.set_defaults(func=cmd_audit)

    # sync-to-index
    p_sync = subparsers.add_parser("sync-to-index", help="Sync proposal-index.md from API")
    p_sync.set_defaults(func=cmd_sync_to_index)

    # tui
    p_tui = subparsers.add_parser("tui", help="Launch interactive TUI")
    p_tui.set_defaults(func=cmd_tui)

    # mcp
    p_mcp = subparsers.add_parser("mcp", help="Start MCP server (stdio or Streamable HTTP)")
    p_mcp.add_argument("--transport", choices=["stdio", "http"], default="stdio",
                        help="Transport type: stdio (default) or http")
    p_mcp.add_argument("--host", default=None, help="[http] Bind host (default: 0.0.0.0)")
    p_mcp.add_argument("--port", type=int, default=None, help="[http] Bind port (default: 8765 to avoid collision with 'aisp run' on 8000)")
    p_mcp.set_defaults(func=cmd_mcp)

    # replay
    p_replay = subparsers.add_parser("replay", help="Replay audit log entries")
    p_replay.add_argument("--dry-run", action="store_true", default=False)
    p_replay.add_argument("--from", dest="from_time", default=None, help="ISO timestamp to replay from")
    p_replay.add_argument("--last", type=int, default=None, help="Replay last N entries")
    p_replay.add_argument("--entity-id", dest="entity_id", default=None, help="Filter by entity ID")
    p_replay.add_argument("--undo", default=None, help="Undo last operation on entity ID")
    p_replay.set_defaults(func=cmd_replay)

    # backup
    p_backup = subparsers.add_parser("backup", help="Backup management")
    p_backup.add_argument("--list", dest="list_backups", action="store_true", default=False)
    p_backup.add_argument("--restore", default=None, help="Restore from backup name")
    p_backup.set_defaults(func=cmd_backup)

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "run":
        cmd_run(args)
    elif args.command == "tui":
        cmd_tui(args)
    elif hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
