#!/usr/bin/env python3
"""
Design Output Tracker -- Tracks designer output, turnaround times,
revision counts, and campaign performance for all creative assets.

Monitors Roie (human designer) and AI-generated content side by side.
Feeds weekly summaries into PREP/Meridian briefings and flags overdue tasks.

Requires:
- data/design_tracking.db (auto-created)
- Links to brief_generator via brief_id (optional)
"""

import os
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "design_tracking.db"

# Valid statuses in order of progression
VALID_STATUSES = ("assigned", "in_progress", "review", "revision", "approved", "live")

# Valid task types
VALID_TASK_TYPES = ("static_ad", "video", "email", "banner", "social")

# Valid platforms for performance metrics
VALID_PLATFORMS = ("meta", "email", "tiktok", "shopify")

# Known designers
KNOWN_DESIGNERS = ("Roie", "AI")


class DesignTracker:
    """Tracks designer output, turnaround, revisions, and campaign performance."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        """Create tables if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS design_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brief_id INTEGER,
                assigned_to TEXT NOT NULL,
                task_type TEXT NOT NULL,
                campaign_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'assigned',
                due_date TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                started_at TEXT,
                first_delivery_at TEXT,
                approved_at TEXT,
                live_at TEXT,
                revision_count INTEGER DEFAULT 0,
                turnaround_hours REAL,
                notes TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS design_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                impressions INTEGER DEFAULT 0,
                clicks INTEGER DEFAULT 0,
                ctr REAL DEFAULT 0.0,
                conversions INTEGER DEFAULT 0,
                roas REAL DEFAULT 0.0,
                spend REAL DEFAULT 0.0,
                revenue REAL DEFAULT 0.0,
                measured_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (task_id) REFERENCES design_tasks(id)
            );

            CREATE TABLE IF NOT EXISTS designer_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                designer_name TEXT NOT NULL,
                period TEXT NOT NULL,
                period_date TEXT NOT NULL,
                tasks_completed INTEGER DEFAULT 0,
                avg_turnaround_hours REAL DEFAULT 0.0,
                avg_revisions REAL DEFAULT 0.0,
                tasks_on_time_pct REAL DEFAULT 0.0,
                total_revenue_generated REAL DEFAULT 0.0
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_status ON design_tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_assigned ON design_tasks(assigned_to);
            CREATE INDEX IF NOT EXISTS idx_tasks_due ON design_tasks(due_date);
            CREATE INDEX IF NOT EXISTS idx_metrics_task ON design_metrics(task_id);
            CREATE INDEX IF NOT EXISTS idx_stats_designer ON designer_stats(designer_name, period);
        """)
        self.conn.commit()

    # --- TASK OPERATIONS ---

    def create_task(self, brief_id: Optional[int], assigned_to: str,
                    task_type: str, campaign_name: str,
                    due_date: Optional[str] = None, notes: str = "") -> int:
        """
        Create a new design task. Returns the task ID.

        Args:
            brief_id: Links to brief_generator (or None)
            assigned_to: Designer name -- 'Roie' or 'AI'
            task_type: One of static_ad, video, email, banner, social
            campaign_name: Human-readable campaign name
            due_date: ISO date string (YYYY-MM-DD) or None
            notes: Optional notes
        """
        if task_type not in VALID_TASK_TYPES:
            raise ValueError(f"Invalid task_type '{task_type}'. Must be one of: {VALID_TASK_TYPES}")

        cursor = self.conn.execute(
            """INSERT INTO design_tasks
               (brief_id, assigned_to, task_type, campaign_name, due_date, notes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (brief_id, assigned_to, task_type, campaign_name, due_date, notes)
        )
        self.conn.commit()
        task_id = cursor.lastrowid
        logger.info(f"Created design task #{task_id}: {campaign_name} -> {assigned_to} ({task_type})")
        return task_id

    def update_task_status(self, task_id: int, new_status: str, notes: str = None) -> dict:
        """
        Update a task's status. Auto-calculates timestamps and turnaround hours.

        Returns the updated task as a dict.
        """
        if new_status not in VALID_STATUSES:
            raise ValueError(f"Invalid status '{new_status}'. Must be one of: {VALID_STATUSES}")

        task = self._get_task(task_id)
        if not task:
            raise ValueError(f"Task #{task_id} not found")

        now = datetime.now().isoformat()
        updates = {"status": new_status}

        # Auto-set timestamps based on status transitions
        if new_status == "in_progress" and not task["started_at"]:
            updates["started_at"] = now

        if new_status == "review" and not task["first_delivery_at"]:
            updates["first_delivery_at"] = now

        if new_status == "revision":
            updates["revision_count"] = (task["revision_count"] or 0) + 1

        if new_status == "approved" and not task["approved_at"]:
            updates["approved_at"] = now

        if new_status == "live":
            updates["live_at"] = now
            # Calculate turnaround: created_at -> live_at
            if task["created_at"]:
                try:
                    created = datetime.fromisoformat(task["created_at"])
                    elapsed = datetime.now() - created
                    updates["turnaround_hours"] = round(elapsed.total_seconds() / 3600, 1)
                except (ValueError, TypeError):
                    pass

        if notes:
            existing_notes = task["notes"] or ""
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            updates["notes"] = f"{existing_notes}\n[{timestamp}] {notes}".strip()

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [task_id]

        self.conn.execute(
            f"UPDATE design_tasks SET {set_clause} WHERE id = ?",
            values
        )
        self.conn.commit()

        updated = self._get_task(task_id)
        logger.info(f"Task #{task_id} status -> {new_status}")
        return dict(updated)

    def _get_task(self, task_id: int) -> Optional[sqlite3.Row]:
        """Fetch a single task by ID."""
        return self.conn.execute(
            "SELECT * FROM design_tasks WHERE id = ?", (task_id,)
        ).fetchone()

    def get_task(self, task_id: int) -> Optional[dict]:
        """Public accessor for a single task."""
        row = self._get_task(task_id)
        return dict(row) if row else None

    # --- PERFORMANCE METRICS ---

    def log_performance(self, task_id: int, platform: str, metrics_dict: dict) -> int:
        """
        Log campaign performance metrics for a design task.

        Args:
            task_id: The design task ID
            platform: One of meta, email, tiktok, shopify
            metrics_dict: Dict with keys like impressions, clicks, ctr, conversions, roas, spend, revenue
        Returns:
            The metric record ID
        """
        if platform not in VALID_PLATFORMS:
            raise ValueError(f"Invalid platform '{platform}'. Must be one of: {VALID_PLATFORMS}")

        task = self._get_task(task_id)
        if not task:
            raise ValueError(f"Task #{task_id} not found")

        cursor = self.conn.execute(
            """INSERT INTO design_metrics
               (task_id, platform, impressions, clicks, ctr, conversions, roas, spend, revenue)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task_id,
                platform,
                metrics_dict.get("impressions", 0),
                metrics_dict.get("clicks", 0),
                metrics_dict.get("ctr", 0.0),
                metrics_dict.get("conversions", 0),
                metrics_dict.get("roas", 0.0),
                metrics_dict.get("spend", 0.0),
                metrics_dict.get("revenue", 0.0),
            )
        )
        self.conn.commit()
        logger.info(f"Logged {platform} metrics for task #{task_id}")
        return cursor.lastrowid

    # --- DESIGNER SUMMARIES ---

    def get_designer_summary(self, designer_name: str, period: str = "weekly",
                             days: int = None) -> dict:
        """
        Return productivity stats for a designer over a given period.

        Args:
            designer_name: 'Roie' or 'AI'
            period: 'daily', 'weekly', or 'monthly'
            days: Override lookback window (default: 1/7/30 based on period)
        """
        if days is None:
            days = {"daily": 1, "weekly": 7, "monthly": 30}.get(period, 7)

        since = (datetime.now() - timedelta(days=days)).isoformat()

        # Tasks completed (status = approved or live)
        completed = self.conn.execute(
            """SELECT COUNT(*) FROM design_tasks
               WHERE assigned_to = ? AND status IN ('approved', 'live')
               AND (approved_at >= ? OR live_at >= ?)""",
            (designer_name, since, since)
        ).fetchone()[0]

        # Average turnaround
        avg_turnaround = self.conn.execute(
            """SELECT AVG(turnaround_hours) FROM design_tasks
               WHERE assigned_to = ? AND turnaround_hours IS NOT NULL
               AND live_at >= ?""",
            (designer_name, since)
        ).fetchone()[0] or 0.0

        # Average revisions
        avg_revisions = self.conn.execute(
            """SELECT AVG(revision_count) FROM design_tasks
               WHERE assigned_to = ? AND status IN ('approved', 'live')
               AND (approved_at >= ? OR live_at >= ?)""",
            (designer_name, since, since)
        ).fetchone()[0] or 0.0

        # On-time percentage (approved or live before due_date)
        tasks_with_due = self.conn.execute(
            """SELECT COUNT(*) FROM design_tasks
               WHERE assigned_to = ? AND due_date IS NOT NULL
               AND status IN ('approved', 'live')
               AND (approved_at >= ? OR live_at >= ?)""",
            (designer_name, since, since)
        ).fetchone()[0]

        on_time = 0
        if tasks_with_due > 0:
            on_time = self.conn.execute(
                """SELECT COUNT(*) FROM design_tasks
                   WHERE assigned_to = ? AND due_date IS NOT NULL
                   AND status IN ('approved', 'live')
                   AND (approved_at >= ? OR live_at >= ?)
                   AND (
                       (approved_at IS NOT NULL AND approved_at <= due_date || 'T23:59:59')
                       OR (live_at IS NOT NULL AND live_at <= due_date || 'T23:59:59')
                   )""",
                (designer_name, since, since)
            ).fetchone()[0]

        on_time_pct = (on_time / tasks_with_due * 100) if tasks_with_due > 0 else 0.0

        # Total revenue generated from designs that went live
        revenue = self.conn.execute(
            """SELECT COALESCE(SUM(dm.revenue), 0) FROM design_metrics dm
               JOIN design_tasks dt ON dm.task_id = dt.id
               WHERE dt.assigned_to = ? AND dt.live_at >= ?""",
            (designer_name, since)
        ).fetchone()[0] or 0.0

        # All tasks in period (any status)
        total_assigned = self.conn.execute(
            """SELECT COUNT(*) FROM design_tasks
               WHERE assigned_to = ? AND created_at >= ?""",
            (designer_name, since)
        ).fetchone()[0]

        summary = {
            "designer": designer_name,
            "period": period,
            "days": days,
            "tasks_assigned": total_assigned,
            "tasks_completed": completed,
            "avg_turnaround_hours": round(avg_turnaround, 1),
            "avg_revisions": round(avg_revisions, 1),
            "on_time_pct": round(on_time_pct, 1),
            "total_revenue": round(revenue, 2),
        }

        # Persist to designer_stats
        self.conn.execute(
            """INSERT INTO designer_stats
               (designer_name, period, period_date, tasks_completed,
                avg_turnaround_hours, avg_revisions, tasks_on_time_pct,
                total_revenue_generated)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                designer_name, period, datetime.now().strftime("%Y-%m-%d"),
                completed, avg_turnaround, avg_revisions, on_time_pct, revenue
            )
        )
        self.conn.commit()

        return summary

    # --- AI vs HUMAN COMPARISON ---

    def get_ai_vs_human_comparison(self, days: int = 30) -> dict:
        """
        Compare AI-generated vs human-designed (Roie) creative performance.

        Returns a dict with side-by-side stats for both designers.
        """
        since = (datetime.now() - timedelta(days=days)).isoformat()

        comparison = {}
        for designer in KNOWN_DESIGNERS:
            # Task stats
            tasks = self.conn.execute(
                """SELECT COUNT(*) as total,
                          SUM(CASE WHEN status IN ('approved', 'live') THEN 1 ELSE 0 END) as completed,
                          AVG(turnaround_hours) as avg_turnaround,
                          AVG(revision_count) as avg_revisions
                   FROM design_tasks
                   WHERE assigned_to = ? AND created_at >= ?""",
                (designer, since)
            ).fetchone()

            # Performance metrics (averaged across all live designs)
            perf = self.conn.execute(
                """SELECT AVG(dm.ctr) as avg_ctr,
                          AVG(dm.roas) as avg_roas,
                          SUM(dm.revenue) as total_revenue,
                          SUM(dm.spend) as total_spend,
                          SUM(dm.conversions) as total_conversions
                   FROM design_metrics dm
                   JOIN design_tasks dt ON dm.task_id = dt.id
                   WHERE dt.assigned_to = ? AND dt.created_at >= ?""",
                (designer, since)
            ).fetchone()

            comparison[designer] = {
                "tasks_total": tasks["total"] or 0,
                "tasks_completed": tasks["completed"] or 0,
                "avg_turnaround_hours": round(tasks["avg_turnaround"] or 0, 1),
                "avg_revisions": round(tasks["avg_revisions"] or 0, 1),
                "avg_ctr": round(perf["avg_ctr"] or 0, 2),
                "avg_roas": round(perf["avg_roas"] or 0, 2),
                "total_revenue": round(perf["total_revenue"] or 0, 2),
                "total_spend": round(perf["total_spend"] or 0, 2),
                "total_conversions": perf["total_conversions"] or 0,
            }

        return {
            "period_days": days,
            "since": since[:10],
            "designers": comparison,
        }

    # --- OVERDUE DETECTION ---

    def get_overdue_tasks(self) -> list:
        """
        Find tasks past their due_date that have not reached approved/live status.
        """
        now = datetime.now().strftime("%Y-%m-%d")
        rows = self.conn.execute(
            """SELECT * FROM design_tasks
               WHERE due_date IS NOT NULL
               AND due_date < ?
               AND status NOT IN ('approved', 'live')
               ORDER BY due_date ASC""",
            (now,)
        ).fetchall()
        return [dict(r) for r in rows]

    # --- PIPELINE STATUS ---

    def format_design_pipeline_status(self) -> str:
        """
        Current pipeline status -- what's assigned, in review, overdue.
        Formatted text suitable for PREP/Meridian briefing injection.
        """
        lines = ["DESIGN PIPELINE STATUS"]
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M NZST')}")
        lines.append("")

        # Tasks by status
        for status in VALID_STATUSES:
            tasks = self.conn.execute(
                """SELECT id, campaign_name, assigned_to, task_type, due_date, revision_count
                   FROM design_tasks WHERE status = ?
                   ORDER BY due_date ASC NULLS LAST""",
                (status,)
            ).fetchall()

            if tasks:
                label = status.upper().replace("_", " ")
                lines.append(f"  {label} ({len(tasks)}):")
                for t in tasks:
                    due_str = f" | due {t['due_date']}" if t["due_date"] else ""
                    rev_str = f" | {t['revision_count']}x revised" if t["revision_count"] else ""
                    lines.append(
                        f"    #{t['id']} {t['campaign_name']} "
                        f"[{t['task_type']}] -> {t['assigned_to']}{due_str}{rev_str}"
                    )
                lines.append("")

        # Overdue tasks (flagged prominently)
        overdue = self.get_overdue_tasks()
        if overdue:
            lines.append(f"  ** OVERDUE ({len(overdue)}) **:")
            for t in overdue:
                days_late = (datetime.now() - datetime.strptime(t["due_date"], "%Y-%m-%d")).days
                lines.append(
                    f"    #{t['id']} {t['campaign_name']} "
                    f"[{t['task_type']}] -> {t['assigned_to']} "
                    f"| {days_late}d late (due {t['due_date']}) | status: {t['status']}"
                )
            lines.append("")

        # Summary counts
        total = self.conn.execute("SELECT COUNT(*) FROM design_tasks").fetchone()[0]
        active = self.conn.execute(
            "SELECT COUNT(*) FROM design_tasks WHERE status NOT IN ('approved', 'live')"
        ).fetchone()[0]
        completed = total - active

        lines.append(f"  TOTALS: {total} tasks ({active} active, {completed} completed)")

        # Per-designer load
        designer_load = self.conn.execute(
            """SELECT assigned_to, COUNT(*) as cnt
               FROM design_tasks WHERE status NOT IN ('approved', 'live')
               GROUP BY assigned_to"""
        ).fetchall()
        if designer_load:
            load_parts = [f"{r['assigned_to']}: {r['cnt']} active" for r in designer_load]
            lines.append(f"  WORKLOAD: {' | '.join(load_parts)}")

        return "\n".join(lines)

    # --- WEEKLY REPORT ---

    def generate_weekly_report(self) -> str:
        """
        Formatted weekly report text for PREP/Meridian briefing injection.
        Covers the last 7 days of design activity and performance.
        """
        lines = ["WEEKLY DESIGN OUTPUT REPORT"]
        lines.append(f"Period: {(datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')} to {datetime.now().strftime('%Y-%m-%d')}")
        lines.append("")

        since = (datetime.now() - timedelta(days=7)).isoformat()

        # Tasks created this week
        created = self.conn.execute(
            "SELECT COUNT(*) FROM design_tasks WHERE created_at >= ?",
            (since,)
        ).fetchone()[0]

        # Tasks completed this week
        completed = self.conn.execute(
            """SELECT COUNT(*) FROM design_tasks
               WHERE status IN ('approved', 'live')
               AND (approved_at >= ? OR live_at >= ?)""",
            (since, since)
        ).fetchone()[0]

        # Tasks that went live
        went_live = self.conn.execute(
            "SELECT COUNT(*) FROM design_tasks WHERE live_at >= ?",
            (since,)
        ).fetchone()[0]

        lines.append(f"  Created: {created} | Completed: {completed} | Went live: {went_live}")
        lines.append("")

        # Per-designer breakdown
        lines.append("  DESIGNER BREAKDOWN:")
        for designer in KNOWN_DESIGNERS:
            summary = self.get_designer_summary(designer, "weekly")
            lines.append(f"    {designer}:")
            lines.append(f"      Assigned: {summary['tasks_assigned']} | Completed: {summary['tasks_completed']}")
            if summary["avg_turnaround_hours"] > 0:
                lines.append(f"      Avg turnaround: {summary['avg_turnaround_hours']}h")
            if summary["avg_revisions"] > 0:
                lines.append(f"      Avg revisions: {summary['avg_revisions']}")
            if summary["on_time_pct"] > 0:
                lines.append(f"      On-time: {summary['on_time_pct']}%")
            if summary["total_revenue"] > 0:
                lines.append(f"      Revenue generated: ${summary['total_revenue']:,.2f}")
        lines.append("")

        # AI vs Human comparison
        comparison = self.get_ai_vs_human_comparison(days=7)
        ai = comparison["designers"].get("AI", {})
        human = comparison["designers"].get("Roie", {})

        if ai.get("tasks_total", 0) > 0 and human.get("tasks_total", 0) > 0:
            lines.append("  AI vs HUMAN (This Week):")
            lines.append(f"    {'Metric':<25s} {'AI':>10s} {'Roie':>10s}")
            lines.append(f"    {'-' * 47}")
            lines.append(f"    {'Tasks completed':<25s} {ai['tasks_completed']:>10d} {human['tasks_completed']:>10d}")
            lines.append(f"    {'Avg turnaround (hrs)':<25s} {ai['avg_turnaround_hours']:>10.1f} {human['avg_turnaround_hours']:>10.1f}")
            lines.append(f"    {'Avg revisions':<25s} {ai['avg_revisions']:>10.1f} {human['avg_revisions']:>10.1f}")
            lines.append(f"    {'Avg CTR':<25s} {ai['avg_ctr']:>9.2f}% {human['avg_ctr']:>9.2f}%")
            lines.append(f"    {'Avg ROAS':<25s} {ai['avg_roas']:>10.2f} {human['avg_roas']:>10.2f}")
            lines.append(f"    {'Total revenue':<25s} ${ai['total_revenue']:>9,.2f} ${human['total_revenue']:>9,.2f}")
            lines.append("")

        # Top performing designs this week
        top_designs = self.conn.execute(
            """SELECT dt.campaign_name, dt.assigned_to, dt.task_type,
                      dm.platform, dm.roas, dm.revenue, dm.ctr
               FROM design_metrics dm
               JOIN design_tasks dt ON dm.task_id = dt.id
               WHERE dm.measured_at >= ?
               ORDER BY dm.roas DESC LIMIT 5""",
            (since,)
        ).fetchall()

        if top_designs:
            lines.append("  TOP PERFORMING DESIGNS:")
            for d in top_designs:
                lines.append(
                    f"    {d['campaign_name']} [{d['task_type']}] by {d['assigned_to']} "
                    f"on {d['platform']}: {d['roas']:.2f}x ROAS, ${d['revenue']:,.2f} rev, "
                    f"{d['ctr']:.2f}% CTR"
                )
            lines.append("")

        # Overdue warning
        overdue = self.get_overdue_tasks()
        if overdue:
            lines.append(f"  WARNING: {len(overdue)} OVERDUE TASK(S):")
            for t in overdue:
                days_late = (datetime.now() - datetime.strptime(t["due_date"], "%Y-%m-%d")).days
                lines.append(
                    f"    #{t['id']} {t['campaign_name']} -> {t['assigned_to']} "
                    f"({days_late}d late)"
                )
            lines.append("")

        # Pipeline snapshot
        lines.append("  PIPELINE SNAPSHOT:")
        for status in VALID_STATUSES:
            count = self.conn.execute(
                "SELECT COUNT(*) FROM design_tasks WHERE status = ?",
                (status,)
            ).fetchone()[0]
            if count > 0:
                label = status.upper().replace("_", " ")
                lines.append(f"    {label}: {count}")

        return "\n".join(lines)

    # --- BRIEFING FORMAT ---

    def format_for_briefing(self) -> str:
        """
        Short-form pipeline + overdue summary suitable for injection
        into the daily Meridian or Oracle briefing.
        """
        overdue = self.get_overdue_tasks()
        active = self.conn.execute(
            """SELECT COUNT(*) FROM design_tasks
               WHERE status NOT IN ('approved', 'live')"""
        ).fetchone()[0]

        in_review = self.conn.execute(
            "SELECT COUNT(*) FROM design_tasks WHERE status = 'review'"
        ).fetchone()[0]

        lines = []
        if active > 0 or overdue:
            lines.append(f"DESIGN PIPELINE: {active} active tasks, {in_review} in review")

            if overdue:
                lines.append(f"  OVERDUE ({len(overdue)}):")
                for t in overdue:
                    days_late = (datetime.now() - datetime.strptime(t["due_date"], "%Y-%m-%d")).days
                    lines.append(
                        f"    #{t['id']} {t['campaign_name']} -> {t['assigned_to']} ({days_late}d late)"
                    )

            # Next due tasks
            upcoming = self.conn.execute(
                """SELECT id, campaign_name, assigned_to, due_date, status
                   FROM design_tasks
                   WHERE status NOT IN ('approved', 'live')
                   AND due_date IS NOT NULL
                   AND due_date >= ?
                   ORDER BY due_date ASC LIMIT 3""",
                (datetime.now().strftime("%Y-%m-%d"),)
            ).fetchall()

            if upcoming:
                lines.append("  UPCOMING DUE:")
                for t in upcoming:
                    lines.append(
                        f"    #{t['id']} {t['campaign_name']} -> {t['assigned_to']} "
                        f"due {t['due_date']} ({t['status']})"
                    )

        return "\n".join(lines)

    def close(self):
        """Close the database connection."""
        self.conn.close()


# --- CLI ---

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    tracker = DesignTracker()

    def print_help():
        print("Design Output Tracker CLI")
        print("=" * 50)
        print()
        print("Commands:")
        print("  python design_tracker.py init                                 -- Initialise database")
        print("  python design_tracker.py add <assigned_to> <type> <campaign> [due_date]  -- Create task")
        print("  python design_tracker.py status <task_id> <new_status> [notes]           -- Update status")
        print("  python design_tracker.py log <task_id> <platform> <json_metrics>         -- Log performance")
        print("  python design_tracker.py pipeline                             -- Show pipeline status")
        print("  python design_tracker.py report                               -- Weekly report")
        print("  python design_tracker.py summary <designer> [period]          -- Designer summary")
        print("  python design_tracker.py compare                              -- AI vs Human comparison")
        print("  python design_tracker.py overdue                              -- List overdue tasks")
        print("  python design_tracker.py briefing                             -- Short briefing format")
        print("  python design_tracker.py task <task_id>                       -- View single task")
        print("  python design_tracker.py list [assigned_to]                   -- List all/filtered tasks")
        print("  python design_tracker.py stats                                -- Database row counts")
        print()
        print("Task types: static_ad, video, email, banner, social")
        print("Statuses:   assigned, in_progress, review, revision, approved, live")
        print("Platforms:  meta, email, tiktok, shopify")
        print("Designers:  Roie, AI")
        print()
        print("Examples:")
        print('  python design_tracker.py add Roie static_ad "GLM March Sale" 2026-03-10')
        print('  python design_tracker.py add AI email "Replenishment Flow v2"')
        print("  python design_tracker.py status 1 in_progress")
        print('  python design_tracker.py status 1 review "First draft delivered"')
        print('  python design_tracker.py log 1 meta \'{"impressions":15000,"clicks":450,"ctr":3.0,"roas":4.2,"spend":200,"revenue":840}\'')

    if len(sys.argv) < 2:
        print_help()
        tracker.close()
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "init":
        print(f"Database initialised at: {DB_PATH}")
        print("Tables: design_tasks, design_metrics, designer_stats")

    elif cmd == "add":
        if len(sys.argv) < 5:
            print("Usage: python design_tracker.py add <assigned_to> <type> <campaign> [due_date]")
            print(f"  Types: {', '.join(VALID_TASK_TYPES)}")
            print(f"  Designers: {', '.join(KNOWN_DESIGNERS)}")
        else:
            assigned = sys.argv[2]
            task_type = sys.argv[3]
            campaign = sys.argv[4]
            due = sys.argv[5] if len(sys.argv) > 5 else None
            try:
                task_id = tracker.create_task(None, assigned, task_type, campaign, due)
                print(f"Created task #{task_id}: {campaign} -> {assigned} ({task_type})")
                if due:
                    print(f"  Due: {due}")
            except ValueError as e:
                print(f"Error: {e}")

    elif cmd == "status":
        if len(sys.argv) < 4:
            print("Usage: python design_tracker.py status <task_id> <new_status> [notes]")
            print(f"  Statuses: {', '.join(VALID_STATUSES)}")
        else:
            task_id = int(sys.argv[2])
            new_status = sys.argv[3]
            notes = sys.argv[4] if len(sys.argv) > 4 else None
            try:
                updated = tracker.update_task_status(task_id, new_status, notes)
                print(f"Task #{task_id} -> {new_status}")
                if updated.get("turnaround_hours"):
                    print(f"  Turnaround: {updated['turnaround_hours']}h")
                if updated.get("revision_count"):
                    print(f"  Revisions: {updated['revision_count']}")
            except ValueError as e:
                print(f"Error: {e}")

    elif cmd == "log":
        if len(sys.argv) < 5:
            print("Usage: python design_tracker.py log <task_id> <platform> <json_metrics>")
            print(f"  Platforms: {', '.join(VALID_PLATFORMS)}")
            print('  Metrics JSON: {"impressions":0,"clicks":0,"ctr":0,"conversions":0,"roas":0,"spend":0,"revenue":0}')
        else:
            task_id = int(sys.argv[2])
            platform = sys.argv[3]
            try:
                metrics = json.loads(sys.argv[4])
                metric_id = tracker.log_performance(task_id, platform, metrics)
                print(f"Logged {platform} metrics (record #{metric_id}) for task #{task_id}")
                if metrics.get("roas"):
                    print(f"  ROAS: {metrics['roas']}x | Revenue: ${metrics.get('revenue', 0):,.2f}")
            except json.JSONDecodeError:
                print("Error: metrics must be valid JSON")
            except ValueError as e:
                print(f"Error: {e}")

    elif cmd == "pipeline":
        print(tracker.format_design_pipeline_status())

    elif cmd == "report":
        print(tracker.generate_weekly_report())

    elif cmd == "summary":
        if len(sys.argv) < 3:
            print("Usage: python design_tracker.py summary <designer> [period]")
            print(f"  Designers: {', '.join(KNOWN_DESIGNERS)}")
            print("  Periods: daily, weekly, monthly")
        else:
            designer = sys.argv[2]
            period = sys.argv[3] if len(sys.argv) > 3 else "weekly"
            summary = tracker.get_designer_summary(designer, period)
            print(f"Designer Summary: {designer} ({period})")
            print(f"  Tasks assigned:    {summary['tasks_assigned']}")
            print(f"  Tasks completed:   {summary['tasks_completed']}")
            print(f"  Avg turnaround:    {summary['avg_turnaround_hours']}h")
            print(f"  Avg revisions:     {summary['avg_revisions']}")
            print(f"  On-time:           {summary['on_time_pct']}%")
            print(f"  Revenue generated: ${summary['total_revenue']:,.2f}")

    elif cmd == "compare":
        comp = tracker.get_ai_vs_human_comparison()
        print(f"AI vs Human Design Comparison (last {comp['period_days']} days)")
        print(f"Since: {comp['since']}")
        print()
        print(f"  {'Metric':<25s} {'AI':>10s} {'Roie':>10s}")
        print(f"  {'-' * 47}")
        ai = comp["designers"].get("AI", {})
        human = comp["designers"].get("Roie", {})
        print(f"  {'Tasks total':<25s} {ai.get('tasks_total', 0):>10d} {human.get('tasks_total', 0):>10d}")
        print(f"  {'Tasks completed':<25s} {ai.get('tasks_completed', 0):>10d} {human.get('tasks_completed', 0):>10d}")
        print(f"  {'Avg turnaround (hrs)':<25s} {ai.get('avg_turnaround_hours', 0):>10.1f} {human.get('avg_turnaround_hours', 0):>10.1f}")
        print(f"  {'Avg revisions':<25s} {ai.get('avg_revisions', 0):>10.1f} {human.get('avg_revisions', 0):>10.1f}")
        print(f"  {'Avg CTR %':<25s} {ai.get('avg_ctr', 0):>10.2f} {human.get('avg_ctr', 0):>10.2f}")
        print(f"  {'Avg ROAS':<25s} {ai.get('avg_roas', 0):>10.2f} {human.get('avg_roas', 0):>10.2f}")
        print(f"  {'Total revenue':<25s} ${ai.get('total_revenue', 0):>9,.2f} ${human.get('total_revenue', 0):>9,.2f}")
        print(f"  {'Total spend':<25s} ${ai.get('total_spend', 0):>9,.2f} ${human.get('total_spend', 0):>9,.2f}")
        print(f"  {'Conversions':<25s} {ai.get('total_conversions', 0):>10d} {human.get('total_conversions', 0):>10d}")

    elif cmd == "overdue":
        overdue = tracker.get_overdue_tasks()
        if overdue:
            print(f"OVERDUE TASKS ({len(overdue)}):")
            for t in overdue:
                days_late = (datetime.now() - datetime.strptime(t["due_date"], "%Y-%m-%d")).days
                print(
                    f"  #{t['id']} {t['campaign_name']} [{t['task_type']}] -> {t['assigned_to']} "
                    f"| {days_late}d late (due {t['due_date']}) | status: {t['status']}"
                )
        else:
            print("No overdue tasks.")

    elif cmd == "briefing":
        output = tracker.format_for_briefing()
        if output:
            print(output)
        else:
            print("No active design tasks to report.")

    elif cmd == "task":
        if len(sys.argv) < 3:
            print("Usage: python design_tracker.py task <task_id>")
        else:
            task_id = int(sys.argv[2])
            task = tracker.get_task(task_id)
            if task:
                print(f"Task #{task['id']}: {task['campaign_name']}")
                print(f"  Type:       {task['task_type']}")
                print(f"  Assigned:   {task['assigned_to']}")
                print(f"  Status:     {task['status']}")
                print(f"  Due:        {task['due_date'] or 'None'}")
                print(f"  Created:    {task['created_at']}")
                print(f"  Started:    {task['started_at'] or '-'}")
                print(f"  Delivered:  {task['first_delivery_at'] or '-'}")
                print(f"  Approved:   {task['approved_at'] or '-'}")
                print(f"  Live:       {task['live_at'] or '-'}")
                print(f"  Revisions:  {task['revision_count']}")
                print(f"  Turnaround: {task['turnaround_hours'] or '-'}h")
                print(f"  Brief ID:   {task['brief_id'] or 'None'}")
                if task["notes"]:
                    print(f"  Notes:\n    {task['notes']}")

                # Show associated metrics
                metrics = tracker.conn.execute(
                    "SELECT * FROM design_metrics WHERE task_id = ? ORDER BY measured_at DESC",
                    (task_id,)
                ).fetchall()
                if metrics:
                    print(f"\n  Performance Metrics ({len(metrics)} records):")
                    for m in metrics:
                        print(
                            f"    [{m['platform']}] {m['measured_at'][:10]}: "
                            f"ROAS {m['roas']:.2f}x | ${m['revenue']:,.2f} rev | "
                            f"{m['ctr']:.2f}% CTR | {m['conversions']} conv"
                        )
            else:
                print(f"Task #{task_id} not found.")

    elif cmd == "list":
        assigned_filter = sys.argv[2] if len(sys.argv) > 2 else None
        if assigned_filter:
            tasks = tracker.conn.execute(
                "SELECT * FROM design_tasks WHERE assigned_to = ? ORDER BY created_at DESC",
                (assigned_filter,)
            ).fetchall()
            print(f"Tasks assigned to {assigned_filter} ({len(tasks)}):")
        else:
            tasks = tracker.conn.execute(
                "SELECT * FROM design_tasks ORDER BY created_at DESC"
            ).fetchall()
            print(f"All design tasks ({len(tasks)}):")

        for t in tasks:
            due_str = f" | due {t['due_date']}" if t["due_date"] else ""
            print(
                f"  #{t['id']} [{t['status']:<12s}] {t['campaign_name']}"
                f" [{t['task_type']}] -> {t['assigned_to']}{due_str}"
            )

    elif cmd == "stats":
        for table in ("design_tasks", "design_metrics", "designer_stats"):
            count = tracker.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:20s}: {count:>6d} rows")

    else:
        print(f"Unknown command: {cmd}")
        print()
        print_help()

    tracker.close()
