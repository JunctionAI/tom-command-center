"""
ASMR Memory — Agentic Search and Memory Retrieval
Inspired by Supermemory's ~99% SOTA memory system (March 2026).

Architecture:
1. INGESTION: 3 parallel observer agents extract structured knowledge
   - Fact Hunter: Named entities, explicit statements, relationships
   - Context Weaver: Patterns, implications, cross-session correlations
   - Timeline Tracker: Temporal sequences, event chronology, knowledge updates

2. STORAGE: Structured findings in SQLite (no vector DB, no embeddings)
   - Findings linked to source sessions with timestamps
   - 6 knowledge vectors: personal, preferences, events, temporal, updates, health

3. RETRIEVAL: 3 parallel search agents reason over stored findings
   - Direct Seeker: Exact match, literal facts, recency-first
   - Inference Engine: Related context, implications, supporting evidence
   - Temporal Reasoner: Timeline reconstruction, state change tracking

4. LOADING: Assembled context replaces flat fact dump in agent prompts

Uses Haiku for all observer/search agents (~$0.005 total per conversation).
Falls back to legacy user_memory.py if ASMR fails.
"""

import sqlite3
import json
import logging
import threading
import concurrent.futures
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

HAIKU_MODEL = "claude-haiku-4-5-20251001"

# Knowledge vectors (structured categories for extraction)
KNOWLEDGE_VECTORS = [
    "personal",       # Name, age, identity, biographical facts
    "health",         # Symptoms, conditions, medications, biomarkers, diagnoses
    "preferences",    # Likes, dislikes, communication style, what works/doesn't
    "events",         # Specific incidents, appointments, milestones, experiences
    "temporal",       # Changes over time, progressions, phase transitions
    "updates",        # Corrections, supersessions, "actually..." statements
    "goals",          # What they want, targets, aspirations
    "relationships",  # People in their life, dynamics, support network
    "patterns",       # Recurring behaviors, triggers, symptom correlations
    "emotional",      # Mood states, fears, breakthroughs, emotional context
]


def _get_db():
    """Get the existing user_memory database."""
    db = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    db.row_factory = sqlite3.Row
    return db


def _ensure_asmr_schema(db):
    """Add ASMR tables to the existing user_memory database (idempotent)."""
    db.executescript("""
        -- Structured findings from observer agents
        CREATE TABLE IF NOT EXISTS knowledge_findings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            vector TEXT NOT NULL,
            finding TEXT NOT NULL,
            source_date TEXT NOT NULL,
            source_session_id TEXT,
            confidence REAL DEFAULT 1.0,
            is_current BOOLEAN DEFAULT 1,
            superseded_by INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_findings_user_vector
        ON knowledge_findings(user_id, vector, is_current);

        CREATE INDEX IF NOT EXISTS idx_findings_temporal
        ON knowledge_findings(user_id, source_date, is_current);

        -- Retrieval cache: stores assembled context from search agents
        CREATE TABLE IF NOT EXISTS retrieval_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            query_context TEXT NOT NULL,
            assembled_context TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_retrieval_cache
        ON retrieval_cache(user_id, agent_id, expires_at);
    """)
    db.commit()


def _call_haiku(prompt: str, max_tokens: int = 2000) -> str:
    """Call Haiku for cheap agent tasks."""
    import anthropic
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
        timeout=30.0,
    )
    return response.content[0].text.strip()


def _parse_json(text: str) -> list:
    """Parse JSON from Haiku response, handling markdown wrapping."""
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        result = json.loads(text)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        # Try to find JSON array in the text
        import re
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return []


# =============================================================================
# STAGE 1: PARALLEL OBSERVER AGENTS (Data Ingestion)
# =============================================================================

def _observer_fact_hunter(conversation: str, existing_findings: str) -> list:
    """Observer Agent 1: Extract explicit facts, entities, and relationships."""
    prompt = f"""You are a Fact Hunter — an observer agent that extracts EXPLICIT facts from conversations.

YOUR FOCUS:
- Named entities (people, places, medications, doctors, conditions)
- Explicit statements the user made about themselves
- Relationship mappings (who is who to the user)
- Direct quotes or strong claims

RULES:
- Only extract what was EXPLICITLY stated or directly quoted
- Include the source context (what was being discussed)
- Never infer or assume — that's another agent's job
- If the user corrected something, extract the CORRECTION, not the original

EXISTING KNOWLEDGE (for dedup — skip if already known):
{existing_findings[:3000]}

CONVERSATION:
{conversation}

Return ONLY a JSON array:
[{{"vector": "personal|health|preferences|relationships|goals", "finding": "fact text", "confidence": 1.0, "is_correction": false}}]

If correcting an existing finding, set is_correction=true and restate the corrected fact."""
    return _parse_json(_call_haiku(prompt))


def _observer_context_weaver(conversation: str, existing_findings: str) -> list:
    """Observer Agent 2: Extract patterns, implications, and cross-session correlations."""
    prompt = f"""You are a Context Weaver — an observer agent that identifies PATTERNS and IMPLICATIONS.

YOUR FOCUS:
- Patterns in behavior, symptoms, or mood the user may not explicitly state
- Implications of what was said (e.g., "I couldn't get out of bed" implies severe fatigue)
- Cross-references with existing knowledge (e.g., "tension worse today" + existing fact about sleep = possible correlation)
- Emotional undertones and psychological state
- What the user might be avoiding saying

RULES:
- Clearly mark findings as "implied" or "pattern" — never present implications as explicit facts
- Connect new information to existing knowledge where possible
- Note emotional context (was the user frustrated? hopeful? scared?)
- Confidence should be 0.6-0.8 for implications, 0.8-1.0 for clear patterns

EXISTING KNOWLEDGE (look for connections):
{existing_findings[:3000]}

CONVERSATION:
{conversation}

Return ONLY a JSON array:
[{{"vector": "patterns|emotional|preferences|health", "finding": "pattern or implication text", "confidence": 0.6-1.0, "context": "what prompted this observation"}}]"""
    return _parse_json(_call_haiku(prompt))


def _observer_timeline_tracker(conversation: str, existing_findings: str) -> list:
    """Observer Agent 3: Extract temporal sequences, changes, and knowledge updates."""
    prompt = f"""You are a Timeline Tracker — an observer agent that tracks CHANGES OVER TIME.

YOUR FOCUS:
- What changed since last known state? (e.g., "my HRV went up from 38 to 42")
- Temporal markers (when things happened, how long things lasted)
- Event chronology (sequence of events mentioned)
- Knowledge updates: when a fact REPLACES a previous one (e.g., "actually my tension has been better this week" supersedes "tension is constant")
- Phase transitions or milestone markers
- Duration tracking (how long has a symptom lasted, how many days of a practice)

RULES:
- Always note WHEN the change happened (date if given, or "today", "this week", "recently")
- If a finding supersedes existing knowledge, explicitly state what it replaces
- Track direction of change (improving, worsening, stable, fluctuating)
- This is CRITICAL for health companions — temporal accuracy is treatment-relevant

EXISTING KNOWLEDGE (check for things that may be outdated):
{existing_findings[:3000]}

CONVERSATION:
{conversation}

Return ONLY a JSON array:
[{{"vector": "temporal|health|updates", "finding": "temporal fact", "confidence": 0.8-1.0, "supersedes": "previous finding text or null", "direction": "improving|worsening|stable|fluctuating|new"}}]"""
    return _parse_json(_call_haiku(prompt))


def extract_with_observers(user_id: str, agent_id: str, conversation: list,
                            agent_display_name: str = ""):
    """
    Run 3 parallel observer agents to extract structured knowledge.
    This REPLACES the single extract_and_store_memories() call.
    Cost: ~$0.003 (3 Haiku calls) vs ~$0.001 (1 Haiku call). Still negligible.
    """
    if not conversation or len(conversation) < 2:
        return

    db = _get_db()
    _ensure_asmr_schema(db)
    now = datetime.now(NZ_TZ)
    today = now.date().isoformat()

    # Format conversation
    conv_text = ""
    for msg in conversation[-12:]:  # Last 12 messages
        speaker = "User" if msg["role"] == "user" else "Agent"
        conv_text += f"{speaker}: {msg['content'][:600]}\n\n"

    # Get existing findings for dedup context
    existing = db.execute("""
        SELECT vector, finding, source_date FROM knowledge_findings
        WHERE user_id = ? AND is_current = 1
        ORDER BY updated_at DESC LIMIT 80
    """, (user_id,)).fetchall()
    existing_text = "\n".join([f"[{r['vector']}|{r['source_date']}] {r['finding']}" for r in existing])

    # Run 3 observers in parallel
    all_findings = []
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(_observer_fact_hunter, conv_text, existing_text): "fact_hunter",
                executor.submit(_observer_context_weaver, conv_text, existing_text): "context_weaver",
                executor.submit(_observer_timeline_tracker, conv_text, existing_text): "timeline_tracker",
            }
            for future in concurrent.futures.as_completed(futures, timeout=45):
                observer_name = futures[future]
                try:
                    findings = future.result()
                    if findings:
                        for f in findings:
                            f["_observer"] = observer_name
                        all_findings.extend(findings)
                except Exception as e:
                    logger.warning(f"Observer {observer_name} failed: {e}")
    except Exception as e:
        logger.error(f"ASMR parallel extraction failed: {e}")
        # Fall back to legacy extraction
        from core.user_memory import extract_and_store_memories
        extract_and_store_memories(user_id, agent_id, conversation, agent_display_name)
        return

    if not all_findings:
        return

    # Store findings
    added = 0
    updated = 0
    for finding in all_findings:
        vector = finding.get("vector", "personal")
        if vector not in KNOWLEDGE_VECTORS:
            vector = "personal"

        text = finding.get("finding", "").strip()
        if not text:
            continue

        confidence = float(finding.get("confidence", 0.8))
        supersedes = finding.get("supersedes")
        is_correction = finding.get("is_correction", False)

        # Handle supersession
        if supersedes or is_correction:
            # Mark old finding as superseded
            old_rows = db.execute("""
                SELECT id FROM knowledge_findings
                WHERE user_id = ? AND is_current = 1 AND finding LIKE ?
                LIMIT 1
            """, (user_id, f"%{supersedes[:50] if supersedes else text[:30]}%")).fetchall()

            for old in old_rows:
                db.execute("""
                    UPDATE knowledge_findings SET is_current = 0, updated_at = ?
                    WHERE id = ?
                """, (now.isoformat(), old["id"]))
                updated += 1

        # Check for duplicate
        dup = db.execute("""
            SELECT id FROM knowledge_findings
            WHERE user_id = ? AND vector = ? AND finding = ? AND is_current = 1
            LIMIT 1
        """, (user_id, vector, text)).fetchone()

        if dup:
            continue  # Skip exact duplicate

        # Insert new finding
        db.execute("""
            INSERT INTO knowledge_findings
            (user_id, agent_id, vector, finding, source_date, confidence,
             is_current, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        """, (user_id, agent_id, vector, text, today, confidence,
              now.isoformat(), now.isoformat()))
        added += 1

    db.commit()
    db.close()

    if added > 0 or updated > 0:
        logger.info(f"ASMR extraction for {agent_id}/{user_id}: "
                    f"+{added} findings, ~{updated} superseded "
                    f"({len(all_findings)} total from 3 observers)")

    # Also run legacy extraction as backup (populates user_facts for backwards compat)
    try:
        from core.user_memory import extract_and_store_memories
        extract_and_store_memories(user_id, agent_id, conversation, agent_display_name)
    except Exception as e:
        logger.warning(f"Legacy extraction backup failed (non-fatal): {e}")


# =============================================================================
# STAGE 3: ACTIVE SEARCH AGENTS (Retrieval)
# =============================================================================

def _search_direct_seeker(query_context: str, findings_text: str) -> str:
    """Search Agent 1: Find exact matches, literal facts, recency-first."""
    prompt = f"""You are a Direct Seeker — a search agent that finds EXACT, RELEVANT facts.

Given the current conversation context, find the most directly relevant facts from the knowledge store.
Prioritize RECENT facts over old ones. If two facts conflict, prefer the more recent one.

CURRENT CONTEXT (what the user is talking about right now):
{query_context[:1500]}

KNOWLEDGE STORE:
{findings_text[:6000]}

Return ONLY the relevant facts, one per line. Include the date if available.
Prefix each with its relevance: [DIRECT] for exact match, [RELATED] for close match.
Maximum 15 facts. Most relevant first."""
    return _call_haiku(prompt, max_tokens=1500)


def _search_inference_engine(query_context: str, findings_text: str) -> str:
    """Search Agent 2: Find related context, implications, and supporting evidence."""
    prompt = f"""You are an Inference Engine — a search agent that finds CONTEXTUAL CONNECTIONS.

Given the current conversation, find facts that are not directly mentioned but provide important context.
Look for: implications, correlations, emotional context, related patterns, supporting evidence.

CURRENT CONTEXT:
{query_context[:1500]}

KNOWLEDGE STORE:
{findings_text[:6000]}

Return ONLY contextually relevant findings, one per line.
Prefix each: [CONTEXT] for background info, [PATTERN] for behavioral patterns, [EMOTIONAL] for emotional context.
Maximum 10 findings. Explain briefly WHY each is relevant."""
    return _call_haiku(prompt, max_tokens=1500)


def _search_temporal_reasoner(query_context: str, findings_text: str) -> str:
    """Search Agent 3: Reconstruct timelines, track state changes, resolve contradictions."""
    prompt = f"""You are a Temporal Reasoner — a search agent that tracks CHANGES OVER TIME.

Given the current conversation, reconstruct the relevant timeline. When facts contradict, determine which is MORE RECENT and flag the outdated one.

CRITICAL: If the knowledge store contains BOTH an old state and a new state for the same fact, ONLY return the current state. Flag what changed.

CURRENT CONTEXT:
{query_context[:1500]}

KNOWLEDGE STORE:
{findings_text[:6000]}

Return a brief timeline of relevant changes, formatted:
[CURRENT] fact that is currently true
[CHANGED] what changed from X to Y (date if known)
[OUTDATED] fact that is no longer true — DO NOT use this in responses
Maximum 10 entries. Most recent state first."""
    return _call_haiku(prompt, max_tokens=1500)


def retrieve_active_memory(user_id: str, agent_id: str,
                            current_context: str) -> str:
    """
    Run 3 parallel search agents to assemble relevant memory context.
    This REPLACES the flat load_user_memory() fact dump.

    current_context: the user's latest message + recent conversation
    Returns: assembled memory context string for injection into agent prompt

    Cost: ~$0.003 (3 Haiku calls). Total ASMR cost per conversation: ~$0.006.
    """
    db = _get_db()
    _ensure_asmr_schema(db)

    # Load all current findings
    findings = db.execute("""
        SELECT vector, finding, source_date, confidence
        FROM knowledge_findings
        WHERE user_id = ? AND is_current = 1
        ORDER BY source_date DESC, confidence DESC
    """, (user_id,)).fetchall()

    # Also load legacy user_facts as fallback
    legacy_facts = db.execute("""
        SELECT fact, category, updated_at
        FROM user_facts
        WHERE user_id = ? AND is_active = 1
        ORDER BY confidence DESC, updated_at DESC
    """, (user_id,)).fetchall()

    db.close()

    if not findings and not legacy_facts:
        return ""  # No memory yet

    # Build findings text for search agents
    findings_text = ""
    for f in findings:
        findings_text += f"[{f['vector']}|{f['source_date']}] {f['finding']}\n"

    # Add legacy facts too (backwards compat)
    for f in legacy_facts[:30]:
        findings_text += f"[legacy|{f['updated_at'][:10]}] {f['fact']}\n"

    if len(findings_text) < 100:
        # Too little data for full ASMR — just return what we have
        return f"=== WHAT YOU KNOW ABOUT THIS USER ===\n{findings_text}"

    # Run 3 search agents in parallel
    search_results = {}
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(_search_direct_seeker, current_context, findings_text): "direct",
                executor.submit(_search_inference_engine, current_context, findings_text): "inference",
                executor.submit(_search_temporal_reasoner, current_context, findings_text): "temporal",
            }
            for future in concurrent.futures.as_completed(futures, timeout=30):
                search_name = futures[future]
                try:
                    search_results[search_name] = future.result()
                except Exception as e:
                    logger.warning(f"Search agent {search_name} failed: {e}")
                    search_results[search_name] = ""
    except Exception as e:
        logger.error(f"ASMR retrieval failed, falling back to legacy: {e}")
        from core.user_memory import load_user_memory
        return load_user_memory(user_id, agent_id)

    # Assemble context
    parts = ["=== ACTIVE MEMORY (retrieved for this conversation) ==="]
    parts.append("Memory assembled by 3 specialized search agents. "
                 "Trust [CURRENT] facts. Ignore [OUTDATED] facts.\n")

    if search_results.get("temporal"):
        parts.append("TIMELINE & STATE CHANGES:")
        parts.append(search_results["temporal"])
        parts.append("")

    if search_results.get("direct"):
        parts.append("DIRECTLY RELEVANT FACTS:")
        parts.append(search_results["direct"])
        parts.append("")

    if search_results.get("inference"):
        parts.append("CONTEXTUAL CONNECTIONS:")
        parts.append(search_results["inference"])
        parts.append("")

    assembled = "\n".join(parts)

    # Token budget: cap at 8K chars (~2K tokens) — search agents already filtered
    if len(assembled) > 8000:
        assembled = assembled[:8000] + "\n[Memory truncated for token budget]"

    logger.info(f"ASMR retrieval for {agent_id}/{user_id}: "
                f"{len(findings)} findings + {len(legacy_facts)} legacy facts → "
                f"{len(assembled)} chars assembled")

    return assembled


# =============================================================================
# INTEGRATION: Drop-in replacements for orchestrator
# =============================================================================

def asmr_extract(user_id: str, agent_id: str, conversation: list,
                  agent_display_name: str = ""):
    """Drop-in replacement for extract_and_store_memories."""
    try:
        extract_with_observers(user_id, agent_id, conversation, agent_display_name)
    except Exception as e:
        logger.error(f"ASMR extraction failed, falling back to legacy: {e}")
        from core.user_memory import extract_and_store_memories
        extract_and_store_memories(user_id, agent_id, conversation, agent_display_name)


def asmr_load(user_id: str, agent_id: str, current_context: str = "") -> str:
    """
    Drop-in replacement for load_user_memory.
    If current_context is provided, uses active retrieval.
    Otherwise falls back to legacy loading.
    """
    if current_context:
        try:
            return retrieve_active_memory(user_id, agent_id, current_context)
        except Exception as e:
            logger.error(f"ASMR retrieval failed, falling back to legacy: {e}")

    # Fallback to legacy
    from core.user_memory import load_user_memory
    return load_user_memory(user_id, agent_id)
