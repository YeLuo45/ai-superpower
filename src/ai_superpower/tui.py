"""TUI interface for ai-superpower."""
import sys

try:
    import curses
except ImportError:
    sys.exit("curses module not available on this platform")


import json
import os
import textwrap
from pathlib import Path

# Add parent to path for imports when run as __main__
if __name__ == "__main__" or Path(__file__).stem == "tui":
    sys.path.insert(0, str(Path(__file__).parent.parent))

from ai_superpower.client import APIClient


class APIStatus:
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    UNKNOWN = "unknown"


class TUI:
    """Main TUI application."""

    # Color pairs
    PAIR_NORMAL = 1
    PAIR_SELECTED = 2
    PAIR_HEADER = 3
    PAIR_STATUS = 4
    PAIR_ERROR = 5
    PAIR_BRIGHT = 6

    # Views
    VIEW_PROJECTS = "projects"
    VIEW_PROPOSALS = "proposals"
    VIEW_DETAIL = "detail"

    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.client = None
        self.api_status = APIStatus.UNKNOWN
        self.current_view = self.VIEW_PROJECTS
        self.projects = []
        self.proposals = []
        self.selected_index = 0
        self.page = 1
        self.page_size = 20
        self.total = 0
        self.detail_item = None
        self.filter_text = ""
        self.filter_owner = ""
        self.filter_stage = ""
        self.status_msg = ""
        self.running = True

        # Curses setup
        curses.curs_set(0)
        curses.mouseinterval(10)
        curses.use_default_colors()
        curses.init_pair(self.PAIR_NORMAL, curses.COLOR_WHITE, -1)
        curses.init_pair(self.PAIR_SELECTED, curses.COLOR_BLACK, curses.COLOR_CYAN)
        curses.init_pair(self.PAIR_HEADER, curses.COLOR_WHITE, curses.COLOR_BLUE)
        curses.init_pair(self.PAIR_STATUS, curses.COLOR_BLACK, curses.COLOR_GREEN)
        curses.init_pair(self.PAIR_ERROR, curses.COLOR_WHITE, curses.COLOR_RED)
        curses.init_pair(self.PAIR_BRIGHT, curses.COLOR_YELLOW, -1)
        self.attr_normal = curses.color_pair(self.PAIR_NORMAL)
        self.attr_selected = curses.color_pair(self.PAIR_SELECTED)
        self.attr_header = curses.color_pair(self.PAIR_HEADER)
        self.attr_status = curses.color_pair(self.PAIR_STATUS)
        self.attr_error = curses.color_pair(self.PAIR_ERROR)
        self.attr_bright = curses.color_pair(self.PAIR_BRIGHT)

    def _connect(self):
        """Try to connect to API server."""
        try:
            self.client = APIClient()
            self.client.list_projects(page=1, page_size=1)
            self.api_status = APIStatus.CONNECTED
        except Exception as e:
            self.api_status = APIStatus.DISCONNECTED
            self.status_msg = f"API disconnected: {e}"

    def _load_projects(self):
        """Load projects from API."""
        try:
            result = self.client._do_request(
                "GET",
                f"/projects?page={self.page}&page_size={self.page_size}"
                + (f"&search={self._quote(self.filter_text)}" if self.filter_text else "")
            )
            self.projects = result.get("items", [])
            self.total = result.get("total", 0)
            self.selected_index = 0
        except Exception as e:
            self.status_msg = f"Failed to load projects: {e}"

    def _load_proposals(self):
        """Load proposals from API."""
        try:
            params = [
                f"page={self.page}",
                f"page_size={self.page_size}",
            ]
            if self.filter_text:
                params.append(f"search={self._quote(self.filter_text)}")
            if self.filter_owner:
                params.append(f"owner={self._quote(self.filter_owner)}")
            if self.filter_stage:
                params.append(f"stage={self._quote(self.filter_stage)}")
            path = "/proposals?" + "&".join(params)
            result = self.client._do_request("GET", path)
            self.proposals = result.get("items", [])
            self.total = result.get("total", 0)
            self.selected_index = 0
        except Exception as e:
            self.status_msg = f"Failed to load proposals: {e}"

    def _quote(self, s):
        import urllib.parse
        return urllib.parse.quote(s)

    def _delete_project(self, project_id):
        """Delete a project."""
        try:
            self.client._do_request("DELETE", f"/projects/{project_id}")
            self.status_msg = f"Deleted project {project_id}"
            self._load_projects()
        except Exception as e:
            self.status_msg = f"Delete failed: {e}"

    def _delete_proposal(self, proposal_id):
        """Delete a proposal."""
        try:
            self.client._do_request("DELETE", f"/proposals/{proposal_id}")
            self.status_msg = f"Deleted proposal {proposal_id}"
            self._load_proposals()
        except Exception as e:
            self.status_msg = f"Delete failed: {e}"

    def _confirm(self, msg):
        """Show confirmation dialog, return True if confirmed."""
        max_y, max_x = self.stdscr.getmaxyx()
        rows = msg.split("\n")
        h = len(rows) + 4
        w = max(len(r) for r in rows) + 6
        y = (max_y - h) // 2
        x = (max_x - w) // 2
        win = curses.newwin(h, w, y, x)
        win.attrset(self.attr_header)
        win.border()
        for i, row in enumerate(rows):
            win.addstr(i + 2, 3, row, self.attr_normal)
        win.addstr(h - 2, 3, "[Y]es  [N]o", self.attr_bright)
        win.refresh()
        while True:
            ch = self.stdscr.getch()
            if ch in (ord("y"), ord("Y")):
                win.erase()
                return True
            if ch in (ord("n"), ord("N"), 27):
                win.erase()
                return False

    def _show_detail(self, item, item_type):
        """Show detail view for a project or proposal."""
        max_y, max_x = self.stdscr.getmaxyx()
        # Build detail lines
        lines = []
        for key, val in item.items():
            if val is None or val == "":
                continue
            if isinstance(val, (list, dict)):
                val = json.dumps(val, ensure_ascii=False)
            lines.append(f"  {key}: {val}")

        # Paginate
        page = 0
        page_size = max_y - 4
        self.stdscr.erase()
        self._draw_header(f"{item_type.upper()} DETAIL — {item.get('id', item.get('name', '?'))}")
        self._draw_footer("[↑/↓] scroll  [Q] back")
        while True:
            self.stdscr.erase()
            self._draw_header(f"{item_type.upper()} DETAIL — {item.get('id', item.get('name', '?'))} [{page + 1}]")
            vis_lines = lines[page * page_size:(page + 1) * page_size]
            for i, ln in enumerate(vis_lines):
                y = i + 2
                if y >= max_y - 1:
                    break
                self.stdscr.addstr(y, 1, ln[:max_x - 2], self.attr_normal)
            self._draw_footer("[↑/↓] scroll  [Q] back")
            self.stdscr.refresh()
            ch = self.stdscr.getch()
            if ch in (ord("q"), ord("Q"), 27):
                break
            if ch == curses.KEY_DOWN and (page + 1) * page_size < len(lines):
                page += 1
            elif ch == curses.KEY_UP and page > 0:
                page -= 1

    def _draw_header(self, title=""):
        """Draw top header bar."""
        max_y, max_x = self.stdscr.getmaxyx()
        self.stdscr.attrset(self.attr_header)
        self.stdscr.addstr(0, 0, " " * (max_x - 1))
        prefix = " ai-superpower TUI "
        self.stdscr.addstr(0, 0, prefix, self.attr_header)
        status_icon = "●"
        status_color = self.attr_status if self.api_status == APIStatus.CONNECTED else self.attr_error
        self.stdscr.addstr(0, max_x - len(status_icon) - 2, status_icon, status_color)
        if title:
            self.stdscr.addstr(1, 0, title.center(max_x - 1), self.attr_normal)

    def _draw_footer(self, hint=""):
        """Draw bottom status bar."""
        max_y, max_x = self.stdscr.getmaxyx()
        self.stdscr.attrset(self.attr_status)
        self.stdscr.addstr(max_y - 1, 0, " " * (max_x - 1))
        if self.status_msg:
            msg = self.status_msg[:max_x - 1]
            self.stdscr.addstr(max_y - 1, 0, msg, self.attr_status)
        elif hint:
            self.stdscr.addstr(max_y - 1, 0, hint, self.attr_normal)
        self.stdscr.attrset(self.attr_normal)

    def _draw_nav_bar(self):
        """Draw tab navigation bar."""
        max_y, max_x = self.stdscr.getmaxyx()
        self.stdscr.attrset(self.attr_normal)
        tabs = [
            ("[P]rojects", self.VIEW_PROJECTS),
            ("[A]ll Proposals", self.VIEW_PROPOSALS),
        ]
        x = 2
        for label, view in tabs:
            attr = self.attr_selected if self.current_view == view else self.attr_normal
            self.stdscr.addstr(2, x, label, attr)
            x += len(label) + 3

    def _render_row(self, y, idx, item, columns):
        """Render a single list row."""
        max_x = self.stdscr.getmaxyx()[1]
        if y < 0 or y >= self.stdscr.getmaxyx()[0] - 1:
            return
        is_selected = idx == self.selected_index
        attr = self.attr_selected if is_selected else self.attr_normal
        self.stdscr.addstr(y, 0, " " * (max_x - 1), attr)
        x = 1
        for col_key, col_label, width in columns:
            val = item.get(col_key, "")
            val_str = str(val) if val is not None else ""
            display = val_str[:width]
            if is_selected:
                self.stdscr.addstr(y, x, display, attr)
            else:
                self.stdscr.addstr(y, x, display, attr)
            x += width + 1

    def _render_projects(self):
        """Render projects list view."""
        max_y, max_x = self.stdscr.getmaxyx()
        columns = [
            ("id", "ID", 20),
            ("name", "NAME", 25),
            ("proposal_count", "#P", 4),
            ("git_repo", "REPO", 20),
            ("last_update", "UPDATED", 12),
        ]
        col_widths = [w for _, _, w in columns]
        total_width = sum(col_widths) + len(col_widths) + 1
        offset_x = max(0, (max_x - total_width) // 2)

        self.stdscr.attrset(self.attr_normal)
        header = "  " + "  ".join(h.ljust(w) for h, _, w in columns)
        self.stdscr.addstr(3, offset_x, header[:max_x - offset_x], self.attr_bright)

        divider_y = 4
        self.stdscr.addstr(divider_y, offset_x, "─" * min(total_width, max_x - offset_x), self.attr_normal)

        for i, proj in enumerate(self.projects):
            row_y = 5 + i
            if row_y >= max_y - 2:
                break
            is_selected = i == self.selected_index
            attr = self.attr_selected if is_selected else self.attr_normal
            self.stdscr.addstr(row_y, offset_x, " " * (max_x - offset_x - 1), attr)
            x = offset_x + 1
            for col_key, _, col_w in columns:
                val = str(proj.get(col_key, "") or "")
                self.stdscr.addstr(row_y, x, val.ljust(col_w)[:col_w], attr)
                x += col_w + 1

        # Pagination info
        total_pages = max(1, (self.total + self.page_size - 1) // self.page_size)
        info = f"Page {self.page}/{total_pages}  Total: {self.total}"
        self.stdscr.addstr(max_y - 2, 2, info, self.attr_normal)

    def _render_proposals(self):
        """Render proposals list view."""
        max_y, max_x = self.stdscr.getmaxyx()
        columns = [
            ("id", "ID", 18),
            ("title", "TITLE", 30),
            ("owner", "OWNER", 12),
            ("status", "STATUS", 12),
            ("stage", "STAGE", 12),
        ]
        col_widths = [w for _, _, w in columns]
        total_width = sum(col_widths) + len(col_widths) + 1
        offset_x = max(0, (max_x - total_width) // 2)

        self.stdscr.attrset(self.attr_normal)
        header = "  " + "  ".join(h.ljust(w) for h, _, w in columns)
        self.stdscr.addstr(3, offset_x, header[:max_x - offset_x], self.attr_bright)

        divider_y = 4
        self.stdscr.addstr(divider_y, offset_x, "─" * min(total_width, max_x - offset_x), self.attr_normal)

        for i, prop in enumerate(self.proposals):
            row_y = 5 + i
            if row_y >= max_y - 2:
                break
            is_selected = i == self.selected_index
            attr = self.attr_selected if is_selected else self.attr_normal
            self.stdscr.addstr(row_y, offset_x, " " * (max_x - offset_x - 1), attr)
            x = offset_x + 1
            for col_key, _, col_w in columns:
                val = str(prop.get(col_key, "") or "")
                self.stdscr.addstr(row_y, x, val.ljust(col_w)[:col_w], attr)
                x += col_w + 1

        total_pages = max(1, (self.total + self.page_size - 1) // self.page_size)
        info = f"Page {self.page}/{total_pages}  Total: {self.total}"
        self.stdscr.addstr(max_y - 2, 2, info, self.attr_normal)

    def _filter_input(self, prompt):
        """Get text input from user."""
        max_y, max_x = self.stdscr.getmaxyx()
        curses.curs_set(1)
        win = curses.newwin(3, max_x - 4, (max_y - 3) // 2, 2)
        win.attrset(self.attr_header)
        win.border()
        win.addstr(0, 2, prompt, self.attr_bright)
        win.refresh()
        curses.echo()
        try:
            text = win.getstr(1, 2, max_x - 6).decode("utf-8", "replace")
        finally:
            curses.noecho()
            curses.curs_set(0)
        win.erase()
        return text

    def run(self):
        """Main TUI loop."""
        self._connect()
        if self.api_status == APIStatus.DISCONNECTED:
            self._show_disconnected_screen()
            return

        # Initial load
        self._load_projects()

        while self.running and self.api_status == APIStatus.CONNECTED:
            self._draw()

    def _show_disconnected_screen(self):
        """Show screen when API is not connected."""
        max_y, max_x = self.stdscr.getmaxyx()
        self.stdscr.erase()
        self.stdscr.attrset(self.attr_error)
        msg = "API Server is not running or socket is not accessible."
        self.stdscr.addstr(max_y // 2 - 2, max(0, (max_x - len(msg)) // 2), msg)
        hint = "Start the server: ai-superpower server"
        self.stdscr.addstr(max_y // 2, max(0, (max_x - len(hint)) // 2), hint, self.attr_normal)
        self.stdscr.addstr(max_y // 2 + 2, max(0, (max_x - 7) // 2), "[Q]uit", self.attr_bright)
        self.stdscr.refresh()
        while True:
            ch = self.stdscr.getch()
            if ch in (ord("q"), ord("Q"), 27):
                return

    def _draw(self):
        """Draw the current screen."""
        max_y, max_x = self.stdscr.getmaxyx()
        self.stdscr.erase()

        self._draw_header()
        self._draw_nav_bar()

        # Filter hint
        filter_parts = []
        if self.filter_text:
            filter_parts.append(f'q="{self.filter_text}"')
        if self.filter_owner:
            filter_parts.append(f'owner={self.filter_owner}')
        if self.filter_stage:
            filter_parts.append(f'stage={self.filter_stage}')
        if filter_parts:
            self.stdscr.addstr(3, 2, " ".join(filter_parts), self.attr_bright)

        if self.current_view == self.VIEW_PROJECTS:
            self._render_projects()
        elif self.current_view == self.VIEW_PROPOSALS:
            self._render_proposals()

        self._draw_footer("[↑↓] nav  [Enter] view  [d] delete  [/] search  [r] refresh  [q] quit")
        self.stdscr.refresh()
        self._handle_input()

    def _handle_input(self):
        """Handle keyboard input."""
        ch = self.stdscr.getch()
        max_items = len(self.projects) if self.current_view == self.VIEW_PROJECTS else len(self.proposals)
        total_pages = max(1, (self.total + self.page_size - 1) // self.page_size)

        if ch == curses.KEY_UP or ch == curses.KEY_PPAGE:
            self.selected_index = max(0, self.selected_index - 1)
        elif ch == curses.KEY_DOWN or ch == curses.KEY_NPAGE:
            self.selected_index = min(max_items - 1, self.selected_index + 1)
        elif ch in (ord("p"), ord("P")):
            self.current_view = self.VIEW_PROJECTS
            self.page = 1
            self._load_projects()
        elif ch in (ord("a"), ord("A")):
            self.current_view = self.VIEW_PROPOSALS
            self.page = 1
            self._load_proposals()
        elif ch in (ord("r"), ord("R")):
            if self.current_view == self.VIEW_PROJECTS:
                self._load_projects()
            else:
                self._load_proposals()
            self.status_msg = "Refreshed"
        elif ch == curses.KEY_HOME:
            self.selected_index = 0
        elif ch == curses.KEY_END:
            self.selected_index = max(0, max_items - 1)
        elif ch in (curses.KEY_ENTER, 10, 13):
            if max_items > 0:
                items = self.projects if self.current_view == self.VIEW_PROJECTS else self.proposals
                item = items[self.selected_index]
                item_type = "project" if self.current_view == self.VIEW_PROJECTS else "proposal"
                self._show_detail(item, item_type)
        elif ch in (ord("d"), ord("D")):
            if max_items > 0:
                items = self.projects if self.current_view == self.VIEW_PROJECTS else self.proposals
                item = items[self.selected_index]
                item_id = item.get("id", "")
                item_type = "project" if self.current_view == self.VIEW_PROJECTS else "proposal"
                msg = f"Delete {item_type} {item_id}?\nThis action cannot be undone."
                if self._confirm(msg):
                    if self.current_view == self.VIEW_PROJECTS:
                        self._delete_project(item_id)
                    else:
                        self._delete_proposal(item_id)
        elif ch == ord("/"):
            self.stdscr.nodelay(False)
            text = self._filter_input("Search: ")
            self.stdscr.nodelay(True)
            if text:
                self.filter_text = text
                self.page = 1
                if self.current_view == self.VIEW_PROJECTS:
                    self._load_projects()
                else:
                    self._load_proposals()
        elif ch in (ord("f"), ord("F")):
            # Filter by owner/stage
            self.stdscr.nodelay(False)
            prompt = "Filter (owner=xxx or stage=xxx): "
            text = self._filter_input(prompt)
            self.stdscr.nodelay(True)
            if "=" in text:
                key, val = text.split("=", 1)
                key = key.strip()
                val = val.strip()
                if key == "owner":
                    self.filter_owner = val
                elif key == "stage":
                    self.filter_stage = val
                self.page = 1
                self._load_proposals()
        elif ch in (ord("c"), ord("C")):
            # Clear filters
            self.filter_text = ""
            self.filter_owner = ""
            self.filter_stage = ""
            self.page = 1
            if self.current_view == self.VIEW_PROJECTS:
                self._load_projects()
            else:
                self._load_proposals()
            self.status_msg = "Filters cleared"
        elif ch in (curses.KEY_LEFT,):
            # Previous page
            if self.page > 1:
                self.page -= 1
                if self.current_view == self.VIEW_PROJECTS:
                    self._load_projects()
                else:
                    self._load_proposals()
        elif ch in (curses.KEY_RIGHT,):
            # Next page
            if self.page < total_pages:
                self.page += 1
                if self.current_view == self.VIEW_PROJECTS:
                    self._load_projects()
                else:
                    self._load_proposals()
        elif ch in (ord("q"), ord("Q"), 27):
            self.running = False
        elif ch == curses.KEY_RESIZE:
            pass  # Curses handles resize automatically


def main(stdscr):
    """Entry point passed to curses.wrapper()."""
    tui = TUI(stdscr)
    tui.run()


if __name__ == "__main__":
    curses.wrapper(main)
