#!/usr/bin/env python3
"""
Asana Client -- Reads tasks, checks completion, marks tasks done.
Used by Oracle for morning briefings and by agents for task management.
"""

import os
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class AsanaClient:
    """Lightweight Asana API client using requests (no SDK needed)."""

    BASE_URL = "https://app.asana.com/api/1.0"

    def __init__(self):
        self.token = os.environ.get("ASANA_ACCESS_TOKEN")
        self.project_id = os.environ.get("ASANA_PROJECT_ID")
        self.workspace_id = os.environ.get("ASANA_WORKSPACE_ID")

    @property
    def available(self) -> bool:
        return bool(self.token)

    @property
    def headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

    def _get(self, path: str, params: dict = None):
        import requests
        resp = requests.get(f"{self.BASE_URL}/{path}", headers=self.headers,
                           params=params, timeout=15)
        resp.raise_for_status()
        return resp.json().get("data", [])

    def _post(self, path: str, data: dict):
        import requests
        resp = requests.post(f"{self.BASE_URL}/{path}", headers=self.headers,
                            json={"data": data}, timeout=15)
        resp.raise_for_status()
        return resp.json().get("data", {})

    def _put(self, path: str, data: dict):
        import requests
        resp = requests.put(f"{self.BASE_URL}/{path}", headers=self.headers,
                           json={"data": data}, timeout=15)
        resp.raise_for_status()
        return resp.json().get("data", {})

    # --- Task Queries ---

    def get_project_tasks(self, completed_since: str = None) -> list:
        """Get all tasks in the configured project."""
        if not self.available or not self.project_id:
            return []

        params = {
            "opt_fields": "name,completed,due_on,assignee.name,notes,memberships.section.name,completed_at",
        }
        if completed_since:
            params["completed_since"] = completed_since

        try:
            return self._get(f"projects/{self.project_id}/tasks", params)
        except Exception as e:
            logger.error(f"Asana fetch error: {e}")
            return []

    def get_tasks_due_today(self) -> list:
        """Get tasks due today or overdue."""
        tasks = self.get_project_tasks()
        today = datetime.now().strftime("%Y-%m-%d")
        return [
            t for t in tasks
            if not t.get("completed")
            and t.get("due_on")
            and t["due_on"] <= today
        ]

    def get_tasks_due_this_week(self) -> list:
        """Get tasks due this week."""
        tasks = self.get_project_tasks()
        today = datetime.now()
        week_end = (today + timedelta(days=7 - today.weekday())).strftime("%Y-%m-%d")
        return [
            t for t in tasks
            if not t.get("completed")
            and t.get("due_on")
            and t["due_on"] <= week_end
        ]

    def get_incomplete_tasks(self) -> list:
        """Get all incomplete tasks."""
        tasks = self.get_project_tasks()
        return [t for t in tasks if not t.get("completed")]

    def get_recently_completed(self, days: int = 1) -> list:
        """Get tasks completed in the last N days."""
        since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
        tasks = self.get_project_tasks(completed_since=since)
        return [t for t in tasks if t.get("completed")]

    # --- Task Actions ---

    def complete_task(self, task_id: str) -> bool:
        """Mark a task as complete."""
        try:
            self._put(f"tasks/{task_id}", {"completed": True})
            logger.info(f"Asana task {task_id} marked complete")
            return True
        except Exception as e:
            logger.error(f"Failed to complete task {task_id}: {e}")
            return False

    def add_comment(self, task_id: str, text: str) -> bool:
        """Add a comment to a task."""
        try:
            self._post(f"tasks/{task_id}/stories", {"text": text})
            return True
        except Exception as e:
            logger.error(f"Failed to comment on task {task_id}: {e}")
            return False

    # --- Briefing Formatters ---

    def format_task_summary(self) -> str:
        """Format a task summary for the morning briefing."""
        if not self.available:
            return "[Asana data unavailable -- set ASANA_ACCESS_TOKEN and ASANA_PROJECT_ID]"

        try:
            overdue = self.get_tasks_due_today()
            this_week = self.get_tasks_due_this_week()
            completed = self.get_recently_completed(days=1)
            all_incomplete = self.get_incomplete_tasks()

            lines = [
                f"ASANA -- Task Status (as of {datetime.now().strftime('%Y-%m-%d %H:%M')})",
                f"  Total open tasks: {len(all_incomplete)}",
                f"  Completed yesterday: {len(completed)}",
            ]

            if overdue:
                lines.append(f"")
                lines.append(f"  DUE TODAY / OVERDUE ({len(overdue)}):")
                for t in overdue:
                    assignee = t.get("assignee", {})
                    name = assignee.get("name", "Unassigned") if assignee else "Unassigned"
                    section = ""
                    for m in t.get("memberships", []):
                        s = m.get("section", {})
                        if s.get("name"):
                            section = f" [{s['name']}]"
                            break
                    lines.append(f"    [{t['due_on']}] {t['name']}{section} -- {name}")

            if this_week:
                week_only = [t for t in this_week if t not in overdue]
                if week_only:
                    lines.append(f"")
                    lines.append(f"  THIS WEEK ({len(week_only)}):")
                    for t in week_only[:10]:
                        lines.append(f"    [{t['due_on']}] {t['name']}")

            if completed:
                lines.append(f"")
                lines.append(f"  COMPLETED RECENTLY ({len(completed)}):")
                for t in completed[:5]:
                    lines.append(f"    [done] {t['name']}")

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Asana summary error: {e}")
            return f"[Asana error: {str(e)}]"


# --- CLI ---

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    client = AsanaClient()
    if not client.available:
        print("ASANA_ACCESS_TOKEN not set")
        print("Get a personal access token from: https://app.asana.com/0/developer-console")
        sys.exit(1)

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "today":
            tasks = client.get_tasks_due_today()
            for t in tasks:
                print(f"  [{t['due_on']}] {t['name']}")
        elif cmd == "summary":
            print(client.format_task_summary())
        elif cmd == "complete" and len(sys.argv) > 2:
            task_id = sys.argv[2]
            client.complete_task(task_id)
        else:
            print("Commands: today, summary, complete <task_id>")
    else:
        print(client.format_task_summary())
