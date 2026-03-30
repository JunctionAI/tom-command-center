"""
graph_memory.py — Neo4j Graph Memory Layer
===========================================

Sits ALONGSIDE SQLite (user_memory.py), not replacing it.
SQLite = primary fact store (writes, history, all facts)
Neo4j  = relationship intelligence layer (targeted retrieval, conflict detection, temporal chains)

SETUP (Tom does this once):
1. Go to https://neo4j.com/cloud/aura-free → create free instance
2. Get connection URI (neo4j+s://xxxxx.databases.neo4j.io) + password
3. Add 3 Railway env vars:
   - NEO4J_URI      → the URI above
   - NEO4J_USERNAME → neo4j  (default)
   - NEO4J_PASSWORD → your password
4. Deploy — graph_memory.py gracefully no-ops if env vars are missing

ARCHITECTURE:
- Nodes:  User, Fact, Goal, Condition, Supplement, Decision
- Edges:  HAS_FACT, SUPPORTS_GOAL, INDICATES_CONDITION, TAKES,
          TARGETS_CONDITION, CONFLICTS_WITH, SUPERSEDES

KEY FUNCTIONS:
- sync_facts_to_graph(user_id, agent_id, facts)
    Called after extract_and_store_memories() — fire-and-forget, wrapped in try/except
- query_relevant_context(user_id, agent_id, message_text, top_k=50)
    Returns top-K facts most relevant to the current message
    Replaces loading all 500 facts → saves ~6,750 tokens/interaction
- detect_conflicts(user_id, agent_id)
    Returns pairs of contradictory facts
- get_temporal_chain(user_id, topic)
    Shows how a fact evolved over time (e.g. sobriety streak)
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

_driver = None
_GRAPH_AVAILABLE = False


def _get_driver():
    """Lazy-initialise the Neo4j driver. Returns None if env vars not set."""
    global _driver, _GRAPH_AVAILABLE

    if _driver is not None:
        return _driver

    uri = os.environ.get("NEO4J_URI")
    username = os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")

    if not uri or not password:
        # Silently no-op — graph layer is optional
        return None

    try:
        from neo4j import GraphDatabase
        _driver = GraphDatabase.driver(uri, auth=(username, password))
        _driver.verify_connectivity()
        _GRAPH_AVAILABLE = True
        logger.info("Neo4j graph memory: connected")
        _ensure_schema()
        return _driver
    except Exception as e:
        logger.warning(f"Neo4j unavailable (non-fatal, using SQLite only): {e}")
        _driver = None
        return None


def is_available() -> bool:
    return _get_driver() is not None


# ---------------------------------------------------------------------------
# Schema bootstrap
# ---------------------------------------------------------------------------

def _ensure_schema():
    """Create constraints and indexes on first connect."""
    driver = _get_driver()
    if not driver:
        return
    with driver.session() as s:
        # Uniqueness constraints (idempotent)
        _safe_run(s, "CREATE CONSTRAINT user_id IF NOT EXISTS FOR (u:User) REQUIRE u.user_id IS UNIQUE")
        _safe_run(s, "CREATE CONSTRAINT fact_id IF NOT EXISTS FOR (f:Fact) REQUIRE f.fact_id IS UNIQUE")
        # Indexes for fast lookup
        _safe_run(s, "CREATE INDEX fact_user IF NOT EXISTS FOR (f:Fact) ON (f.user_id)")
        _safe_run(s, "CREATE INDEX fact_category IF NOT EXISTS FOR (f:Fact) ON (f.category)")
        _safe_run(s, "CREATE INDEX supplement_name IF NOT EXISTS FOR (s:Supplement) ON (s.name, s.user_id)")
        _safe_run(s, "CREATE INDEX condition_name IF NOT EXISTS FOR (c:Condition) ON (c.name, c.user_id)")
    logger.info("Neo4j schema ensured")


def _safe_run(session, query: str, **params):
    try:
        session.run(query, **params)
    except Exception as e:
        # Schema operations are idempotent — ignore "already exists" errors
        if "already exists" not in str(e).lower() and "equivalent" not in str(e).lower():
            logger.debug(f"Schema op skipped: {e}")


# ---------------------------------------------------------------------------
# Core node patterns extracted from facts
# ---------------------------------------------------------------------------

# Simple keyword patterns to classify facts into richer node types
_SUPPLEMENT_WORDS = {
    "omega-3", "fish oil", "magnesium", "ginkgo", "creatine", "vitamin d", "b complex",
    "5-htp", "green lipped mussel", "glutamine", "probiotic", "terbinafine", "vyvanse",
    "methylphenidate", "ssri", "melatonin", "zinc", "iron", "collagen", "protein powder",
    "l-theanine", "ashwagandha", "rhodiola", "nad+", "nmn", "berberine",
}

_CONDITION_WORDS = {
    "adhd", "anxiety", "depression", "back pain", "l5/s1", "pots", "c-ptsd", "ptsd",
    "concussion", "tbi", "pcs", "sleep apnoea", "insomnia", "ocd", "dysautonomia",
    "central sensitization", "neuroplastic", "inflammation", "gut", "ibs",
}

_GOAL_WORDS = {
    "goal", "want to", "aim to", "trying to", "working towards", "building",
    "planning to", "hoping to", "target", "milestone",
}


def _classify_fact(fact_text: str) -> str:
    """Return 'supplement', 'condition', 'goal', or 'fact'."""
    lower = fact_text.lower()
    if any(w in lower for w in _SUPPLEMENT_WORDS):
        return "supplement"
    if any(w in lower for w in _CONDITION_WORDS):
        return "condition"
    if any(w in lower for w in _GOAL_WORDS):
        return "goal"
    return "fact"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sync_facts_to_graph(user_id: str, agent_id: str, facts: list[dict]):
    """
    Mirror new/updated facts from SQLite to Neo4j.
    Fire-and-forget — wrapped in try/except so it can never break main flow.

    Called after extract_and_store_memories() with the list of new facts.
    Each fact dict should have: {fact, category, confidence, fact_id (optional)}
    """
    driver = _get_driver()
    if not driver:
        return

    try:
        with driver.session() as session:
            # Ensure User node exists
            session.run(
                "MERGE (u:User {user_id: $uid}) ON CREATE SET u.agent_id = $aid",
                uid=user_id, aid=agent_id
            )

            for f in facts:
                fact_text = f.get("fact", "")
                category = f.get("category", "general")
                confidence = float(f.get("confidence", 1.0))
                fact_id = f.get("fact_id") or f.get("id") or _make_fact_id(user_id, fact_text)
                node_type = _classify_fact(fact_text)
                now = datetime.utcnow().isoformat()

                # Upsert the Fact node
                session.run("""
                    MERGE (f:Fact {fact_id: $fid})
                    ON CREATE SET
                        f.user_id   = $uid,
                        f.agent_id  = $aid,
                        f.text      = $text,
                        f.category  = $cat,
                        f.node_type = $ntype,
                        f.confidence = $conf,
                        f.created_at = $now,
                        f.updated_at = $now
                    ON MATCH SET
                        f.text       = $text,
                        f.confidence = $conf,
                        f.updated_at = $now
                """, fid=fact_id, uid=user_id, aid=agent_id, text=fact_text,
                     cat=category, ntype=node_type, conf=confidence, now=now)

                # Link to User
                session.run("""
                    MATCH (u:User {user_id: $uid})
                    MATCH (f:Fact {fact_id: $fid})
                    MERGE (u)-[:HAS_FACT]->(f)
                """, uid=user_id, fid=fact_id)

                # Create typed sub-nodes for richer relationships
                if node_type == "supplement":
                    _upsert_supplement_node(session, user_id, fact_text, fact_id)
                elif node_type == "condition":
                    _upsert_condition_node(session, user_id, fact_text, fact_id)
                elif node_type == "goal":
                    _upsert_goal_node(session, user_id, fact_text, fact_id)

        logger.debug(f"Graph sync: {len(facts)} facts for {user_id}/{agent_id}")

    except Exception as e:
        logger.warning(f"Graph sync failed (non-fatal, SQLite still primary): {e}")


def query_relevant_context(user_id: str, agent_id: str, message_text: str,
                           top_k: int = 50) -> list[dict]:
    """
    Return top-K facts most relevant to the current message using keyword + category matching.
    Falls back to empty list if Neo4j unavailable (SQLite loader handles it).

    This is the token-saver: instead of loading 500 facts, load only the ~50 most
    relevant to this specific conversation turn.

    Returns list of {fact, category, confidence, node_type} dicts.
    """
    driver = _get_driver()
    if not driver:
        return []

    try:
        # Extract likely relevant categories from message
        relevant_categories = _infer_categories(message_text)
        keywords = _extract_keywords(message_text)

        with driver.session() as session:
            # Strategy 1: category match (high precision)
            category_facts = []
            if relevant_categories:
                result = session.run("""
                    MATCH (u:User {user_id: $uid})-[:HAS_FACT]->(f:Fact)
                    WHERE f.category IN $cats
                    RETURN f.text AS fact, f.category AS category,
                           f.confidence AS confidence, f.node_type AS node_type
                    ORDER BY f.confidence DESC, f.updated_at DESC
                    LIMIT $lim
                """, uid=user_id, cats=relevant_categories, lim=top_k)
                category_facts = [dict(r) for r in result]

            # Strategy 2: keyword match against fact text
            keyword_facts = []
            if keywords:
                # Build case-insensitive keyword filter
                kw_filter = " OR ".join([f"toLower(f.text) CONTAINS '{kw}'" for kw in keywords[:8]])
                result = session.run(f"""
                    MATCH (u:User {{user_id: $uid}})-[:HAS_FACT]->(f:Fact)
                    WHERE {kw_filter}
                    RETURN f.text AS fact, f.category AS category,
                           f.confidence AS confidence, f.node_type AS node_type
                    ORDER BY f.confidence DESC
                    LIMIT $lim
                """, uid=user_id, lim=top_k // 2)
                keyword_facts = [dict(r) for r in result]

            # Strategy 3: always include high-confidence constraint/biographical facts
            core_facts = []
            result = session.run("""
                MATCH (u:User {user_id: $uid})-[:HAS_FACT]->(f:Fact)
                WHERE f.category IN ['constraint', 'biographical', 'goal'] AND f.confidence >= 0.9
                RETURN f.text AS fact, f.category AS category,
                       f.confidence AS confidence, f.node_type AS node_type
                ORDER BY f.confidence DESC
                LIMIT 20
            """, uid=user_id)
            core_facts = [dict(r) for r in result]

            # Merge and deduplicate
            seen = set()
            combined = []
            for fact in (core_facts + category_facts + keyword_facts):
                key = fact.get("fact", "")[:80]
                if key not in seen:
                    seen.add(key)
                    combined.append(fact)
                if len(combined) >= top_k:
                    break

            return combined

    except Exception as e:
        logger.warning(f"Graph query failed (non-fatal): {e}")
        return []


def detect_conflicts(user_id: str, agent_id: str) -> list[dict]:
    """
    Detect potentially contradictory facts for this user.
    Returns list of {fact_a, fact_b, reason} dicts.
    Currently uses pattern matching; can be upgraded with Claude comparison.
    """
    driver = _get_driver()
    if not driver:
        return []

    try:
        with driver.session() as session:
            # Look for CONFLICTS_WITH relationships (set during sync)
            result = session.run("""
                MATCH (u:User {user_id: $uid})-[:HAS_FACT]->(a:Fact)-[:CONFLICTS_WITH]->(b:Fact)
                RETURN a.text AS fact_a, b.text AS fact_b
                LIMIT 10
            """, uid=user_id)
            conflicts = [{"fact_a": r["fact_a"], "fact_b": r["fact_b"],
                          "reason": "Flagged as conflicting"} for r in result]

            # Also: simple heuristic — same category facts with opposite sentiment
            # (e.g., "does not drink alcohol" vs "had beers last night")
            sobriety_result = session.run("""
                MATCH (u:User {user_id: $uid})-[:HAS_FACT]->(f:Fact)
                WHERE f.category IN ['pattern', 'constraint', 'decision']
                  AND (toLower(f.text) CONTAINS 'sober' OR toLower(f.text) CONTAINS 'clean'
                       OR toLower(f.text) CONTAINS 'alcohol free' OR toLower(f.text) CONTAINS 'no alcohol')
                RETURN f.text AS fact
                LIMIT 5
            """, uid=user_id)
            sober_facts = [r["fact"] for r in sobriety_result]

            drinking_result = session.run("""
                MATCH (u:User {user_id: $uid})-[:HAS_FACT]->(f:Fact)
                WHERE toLower(f.text) CONTAINS 'drinks' OR toLower(f.text) CONTAINS 'had a beer'
                   OR toLower(f.text) CONTAINS 'had beers' OR toLower(f.text) CONTAINS 'had drinks'
                RETURN f.text AS fact
                LIMIT 5
            """, uid=user_id)
            drinking_facts = [r["fact"] for r in drinking_result]

            if sober_facts and drinking_facts:
                for sf in sober_facts[:2]:
                    for df in drinking_facts[:2]:
                        conflicts.append({
                            "fact_a": sf, "fact_b": df,
                            "reason": "Sobriety claim vs reported drinking behaviour"
                        })

            return conflicts

    except Exception as e:
        logger.warning(f"Conflict detection failed (non-fatal): {e}")
        return []


def get_temporal_chain(user_id: str, topic: str, limit: int = 10) -> list[dict]:
    """
    Return facts about a topic ordered by creation time — shows how something evolved.
    E.g., topic='sober' returns the sobriety journey in order.
    """
    driver = _get_driver()
    if not driver:
        return []

    try:
        with driver.session() as session:
            result = session.run("""
                MATCH (u:User {user_id: $uid})-[:HAS_FACT]->(f:Fact)
                WHERE toLower(f.text) CONTAINS toLower($topic)
                RETURN f.text AS fact, f.category AS category,
                       f.created_at AS created_at, f.confidence AS confidence
                ORDER BY f.created_at ASC
                LIMIT $lim
            """, uid=user_id, topic=topic, lim=limit)
            return [dict(r) for r in result]
    except Exception as e:
        logger.warning(f"Temporal chain failed (non-fatal): {e}")
        return []


def get_supplement_condition_chains(user_id: str) -> list[dict]:
    """
    Return Supplement→Condition relationships (what supplements target which conditions).
    Useful for safety checks: does this supplement conflict with another? Does it
    target a known condition?
    """
    driver = _get_driver()
    if not driver:
        return []

    try:
        with driver.session() as session:
            result = session.run("""
                MATCH (u:User {user_id: $uid})
                MATCH (s:Supplement {user_id: $uid})-[r:TARGETS_CONDITION]->(c:Condition {user_id: $uid})
                RETURN s.name AS supplement, c.name AS condition,
                       r.evidence_level AS evidence_level
                LIMIT 30
            """, uid=user_id)
            return [dict(r) for r in result]
    except Exception as e:
        logger.warning(f"Supplement-condition chains failed (non-fatal): {e}")
        return []


def format_graph_context_for_prompt(user_id: str, agent_id: str,
                                     message_text: str) -> str:
    """
    Format relevant graph-retrieved facts as a prompt section.
    Drop-in replacement for the full fact dump in load_user_memory().
    Returns empty string if Neo4j unavailable.
    """
    facts = query_relevant_context(user_id, agent_id, message_text, top_k=50)
    if not facts:
        return ""

    # Group by category for readable output
    by_cat: dict[str, list] = {}
    for f in facts:
        cat = f.get("category", "general")
        by_cat.setdefault(cat, []).append(f.get("fact", ""))

    lines = ["=== WHAT YOU KNOW ABOUT THIS PERSON (graph-retrieved, most relevant) ==="]
    for cat, fact_list in sorted(by_cat.items()):
        lines.append(f"\n{cat.upper()}:")
        for fact in fact_list[:15]:  # cap per category
            lines.append(f"  - {fact}")

    # Add any detected conflicts as a warning
    conflicts = detect_conflicts(user_id, agent_id)
    if conflicts:
        lines.append("\n⚠️ CONFLICTING FACTS DETECTED:")
        for c in conflicts[:3]:
            lines.append(f"  - '{c['fact_a']}' vs '{c['fact_b']}' ({c['reason']})")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _make_fact_id(user_id: str, fact_text: str) -> str:
    """Deterministic ID from user + fact text (first 60 chars)."""
    import hashlib
    raw = f"{user_id}:{fact_text[:60]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _infer_categories(text: str) -> list[str]:
    """Guess which fact categories are relevant to this message."""
    lower = text.lower()
    cats = []
    if any(w in lower for w in ["eat", "food", "protein", "shake", "calories", "diet", "nutrition"]):
        cats.append("preference")
    if any(w in lower for w in ["train", "gym", "workout", "exercise", "session", "push", "pull", "legs"]):
        cats.append("pattern")
    if any(w in lower for w in ["back", "pain", "hurt", "injury", "sore", "tension", "pots", "heart"]):
        cats.append("constraint")
    if any(w in lower for w in ["supplement", "pill", "take", "omega", "magnesium", "vitamin", "vyvanse"]):
        cats.append("constraint")
    if any(w in lower for w in ["goal", "target", "want", "plan", "build", "achieve"]):
        cats.append("goal")
    if any(w in lower for w in ["sober", "clean", "weed", "alcohol", "substance", "drink"]):
        cats.append("decision")
    if any(w in lower for w in ["feel", "mood", "anxiety", "stress", "emotion", "mental"]):
        cats.append("pattern")
    if any(w in lower for w in ["sleep", "woke", "night", "tired", "rest", "hours"]):
        cats.append("pattern")
    # Always include biographical and context
    cats += ["biographical", "context"]
    return list(set(cats))


def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful keywords from message (excluding stopwords)."""
    stopwords = {
        "i", "me", "my", "we", "you", "the", "a", "an", "is", "are", "was",
        "did", "do", "have", "had", "been", "how", "what", "when", "where",
        "today", "yesterday", "tomorrow", "just", "so", "and", "but", "or",
        "it", "that", "this", "in", "on", "at", "to", "for", "of", "with",
        "can", "will", "would", "should", "could", "not", "no", "yes", "ok"
    }
    words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    return [w for w in words if w not in stopwords][:15]


def _upsert_supplement_node(session, user_id: str, fact_text: str, fact_id: str):
    """Create or merge a Supplement node and link it to the Fact."""
    # Extract supplement name (first matching keyword)
    lower = fact_text.lower()
    supp_name = next((w for w in _SUPPLEMENT_WORDS if w in lower), None)
    if not supp_name:
        return
    session.run("""
        MERGE (s:Supplement {name: $name, user_id: $uid})
        WITH s
        MATCH (f:Fact {fact_id: $fid})
        MERGE (f)-[:RELATES_TO_SUPPLEMENT]->(s)
    """, name=supp_name.title(), uid=user_id, fid=fact_id)


def _upsert_condition_node(session, user_id: str, fact_text: str, fact_id: str):
    """Create or merge a Condition node and link it to the Fact."""
    lower = fact_text.lower()
    cond_name = next((w for w in _CONDITION_WORDS if w in lower), None)
    if not cond_name:
        return
    session.run("""
        MERGE (c:Condition {name: $name, user_id: $uid})
        WITH c
        MATCH (f:Fact {fact_id: $fid})
        MERGE (f)-[:INDICATES_CONDITION]->(c)
    """, name=cond_name.upper(), uid=user_id, fid=fact_id)


def _upsert_goal_node(session, user_id: str, fact_text: str, fact_id: str):
    """Create or merge a Goal node and link it to the Fact."""
    session.run("""
        MERGE (g:Goal {text: $text, user_id: $uid})
        ON CREATE SET g.created_at = $now
        WITH g
        MATCH (f:Fact {fact_id: $fid})
        MERGE (f)-[:SUPPORTS_GOAL]->(g)
    """, text=fact_text[:120], uid=user_id, fid=fact_id, now=datetime.utcnow().isoformat())
