"""
neo4j_memory.py — Neo4j Single-Source-of-Truth Memory Module
=============================================================

Replaces the 3-layer redundant memory system (ASMR 6x Haiku, legacy SQLite,
Neo4j) with Neo4j as the sole source of truth.

ARCHITECTURE:
- retrieve()       — Zero API calls. Pure Cypher. 3 parallel queries.
- extract()        — 1 Haiku call → structured JSON → Neo4j writes.
- get_constraints() — Zero API calls. Pure Cypher.

DESIGN PRINCIPLES:
- Reads are free (Cypher only, no LLM).
- Writes are 1 Haiku call per conversation turn.
- All writes use MERGE with stable hash IDs to prevent duplicates.
- Gracefully no-ops if Neo4j is unavailable — never raises to caller.
- extract() is fire-and-forget — errors are logged, never raised.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Project root — two levels up from core/neo4j_memory.py
BASE_DIR = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# Haiku model config
# ---------------------------------------------------------------------------

_HAIKU_MODEL = "claude-haiku-4-5-20251001"
_HAIKU_MAX_TOKENS = 1000

# ---------------------------------------------------------------------------
# Category keyword map (used by retrieve() to infer relevant categories)
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "biographical": [
        "who", "age", "born", "name", "live", "location", "city", "country",
        "job", "work", "founder", "ceo", "business", "company",
    ],
    "goal": [
        "goal", "want", "aim", "target", "plan", "build", "achieve",
        "milestone", "aspire", "vision", "dream", "ambition",
    ],
    "constraint": [
        "can't", "cannot", "avoid", "limit", "restriction", "allergy",
        "pain", "injury", "condition", "medical", "health", "hurt",
        "back", "pots", "adhd", "anxiety", "never",
    ],
    "preference": [
        "like", "prefer", "enjoy", "love", "hate", "dislike", "favourite",
        "food", "eat", "drink", "taste", "music", "style",
    ],
    "pattern": [
        "usually", "often", "always", "habit", "routine", "train",
        "gym", "workout", "sleep", "wake", "morning", "evening",
        "mood", "feel", "energy",
    ],
    "decision": [
        "decided", "chose", "committed", "sober", "clean", "quit",
        "stopped", "started", "switched", "changed",
    ],
    "event": [
        "happened", "occurred", "today", "yesterday", "last week",
        "recently", "ago", "when", "date",
    ],
}

# Stopwords for keyword extraction
_STOPWORDS = {
    "i", "me", "my", "we", "you", "the", "a", "an", "is", "are", "was",
    "did", "do", "have", "had", "been", "how", "what", "when", "where",
    "today", "yesterday", "tomorrow", "just", "so", "and", "but", "or",
    "it", "that", "this", "in", "on", "at", "to", "for", "of", "with",
    "can", "will", "would", "should", "could", "not", "no", "yes", "ok",
    "then", "than", "also", "some", "get", "got", "its", "they", "them",
}

# ---------------------------------------------------------------------------
# Schema bootstrap (called once on first Neo4j connection)
# ---------------------------------------------------------------------------

_SCHEMA_ENSURED = False


def _ensure_new_schema() -> None:
    """Idempotently create Constraint and Event schema on first use."""
    global _SCHEMA_ENSURED
    if _SCHEMA_ENSURED:
        return

    from core.graph_memory import _get_driver  # noqa: PLC0415

    driver = _get_driver()
    if not driver:
        return

    def _safe(session, query: str) -> None:
        try:
            session.run(query)
        except Exception as exc:
            low = str(exc).lower()
            if "already exists" not in low and "equivalent" not in low:
                logger.debug(f"Schema op skipped: {exc}")

    try:
        with driver.session() as s:
            _safe(s, "CREATE CONSTRAINT constraint_id IF NOT EXISTS FOR (c:Constraint) REQUIRE c.constraint_id IS UNIQUE")
            _safe(s, "CREATE CONSTRAINT event_id IF NOT EXISTS FOR (e:Event) REQUIRE e.event_id IS UNIQUE")
            _safe(s, "CREATE INDEX constraint_user IF NOT EXISTS FOR (c:Constraint) ON (c.user_id)")
            _safe(s, "CREATE INDEX event_user IF NOT EXISTS FOR (e:Event) ON (e.user_id)")
        _SCHEMA_ENSURED = True
        logger.debug("neo4j_memory: new schema ensured")
    except Exception as exc:
        logger.debug(f"neo4j_memory: schema setup failed (non-fatal): {exc}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _stable_id(user_id: str, text: str) -> str:
    """Deterministic 16-char hex ID from user + text (first 80 chars)."""
    raw = f"{user_id}:{text[:80]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _infer_categories(message: str) -> list[str]:
    """Infer relevant fact categories from message keywords."""
    lower = message.lower()
    matched = []
    for category, keywords in _CATEGORY_KEYWORDS.items():
        if any(kw in lower for kw in keywords):
            matched.append(category)
    # Always include core identity categories
    for always in ("biographical", "constraint", "goal"):
        if always not in matched:
            matched.append(always)
    return matched


def _extract_keywords(message: str) -> list[str]:
    """Extract meaningful nouns/terms from message text."""
    words = re.findall(r'\b[a-z]{3,}\b', message.lower())
    seen: set[str] = set()
    result = []
    for w in words:
        if w not in _STOPWORDS and w not in seen:
            seen.add(w)
            result.append(w)
        if len(result) >= 15:
            break
    return result


def _format_facts_as_prompt(facts: list[dict]) -> str:
    """
    Format a deduplicated, sorted list of fact dicts as the === WHAT YOU KNOW === block.
    Each dict must have keys: text, category, confidence.
    """
    if not facts:
        return ""

    by_cat: dict[str, list[dict]] = {}
    for f in facts:
        cat = f.get("category") or "general"
        by_cat.setdefault(cat, []).append(f)

    lines = ["=== WHAT YOU KNOW ABOUT THIS USER ==="]
    for cat in sorted(by_cat.keys()):
        lines.append(f"\n[{cat}]")
        for f in by_cat[cat]:
            conf = f.get("confidence", 1.0)
            lines.append(f"- {f['text']} (confidence: {conf:.2f})")

    return "\n".join(lines)


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences that Haiku sometimes wraps JSON in."""
    text = text.strip()
    # Remove ```json ... ``` or ``` ... ```
    text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*```$', '', text)
    return text.strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def retrieve(message: str, user_id: str, agent_id: str) -> str:
    """
    Return a formatted memory block for this user relevant to the message.
    Zero API calls — pure Cypher, 3 parallel queries.
    Returns empty string if Neo4j is unavailable.
    """
    from core.graph_memory import _get_driver  # noqa: PLC0415

    driver = _get_driver()
    if not driver:
        return ""

    _ensure_new_schema()

    categories = _infer_categories(message)
    keywords = _extract_keywords(message)

    # Build the keyword WHERE fragment once (used in query 2)
    if keywords:
        kw_conditions = " OR ".join(
            f"toLower(f.text) CONTAINS '{kw.replace(chr(39), '')}'"
            for kw in keywords[:10]
        )
    else:
        kw_conditions = "false"

    # --- Query functions (run in parallel) ---

    def _query_category(session_factory) -> list[dict]:
        try:
            with session_factory() as s:
                result = s.run(
                    """
                    MATCH (u:User {user_id: $uid})-[:HAS_FACT]->(f:Fact)
                    WHERE f.category IN $cats
                    RETURN f.text AS text, f.category AS category,
                           f.confidence AS confidence, f.updated_at AS updated_at
                    ORDER BY f.confidence DESC, f.updated_at DESC
                    LIMIT 50
                    """,
                    uid=user_id,
                    cats=categories,
                )
                return [dict(r) for r in result]
        except Exception as exc:
            logger.debug(f"retrieve._query_category failed: {exc}")
            return []

    def _query_keyword(session_factory) -> list[dict]:
        if not keywords:
            return []
        try:
            with session_factory() as s:
                result = s.run(
                    f"""
                    MATCH (u:User {{user_id: $uid}})-[:HAS_FACT]->(f:Fact)
                    WHERE {kw_conditions}
                    RETURN f.text AS text, f.category AS category,
                           f.confidence AS confidence, f.updated_at AS updated_at
                    ORDER BY f.confidence DESC
                    LIMIT 30
                    """,
                    uid=user_id,
                )
                return [dict(r) for r in result]
        except Exception as exc:
            logger.debug(f"retrieve._query_keyword failed: {exc}")
            return []

    def _query_core(session_factory) -> list[dict]:
        try:
            with session_factory() as s:
                result = s.run(
                    """
                    MATCH (u:User {user_id: $uid})-[:HAS_FACT]->(f:Fact)
                    WHERE f.category IN ['constraint', 'goal', 'biographical']
                      AND f.confidence >= 0.9
                    RETURN f.text AS text, f.category AS category,
                           f.confidence AS confidence, f.updated_at AS updated_at
                    ORDER BY f.confidence DESC
                    LIMIT 20
                    """,
                    uid=user_id,
                )
                return [dict(r) for r in result]
        except Exception as exc:
            logger.debug(f"retrieve._query_core failed: {exc}")
            return []

    # Run all 3 in parallel
    all_rows: list[dict] = []
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = {
                pool.submit(_query_category, driver.session): "category",
                pool.submit(_query_keyword, driver.session): "keyword",
                pool.submit(_query_core, driver.session): "core",
            }
            for future in as_completed(futures):
                try:
                    all_rows.extend(future.result())
                except Exception as exc:
                    logger.debug(f"retrieve: future {futures[future]} raised: {exc}")
    except Exception as exc:
        logger.debug(f"retrieve: ThreadPoolExecutor failed: {exc}")
        return ""

    if not all_rows:
        return ""

    # Deduplicate by text (case-insensitive, first 80 chars as key)
    seen: set[str] = set()
    deduped: list[dict] = []
    for row in all_rows:
        key = (row.get("text") or "")[:80].lower()
        if key and key not in seen:
            seen.add(key)
            deduped.append(row)

    # Sort: confidence DESC, updated_at DESC
    def _sort_key(r: dict):
        conf = r.get("confidence") or 0.0
        upd = r.get("updated_at") or ""
        return (-float(conf), str(upd))

    deduped.sort(key=_sort_key)
    top50 = deduped[:50]

    return _format_facts_as_prompt(top50)


def extract(conversation: list[dict], user_id: str, agent_id: str) -> None:
    """
    Extract facts, constraints, events and plan notes from a conversation.
    1 Haiku call → structured JSON → Neo4j writes.
    Fire-and-forget: all errors are logged, never raised.
    """
    try:
        _extract_inner(conversation, user_id, agent_id)
    except Exception as exc:
        logger.warning(f"neo4j_memory.extract failed (non-fatal): {exc}")


def _extract_inner(conversation: list[dict], user_id: str, agent_id: str) -> None:
    """Inner implementation — called by extract(), which wraps it in try/except."""
    from core.graph_memory import _get_driver  # noqa: PLC0415

    driver = _get_driver()
    if not driver:
        logger.debug("neo4j_memory.extract: Neo4j unavailable, skipping")
        return

    _ensure_new_schema()

    if not conversation:
        return

    # Build conversation text for the Haiku prompt
    conv_lines = []
    for turn in conversation:
        role = turn.get("role", "unknown")
        content = turn.get("content", "")
        conv_lines.append(f"{role.upper()}: {content}")
    conv_text = "\n".join(conv_lines)

    system_prompt = (
        "You are a memory extraction system. Extract facts, constraints, events "
        "and plan notes from this conversation. Be precise. Only extract things "
        "explicitly stated or clearly implied."
    )

    user_prompt = f"""Here is the conversation to analyse:

{conv_text}

Extract all relevant memory from this conversation and return ONLY valid JSON in this exact schema:

{{
  "facts": [
    {{
      "text": "...",
      "category": "biographical|goal|constraint|pattern|preference|event",
      "confidence": 0.0,
      "supersedes": "exact text of fact this replaces, or null"
    }}
  ],
  "constraints": [
    {{
      "text": "...",
      "active": true
    }}
  ],
  "events": [
    {{
      "description": "...",
      "date": "YYYY-MM-DD or null",
      "outcome": "..."
    }}
  ],
  "plan_note": "one line summary of any plan change, or null"
}}

Return only the JSON object. No explanation."""

    # Call Haiku
    import anthropic  # noqa: PLC0415

    client = anthropic.Anthropic()
    response = client.messages.create(
        model=_HAIKU_MODEL,
        max_tokens=_HAIKU_MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = response.content[0].text if response.content else ""
    clean_text = _strip_code_fences(raw_text)

    try:
        extracted = json.loads(clean_text)
    except json.JSONDecodeError as exc:
        logger.warning(f"neo4j_memory.extract: JSON parse failed: {exc}\nRaw: {raw_text[:300]}")
        return

    now = datetime.now(timezone.utc).isoformat()

    with driver.session() as session:
        # Ensure User node exists
        session.run(
            "MERGE (u:User {user_id: $uid}) ON CREATE SET u.agent_id = $aid, u.created_at = $now",
            uid=user_id, aid=agent_id, now=now,
        )

        # --- Write facts ---
        for fact in extracted.get("facts") or []:
            text = (fact.get("text") or "").strip()
            if not text:
                continue
            category = fact.get("category") or "general"
            confidence = float(fact.get("confidence") or 1.0)
            supersedes_text = fact.get("supersedes")
            fact_id = _stable_id(user_id, text)

            session.run(
                """
                MERGE (f:Fact {fact_id: $fid})
                ON CREATE SET
                    f.user_id    = $uid,
                    f.agent_id   = $aid,
                    f.text       = $text,
                    f.category   = $cat,
                    f.confidence = $conf,
                    f.created_at = $now,
                    f.updated_at = $now
                ON MATCH SET
                    f.text       = $text,
                    f.confidence = $conf,
                    f.updated_at = $now
                """,
                fid=fact_id, uid=user_id, aid=agent_id,
                text=text, cat=category, conf=confidence, now=now,
            )
            # Link Fact to User
            session.run(
                """
                MATCH (u:User {user_id: $uid})
                MATCH (f:Fact {fact_id: $fid})
                MERGE (u)-[:HAS_FACT]->(f)
                """,
                uid=user_id, fid=fact_id,
            )
            # SUPERSEDES relationship
            if supersedes_text:
                old_id = _stable_id(user_id, supersedes_text)
                session.run(
                    """
                    MATCH (new:Fact {fact_id: $new_id})
                    MERGE (old:Fact {fact_id: $old_id})
                    ON CREATE SET old.user_id = $uid, old.text = $old_text,
                                  old.category = 'archived', old.confidence = 0.0,
                                  old.created_at = $now, old.updated_at = $now
                    MERGE (new)-[:SUPERSEDES]->(old)
                    """,
                    new_id=fact_id, old_id=old_id,
                    uid=user_id, old_text=supersedes_text, now=now,
                )

        # --- Write constraints ---
        for constraint in extracted.get("constraints") or []:
            text = (constraint.get("text") or "").strip()
            if not text:
                continue
            active = bool(constraint.get("active", True))
            constraint_id = _stable_id(user_id, text)

            session.run(
                """
                MERGE (c:Constraint {constraint_id: $cid})
                ON CREATE SET
                    c.user_id    = $uid,
                    c.agent_id   = $aid,
                    c.text       = $text,
                    c.active     = $active,
                    c.created_at = $now,
                    c.updated_at = $now
                ON MATCH SET
                    c.text       = $text,
                    c.active     = $active,
                    c.updated_at = $now
                """,
                cid=constraint_id, uid=user_id, aid=agent_id,
                text=text, active=active, now=now,
            )
            session.run(
                """
                MATCH (u:User {user_id: $uid})
                MATCH (c:Constraint {constraint_id: $cid})
                MERGE (u)-[:HAS_CONSTRAINT]->(c)
                """,
                uid=user_id, cid=constraint_id,
            )

        # --- Write events ---
        for event in extracted.get("events") or []:
            description = (event.get("description") or "").strip()
            if not description:
                continue
            event_date = event.get("date")
            outcome = (event.get("outcome") or "").strip()
            event_id = _stable_id(user_id, description)

            session.run(
                """
                MERGE (e:Event {event_id: $eid})
                ON CREATE SET
                    e.user_id     = $uid,
                    e.agent_id    = $aid,
                    e.description = $desc,
                    e.date        = $date,
                    e.outcome     = $outcome,
                    e.created_at  = $now
                ON MATCH SET
                    e.description = $desc,
                    e.date        = $date,
                    e.outcome     = $outcome
                """,
                eid=event_id, uid=user_id, aid=agent_id,
                desc=description, date=event_date, outcome=outcome, now=now,
            )
            session.run(
                """
                MATCH (u:User {user_id: $uid})
                MATCH (e:Event {event_id: $eid})
                MERGE (u)-[:EXPERIENCED]->(e)
                """,
                uid=user_id, eid=event_id,
            )

    # --- Append plan_note to agent's CONTEXT.md ---
    plan_note = (extracted.get("plan_note") or "").strip()
    if plan_note:
        context_path = BASE_DIR / "agents" / agent_id / "state" / "CONTEXT.md"
        try:
            context_path.parent.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            with open(context_path, "a", encoding="utf-8") as fh:
                fh.write(f"\n<!-- plan_note {timestamp} -->\n{plan_note}\n")
            logger.debug(f"neo4j_memory: plan_note appended to {context_path}")
        except Exception as exc:
            logger.warning(f"neo4j_memory: could not write plan_note to {context_path}: {exc}")

    logger.debug(
        f"neo4j_memory.extract: wrote "
        f"{len(extracted.get('facts') or [])} facts, "
        f"{len(extracted.get('constraints') or [])} constraints, "
        f"{len(extracted.get('events') or [])} events "
        f"for {user_id}/{agent_id}"
    )


def get_constraints(user_id: str, agent_id: str) -> list[str]:
    """
    Return active constraints for a user.
    Zero API calls — pure Cypher.
    Returns empty list if Neo4j is unavailable.
    """
    from core.graph_memory import _get_driver  # noqa: PLC0415

    driver = _get_driver()
    if not driver:
        return []

    _ensure_new_schema()

    try:
        with driver.session() as s:
            result = s.run(
                "MATCH (u:User {user_id: $uid})-[:HAS_CONSTRAINT]->(c:Constraint {active: true}) "
                "RETURN c.text AS text",
                uid=user_id,
            )
            return [r["text"] for r in result if r["text"]]
    except Exception as exc:
        logger.debug(f"neo4j_memory.get_constraints failed (non-fatal): {exc}")
        return []
