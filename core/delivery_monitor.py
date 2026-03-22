#!/usr/bin/env python3
"""
Delivery Monitor — Cross-bot delivery tracking for Tom's Command Center.

Logs every scheduled message delivery (success or failure) to:
1. SQLite delivery_log table (for dashboard queries)
2. Tom's admin Telegram channel (instant visibility)

Works for command center agents AND external bots (tidefix, future bots).

Usage:
    from core.delivery_monitor import log_delivery
    log_delivery("command-center", "Tom", "asclepius-brain", "daily_protocol", "delivered", 12.3)
    log_delivery("tidefix", "Tyler", None, "morning_checkin", "failed", 0.5, error_msg="timeout")
"""

import os
import sqlite3
import logging
import threading
from pathlib import Path
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

NZ_TZ = ZoneInfo("Pacific/Auckland")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "delivery_log.db"

# Thread-local storage for SQLite connections
_local = threading.local()

# Agent -> human-readable recipient mapping
AGENT_RECIPIENTS = {
    "walker-capital": "Trent+Tom",
    "walker-capital-tom": "Tom",
    "walker-capital-trent": "Trent",
    "health-fitness": "Tom",
    "global-events": "Tom",
    "dbh-marketing": "Tom",
    "health-science": "Tom",
    "daily-briefing": "Tom",
    "command-center": "Tom",
    "strategic-advisor": "Tom",
    "evening-reading": "Tom",
    "beacon": "Tom",
    "odysseus-money": "Tom",
    "strategos-pg": "Tom",
    "asclepius-brain": "Tom",
    "marcus-stoic": "Tom",
    "social": "Tom",
    "muse": "Tom",
    "medici": "Tom",
    "prospector": "Tom",
    "scout": "Tom",
}

# Agent -> display name
AGENT_DISPLAY = {
    "walker-capital": "Vesper",
    "health-fitness": "Titan",
    "global-events": "Atlas",
    "dbh-marketing": "Meridian",
    "health-science": "Helix",
    "daily-briefing": "Oracle",
    "command-center": "Nexus",
    "strategic-advisor": "PREP",
    "evening-reading": "ASI",
    "beacon": "Beacon",
    "odysseus-money": "Odysseus",
    "strategos-pg": "Strategos",
    "asclepius-brain": "Asclepius",
    "marcus-stoic": "Marcus",
    "social": "Compass",
    "muse": "Muse",
    "medici": "Medici",
    "prospector": "Prospector",
    "scout": "Scout",
}


def _get_conn():
    if not hasattr(_local, 'conn') or _local.conn is None:
        DATA_DIR.mkdir(exist_ok=True)
        _local.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.executescript("""
            CREATE TABLE IF NOT EXISTS delivery_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_name TEXT NOT NULL,
                recipient TEXT NOT NULL,
                agent TEXT,
                task TEXT NOT NULL,
                status TEXT NOT NULL,
                elapsed_secs REAL,
                error_msg TEXT DEFAULT '',
                delivered_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_delivery_bot
                ON delivery_log(bot_name);
            CREATE INDEX IF NOT EXISTS idx_delivery_time
                ON delivery_log(delivered_at);
        """)
        _local.conn.commit()
    return _local.conn


def log_delivery(bot_name: str, recipient: str, agent: str, task: str,
                 status: str, elapsed_secs: float, error_msg: str = "",
                 notify_admin: bool = True):
    """
    Log a delivery event and optionally notify Tom's admin channel.

    Args:
        bot_name:     'command-center', 'tidefix', etc.
        recipient:    'Tom', 'Tyler', 'Trent+Tom'
        agent:        Agent name or None for external bots
        task:         Task name ('discovery_scan', 'morning_checkin')
        status:       'delivered' or 'failed'
        elapsed_secs: How long the task took
        error_msg:    Error details if failed
        notify_admin: Whether to post to Tom's admin Telegram channel
    """
    # 1. Write to SQLite
    try:
        conn = _get_conn()
        conn.execute(
            """INSERT INTO delivery_log
               (bot_name, recipient, agent, task, status, elapsed_secs, error_msg)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (bot_name, recipient, agent or "", task, status,
             round(elapsed_secs, 1), (error_msg or "")[:300])
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"delivery_log write failed (non-fatal): {e}")

    # 2. Post to Tom's admin channel
    if notify_admin:
        _notify_admin(bot_name, recipient, agent, task, status, elapsed_secs, error_msg)


def _notify_admin(bot_name: str, recipient: str, agent: str, task: str,
                  status: str, elapsed_secs: float, error_msg: str):
    """Post a one-line delivery confirmation to Tom's admin Telegram channel."""
    try:
        import requests

        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        admin_chat_id = os.environ.get("DELIVERY_MONITOR_CHAT_ID", "") or \
                        os.environ.get("ADMIN_CHAT_ID", "")

        if not bot_token or not admin_chat_id:
            return

        display = AGENT_DISPLAY.get(agent, agent or bot_name)
        task_display = task.replace("_", " ")

        if status == "delivered":
            msg = f"[{display}] {recipient}: {task_display} delivered ({elapsed_secs}s)"
        else:
            err = f" — {error_msg[:100]}" if error_msg else ""
            msg = f"[{display}] {recipient}: {task_display} FAILED{err}"

        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={
                "chat_id": admin_chat_id,
                "text": msg,
                "disable_notification": True,
            },
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"Admin notification failed (non-fatal): {e}")


def get_recent_deliveries(hours: int = 24, bot_name: str = None) -> list[dict]:
    """Get recent deliveries for dashboard queries."""
    conn = _get_conn()
    query = """SELECT * FROM delivery_log
               WHERE delivered_at > datetime('now', ?)"""
    params = [f"-{hours} hours"]

    if bot_name:
        query += " AND bot_name = ?"
        params.append(bot_name)

    query += " ORDER BY delivered_at DESC"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_delivery_summary() -> list[dict]:
    """Per-bot, per-recipient summary with last delivery and success rate."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT
            bot_name,
            recipient,
            agent,
            COUNT(*) as total_24h,
            SUM(CASE WHEN status = 'delivered' THEN 1 ELSE 0 END) as delivered_24h,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_24h,
            MAX(CASE WHEN status = 'delivered' THEN delivered_at END) as last_delivered,
            MAX(CASE WHEN status = 'failed' THEN delivered_at END) as last_failed
        FROM delivery_log
        WHERE delivered_at > datetime('now', '-24 hours')
        GROUP BY bot_name, recipient, agent
        ORDER BY bot_name, recipient
    """).fetchall()
    return [dict(r) for r in rows]
