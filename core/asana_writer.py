#!/usr/bin/env python3
"""
Asana Write-Back Client -- Extended write operations for Asana API.

Extends the existing asana_client.py (which already has complete_task and
add_comment) with full task creation, subtask management, project operations,
and file attachments.

Uses Asana REST API v1.0.

Rate Limits:
  - 1,500 requests per minute per Personal Access Token
  - Response headers include rate limit info
  - 429 response with Retry-After header when exceeded
  - Free tier: 500 requests/min for free workspaces

Authentication:
  - Personal Access Token: Authorization: Bearer 1/1234567890:abcdef...
  - Get from: https://app.asana.com/0/developer-console > Personal access tokens
  - Scopes are implicit with PAT (full access to user's workspaces)

What can be done WITHOUT human approval:
  - Create tasks from agent outputs (action items)
  - Create subtasks (break down work)
  - Add comments (status updates, agent insights)
  - Move tasks between sections (workflow progression)
  - Set custom fields (data enrichment)
  - Attach files (reports, analysis outputs)

What NEEDS human approval:
  - Delete tasks or projects
  - Reassign tasks to other people
  - Create new projects (organizational decision)
  - Archive projects
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class AsanaWriter:
    """
    Extended write-back client for Asana REST API.

    Builds on top of the existing AsanaClient pattern in asana_client.py.
    Adds task creation, subtasks, project management, and file attachments.
    """

    BASE_URL = "https://app.asana.com/api/1.0"

    def __init__(self):
        self.token = os.environ.get("ASANA_ACCESS_TOKEN")
        self.project_id = os.environ.get("ASANA_PROJECT_ID")
        self.workspace_id = os.environ.get("ASANA_WORKSPACE_ID")

    @property
    def available(self) -> bool:
        return bool(self.token)

    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    # --- Internal HTTP Methods with Retry Logic ---

    def _request(self, method: str, path: str, data: dict = None,
                 params: dict = None, files: dict = None,
                 max_retries: int = 3) -> dict:
        """
        Make an HTTP request with retry logic and rate limit handling.
        """
        import requests

        url = f"{self.BASE_URL}/{path}"

        for attempt in range(max_retries):
            try:
                if files:
                    # Multipart upload for file attachments
                    headers = {"Authorization": f"Bearer {self.token}"}
                    resp = requests.request(
                        method, url, headers=headers,
                        data=data, files=files, timeout=60
                    )
                else:
                    body = {"data": data} if data and method.upper() != "GET" else None
                    resp = requests.request(
                        method, url, headers=self.headers,
                        json=body, params=params, timeout=30
                    )

                # Handle rate limiting
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", 30))
                    logger.warning(f"Asana rate limited. Waiting {retry_after}s (attempt {attempt + 1})")
                    time.sleep(retry_after)
                    continue

                resp.raise_for_status()
                result = resp.json() if resp.content else {}
                return result.get("data", result)

            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"Asana {method} {path} failed after {max_retries} attempts: {e}")
                    raise
                wait_time = 2 ** attempt
                logger.warning(f"Asana request failed, retrying in {wait_time}s: {e}")
                time.sleep(wait_time)

        return {}

    def _get(self, path: str, params: dict = None) -> dict:
        return self._request("GET", path, params=params)

    def _post(self, path: str, data: dict = None, files: dict = None) -> dict:
        return self._request("POST", path, data=data, files=files)

    def _put(self, path: str, data: dict = None) -> dict:
        return self._request("PUT", path, data=data)

    def _delete(self, path: str) -> dict:
        return self._request("DELETE", path)

    # ===================================================================
    # 1. CREATE TASKS
    #    Endpoint: POST /tasks
    #    Autonomy: SAFE -- creating work items from agent outputs
    # ===================================================================

    def create_task(self, name: str, notes: str = "",
                     due_on: str = None, assignee: str = None,
                     project_id: str = None, section_id: str = None,
                     tags: list = None, custom_fields: dict = None,
                     html_notes: str = None) -> dict:
        """
        Create a task in a project.

        POST /tasks

        Args:
            name: Task name/title
            notes: Plain text description
            due_on: Due date as "YYYY-MM-DD"
            assignee: Assignee user GID (or "me" for token owner)
            project_id: Project GID (defaults to ASANA_PROJECT_ID)
            section_id: Section GID to place task in (optional)
            tags: List of tag GIDs
            custom_fields: Dict of {custom_field_gid: value}
            html_notes: Rich HTML notes (overrides plain notes)

        Returns:
            Created task object

        Example:
            writer.create_task(
                name="Launch replenishment email campaign",
                notes="Auto-created by Meridian agent.\\n\\nBased on analysis...",
                due_on="2026-03-05",
                assignee="me",
            )
        """
        task_data = {
            "name": name,
            "workspace": self.workspace_id,
        }

        pid = project_id or self.project_id
        if pid:
            task_data["projects"] = [pid]

        if notes:
            task_data["notes"] = notes
        if html_notes:
            task_data["html_notes"] = html_notes
        if due_on:
            task_data["due_on"] = due_on
        if assignee:
            task_data["assignee"] = assignee
        if tags:
            task_data["tags"] = tags
        if custom_fields:
            task_data["custom_fields"] = custom_fields

        # Memberships (for section placement)
        if section_id and pid:
            task_data["memberships"] = [{
                "project": pid,
                "section": section_id,
            }]

        result = self._post("tasks", data=task_data)
        task_gid = result.get("gid", "?")
        logger.info(f"Created task '{name}' (GID: {task_gid}) due: {due_on or 'no date'}")
        return result

    def create_task_from_agent(self, agent_name: str, title: str,
                                 description: str, priority: str = "medium",
                                 due_days: int = 3) -> dict:
        """
        Convenience: Create a task from an agent's output.
        Automatically formats notes with agent attribution and sets due date.

        Args:
            agent_name: Agent name (e.g. "Meridian", "Atlas", "PREP")
            title: Task title
            description: Task description/details
            priority: "low", "medium", "high", "critical"
            due_days: Days from now for due date

        Returns:
            Created task object
        """
        due_date = (datetime.now() + timedelta(days=due_days)).strftime("%Y-%m-%d")
        priority_emoji = {
            "critical": "[CRITICAL]",
            "high": "[HIGH]",
            "medium": "",
            "low": "[LOW]",
        }

        prefix = priority_emoji.get(priority, "")
        full_title = f"{prefix} {title}".strip()

        notes = (
            f"{description}\n\n"
            f"---\n"
            f"Auto-created by {agent_name} agent\n"
            f"Created: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"Priority: {priority}"
        )

        return self.create_task(
            name=full_title,
            notes=notes,
            due_on=due_date,
            assignee="me",
        )

    # ===================================================================
    # 2. SUBTASKS
    #    Endpoint: POST /tasks/{task_gid}/subtasks
    #    Autonomy: SAFE -- breaking down work
    # ===================================================================

    def create_subtask(self, parent_task_id: str, name: str,
                        notes: str = "", due_on: str = None,
                        assignee: str = None) -> dict:
        """
        Create a subtask under a parent task.

        POST /tasks/{task_gid}/subtasks

        Args:
            parent_task_id: Parent task GID
            name: Subtask name
            notes: Subtask description
            due_on: Due date "YYYY-MM-DD"
            assignee: Assignee GID

        Returns:
            Created subtask object
        """
        subtask_data = {"name": name}
        if notes:
            subtask_data["notes"] = notes
        if due_on:
            subtask_data["due_on"] = due_on
        if assignee:
            subtask_data["assignee"] = assignee

        result = self._post(f"tasks/{parent_task_id}/subtasks", data=subtask_data)
        logger.info(f"Created subtask '{name}' under task {parent_task_id}")
        return result

    def create_checklist(self, parent_task_id: str,
                          items: list) -> list:
        """
        Create multiple subtasks as a checklist.

        Args:
            parent_task_id: Parent task GID
            items: List of strings (subtask names) or dicts with
                   {"name": str, "due_on": str, "assignee": str}

        Returns:
            List of created subtask objects
        """
        results = []
        for item in items:
            if isinstance(item, str):
                item = {"name": item}

            result = self.create_subtask(
                parent_task_id,
                name=item["name"],
                notes=item.get("notes", ""),
                due_on=item.get("due_on"),
                assignee=item.get("assignee"),
            )
            results.append(result)
            time.sleep(0.1)  # Gentle rate limiting

        logger.info(f"Created {len(results)} subtasks under task {parent_task_id}")
        return results

    # ===================================================================
    # 3. COMMENTS (Stories)
    #    Endpoint: POST /tasks/{task_gid}/stories
    #    Autonomy: SAFE -- informational updates
    # ===================================================================

    def add_comment(self, task_id: str, text: str) -> dict:
        """
        Add a comment to a task.

        POST /tasks/{task_gid}/stories

        Args:
            task_id: Task GID
            text: Comment text (plain text)

        Returns:
            Created story object
        """
        result = self._post(f"tasks/{task_id}/stories", data={"text": text})
        logger.info(f"Added comment to task {task_id}")
        return result

    def add_html_comment(self, task_id: str, html_text: str) -> dict:
        """
        Add a rich HTML comment to a task.

        POST /tasks/{task_gid}/stories

        Args:
            task_id: Task GID
            html_text: Rich HTML content (supports <b>, <i>, <a>, <ul>, etc.)

        Returns:
            Created story object
        """
        result = self._post(f"tasks/{task_id}/stories", data={
            "html_text": html_text,
            "is_pinned": False,
        })
        logger.info(f"Added HTML comment to task {task_id}")
        return result

    def add_agent_update(self, task_id: str, agent_name: str,
                           update_text: str) -> dict:
        """
        Convenience: Add an agent-attributed status update comment.

        Args:
            task_id: Task GID
            agent_name: Agent name
            update_text: Update content
        """
        text = (
            f"[{agent_name} Agent Update - {datetime.now().strftime('%Y-%m-%d %H:%M')}]\n\n"
            f"{update_text}"
        )
        return self.add_comment(task_id, text)

    # ===================================================================
    # 4. MOVE TASKS BETWEEN SECTIONS
    #    Endpoint: POST /sections/{section_gid}/addTask
    #    Autonomy: SAFE -- workflow progression
    # ===================================================================

    def get_sections(self, project_id: str = None) -> list:
        """
        Get all sections in a project.

        GET /projects/{project_gid}/sections

        Returns:
            List of section objects [{gid, name}, ...]
        """
        pid = project_id or self.project_id
        result = self._get(f"projects/{pid}/sections", params={
            "opt_fields": "name,created_at"
        })
        # _request already extracts 'data', but sections endpoint wraps in list
        if isinstance(result, list):
            return result
        return result if isinstance(result, list) else [result] if result else []

    def move_task_to_section(self, task_id: str, section_id: str,
                               insert_before: str = None,
                               insert_after: str = None) -> dict:
        """
        Move a task to a different section within a project.

        POST /sections/{section_gid}/addTask

        Args:
            task_id: Task GID to move
            section_id: Destination section GID
            insert_before: Optional task GID to insert before
            insert_after: Optional task GID to insert after

        Returns:
            Empty on success (200)
        """
        data = {"task": task_id}
        if insert_before:
            data["insert_before"] = insert_before
        if insert_after:
            data["insert_after"] = insert_after

        result = self._post(f"sections/{section_id}/addTask", data=data)
        logger.info(f"Moved task {task_id} to section {section_id}")
        return result

    def move_task_to_section_by_name(self, task_id: str,
                                        section_name: str,
                                        project_id: str = None) -> dict:
        """
        Move a task to a section by name (resolves section GID automatically).

        Args:
            task_id: Task GID
            section_name: Section name (case-insensitive match)
            project_id: Optional project GID

        Returns:
            Empty on success

        Raises:
            ValueError if section not found
        """
        sections = self.get_sections(project_id)
        for section in sections:
            if section.get("name", "").lower() == section_name.lower():
                return self.move_task_to_section(task_id, section["gid"])

        available = [s.get("name", "?") for s in sections]
        raise ValueError(
            f"Section '{section_name}' not found. Available: {available}"
        )

    # ===================================================================
    # 5. PROJECTS
    #    Endpoint: POST /projects
    #    Autonomy: NEEDS APPROVAL -- organizational structure
    # ===================================================================

    def create_project(self, name: str, notes: str = "",
                        layout: str = "board",
                        color: str = "dark-blue",
                        team: str = None) -> dict:
        """
        Create a new project.

        POST /projects

        Args:
            name: Project name
            notes: Project description
            layout: "board" (kanban) or "list"
            color: Project color (dark-blue, dark-green, dark-orange, etc.)
            team: Team GID (required for Organization workspaces)

        Returns:
            Created project object
        """
        project_data = {
            "name": name,
            "workspace": self.workspace_id,
            "default_view": layout,
            "color": color,
        }
        if notes:
            project_data["notes"] = notes
        if team:
            project_data["team"] = team

        result = self._post("projects", data=project_data)
        logger.info(f"Created project '{name}' (GID: {result.get('gid', '?')})")
        return result

    def create_section(self, name: str, project_id: str = None) -> dict:
        """
        Create a section (column in board view) in a project.

        POST /projects/{project_gid}/sections

        Args:
            name: Section name (e.g. "To Do", "In Progress", "Done")
            project_id: Project GID

        Returns:
            Created section object
        """
        pid = project_id or self.project_id
        result = self._post(f"projects/{pid}/sections", data={"name": name})
        logger.info(f"Created section '{name}' in project {pid}")
        return result

    # ===================================================================
    # 6. FILE ATTACHMENTS
    #    Endpoint: POST /tasks/{task_gid}/attachments
    #    Autonomy: SAFE -- attaching reports and analysis outputs
    # ===================================================================

    def attach_file(self, task_id: str, file_path: str,
                     file_name: str = None) -> dict:
        """
        Attach a file to a task.

        POST /tasks/{task_gid}/attachments

        Args:
            task_id: Task GID
            file_path: Local path to file
            file_name: Optional display name (defaults to filename)

        Returns:
            Created attachment object
        """
        path = Path(file_path)
        name = file_name or path.name

        with open(path, "rb") as f:
            result = self._post(
                f"tasks/{task_id}/attachments",
                data={"name": name},
                files={"file": (name, f)},
            )

        logger.info(f"Attached '{name}' to task {task_id}")
        return result

    def attach_text_as_file(self, task_id: str, content: str,
                              file_name: str) -> dict:
        """
        Create a text file and attach it to a task.

        Args:
            task_id: Task GID
            content: Text content
            file_name: File name (e.g. "analysis_report.md")

        Returns:
            Created attachment object
        """
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=Path(file_name).suffix,
                                          delete=False) as f:
            f.write(content)
            temp_path = f.name

        try:
            return self.attach_file(task_id, temp_path, file_name)
        finally:
            os.unlink(temp_path)

    # ===================================================================
    # 7. CUSTOM FIELDS
    #    Endpoint: PUT /tasks/{task_gid} with custom_fields
    #    Autonomy: SAFE -- data enrichment
    # ===================================================================

    def set_custom_fields(self, task_id: str,
                            custom_fields: dict) -> dict:
        """
        Set custom field values on a task.

        PUT /tasks/{task_gid}

        Args:
            task_id: Task GID
            custom_fields: Dict of {custom_field_gid: value}
                For enum fields, value is the enum option GID.
                For text fields, value is a string.
                For number fields, value is a number.

        Returns:
            Updated task object

        Example:
            writer.set_custom_fields("12345", {
                "1234567890": "high",          # text field
                "0987654321": 42,               # number field
                "1111111111": "enum_option_gid", # enum field
            })
        """
        result = self._put(f"tasks/{task_id}", data={
            "custom_fields": custom_fields
        })
        logger.info(f"Set custom fields on task {task_id}: {list(custom_fields.keys())}")
        return result

    # ===================================================================
    # 8. TASK UPDATES
    #    Endpoint: PUT /tasks/{task_gid}
    #    Autonomy: SAFE for most updates
    # ===================================================================

    def update_task(self, task_id: str, **kwargs) -> dict:
        """
        Update any task field.

        PUT /tasks/{task_gid}

        Args:
            task_id: Task GID
            **kwargs: Any task fields to update:
                name, notes, html_notes, due_on, due_at,
                assignee, completed, start_on, liked, etc.

        Returns:
            Updated task object
        """
        result = self._put(f"tasks/{task_id}", data=kwargs)
        logger.info(f"Updated task {task_id}: {list(kwargs.keys())}")
        return result

    def complete_task(self, task_id: str) -> dict:
        """Mark a task as complete."""
        return self.update_task(task_id, completed=True)

    def uncomplete_task(self, task_id: str) -> dict:
        """Mark a task as incomplete."""
        return self.update_task(task_id, completed=False)

    def set_due_date(self, task_id: str, due_on: str) -> dict:
        """Set or update the due date on a task."""
        return self.update_task(task_id, due_on=due_on)

    # ===================================================================
    # CONVENIENCE / BATCH METHODS
    # ===================================================================

    def create_campaign_task_with_checklist(self, campaign_name: str,
                                              launch_date: str,
                                              channel: str = "email",
                                              agent_name: str = "Meridian") -> dict:
        """
        Convenience: Create a campaign task with standard checklist.
        Used by agents to auto-create campaign execution tasks.

        Args:
            campaign_name: Campaign name
            launch_date: Target launch date "YYYY-MM-DD"
            channel: "email", "meta", "social"
            agent_name: Creating agent

        Returns:
            Dict with "task" and "subtasks"
        """
        task = self.create_task_from_agent(
            agent_name=agent_name,
            title=f"Launch: {campaign_name}",
            description=f"Campaign: {campaign_name}\nChannel: {channel}\nTarget date: {launch_date}",
            priority="high",
            due_days=max(0, (datetime.strptime(launch_date, "%Y-%m-%d") - datetime.now()).days),
        )

        checklist_items = {
            "email": [
                "Draft copy using proven patterns",
                "Design creative (brief to Roie)",
                "Build email in Klaviyo",
                "Set up A/B test (subject line)",
                "Review and approve",
                "Schedule send",
                "Monitor performance (24hr check)",
            ],
            "meta": [
                "Select creative assets",
                "Write ad copy (3 variants)",
                "Set targeting and budget",
                "Create campaign in Ads Manager",
                "Review and launch",
                "Monitor ROAS at 24hr mark",
                "Optimize or kill at 48hr mark",
            ],
            "social": [
                "Create content calendar",
                "Design visual assets",
                "Write captions",
                "Schedule posts",
                "Monitor engagement",
            ],
        }

        items = checklist_items.get(channel, checklist_items["email"])
        subtasks = self.create_checklist(task.get("gid", ""), items)

        return {"task": task, "subtasks": subtasks}

    def get_section_map(self, project_id: str = None) -> dict:
        """
        Get a name-to-GID mapping of all sections in a project.

        Returns:
            Dict like {"To Do": "123", "In Progress": "456", "Done": "789"}
        """
        sections = self.get_sections(project_id)
        return {s.get("name", ""): s.get("gid", "") for s in sections if s.get("name")}


# --- CLI ---

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    writer = AsanaWriter()
    if not writer.available:
        print("ASANA_ACCESS_TOKEN required")
        sys.exit(1)

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python asana_writer.py sections")
        print("  python asana_writer.py create-task 'Task name' 'description' [due_date]")
        print("  python asana_writer.py add-comment <task_gid> 'comment text'")
        print("  python asana_writer.py move-task <task_gid> 'Section Name'")
        print("  python asana_writer.py complete <task_gid>")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "sections":
        for name, gid in writer.get_section_map().items():
            print(f"  {gid}: {name}")

    elif cmd == "create-task" and len(sys.argv) >= 3:
        name = sys.argv[2]
        notes = sys.argv[3] if len(sys.argv) > 3 else ""
        due = sys.argv[4] if len(sys.argv) > 4 else None
        result = writer.create_task(name=name, notes=notes, due_on=due, assignee="me")
        print(f"Created: {result.get('name')} (GID: {result.get('gid')})")

    elif cmd == "add-comment" and len(sys.argv) >= 4:
        task_gid = sys.argv[2]
        text = " ".join(sys.argv[3:])
        writer.add_comment(task_gid, text)
        print("Comment added")

    elif cmd == "move-task" and len(sys.argv) >= 4:
        task_gid = sys.argv[2]
        section_name = sys.argv[3]
        writer.move_task_to_section_by_name(task_gid, section_name)
        print(f"Moved to section: {section_name}")

    elif cmd == "complete" and len(sys.argv) >= 3:
        task_gid = sys.argv[2]
        writer.complete_task(task_gid)
        print(f"Task {task_gid} marked complete")

    else:
        print(f"Unknown command: {cmd}")
