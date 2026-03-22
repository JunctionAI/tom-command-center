#!/usr/bin/env python3
"""
Notification Router — Severity-based message delivery for Tom's Command Center.

Replaces direct send_telegram() calls with intelligent routing:
- CRITICAL:  Bypasses DND, sends with sound. System failures, breaking alerts.
- IMPORTANT: Normal notification. Held during DND hours.
- NOTABLE:   Silent notification (disable_notification=True). Held during DND.
- INFO:      Batched into hourly digest. Held during DND.

DND hours: 10pm-6am NZST (Pacific/Auckland). Only CRITICAL bypasses DND.
Batch queue is SQLite-backed so nothing is lost on restart.

Usage:
    from core.notification_router import NotificationRouter

    router = NotificationRouter(bot_token="...", default_chat_id="-123456")
    router.send("Server is on fire", severity="CRITICAL")
    router.send("Weekly report ready", severity="IMPORTANT")
    router.send("Sync complete: 3 orders", severity="INFO")
    router.send(agent_response)  # auto-classifies from [PRIORITY: ...] marker

CLI:
    python -m core.notification_router send CRITICAL "Test critical alert" --chat-id "-123"
    python -m core.notification_router flush --chat-id "-123"
    python -m core.notification_router status
    python -m core.notification_router test
"""

import os
import re
import json
import sqlite3
import logging
import threading
from enum import IntEnum
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Optional

# --- Configuration ---

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
QUEUE_DB_PATH = DATA_DIR / "notification_queue.db"
TIMEZONE = "Pacific/Auckland"

# DND window (NZST): 22:00 - 06:00
DND_START_HOUR = 22
DND_END_HOUR = 6

# Logging configured by entrypoint.py — just get the logger
logger = logging.getLogger(__name__)


# --- Severity Levels ---

class Severity(IntEnum):
    """
    Notification severity levels, ordered by urgency.
    Higher value = more urgent.
    """
    INFO = 0       # Batched into digest
    NOTABLE = 1    # Silent notification
    IMPORTANT = 2  # Normal notification
    CRITICAL = 3   # Bypasses DND, sound notification

    @classmethod
    def from_string(cls, s: str) -> "Severity":
        """Parse a severity string, case-insensitive. Defaults to IMPORTANT."""
        mapping = {
            "info": cls.INFO,
            "notable": cls.NOTABLE,
            "important": cls.IMPORTANT,
            "critical": cls.CRITICAL,
        }
        return mapping.get(s.strip().lower(), cls.IMPORTANT)


# --- Severity Classifier ---

# Pattern: [PRIORITY: CRITICAL] or [PRIORITY: INFO] etc.
_PRIORITY_PATTERN = re.compile(
    r'\[PRIORITY:\s*(CRITICAL|IMPORTANT|NOTABLE|INFO)\s*\]',
    re.IGNORECASE
)


def classify_severity(text: str) -> tuple[Severity, str]:
    """
    Parse a [PRIORITY: LEVEL] marker from text.

    Returns (severity, cleaned_text) where cleaned_text has the marker removed.
    If no marker is found, defaults to IMPORTANT.
    """
    match = _PRIORITY_PATTERN.search(text)
    if match:
        severity = Severity.from_string(match.group(1))
        cleaned = text[:match.start()] + text[match.end():]
        cleaned = cleaned.strip()
        return severity, cleaned
    return Severity.IMPORTANT, text


# --- Queue Database ---

class NotificationQueue:
    """
    SQLite-backed queue for batched INFO messages.
    Survives restarts -- nothing is lost.
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(QUEUE_DB_PATH)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._local = threading.local()
        # Initialise schema on the creating thread
        self._init_schema(self._get_conn())

    def _get_conn(self) -> sqlite3.Connection:
        """Get a thread-local connection (SQLite connections are not thread-safe)."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_path)
            self._local.conn.row_factory = sqlite3.Row
            self._init_schema(self._local.conn)
        return self._local.conn

    @staticmethod
    def _init_schema(conn: sqlite3.Connection):
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS pending_notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                agent TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS notification_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                severity TEXT NOT NULL,
                message_preview TEXT,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                was_batched BOOLEAN DEFAULT 0,
                was_dnd_held BOOLEAN DEFAULT 0,
                delivery_status TEXT DEFAULT 'unknown'
            );

            CREATE INDEX IF NOT EXISTS idx_pending_chat
                ON pending_notifications(chat_id);
            CREATE INDEX IF NOT EXISTS idx_pending_unsent
                ON pending_notifications(sent_at);
            CREATE INDEX IF NOT EXISTS idx_log_sent
                ON notification_log(sent_at);
        """)
        # Migration: add delivery_status column if missing (existing tables)
        try:
            conn.execute("SELECT delivery_status FROM notification_log LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE notification_log ADD COLUMN delivery_status TEXT DEFAULT 'unknown'")
        conn.commit()

    def enqueue(self, chat_id: str, message: str, severity: str, agent: str = None):
        """Add a message to the batch queue."""
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO pending_notifications (chat_id, severity, message, agent)
               VALUES (?, ?, ?, ?)""",
            (str(chat_id), severity, message, agent)
        )
        conn.commit()
        logger.info(f"Queued {severity} notification for chat {chat_id} "
                     f"({len(message)} chars)")

    def get_pending(self, chat_id: str = None) -> list[dict]:
        """Get all unsent messages, optionally filtered by chat_id."""
        conn = self._get_conn()
        if chat_id:
            rows = conn.execute(
                """SELECT * FROM pending_notifications
                   WHERE sent_at IS NULL AND chat_id = ?
                   ORDER BY created_at ASC""",
                (str(chat_id),)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM pending_notifications
                   WHERE sent_at IS NULL
                   ORDER BY chat_id, created_at ASC"""
            ).fetchall()
        return [dict(r) for r in rows]

    def mark_sent(self, ids: list[int]):
        """Mark messages as sent."""
        if not ids:
            return
        conn = self._get_conn()
        now = datetime.now(tz=timezone.utc).isoformat()
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE pending_notifications SET sent_at = ? WHERE id IN ({placeholders})",
            [now] + ids
        )
        conn.commit()

    def log_sent(self, chat_id: str, severity: str, message_preview: str,
                 was_batched: bool = False, was_dnd_held: bool = False,
                 delivery_status: str = "delivered"):
        """Record a sent notification for audit trail."""
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO notification_log
               (chat_id, severity, message_preview, was_batched, was_dnd_held, delivery_status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (str(chat_id), severity, message_preview[:200], was_batched, was_dnd_held, delivery_status)
        )
        conn.commit()

    def get_stats(self) -> dict:
        """Get queue and log statistics."""
        conn = self._get_conn()
        pending = conn.execute(
            "SELECT COUNT(*) FROM pending_notifications WHERE sent_at IS NULL"
        ).fetchone()[0]
        total_sent = conn.execute(
            "SELECT COUNT(*) FROM notification_log"
        ).fetchone()[0]
        sent_today = conn.execute(
            """SELECT COUNT(*) FROM notification_log
               WHERE sent_at > datetime('now', '-1 day')"""
        ).fetchone()[0]
        by_severity = {}
        for row in conn.execute(
            """SELECT severity, COUNT(*) as cnt FROM notification_log
               WHERE sent_at > datetime('now', '-7 days')
               GROUP BY severity"""
        ).fetchall():
            by_severity[row["severity"]] = row["cnt"]

        return {
            "pending": pending,
            "total_sent": total_sent,
            "sent_today": sent_today,
            "last_7d_by_severity": by_severity,
        }

    def close(self):
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None


# --- DND Logic ---

def _now_nzst() -> datetime:
    """Get current time in Pacific/Auckland timezone."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        # Python 3.8 fallback
        from backports.zoneinfo import ZoneInfo

    from datetime import timezone as tz
    return datetime.now(ZoneInfo(TIMEZONE))


def is_dnd_active() -> bool:
    """
    Check if Do Not Disturb is active.
    DND: 10pm-6am NZST. Returns True during those hours.
    """
    now = _now_nzst()
    hour = now.hour
    # DND is active from 22:00 to 05:59 (inclusive)
    return hour >= DND_START_HOUR or hour < DND_END_HOUR


def next_dnd_end() -> datetime:
    """Return the next 6am NZST as a timezone-aware datetime."""
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    now = _now_nzst()
    if now.hour >= DND_END_HOUR:
        # Next 6am is tomorrow
        tomorrow = now + timedelta(days=1)
        return tomorrow.replace(hour=DND_END_HOUR, minute=0, second=0, microsecond=0)
    else:
        # Next 6am is today
        return now.replace(hour=DND_END_HOUR, minute=0, second=0, microsecond=0)


# --- Core Telegram Sender (wraps existing pattern) ---

def _sanitize_telegram_markdown(text: str) -> str:
    """
    Sanitize text for Telegram Markdown (v1) to prevent parse failures.

    Telegram Markdown v1 supports: *bold*, _italic_, `inline code`, [link](url)
    It does NOT support: **double bold**, # headers, ``` code blocks, ---, > blockquotes
    """
    import re

    # 1. Convert **double asterisk bold** → *single*
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text, flags=re.DOTALL)

    # 2. Convert __double underscore italic__ → _single_
    text = re.sub(r'__(.+?)__', r'_\1_', text, flags=re.DOTALL)

    # 3. Replace ``` code blocks
    def handle_code_block(m):
        content = m.group(1).strip()
        if len(content) < 200:
            return '`' + content.replace('`', "'") + '`'
        return content
    text = re.sub(r'```[\w]*\n?(.*?)```', handle_code_block, text, flags=re.DOTALL)
    text = re.sub(r'```[\w]*', '', text)

    # 4. Strip # headers — remove leading # chars, keep the text
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    # 5. Strip horizontal rules
    text = re.sub(r'^\s*[-=_]{3,}\s*$', '', text, flags=re.MULTILINE)

    # 6. Strip > blockquote markers
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)

    # 7. Fix unmatched asterisks
    if text.count('*') % 2 != 0:
        idx = text.rfind('*')
        text = text[:idx] + text[idx+1:]

    # 8. Fix unmatched underscores
    if text.count('_') % 2 != 0:
        idx = text.rfind('_')
        text = text[:idx] + '\\_' + text[idx+1:]

    # 9. Fix unmatched square brackets
    if text.count('[') != text.count(']'):
        text = text.replace('[', '(').replace(']', ')')

    return text


def _split_telegram_message(text: str, limit: int = 4000) -> list:
    """Split long messages on paragraph boundaries to avoid cutting Markdown spans."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while len(text) > limit:
        split_at = text.rfind('\n\n', 0, limit)
        if split_at == -1:
            split_at = text.rfind('\n', 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()
    if text:
        chunks.append(text)
    return chunks


def _send_telegram_raw(chat_id: str, text: str, bot_token: str,
                       disable_notification: bool = False):
    """
    Low-level Telegram send. Wraps the existing send_telegram pattern:
    - parse_mode=Markdown
    - Splits messages >4000 chars
    - Optional silent mode via disable_notification
    """
    import requests

    text = _sanitize_telegram_markdown(text)
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def _post(chunk: str) -> bool:
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "Markdown",
        }
        if disable_notification:
            payload["disable_notification"] = True
        try:
            resp = requests.post(url, json=payload, timeout=60)
            data = resp.json() if resp.status_code == 200 else {}
            if data.get("ok"):
                return True
            # Markdown can fail with unmatched formatting -- retry as plain text
            desc = str(data.get("description", "")).lower()
            if "can't parse" in desc or "bad request" in desc:
                logger.warning(f"Telegram Markdown send failed, retrying as plain text")
                payload.pop("parse_mode")
                resp2 = requests.post(url, json=payload, timeout=60)
                data2 = resp2.json() if resp2.status_code == 200 else {}
                if data2.get("ok"):
                    return True
            logger.error(f"Telegram send failed for {chat_id}: {data.get('description', 'unknown')}")
            return False
        except requests.RequestException as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    chunks = _split_telegram_message(text)
    return all(_post(chunk) for chunk in chunks)


# --- Notification Router ---

class NotificationRouter:
    """
    Severity-based notification router for Tom's Command Center.

    Wraps send_telegram() with:
    - Severity classification (CRITICAL / IMPORTANT / NOTABLE / INFO)
    - DND hours enforcement (10pm-6am NZST, only CRITICAL bypasses)
    - Silent mode for NOTABLE messages
    - Batch digest for INFO messages (SQLite-backed queue)
    - Automatic severity parsing from [PRIORITY: ...] markers
    """

    def __init__(self, bot_token: str = None, default_chat_id: str = None,
                 queue_db_path: str = None):
        self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.default_chat_id = default_chat_id
        self.queue = NotificationQueue(db_path=queue_db_path)

        if not self.bot_token:
            logger.warning("NotificationRouter: no bot_token provided. "
                           "Set TELEGRAM_BOT_TOKEN env var or pass bot_token=")

    def send(self, text: str, severity: str = None, chat_id: str = None,
             agent: str = None, force: bool = False) -> dict:
        """
        Route a notification based on severity and DND status.

        Args:
            text:     Message text. May contain [PRIORITY: LEVEL] marker.
            severity: Override severity (CRITICAL|IMPORTANT|NOTABLE|INFO).
                      If None, auto-classifies from text markers.
            chat_id:  Target Telegram chat. Falls back to default_chat_id.
            agent:    Agent name for logging/context.
            force:    If True, bypass DND regardless of severity.

        Returns:
            dict with keys: severity, action, dnd_active, chat_id
            action is one of: "sent", "queued", "held"
        """
        target_chat = str(chat_id or self.default_chat_id or "")
        if not target_chat:
            logger.error("NotificationRouter.send(): no chat_id provided")
            return {"severity": "UNKNOWN", "action": "error",
                    "error": "no chat_id"}

        # Auto-classify if no severity override
        if severity:
            sev = Severity.from_string(severity)
            # Still clean the marker if present
            _, text = classify_severity(text)
        else:
            sev, text = classify_severity(text)

        dnd = is_dnd_active()
        result = {
            "severity": sev.name,
            "dnd_active": dnd,
            "chat_id": target_chat,
        }

        # --- Routing Logic ---

        # CRITICAL: Always send immediately, with sound
        if sev == Severity.CRITICAL or force:
            ok = self._send_now(target_chat, text, disable_notification=False)
            self.queue.log_sent(target_chat, sev.name, text,
                                was_dnd_held=False,
                                delivery_status="delivered" if ok else "failed")
            result["action"] = "sent" if ok else "failed"
            logger.info(f"[CRITICAL] {'Sent' if ok else 'FAILED'} to {target_chat} "
                        f"(DND={'active' if dnd else 'inactive'})")
            return result

        # During DND: queue everything except CRITICAL
        if dnd:
            self.queue.enqueue(target_chat, text, sev.name, agent=agent)
            result["action"] = "held"
            logger.info(f"[{sev.name}] Held for DND (queued) -- "
                        f"chat {target_chat}")
            return result

        # Outside DND: route by severity

        if sev == Severity.INFO:
            # Batch into digest queue
            self.queue.enqueue(target_chat, text, sev.name, agent=agent)
            result["action"] = "queued"
            logger.info(f"[INFO] Queued for digest -- chat {target_chat}")
            return result

        if sev == Severity.NOTABLE:
            # Send immediately but silently
            ok = self._send_now(target_chat, text, disable_notification=True)
            self.queue.log_sent(target_chat, sev.name, text,
                                delivery_status="delivered" if ok else "failed")
            result["action"] = "sent" if ok else "failed"
            logger.info(f"[NOTABLE] {'Sent silently' if ok else 'FAILED'} to {target_chat}")
            return result

        # IMPORTANT: normal notification
        ok = self._send_now(target_chat, text, disable_notification=False)
        self.queue.log_sent(target_chat, sev.name, text,
                            delivery_status="delivered" if ok else "failed")
        result["action"] = "sent" if ok else "failed"
        logger.info(f"[IMPORTANT] {'Sent' if ok else 'FAILED'} to {target_chat}")
        return result

    def flush_digest(self, chat_id: str = None) -> dict:
        """
        Send all batched messages as a single formatted digest.

        If chat_id is None, flushes all chats.
        Returns dict with count of messages flushed per chat.
        """
        pending = self.queue.get_pending(chat_id=chat_id)
        if not pending:
            logger.info("flush_digest: no pending messages")
            return {"flushed": 0}

        # Group by chat_id
        by_chat: dict[str, list[dict]] = {}
        for msg in pending:
            by_chat.setdefault(msg["chat_id"], []).append(msg)

        results = {}
        for cid, messages in by_chat.items():
            digest = self._format_digest(messages)
            # Send digest as a NOTABLE (silent) message -- it is a batch summary
            self._send_now(cid, digest, disable_notification=True)

            # Mark all as sent
            ids = [m["id"] for m in messages]
            self.queue.mark_sent(ids)
            self.queue.log_sent(cid, "DIGEST", digest,
                                was_batched=True, was_dnd_held=any(
                                    m["severity"] != "INFO" for m in messages))

            results[cid] = len(messages)
            logger.info(f"Flushed digest to {cid}: {len(messages)} messages")

        return {"flushed": sum(results.values()), "by_chat": results}

    def flush_held(self, chat_id: str = None) -> dict:
        """
        Flush messages that were held during DND, respecting their original severity.

        Unlike flush_digest (which batches INFO), this sends each held
        IMPORTANT/NOTABLE message individually with its proper delivery mode.
        INFO messages are still batched into a digest.

        Intended to be called at 6am when DND ends.
        """
        pending = self.queue.get_pending(chat_id=chat_id)
        if not pending:
            return {"flushed": 0}

        by_chat: dict[str, list[dict]] = {}
        for msg in pending:
            by_chat.setdefault(msg["chat_id"], []).append(msg)

        total_flushed = 0
        for cid, messages in by_chat.items():
            # Separate INFO (batch) from IMPORTANT/NOTABLE (send individually)
            info_msgs = [m for m in messages if m["severity"] == "INFO"]
            individual_msgs = [m for m in messages if m["severity"] != "INFO"]

            # Send individual held messages
            for msg in individual_msgs:
                sev = Severity.from_string(msg["severity"])
                silent = sev == Severity.NOTABLE
                self._send_now(cid, msg["message"], disable_notification=silent)
                self.queue.mark_sent([msg["id"]])
                self.queue.log_sent(cid, msg["severity"], msg["message"],
                                    was_dnd_held=True)
                total_flushed += 1

            # Batch INFO messages into digest
            if info_msgs:
                digest = self._format_digest(info_msgs)
                self._send_now(cid, digest, disable_notification=True)
                self.queue.mark_sent([m["id"] for m in info_msgs])
                self.queue.log_sent(cid, "DIGEST", digest,
                                    was_batched=True, was_dnd_held=True)
                total_flushed += len(info_msgs)

        return {"flushed": total_flushed}

    def status(self) -> dict:
        """Return current router status: DND state, queue stats, config."""
        now = _now_nzst()
        stats = self.queue.get_stats()
        return {
            "current_time_nzst": now.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "dnd_active": is_dnd_active(),
            "dnd_window": f"{DND_START_HOUR:02d}:00 - {DND_END_HOUR:02d}:00 NZST",
            "queue": stats,
            "bot_token_set": bool(self.bot_token),
            "default_chat_id": self.default_chat_id,
        }

    def close(self):
        """Clean up database connection."""
        self.queue.close()

    # --- Internal ---

    def _send_now(self, chat_id: str, text: str,
                  disable_notification: bool = False) -> bool:
        """Send a message via Telegram immediately. Returns True if delivered."""
        if not self.bot_token:
            logger.error("Cannot send: no bot_token configured")
            return False
        return _send_telegram_raw(
            chat_id=chat_id,
            text=text,
            bot_token=self.bot_token,
            disable_notification=disable_notification
        ) or False

    @staticmethod
    def _format_digest(messages: list[dict]) -> str:
        """Format a list of queued messages into a single digest message."""
        now_str = _now_nzst().strftime("%H:%M NZST")
        lines = [f"*Digest* ({len(messages)} updates as of {now_str})\n"]

        for i, msg in enumerate(messages, 1):
            # Timestamp from created_at
            created = msg.get("created_at", "")
            if created:
                try:
                    ts = datetime.fromisoformat(created)
                    time_str = ts.strftime("%H:%M")
                except (ValueError, TypeError):
                    time_str = "?"
            else:
                time_str = "?"

            agent_prefix = f"[{msg['agent']}] " if msg.get("agent") else ""
            # Truncate long messages in digest
            text = msg["message"]
            if len(text) > 300:
                text = text[:297] + "..."
            lines.append(f"{i}. `{time_str}` {agent_prefix}{text}")

        return "\n".join(lines)


# --- Convenience Functions ---
# Drop-in replacements for direct send_telegram() calls.

_default_router: Optional[NotificationRouter] = None
_router_lock = threading.Lock()


def get_router(bot_token: str = None, default_chat_id: str = None) -> NotificationRouter:
    """
    Get or create the singleton NotificationRouter.

    Safe to call from any thread. First call initialises, subsequent calls
    return the same instance.
    """
    global _default_router
    if _default_router is None:
        with _router_lock:
            if _default_router is None:
                _default_router = NotificationRouter(
                    bot_token=bot_token,
                    default_chat_id=default_chat_id
                )
    return _default_router


def route_notification(chat_id: str, text: str, bot_token: str,
                       severity: str = None, agent: str = None) -> dict:
    """
    Drop-in replacement for send_telegram() with severity routing.

    Signature mirrors send_telegram(chat_id, text, bot_token) for easy migration.
    Add severity= and agent= for full routing control.
    """
    router = get_router(bot_token=bot_token)
    return router.send(text, severity=severity, chat_id=chat_id, agent=agent)


# --- CLI ---

def _cli():
    """Command-line interface for testing and managing the notification router."""
    import sys

    def usage():
        print("Notification Router CLI")
        print()
        print("Commands:")
        print("  send SEVERITY \"message\" [--chat-id CID]   Send a test notification")
        print("  flush [--chat-id CID]                     Flush all pending digests")
        print("  flush-held [--chat-id CID]                Flush DND-held messages")
        print("  status                                    Show router status")
        print("  pending                                   Show pending queue")
        print("  test                                      Run self-test (no Telegram)")
        print()
        print("Severity: CRITICAL | IMPORTANT | NOTABLE | INFO")
        print()
        print("Environment variables:")
        print("  TELEGRAM_BOT_TOKEN   Bot token (required for send)")
        print("  TELEGRAM_OWNER_ID    Owner user ID")

    args = sys.argv[1:] if len(sys.argv) > 1 else []

    if not args or args[0] in ("--help", "-h", "help"):
        usage()
        return

    cmd = args[0].lower()

    # Parse --chat-id from anywhere in args
    chat_id = None
    if "--chat-id" in args:
        idx = args.index("--chat-id")
        if idx + 1 < len(args):
            chat_id = args[idx + 1]
            args = args[:idx] + args[idx + 2:]

    if cmd == "send":
        if len(args) < 3:
            print("Usage: send SEVERITY \"message\" [--chat-id CID]")
            sys.exit(1)

        severity = args[1].upper()
        message = args[2]

        if severity not in ("CRITICAL", "IMPORTANT", "NOTABLE", "INFO"):
            print(f"Invalid severity: {severity}")
            print("Must be: CRITICAL | IMPORTANT | NOTABLE | INFO")
            sys.exit(1)

        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            print("ERROR: TELEGRAM_BOT_TOKEN not set")
            sys.exit(1)

        if not chat_id:
            # Try to load from config
            try:
                config_path = BASE_DIR / "config" / "telegram.json"
                with open(config_path, encoding='utf-8') as f:
                    config = json.load(f)
                chat_id = config.get("chat_ids", {}).get("command-center")
                if chat_id:
                    print(f"Using command-center chat ID: {chat_id}")
            except Exception:
                pass

        if not chat_id:
            print("ERROR: No --chat-id provided and could not load from config")
            sys.exit(1)

        router = NotificationRouter(bot_token=bot_token, default_chat_id=chat_id)
        result = router.send(message, severity=severity, chat_id=chat_id)
        print(f"Result: {json.dumps(result, indent=2)}")
        router.close()

    elif cmd == "flush":
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            print("ERROR: TELEGRAM_BOT_TOKEN not set")
            sys.exit(1)

        router = NotificationRouter(bot_token=bot_token)
        result = router.flush_digest(chat_id=chat_id)
        print(f"Flushed: {json.dumps(result, indent=2)}")
        router.close()

    elif cmd == "flush-held":
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            print("ERROR: TELEGRAM_BOT_TOKEN not set")
            sys.exit(1)

        router = NotificationRouter(bot_token=bot_token)
        result = router.flush_held(chat_id=chat_id)
        print(f"Flushed held: {json.dumps(result, indent=2)}")
        router.close()

    elif cmd == "status":
        router = NotificationRouter()
        status = router.status()
        print(json.dumps(status, indent=2, default=str))
        router.close()

    elif cmd == "pending":
        router = NotificationRouter()
        pending = router.queue.get_pending(chat_id=chat_id)
        if not pending:
            print("No pending messages.")
        else:
            print(f"{len(pending)} pending message(s):\n")
            for msg in pending:
                agent_str = f" [{msg['agent']}]" if msg.get('agent') else ""
                print(f"  [{msg['severity']}]{agent_str} chat={msg['chat_id']} "
                      f"@ {msg['created_at']}")
                preview = msg['message'][:80]
                print(f"    {preview}{'...' if len(msg['message']) > 80 else ''}")
                print()
        router.close()

    elif cmd == "test":
        print("=== Notification Router Self-Test ===\n")

        # Test 1: Severity parsing
        print("1. Severity parsing:")
        test_cases = [
            ("[PRIORITY: CRITICAL] Server down!", Severity.CRITICAL, "Server down!"),
            ("[PRIORITY: info] Sync complete", Severity.INFO, "Sync complete"),
            ("No marker here", Severity.IMPORTANT, "No marker here"),
            ("Before [PRIORITY: NOTABLE] after", Severity.NOTABLE, "Before  after"),
        ]
        all_pass = True
        for text, expected_sev, expected_clean in test_cases:
            sev, cleaned = classify_severity(text)
            passed = sev == expected_sev and cleaned == expected_clean
            status = "PASS" if passed else "FAIL"
            if not passed:
                all_pass = False
            print(f"  [{status}] '{text[:40]}' -> {sev.name}, '{cleaned[:40]}'")

        # Test 2: DND check
        print(f"\n2. DND status:")
        now = _now_nzst()
        dnd = is_dnd_active()
        print(f"  Current time NZST: {now.strftime('%H:%M')}")
        print(f"  DND active: {dnd}")
        print(f"  DND window: {DND_START_HOUR:02d}:00 - {DND_END_HOUR:02d}:00")

        # Test 3: Queue operations
        print(f"\n3. Queue operations:")
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            test_db = tmp.name

        try:
            queue = NotificationQueue(db_path=test_db)

            queue.enqueue("-123", "Test message 1", "INFO", agent="test-agent")
            queue.enqueue("-123", "Test message 2", "INFO", agent="test-agent")
            queue.enqueue("-456", "Other chat", "NOTABLE")

            pending = queue.get_pending("-123")
            print(f"  [{'PASS' if len(pending) == 2 else 'FAIL'}] "
                  f"Enqueue + get_pending: {len(pending)} messages for chat -123")

            all_pending = queue.get_pending()
            print(f"  [{'PASS' if len(all_pending) == 3 else 'FAIL'}] "
                  f"Total pending: {len(all_pending)}")

            ids = [p["id"] for p in pending]
            queue.mark_sent(ids)
            remaining = queue.get_pending("-123")
            print(f"  [{'PASS' if len(remaining) == 0 else 'FAIL'}] "
                  f"After mark_sent: {len(remaining)} pending for chat -123")

            stats = queue.get_stats()
            print(f"  [{'PASS' if stats['pending'] == 1 else 'FAIL'}] "
                  f"Stats: {stats['pending']} pending, "
                  f"{stats['total_sent']} logged")

            queue.close()
        finally:
            os.unlink(test_db)

        # Test 4: Router routing logic (dry run, no Telegram)
        print(f"\n4. Router logic (dry run):")
        router = NotificationRouter(bot_token="TEST_TOKEN_DO_NOT_SEND")
        # Override _send_now to not actually call Telegram
        sent_log = []
        router._send_now = lambda cid, text, disable_notification=False: \
            sent_log.append({"chat_id": cid, "silent": disable_notification})

        result = router.send("[PRIORITY: CRITICAL] Alert!", chat_id="-999")
        print(f"  [{'PASS' if result['action'] == 'sent' else 'FAIL'}] "
              f"CRITICAL -> {result['action']}")

        result = router.send("Normal message", severity="INFO", chat_id="-999")
        expected = "queued" if not dnd else "held"
        print(f"  [{'PASS' if result['action'] == expected else 'FAIL'}] "
              f"INFO -> {result['action']} (expected {expected})")

        if not dnd:
            result = router.send("Notable update", severity="NOTABLE", chat_id="-999")
            print(f"  [{'PASS' if result['action'] == 'sent' else 'FAIL'}] "
                  f"NOTABLE -> {result['action']}")
            # Check silent flag
            if sent_log:
                last = sent_log[-1]
                print(f"  [{'PASS' if last['silent'] else 'FAIL'}] "
                      f"NOTABLE was silent: {last['silent']}")

        router.close()

        print(f"\n{'='*40}")
        print("Self-test complete.")

    else:
        print(f"Unknown command: {cmd}")
        usage()
        sys.exit(1)


if __name__ == "__main__":
    _cli()
