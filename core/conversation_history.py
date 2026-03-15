"""
Conversation History -- Persistent multi-turn memory for agents.

Stores Tom's messages and agent responses in SQLite so agents can
maintain conversational context across API calls.

Each agent/chat pair has its own conversation thread.
Recent messages are loaded into the Claude API messages array,
giving agents true multi-turn memory.
"""

import sqlite3
import logging
import os
from pathlib import Path
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

NZ_TZ = ZoneInfo("Pacific/Auckland")

logger = logging.getLogger("orchestrator")

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "conversation_history.db"

_db = None


def get_db() -> sqlite3.Connection:
    """Get or create the conversation history database."""
    global _db
    if _db is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _db = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _db.row_factory = sqlite3.Row
        _db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        _db.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_agent_chat
            ON messages(agent, chat_id, created_at DESC)
        """)
        _db.commit()
    return _db


def save_message(agent: str, chat_id: str, role: str, content: str):
    """Save a message (user or assistant) to history."""
    db = get_db()
    now = datetime.now(NZ_TZ).isoformat()
    db.execute(
        "INSERT INTO messages (agent, chat_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (agent, chat_id, role, content, now)
    )
    db.commit()


def get_recent_messages(agent: str, chat_id: str, max_messages: int = 10,
                        max_age_hours: int = 48) -> list:
    """
    Get recent conversation messages for an agent/chat pair.

    Returns list of {"role": "user"|"assistant", "content": "..."} dicts
    suitable for passing directly to Claude API messages array.

    Limits:
    - max_messages: Maximum number of message pairs to return (default 10 = 5 exchanges)
    - max_age_hours: Only include messages from the last N hours (default 48)
    """
    db = get_db()
    cutoff = (datetime.now(NZ_TZ) - timedelta(hours=max_age_hours)).isoformat()

    rows = db.execute("""
        SELECT role, content FROM messages
        WHERE agent = ? AND chat_id = ? AND created_at > ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (agent, chat_id, cutoff, max_messages)).fetchall()

    # Reverse to chronological order
    messages = [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    # Ensure conversation starts with a user message (Claude API requirement)
    while messages and messages[0]["role"] != "user":
        messages.pop(0)

    return messages


def cleanup_old_messages(days: int = 7):
    """Remove messages older than N days to prevent unbounded growth."""
    db = get_db()
    cutoff = (datetime.now(NZ_TZ) - timedelta(days=days)).isoformat()
    db.execute("DELETE FROM messages WHERE created_at < ?", (cutoff,))
    db.commit()
    logger.info(f"Cleaned up conversation history older than {days} days")
