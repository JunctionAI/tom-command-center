#!/usr/bin/env python3
"""
Snapshot Reporter -- Format snapshot data for agent briefings.

Instead of agents pulling rolling API data, they read yesterday's locked snapshot.
This ensures all agents see the same ground truth for that day.
"""

import os
import sqlite3
import json
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

NZ_TZ = ZoneInfo("Pacific/Auckland")


def get_snapshots_db():
    """Open customer_intelligence.db with snapshots table."""
    db_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "data",
        "customer_intelligence.db"
    )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_yesterday_snapshot() -> dict:
    """Get yesterday's locked snapshot (YYYY-MM-DD format)."""
    now_nz = datetime.now(NZ_TZ)
    yesterday = now_nz - timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d")

    db = get_snapshots_db()
    try:
        row = db.execute(
            "SELECT * FROM daily_snapshots WHERE date = ?",
            (yesterday_str,)
        ).fetchone()

        if row:
            return dict(row)
        return None
    finally:
        db.close()


def format_snapshot_briefing(snapshot: dict) -> str:
    """
    Format snapshot data for agent briefing.
    Returns a clean text report ready for agent analysis.
    """
    if not snapshot:
        return ""

    day_label = snapshot["date"]
    revenue = float(snapshot["revenue"])
    order_count = snapshot["order_count"]
    new_customers = snapshot["new_customers"]
    returning = snapshot["returning_customers"]
    repeat_rate = float(snapshot["repeat_rate"]) if snapshot["repeat_rate"] else 0

    # Parse channel breakdown if it's JSON
    channel_breakdown = {}
    if snapshot.get("channel_breakdown"):
        if isinstance(snapshot["channel_breakdown"], str):
            try:
                channel_breakdown = json.loads(snapshot["channel_breakdown"])
            except:
                pass
        else:
            channel_breakdown = snapshot["channel_breakdown"]

    # Parse shopify_data for additional context
    shopify_data = {}
    if snapshot.get("shopify_data"):
        if isinstance(snapshot["shopify_data"], str):
            try:
                shopify_data = json.loads(snapshot["shopify_data"])
            except:
                pass
        else:
            shopify_data = snapshot["shopify_data"]

    # Build the report
    lines = [
        f"=== DAILY SNAPSHOT (LOCKED) -- {day_label} ===",
        f"Captured at: {snapshot['captured_at']}",
        f"",
        f"REVENUE: ${revenue:.2f}",
        f"Orders: {order_count}",
        f"Customers: {new_customers} new, {returning} returning",
        f"Repeat rate: {repeat_rate:.1%}",
    ]

    # Channel breakdown (if available)
    if channel_breakdown:
        lines.append(f"")
        lines.append(f"CHANNEL BREAKDOWN:")
        for channel, amount in channel_breakdown.items():
            lines.append(f"  {channel}: ${amount:.2f}")

    # Meta spend (if tracked)
    if snapshot.get("meta_spend"):
        meta_spend = float(snapshot["meta_spend"])
        meta_conversions = int(snapshot.get("meta_conversions", 0))
        meta_roas = float(snapshot.get("meta_roas", 0))
        lines.append(f"")
        lines.append(f"META ADS:")
        lines.append(f"  Spend: ${meta_spend:.2f}")
        lines.append(f"  Conversions: {meta_conversions}")
        if meta_roas > 0:
            lines.append(f"  ROAS: {meta_roas:.2f}x")

    # Shopify API status
    if shopify_data and shopify_data.get("api_status") == "success":
        lines.append(f"")
        lines.append(f"Data Status: ✓ Verified from Shopify API")

    # Notes if any
    if snapshot.get("notes"):
        lines.append(f"")
        lines.append(f"Notes: {snapshot['notes']}")

    lines.append(f"")
    lines.append(
        "This is a LOCKED snapshot. All agents see the same figures for this date."
    )

    return "\n".join(lines)


def inject_snapshot_data(agent_name: str, task_name: str) -> str:
    """
    Get yesterday's snapshot and format it for agent briefing.
    Returns formatted text ready to inject into task_prompt.
    If no snapshot exists yet, returns empty string (fallback to live API).
    """

    # Only inject snapshots for briefing tasks
    relevant_tasks = ("morning_briefing", "morning_brief", "weekly_review")
    relevant_agents = ("daily-briefing", "dbh-marketing", "strategic-advisor")

    if task_name not in relevant_tasks or agent_name not in relevant_agents:
        return ""

    snapshot = get_yesterday_snapshot()
    if not snapshot:
        return ""  # No snapshot yet, fallback to live API

    formatted = format_snapshot_briefing(snapshot)
    return formatted


if __name__ == "__main__":
    # Test: print yesterday's snapshot
    snapshot = get_yesterday_snapshot()
    if snapshot:
        print(format_snapshot_briefing(snapshot))
    else:
        print("No snapshot found for yesterday")
