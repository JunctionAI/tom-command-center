"""
User Memory — Production-grade persistent memory system.

This is the core of the product. Every conversation permanently contributes
to an ever-improving understanding of the user, like how CLAUDE.md works
in Claude Code but auto-generated from Telegram conversations.

Architecture (inspired by ChatGPT + Mem0):
- Every message is stored permanently
- After every conversation, Haiku extracts facts automatically (no markers needed)
- Facts are deduplicated: Add / Update / Skip / Merge against existing facts
- Facts are loaded into every agent prompt as "=== WHAT YOU KNOW ABOUT THIS USER ==="
- Session summaries compress old conversations into medium-term memory
- Users can /memory to see what the agent knows, /forget to delete

Three tiers loaded into every prompt:
1. User facts (permanent, deduplicated, ~200-500 facts per user)
2. Session summaries (last 30 days of daily summaries)
3. Recent messages (last 10 messages verbatim — from conversation_history.py)
"""

import sqlite3
import json
import logging
import os
import threading
from pathlib import Path
from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

NZ_TZ = ZoneInfo("Pacific/Auckland")
logger = logging.getLogger("orchestrator")

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "user_memory.db"

_db = None
_db_lock = threading.Lock()


# =============================================================================
# DATABASE
# =============================================================================

def get_db() -> sqlite3.Connection:
    """Get or create the user memory database."""
    global _db
    if _db is None:
        with _db_lock:
            if _db is None:
                DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                _db = sqlite3.connect(str(DB_PATH), check_same_thread=False)
                _db.row_factory = sqlite3.Row
                _init_schema(_db)
    return _db


def _init_schema(db: sqlite3.Connection):
    """Create tables if they don't exist."""
    db.executescript("""
        -- Core fact store: what the agent knows about the user
        CREATE TABLE IF NOT EXISTS user_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            fact TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            confidence REAL NOT NULL DEFAULT 1.0,
            source_summary TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            superseded_by INTEGER,
            is_active BOOLEAN NOT NULL DEFAULT 1
        );

        CREATE INDEX IF NOT EXISTS idx_facts_user_agent
        ON user_facts(user_id, agent_id, is_active);

        CREATE INDEX IF NOT EXISTS idx_facts_category
        ON user_facts(user_id, agent_id, category, is_active);

        -- Session summaries: daily conversation digests
        CREATE TABLE IF NOT EXISTS session_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            summary TEXT NOT NULL,
            message_count INTEGER NOT NULL DEFAULT 0,
            date TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_summaries_unique
        ON session_summaries(user_id, agent_id, date);

        -- Full conversation messages (permanent archive)
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_messages_lookup
        ON messages(user_id, agent_id, chat_id, created_at DESC);

        -- Memory extraction log: track what was extracted when
        CREATE TABLE IF NOT EXISTS extraction_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            facts_added INTEGER NOT NULL DEFAULT 0,
            facts_updated INTEGER NOT NULL DEFAULT 0,
            facts_skipped INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
    """)
    db.commit()
    logger.info("User memory database initialized")


# =============================================================================
# MESSAGE STORAGE (Permanent — never deleted)
# =============================================================================

def save_message(user_id: str, agent_id: str, chat_id: str, role: str, content: str):
    """Save a message permanently. Every message, forever."""
    db = get_db()
    now = datetime.now(NZ_TZ).isoformat()
    db.execute(
        "INSERT INTO messages (user_id, agent_id, chat_id, role, content, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, agent_id, chat_id, role, content, now)
    )
    db.commit()


def get_recent_messages(user_id: str, agent_id: str, chat_id: str,
                        max_messages: int = 20, max_age_hours: int = 72) -> list:
    """
    Get recent conversation messages for multi-turn context.
    Returns list of {"role": "user"|"assistant", "content": "..."} dicts.
    """
    db = get_db()
    cutoff = (datetime.now(NZ_TZ) - timedelta(hours=max_age_hours)).isoformat()

    rows = db.execute("""
        SELECT role, content FROM messages
        WHERE user_id = ? AND agent_id = ? AND chat_id = ? AND created_at > ?
        ORDER BY created_at DESC
        LIMIT ?
    """, (user_id, agent_id, chat_id, cutoff, max_messages)).fetchall()

    messages = [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]

    # Ensure conversation starts with a user message (Claude API requirement)
    while messages and messages[0]["role"] != "user":
        messages.pop(0)

    return messages


def get_message_count(user_id: str, agent_id: str) -> int:
    """Get total message count for a user/agent pair."""
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) as cnt FROM messages WHERE user_id = ? AND agent_id = ?",
        (user_id, agent_id)
    ).fetchone()
    return row["cnt"] if row else 0


def get_last_user_message_age_hours(user_id: str, agent_id: str) -> float | None:
    """
    Returns how many hours ago the user last sent a message, or None if never.
    Used by scheduled tasks to detect non-engagement and live-conversation state.
    """
    db = get_db()
    row = db.execute(
        """SELECT created_at FROM messages
           WHERE user_id = ? AND agent_id = ? AND role = 'user'
           ORDER BY created_at DESC LIMIT 1""",
        (user_id, agent_id)
    ).fetchone()
    if not row:
        return None
    try:
        last_ts = datetime.fromisoformat(row["created_at"])
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=NZ_TZ)
        now = datetime.now(NZ_TZ)
        return (now - last_ts).total_seconds() / 3600
    except Exception:
        return None


# =============================================================================
# FACT STORE (Permanent, deduplicated)
# =============================================================================

FACT_CATEGORIES = [
    "preference",      # Likes, dislikes, style choices
    "biographical",    # Name, age, location, job, relationships
    "goal",           # What they want to achieve
    "decision",       # Choices they've made
    "constraint",     # Limitations, allergies, budget, time
    "pattern",        # Recurring behaviors, habits, routines
    "opinion",        # Views on topics, products, ideas
    "relationship",   # People in their life, dynamics
    "context",        # Current situation, projects, events
    "learning",       # What they've learned or been taught
]


def get_user_facts(user_id: str, agent_id: str, category: str = None,
                   include_global: bool = True) -> list:
    """
    Get all active facts about a user for a specific agent.
    If include_global=True, also includes facts from other agents
    (cross-agent knowledge sharing).
    """
    db = get_db()

    if include_global:
        # Get facts from this agent + global facts from other agents
        if category:
            rows = db.execute("""
                SELECT fact, category, confidence, updated_at, agent_id
                FROM user_facts
                WHERE user_id = ? AND is_active = 1 AND category = ?
                ORDER BY confidence DESC, updated_at DESC
            """, (user_id, category)).fetchall()
        else:
            rows = db.execute("""
                SELECT fact, category, confidence, updated_at, agent_id
                FROM user_facts
                WHERE user_id = ? AND is_active = 1
                ORDER BY confidence DESC, updated_at DESC
            """, (user_id,)).fetchall()
    else:
        if category:
            rows = db.execute("""
                SELECT fact, category, confidence, updated_at, agent_id
                FROM user_facts
                WHERE user_id = ? AND agent_id = ? AND is_active = 1 AND category = ?
                ORDER BY confidence DESC, updated_at DESC
            """, (user_id, agent_id, category)).fetchall()
        else:
            rows = db.execute("""
                SELECT fact, category, confidence, updated_at, agent_id
                FROM user_facts
                WHERE user_id = ? AND agent_id = ? AND is_active = 1
                ORDER BY confidence DESC, updated_at DESC
            """, (user_id, agent_id)).fetchall()

    return [dict(row) for row in rows]


def add_fact(user_id: str, agent_id: str, fact: str, category: str = "general",
             confidence: float = 1.0, source_summary: str = None) -> int:
    """Add a new fact. Returns the fact ID."""
    db = get_db()
    now = datetime.now(NZ_TZ).isoformat()
    cursor = db.execute(
        "INSERT INTO user_facts (user_id, agent_id, fact, category, confidence, "
        "source_summary, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, agent_id, fact, category, confidence, source_summary, now, now)
    )
    db.commit()
    return cursor.lastrowid


def update_fact(fact_id: int, new_fact: str, new_confidence: float = None):
    """Update an existing fact (preserves history via superseded_by chain)."""
    db = get_db()
    now = datetime.now(NZ_TZ).isoformat()

    updates = ["fact = ?", "updated_at = ?"]
    params = [new_fact, now]

    if new_confidence is not None:
        updates.append("confidence = ?")
        params.append(new_confidence)

    params.append(fact_id)
    db.execute(f"UPDATE user_facts SET {', '.join(updates)} WHERE id = ?", params)
    db.commit()


def deactivate_fact(fact_id: int, superseded_by: int = None):
    """Soft-delete a fact (mark as inactive, optionally link to replacement)."""
    db = get_db()
    now = datetime.now(NZ_TZ).isoformat()
    db.execute(
        "UPDATE user_facts SET is_active = 0, superseded_by = ?, updated_at = ? WHERE id = ?",
        (superseded_by, now, fact_id)
    )
    db.commit()


def delete_facts_by_text(user_id: str, search_text: str) -> int:
    """Delete facts matching a search string. For /forget command. Returns count deleted."""
    db = get_db()
    now = datetime.now(NZ_TZ).isoformat()
    cursor = db.execute(
        "UPDATE user_facts SET is_active = 0, updated_at = ? "
        "WHERE user_id = ? AND is_active = 1 AND fact LIKE ?",
        (now, user_id, f"%{search_text}%")
    )
    db.commit()
    return cursor.rowcount


def delete_all_facts(user_id: str) -> int:
    """Nuclear option: delete all facts for a user. For /forget all command."""
    db = get_db()
    now = datetime.now(NZ_TZ).isoformat()
    cursor = db.execute(
        "UPDATE user_facts SET is_active = 0, updated_at = ? WHERE user_id = ? AND is_active = 1",
        (now, user_id)
    )
    db.commit()
    return cursor.rowcount


# =============================================================================
# SESSION SUMMARIES (Medium-term memory)
# =============================================================================

def save_session_summary(user_id: str, agent_id: str, summary: str,
                         message_count: int, date_str: str = None):
    """Save a daily session summary. Replaces existing summary for same date."""
    db = get_db()
    now = datetime.now(NZ_TZ)
    if not date_str:
        date_str = now.date().isoformat()

    db.execute("""
        INSERT INTO session_summaries (user_id, agent_id, summary, message_count, date, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, agent_id, date) DO UPDATE SET
            summary = excluded.summary,
            message_count = excluded.message_count,
            created_at = excluded.created_at
    """, (user_id, agent_id, summary, message_count, date_str, now.isoformat()))
    db.commit()


def get_recent_summaries(user_id: str, agent_id: str, days: int = 30) -> list:
    """Get session summaries from the last N days."""
    db = get_db()
    cutoff = (datetime.now(NZ_TZ).date() - timedelta(days=days)).isoformat()

    rows = db.execute("""
        SELECT summary, message_count, date FROM session_summaries
        WHERE user_id = ? AND agent_id = ? AND date > ?
        ORDER BY date DESC
    """, (user_id, agent_id, cutoff)).fetchall()

    return [dict(row) for row in rows]


# =============================================================================
# MEMORY EXTRACTION (The core intelligence — runs after every conversation)
# =============================================================================

def extract_and_store_memories(user_id: str, agent_id: str,
                                conversation: list, agent_display_name: str = "",
                                api_key: str = None):
    """
    Extract facts from a conversation and store them.
    Uses Haiku for cost efficiency (~$0.001 per extraction).

    This is the key differentiator: automatic, continuous learning
    from every conversation. No markers needed.

    conversation: list of {"role": "user"|"assistant", "content": "..."}
    """
    if not conversation or len(conversation) < 2:
        return  # Need at least one exchange

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()

        # Get existing facts for dedup context
        existing_facts = get_user_facts(user_id, agent_id, include_global=False)
        existing_text = "\n".join([f"- [{f['category']}] {f['fact']}" for f in existing_facts[:50]])

        # Format conversation for extraction
        conv_text = ""
        for msg in conversation[-10:]:  # Last 10 messages max
            speaker = "User" if msg["role"] == "user" else "Agent"
            conv_text += f"{speaker}: {msg['content'][:500]}\n\n"

        extraction_prompt = f"""You are a memory extraction system. Extract PERMANENT facts about the USER that will still be relevant in future conversations.

RULES:
- Only extract facts the user EXPLICITLY stated or clearly implied
- Never infer or assume anything not directly supported by the text
- If the user corrects something, extract the CORRECTED version
- Rate confidence: 1.0 = explicitly stated, 0.8 = strongly implied, 0.5 = loosely implied
- Compare against existing facts. For each new fact, decide: ADD (new info), UPDATE (modifies existing), SKIP (already known)

CATEGORIES (use exactly one):
- biographical: permanent facts about who they are (name, age, location, medical history, diagnoses)
- goal: enduring goals and aspirations (not what they asked about in this message)
- constraint: hard limits (medical restrictions, intolerances, can't-do-list)
- pattern: recurring behaviours, triggers, responses observed across multiple instances
- preference: stable likes/dislikes/ways of working
- decision: significant choices they've made (stopped a medication, started a protocol)
- relationship: people in their life and dynamics
- opinion: their views and beliefs
- learning: insights they've had or things they've understood
- context: current life situation (job, living situation, phase of recovery) — only if durable, not momentary

DO NOT EXTRACT:
- What the user asked about in this specific conversation ("User asked about X")
- What the agent said or recommended
- Timestamps, dates, or time references ("Current time is...", "Monday morning...")
- Scheduled tasks or check-in prompts ("User was prompted to report...")
- Transient states that won't matter next week ("User is feeling groggy this morning")
- Anything that is already captured in the existing facts

EXISTING FACTS ABOUT THIS USER:
{existing_text if existing_text else "(No existing facts yet — this is a new user)"}

CONVERSATION:
{conv_text}

Return ONLY a JSON array. No explanation, no markdown, just the array:
[
  {{"action": "ADD|UPDATE|SKIP", "fact": "...", "category": "...", "confidence": 0.0-1.0, "updates_fact_index": null}}
]

If updating, set updates_fact_index to the 0-based index of the existing fact being updated.
If no new facts to extract, return: []"""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{"role": "user", "content": extraction_prompt}],
            timeout=30.0,
        )

        result_text = response.content[0].text.strip()

        # Parse JSON response (handle potential markdown wrapping)
        if result_text.startswith("```"):
            result_text = result_text.split("```")[1]
            if result_text.startswith("json"):
                result_text = result_text[4:]
            result_text = result_text.strip()

        facts_to_process = json.loads(result_text)

        if not isinstance(facts_to_process, list):
            logger.warning(f"Memory extraction returned non-list: {type(facts_to_process)}")
            return

        added = 0
        updated = 0
        skipped = 0

        for item in facts_to_process:
            action = item.get("action", "SKIP").upper()
            fact_text = item.get("fact", "").strip()
            category = item.get("category", "general").strip().lower()
            confidence = float(item.get("confidence", 0.8))

            if not fact_text:
                continue

            if category not in FACT_CATEGORIES:
                category = "general"

            if action == "ADD":
                add_fact(user_id, agent_id, fact_text, category, confidence,
                         source_summary=f"Extracted from {agent_display_name} conversation")
                added += 1
            elif action == "UPDATE":
                idx = item.get("updates_fact_index")
                if idx is not None and 0 <= idx < len(existing_facts):
                    old_fact = existing_facts[idx]
                    # Find the actual DB ID
                    db = get_db()
                    row = db.execute(
                        "SELECT id FROM user_facts WHERE user_id = ? AND agent_id = ? "
                        "AND fact = ? AND is_active = 1 LIMIT 1",
                        (user_id, agent_id, old_fact["fact"])
                    ).fetchone()
                    if row:
                        update_fact(row["id"], fact_text, confidence)
                        updated += 1
                    else:
                        # Can't find old fact to update — add as new
                        add_fact(user_id, agent_id, fact_text, category, confidence,
                                 source_summary=f"Updated from {agent_display_name} conversation")
                        added += 1
                else:
                    # Index out of range — add as new
                    add_fact(user_id, agent_id, fact_text, category, confidence,
                             source_summary=f"Updated from {agent_display_name} conversation")
                    added += 1
            else:
                skipped += 1

        # Log extraction
        db = get_db()
        now = datetime.now(NZ_TZ).isoformat()
        db.execute(
            "INSERT INTO extraction_log (user_id, agent_id, facts_added, facts_updated, "
            "facts_skipped, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, agent_id, added, updated, skipped, now)
        )
        db.commit()

        if added > 0 or updated > 0:
            logger.info(f"Memory extraction for {agent_id}: +{added} new, ~{updated} updated, "
                        f"={skipped} skipped (total active: {len(existing_facts) + added})")

    except json.JSONDecodeError as e:
        logger.warning(f"Memory extraction JSON parse failed: {e}")
    except Exception as e:
        logger.error(f"Memory extraction failed for {agent_id}: {e}")


# =============================================================================
# SESSION SUMMARY GENERATION (Runs daily at end of day)
# =============================================================================

def generate_daily_summary(user_id: str, agent_id: str, date_str: str = None):
    """
    Generate a daily summary from all messages for a given date.
    Uses Haiku for cost efficiency.
    """
    if not date_str:
        date_str = (datetime.now(NZ_TZ).date() - timedelta(days=1)).isoformat()

    db = get_db()

    # Get all messages for this date
    rows = db.execute("""
        SELECT role, content, created_at FROM messages
        WHERE user_id = ? AND agent_id = ? AND DATE(created_at) = ?
        ORDER BY created_at ASC
    """, (user_id, agent_id, date_str)).fetchall()

    if not rows:
        return  # No messages to summarise

    message_count = len(rows)
    conv_text = ""
    for row in rows:
        speaker = "User" if row["role"] == "user" else "Agent"
        conv_text += f"{speaker}: {row['content'][:300]}\n"

    try:
        import anthropic
        client = anthropic.Anthropic()

        summary_prompt = f"""Summarise this day's conversation between a user and their AI agent in 3-5 sentences.
Focus on: what was discussed, decisions made, goals mentioned, emotional tone, any important context.
Be specific — names, numbers, dates matter.

Date: {date_str}
Messages: {message_count}

Conversation:
{conv_text[:4000]}

Return ONLY the summary text, no formatting or labels."""

        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": summary_prompt}],
            timeout=30.0,
        )

        summary = response.content[0].text.strip()
        save_session_summary(user_id, agent_id, summary, message_count, date_str)
        logger.info(f"Daily summary generated for {agent_id}/{date_str}: {message_count} messages")

    except Exception as e:
        logger.error(f"Daily summary generation failed for {agent_id}/{date_str}: {e}")


def generate_all_daily_summaries(telegram_config: dict, date_str: str = None):
    """Generate summaries for all agent/user pairs that had conversations yesterday."""
    if not date_str:
        date_str = (datetime.now(NZ_TZ).date() - timedelta(days=1)).isoformat()

    db = get_db()
    pairs = db.execute("""
        SELECT DISTINCT user_id, agent_id FROM messages
        WHERE DATE(created_at) = ?
    """, (date_str,)).fetchall()

    for pair in pairs:
        generate_daily_summary(pair["user_id"], pair["agent_id"], date_str)


# =============================================================================
# MEMORY LOADING (Injected into agent prompts before every response)
# =============================================================================

def load_user_memory(user_id: str, agent_id: str) -> str:
    """
    Build the complete memory context for a user/agent pair.
    This is injected into the system prompt before every response.

    Returns formatted string with three tiers:
    1. User facts (permanent, deduplicated)
    2. Recent session summaries (last 30 days)
    3. (Recent messages are handled separately by get_recent_messages)
    """
    parts = []

    # Tier 1: Core facts about this user (from ALL agents — cross-agent knowledge)
    facts = get_user_facts(user_id, agent_id, include_global=True)
    if facts:
        parts.append("=== WHAT YOU KNOW ABOUT THIS USER ===")
        parts.append("These are facts learned from your conversations. "
                     "They are your long-term memory. Reference them naturally.")

        # Group by category for readability
        by_category = {}
        for f in facts:
            cat = f["category"]
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(f)

        for cat in FACT_CATEGORIES:
            if cat in by_category:
                parts.append(f"\n*{cat.upper()}:*")
                for f in by_category[cat]:
                    source = f" (from {f['agent_id']})" if f["agent_id"] != agent_id else ""
                    parts.append(f"- {f['fact']}{source}")

    # Tier 2: Recent session summaries
    summaries = get_recent_summaries(user_id, agent_id, days=30)
    if summaries:
        parts.append("\n=== RECENT CONVERSATION HISTORY (Summaries) ===")
        for s in summaries[:14]:  # Cap at 14 days to manage token budget
            parts.append(f"[{s['date']}] ({s['message_count']} messages) {s['summary']}")

    if not parts:
        return ""

    total = "\n".join(parts)

    # Token budget guard: if memory exceeds ~15K chars (~4K tokens), truncate summaries
    if len(total) > 15000:
        # Keep all facts, truncate summaries
        fact_section = "\n".join(parts[:parts.index("\n=== RECENT CONVERSATION HISTORY (Summaries) ===")]
                                 if "\n=== RECENT CONVERSATION HISTORY (Summaries) ===" in parts
                                 else parts)
        remaining = 15000 - len(fact_section)
        if remaining > 500 and summaries:
            summary_text = "\n=== RECENT CONVERSATION HISTORY (Summaries) ===\n"
            for s in summaries[:7]:  # Reduce to 7 days
                line = f"[{s['date']}] ({s['message_count']} messages) {s['summary']}\n"
                if len(summary_text) + len(line) < remaining:
                    summary_text += line
                else:
                    break
            total = fact_section + "\n" + summary_text

    return total


# =============================================================================
# USER COMMANDS (/memory, /forget)
# =============================================================================

def format_memory_for_display(user_id: str, agent_id: str = None) -> str:
    """Format all known facts about a user for display via /memory command."""
    db = get_db()

    if agent_id:
        facts = get_user_facts(user_id, agent_id, include_global=False)
    else:
        facts = get_user_facts(user_id, "", include_global=True)

    if not facts:
        return "I don't have any stored memories about you yet. As we chat, I'll learn and remember things about you."

    lines = ["*Your Memory Profile*\n"]

    by_category = {}
    for f in facts:
        cat = f["category"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(f)

    for cat in FACT_CATEGORIES:
        if cat in by_category:
            lines.append(f"*{cat.title()}:*")
            for f in by_category[cat]:
                lines.append(f"  - {f['fact']}")
            lines.append("")

    total = get_message_count(user_id, agent_id or "")
    lines.append(f"Total messages in history: {total}")
    lines.append(f"Active facts: {len(facts)}")
    lines.append("\nUse /forget <text> to remove specific memories")
    lines.append("Use /forget all to clear everything")

    return "\n".join(lines)


# =============================================================================
# MAINTENANCE
# =============================================================================

def compact_old_messages(days: int = 30):
    """
    Archive messages older than N days by ensuring they have summaries.
    Raw messages are kept forever but summaries make them searchable.
    """
    db = get_db()
    cutoff = (datetime.now(NZ_TZ).date() - timedelta(days=days)).isoformat()

    # Find dates with messages but no summary
    unsummarised = db.execute("""
        SELECT DISTINCT user_id, agent_id, DATE(created_at) as msg_date
        FROM messages
        WHERE DATE(created_at) < ?
        AND NOT EXISTS (
            SELECT 1 FROM session_summaries
            WHERE session_summaries.user_id = messages.user_id
            AND session_summaries.agent_id = messages.agent_id
            AND session_summaries.date = DATE(messages.created_at)
        )
    """, (cutoff,)).fetchall()

    for row in unsummarised:
        generate_daily_summary(row["user_id"], row["agent_id"], row["msg_date"])

    if unsummarised:
        logger.info(f"Compacted {len(unsummarised)} unsummarised message days")


def get_memory_stats(user_id: str) -> dict:
    """Get memory statistics for a user."""
    db = get_db()

    facts_count = db.execute(
        "SELECT COUNT(*) as cnt FROM user_facts WHERE user_id = ? AND is_active = 1",
        (user_id,)
    ).fetchone()["cnt"]

    messages_count = db.execute(
        "SELECT COUNT(*) as cnt FROM messages WHERE user_id = ?",
        (user_id,)
    ).fetchone()["cnt"]

    summaries_count = db.execute(
        "SELECT COUNT(*) as cnt FROM session_summaries WHERE user_id = ?",
        (user_id,)
    ).fetchone()["cnt"]

    extractions = db.execute(
        "SELECT COUNT(*) as cnt, SUM(facts_added) as added, SUM(facts_updated) as updated "
        "FROM extraction_log WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    return {
        "active_facts": facts_count,
        "total_messages": messages_count,
        "session_summaries": summaries_count,
        "extraction_runs": extractions["cnt"] or 0,
        "facts_ever_added": extractions["added"] or 0,
        "facts_ever_updated": extractions["updated"] or 0,
    }
