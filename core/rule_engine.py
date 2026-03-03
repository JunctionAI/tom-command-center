#!/usr/bin/env python3
"""
Rule Engine — Automated Asana task creation from business rules.

Runs nightly at 11:30pm (after intelligence_sync and ROAS check).
Checks predefined rules against live data and creates Asana tasks when triggered.

Rate-limiting: won't recreate the same rule-triggered task within 7 days.
"""

import sqlite3
import logging
from datetime import datetime, date, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

NZ_TZ = ZoneInfo("Pacific/Auckland")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
INTELLIGENCE_DB = BASE_DIR / "data" / "intelligence.db"
CUSTOMER_DB = BASE_DIR / "data" / "customer_intelligence.db"


def _get_db() -> sqlite3.Connection:
    """Get intelligence.db with rule tracking table."""
    conn = sqlite3.connect(str(INTELLIGENCE_DB))
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS rule_triggers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id TEXT NOT NULL,
            triggered_at TEXT NOT NULL,
            details TEXT,
            asana_task_id TEXT,
            UNIQUE(rule_id, triggered_at)
        );
        CREATE INDEX IF NOT EXISTS idx_rule_triggers_rule
            ON rule_triggers(rule_id);
    """)
    conn.commit()
    return conn


def _was_recently_triggered(db: sqlite3.Connection, rule_id: str, days: int = 7) -> bool:
    """Check if a rule was triggered within the last N days."""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM rule_triggers WHERE rule_id = ? AND triggered_at >= ?",
        (rule_id, cutoff)
    ).fetchone()
    return (row["cnt"] or 0) > 0


def _record_trigger(db: sqlite3.Connection, rule_id: str, details: str,
                    asana_task_id: str = None):
    """Record that a rule was triggered."""
    db.execute(
        "INSERT OR IGNORE INTO rule_triggers (rule_id, triggered_at, details, asana_task_id) VALUES (?, ?, ?, ?)",
        (rule_id, date.today().isoformat(), details, asana_task_id)
    )
    db.commit()


def _create_asana_task(name: str, notes: str, due_days: int = 3,
                       assignee: str = None) -> str:
    """Create an Asana task. Returns task ID or empty string."""
    try:
        from core.asana_writer import AsanaWriter
        writer = AsanaWriter()
        if not writer.available:
            logger.warning("Asana not available for rule engine task creation")
            return ""

        due_date = (date.today() + timedelta(days=due_days)).isoformat()
        task = writer.create_task(
            name=name,
            notes=notes,
            due_on=due_date,
            assignee=assignee
        )
        return str(task.get("gid", ""))
    except Exception as e:
        logger.error(f"Failed to create Asana task: {e}")
        return ""


# --- Rule Definitions ---

def check_roas_low(db: sqlite3.Connection) -> list:
    """Rule: Meta campaigns with avg ROAS < 2x for 3+ days."""
    results = []
    try:
        idb = sqlite3.connect(str(INTELLIGENCE_DB))
        idb.row_factory = sqlite3.Row

        three_days_ago = (date.today() - timedelta(days=3)).isoformat()
        rows = idb.execute("""
            SELECT campaign_name, AVG(verified_roas) as avg_roas, SUM(meta_spend) as total_spend
            FROM roas_daily
            WHERE date >= ? AND meta_spend > 0
            GROUP BY campaign_name
            HAVING AVG(verified_roas) < 2.0
        """, (three_days_ago,)).fetchall()

        for row in rows:
            rule_id = f"roas_low_{row['campaign_name']}"
            if not _was_recently_triggered(db, rule_id):
                results.append({
                    "rule_id": rule_id,
                    "task_name": f"Review {row['campaign_name']} creative — ROAS below 2x for 3 days",
                    "notes": f"Campaign: {row['campaign_name']}\n3-day avg ROAS: {row['avg_roas']:.2f}x\nTotal spend: ${row['total_spend']:,.2f}\n\nAction: Review creative, test new variant, or pause.",
                    "priority": "urgent",
                    "due_days": 2,
                    "assignee": "Tom",
                })
        idb.close()
    except Exception as e:
        logger.warning(f"ROAS low check failed: {e}")

    return results


def check_cohort_reorder_low(db: sqlite3.Connection) -> list:
    """Rule: 60-day cohort reorder rate below 15%."""
    results = []
    try:
        cdb = sqlite3.connect(str(CUSTOMER_DB))
        cdb.row_factory = sqlite3.Row

        sixty_days_ago = (date.today() - timedelta(days=60)).isoformat()
        thirty_days_ago = (date.today() - timedelta(days=30)).isoformat()

        row = cdb.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN total_orders > 1 THEN 1 ELSE 0 END) as repeaters
            FROM customers
            WHERE first_order_date BETWEEN ? AND ?
        """, (sixty_days_ago, thirty_days_ago)).fetchone()

        if row and row["total"] > 10:
            repeat_rate = (row["repeaters"] / row["total"]) * 100
            if repeat_rate < 15:
                rule_id = "cohort_reorder_low"
                if not _was_recently_triggered(db, rule_id):
                    results.append({
                        "rule_id": rule_id,
                        "task_name": f"Review retention flow — 60-day cohort reorder rate at {repeat_rate:.0f}%",
                        "notes": f"60-day cohort: {row['total']} customers, {row['repeaters']} reordered ({repeat_rate:.1f}%)\nTarget: 15%+\n\nAction: Check post-purchase flows, replenishment timing, and win-back campaigns.",
                        "priority": "medium",
                        "due_days": 5,
                        "assignee": "Tom",
                    })
        cdb.close()
    except Exception as e:
        logger.warning(f"Cohort reorder check failed: {e}")

    return results


def check_email_open_rate_drop(db: sqlite3.Connection) -> list:
    """Rule: Email open rate drops below 40%."""
    results = []
    try:
        from core.data_fetcher import fetch_klaviyo_data
        data = fetch_klaviyo_data(days=7)

        # Look for open rate in the formatted string
        if "open rate" in data.lower() or "open_rate" in data.lower():
            import re
            matches = re.findall(r'(\d+\.?\d*)%?\s*(?:open rate|open_rate)', data.lower())
            if matches:
                open_rate = float(matches[0])
                if open_rate < 40:
                    rule_id = "email_open_rate_low"
                    if not _was_recently_triggered(db, rule_id):
                        results.append({
                            "rule_id": rule_id,
                            "task_name": f"Review email subject line strategy — open rate at {open_rate:.0f}%",
                            "notes": f"Email open rate: {open_rate:.1f}% (below 40% target)\n\nAction: A/B test subject lines, check send timing, review list health.",
                            "priority": "medium",
                            "due_days": 5,
                            "assignee": "Tom",
                        })
    except Exception as e:
        logger.warning(f"Email open rate check failed: {e}")

    return results


# --- Main Runner ---

def run_rule_checks() -> str:
    """
    Run all rule checks and create Asana tasks for triggered rules.
    Returns summary string.
    """
    db = _get_db()

    all_checks = [
        ("ROAS Floor", check_roas_low),
        ("Cohort Reorder", check_cohort_reorder_low),
        ("Email Open Rate", check_email_open_rate_drop),
    ]

    triggered = []

    for check_name, check_fn in all_checks:
        try:
            results = check_fn(db)
            for result in results:
                # Create Asana task
                task_id = _create_asana_task(
                    name=result["task_name"],
                    notes=result["notes"],
                    due_days=result.get("due_days", 3),
                    assignee=result.get("assignee"),
                )

                # Record trigger
                _record_trigger(db, result["rule_id"], result["notes"], task_id)
                triggered.append(f"- [{check_name}] {result['task_name']}")

        except Exception as e:
            logger.error(f"Rule check '{check_name}' crashed: {e}")

    db.close()

    if triggered:
        summary = f"Rule Engine: {len(triggered)} task(s) created\n" + "\n".join(triggered)
        return f"[PRIORITY: IMPORTANT]\n{summary}"

    return "[PRIORITY: INFO]\nRule Engine: all checks passed, no tasks created."


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run_rule_checks())
