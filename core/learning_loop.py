#!/usr/bin/env python3
"""
Learning Loop Engine — The Intelligence Compounding System

This is the brain behind every agent's ability to get smarter over time.
The database captures every cycle of: ANALYSE → INSIGHT → STRATEGY → EXECUTE → MEASURE

The loop:
1. Agent analyses situation (scheduled or triggered)
2. Insights are extracted and stored with confidence levels
3. Strategy decisions are logged with reasoning
4. Execution actions are tracked
5. Outcomes are measured against predictions
6. Insights get promoted (EMERGING → PROVEN) or demoted (→ DISPROVEN)
7. Agent's state file (CONTEXT.md) gets regenerated FROM the database
8. Next cycle starts with richer context

The database is the source of truth. Files are just snapshots.
"""

import sqlite3
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict

BASE_DIR = Path.home() / "tom-command-center"
DB_PATH = BASE_DIR / "data" / "intelligence.db"


def get_db():
    """Get database connection, creating schema if needed."""
    os.makedirs(DB_PATH.parent, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    create_schema(conn)
    return conn


def create_schema(conn):
    """Create the learning loop database schema."""
    conn.executescript("""
    
    -- ═══════════════════════════════════════════════════════════════
    -- INSIGHTS: The core knowledge that compounds over time
    -- Every observation, pattern, or learning from any agent
    -- ═══════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS insights (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent TEXT NOT NULL,                    -- which agent generated this
        domain TEXT NOT NULL,                   -- topic area (e.g., "meta_ads", "geopolitics", "nutrition")
        insight TEXT NOT NULL,                  -- the actual insight
        evidence TEXT,                          -- what data supports this
        confidence TEXT DEFAULT 'EMERGING',     -- EMERGING | PROVEN | DISPROVEN | SUPERSEDED
        confidence_score REAL DEFAULT 0.5,      -- 0.0 to 1.0 numeric confidence
        validations INTEGER DEFAULT 0,          -- how many times confirmed
        contradictions INTEGER DEFAULT 0,       -- how many times contradicted
        source TEXT,                            -- where this came from (campaign, research, observation)
        tags TEXT,                              -- JSON array of tags for cross-referencing
        parent_insight_id INTEGER,              -- if this refines/updates a previous insight
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (parent_insight_id) REFERENCES insights(id)
    );
    
    -- ═══════════════════════════════════════════════════════════════
    -- CYCLES: Every analyse→strategy→execute→measure loop
    -- Links insights to actions to outcomes
    -- ═══════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS cycles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent TEXT NOT NULL,
        cycle_type TEXT NOT NULL,               -- ANALYSIS | STRATEGY | EXECUTION | MEASUREMENT
        title TEXT NOT NULL,                    -- short description
        description TEXT,                       -- detailed explanation
        input_data TEXT,                        -- what data/context triggered this cycle (JSON)
        output_data TEXT,                       -- what was produced (JSON)
        linked_insight_ids TEXT,                -- JSON array of insight IDs used/generated
        outcome TEXT,                           -- SUCCESS | PARTIAL | FAILED | PENDING
        outcome_metrics TEXT,                   -- JSON of measured results
        predictions TEXT,                       -- what was predicted (JSON) — to verify later
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    -- ═══════════════════════════════════════════════════════════════
    -- DECISIONS: Strategic decisions with reasoning and outcomes
    -- Tracks what was decided, why, and whether it worked
    -- ═══════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent TEXT NOT NULL,
        decision TEXT NOT NULL,                 -- what was decided
        reasoning TEXT,                         -- why (linked to insights)
        alternatives TEXT,                      -- what else was considered (JSON)
        expected_outcome TEXT,                  -- what we thought would happen
        actual_outcome TEXT,                    -- what actually happened
        outcome_delta TEXT,                     -- difference between expected and actual
        linked_insight_ids TEXT,                -- insights that informed this
        generated_insight_ids TEXT,             -- new insights generated from outcome
        status TEXT DEFAULT 'PENDING',          -- PENDING | EXECUTED | MEASURED | CLOSED
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        measured_at TIMESTAMP
    );
    
    -- ═══════════════════════════════════════════════════════════════
    -- EVENTS: Timeline of significant events across all domains
    -- The shared timeline that Oracle (Daily Briefing) reads
    -- ═══════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent TEXT NOT NULL,                    -- which agent logged this
        event_type TEXT NOT NULL,               -- OBSERVATION | ACTION | MILESTONE | ALERT | UPDATE
        severity TEXT DEFAULT 'INFO',           -- INFO | NOTABLE | IMPORTANT | CRITICAL
        title TEXT NOT NULL,
        description TEXT,
        data TEXT,                              -- JSON of structured event data
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    -- ═══════════════════════════════════════════════════════════════
    -- METRICS: Quantitative tracking over time
    -- Enables trend analysis and performance comparison
    -- ═══════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent TEXT NOT NULL,
        metric_name TEXT NOT NULL,              -- e.g., "email_open_rate", "meta_roas", "weight_kg"
        metric_value REAL NOT NULL,
        unit TEXT,                              -- e.g., "%", "x", "kg", "$"
        context TEXT,                           -- what this measurement relates to
        period_start TIMESTAMP,
        period_end TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    
    -- ═══════════════════════════════════════════════════════════════
    -- AGENT_STATE: Structured state that generates CONTEXT.md
    -- Each agent's current operational state
    -- ═══════════════════════════════════════════════════════════════
    CREATE TABLE IF NOT EXISTS agent_state (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent TEXT NOT NULL,
        state_key TEXT NOT NULL,                -- e.g., "current_phase", "active_campaigns", "watchlist"
        state_value TEXT NOT NULL,              -- JSON value
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(agent, state_key)
    );
    
    -- Indexes for fast querying
    CREATE INDEX IF NOT EXISTS idx_insights_agent ON insights(agent);
    CREATE INDEX IF NOT EXISTS idx_insights_confidence ON insights(confidence);
    CREATE INDEX IF NOT EXISTS idx_insights_domain ON insights(domain);
    CREATE INDEX IF NOT EXISTS idx_cycles_agent ON cycles(agent);
    CREATE INDEX IF NOT EXISTS idx_events_agent ON events(agent);
    CREATE INDEX IF NOT EXISTS idx_events_severity ON events(severity);
    CREATE INDEX IF NOT EXISTS idx_metrics_agent_name ON metrics(agent, metric_name);
    CREATE INDEX IF NOT EXISTS idx_agent_state_agent ON agent_state(agent);
    """)
    conn.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# INSIGHT MANAGEMENT — The knowledge that compounds
# ═══════════════════════════════════════════════════════════════════════════════

def add_insight(agent: str, domain: str, insight: str, evidence: str = None,
                source: str = None, tags: list = None, confidence: str = "EMERGING") -> int:
    """Add a new insight to the knowledge base."""
    conn = get_db()
    cursor = conn.execute("""
        INSERT INTO insights (agent, domain, insight, evidence, source, tags, confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (agent, domain, insight, evidence, source, json.dumps(tags or []), confidence))
    conn.commit()
    insight_id = cursor.lastrowid
    conn.close()
    return insight_id


def validate_insight(insight_id: int, new_evidence: str = None):
    """Record a validation of an existing insight. Promotes EMERGING → PROVEN after 3 validations."""
    conn = get_db()
    conn.execute("""
        UPDATE insights 
        SET validations = validations + 1,
            evidence = CASE WHEN ? IS NOT NULL 
                       THEN COALESCE(evidence, '') || '\n---\n' || ?
                       ELSE evidence END,
            confidence = CASE 
                WHEN validations + 1 >= 3 AND confidence = 'EMERGING' THEN 'PROVEN'
                ELSE confidence END,
            confidence_score = MIN(1.0, confidence_score + 0.15),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (new_evidence, new_evidence, insight_id))
    conn.commit()
    conn.close()


def contradict_insight(insight_id: int, counter_evidence: str = None):
    """Record a contradiction. Demotes to DISPROVEN after 2 contradictions."""
    conn = get_db()
    conn.execute("""
        UPDATE insights 
        SET contradictions = contradictions + 1,
            evidence = CASE WHEN ? IS NOT NULL 
                       THEN COALESCE(evidence, '') || '\n---CONTRADICTED---\n' || ?
                       ELSE evidence END,
            confidence = CASE 
                WHEN contradictions + 1 >= 2 AND confidence IN ('EMERGING', 'PROVEN') THEN 'DISPROVEN'
                ELSE confidence END,
            confidence_score = MAX(0.0, confidence_score - 0.25),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
    """, (counter_evidence, counter_evidence, insight_id))
    conn.commit()
    conn.close()


def get_active_insights(agent: str, domain: str = None, limit: int = 50) -> list:
    """Get active (non-disproven) insights for an agent, optionally filtered by domain."""
    conn = get_db()
    query = """
        SELECT * FROM insights 
        WHERE agent = ? AND confidence != 'DISPROVEN'
    """
    params = [agent]
    if domain:
        query += " AND domain = ?"
        params.append(domain)
    query += " ORDER BY confidence_score DESC, updated_at DESC LIMIT ?"
    params.append(limit)
    
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_disproven_insights(agent: str, limit: int = 20) -> list:
    """Get disproven insights — important for avoiding repeated mistakes."""
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM insights 
        WHERE agent = ? AND confidence = 'DISPROVEN'
        ORDER BY updated_at DESC LIMIT ?
    """, (agent, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# CYCLE MANAGEMENT — Analyse → Strategy → Execute → Measure
# ═══════════════════════════════════════════════════════════════════════════════

def log_cycle(agent: str, cycle_type: str, title: str, description: str = None,
              input_data: dict = None, output_data: dict = None,
              linked_insights: list = None, predictions: dict = None) -> int:
    """Log a cycle step in the learning loop."""
    conn = get_db()
    cursor = conn.execute("""
        INSERT INTO cycles (agent, cycle_type, title, description, input_data, 
                          output_data, linked_insight_ids, predictions)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (agent, cycle_type, title, description,
          json.dumps(input_data) if input_data else None,
          json.dumps(output_data) if output_data else None,
          json.dumps(linked_insights or []),
          json.dumps(predictions) if predictions else None))
    conn.commit()
    cycle_id = cursor.lastrowid
    conn.close()
    return cycle_id


def close_cycle(cycle_id: int, outcome: str, outcome_metrics: dict = None):
    """Close a cycle with its measured outcome."""
    conn = get_db()
    conn.execute("""
        UPDATE cycles 
        SET outcome = ?, outcome_metrics = ?
        WHERE id = ?
    """, (outcome, json.dumps(outcome_metrics) if outcome_metrics else None, cycle_id))
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════════════════════
# EVENT LOGGING — The shared timeline
# ═══════════════════════════════════════════════════════════════════════════════

def log_event(agent: str, event_type: str, title: str, description: str = None,
              severity: str = "INFO", data: dict = None) -> int:
    """Log a significant event."""
    conn = get_db()
    cursor = conn.execute("""
        INSERT INTO events (agent, event_type, severity, title, description, data)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (agent, event_type, severity, title, description,
          json.dumps(data) if data else None))
    conn.commit()
    event_id = cursor.lastrowid
    conn.close()
    return event_id


def get_recent_events(hours: int = 24, agent: str = None, min_severity: str = None) -> list:
    """Get recent events, optionally filtered."""
    conn = get_db()
    query = "SELECT * FROM events WHERE created_at > datetime('now', ?)"
    params = [f'-{hours} hours']
    
    if agent:
        query += " AND agent = ?"
        params.append(agent)
    
    severity_order = {'INFO': 0, 'NOTABLE': 1, 'IMPORTANT': 2, 'CRITICAL': 3}
    if min_severity and min_severity in severity_order:
        severities = [s for s, v in severity_order.items() if v >= severity_order[min_severity]]
        query += f" AND severity IN ({','.join('?' * len(severities))})"
        params.extend(severities)
    
    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# METRICS TRACKING — Quantitative trends over time
# ═══════════════════════════════════════════════════════════════════════════════

def log_metric(agent: str, metric_name: str, value: float, unit: str = None,
               context: str = None, period_start: str = None, period_end: str = None):
    """Log a quantitative metric."""
    conn = get_db()
    conn.execute("""
        INSERT INTO metrics (agent, metric_name, metric_value, unit, context, period_start, period_end)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (agent, metric_name, value, unit, context, period_start, period_end))
    conn.commit()
    conn.close()


def get_metric_trend(agent: str, metric_name: str, days: int = 30) -> list:
    """Get metric values over time for trend analysis."""
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM metrics 
        WHERE agent = ? AND metric_name = ? AND created_at > datetime('now', ?)
        ORDER BY created_at ASC
    """, (agent, metric_name, f'-{days} days')).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# STATE MANAGEMENT — Generates CONTEXT.md from database
# ═══════════════════════════════════════════════════════════════════════════════

def set_state(agent: str, key: str, value):
    """Set a state value for an agent. Upserts."""
    conn = get_db()
    conn.execute("""
        INSERT INTO agent_state (agent, state_key, state_value, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(agent, state_key) DO UPDATE SET
            state_value = excluded.state_value,
            updated_at = CURRENT_TIMESTAMP
    """, (agent, key, json.dumps(value)))
    conn.commit()
    conn.close()


def get_state(agent: str, key: str = None) -> dict:
    """Get state for an agent. If key is None, returns all state."""
    conn = get_db()
    if key:
        row = conn.execute("""
            SELECT state_value FROM agent_state WHERE agent = ? AND state_key = ?
        """, (agent, key)).fetchone()
        conn.close()
        return json.loads(row['state_value']) if row else None
    else:
        rows = conn.execute("""
            SELECT state_key, state_value, updated_at FROM agent_state WHERE agent = ?
        """, (agent,)).fetchall()
        conn.close()
        return {r['state_key']: json.loads(r['state_value']) for r in rows}


def regenerate_context_md(agent: str):
    """
    THE KEY FUNCTION: Regenerate an agent's CONTEXT.md from the database.
    This ensures the flat file always reflects the latest intelligence.
    Called after every meaningful interaction or data update.
    """
    state = get_state(agent)
    active_insights = get_active_insights(agent, limit=30)
    disproven = get_disproven_insights(agent, limit=10)
    recent_events = get_recent_events(hours=48, agent=agent)
    
    # Build the markdown
    lines = [
        f"# CONTEXT.md — {agent} State",
        f"## Last Updated: {datetime.now().strftime('%B %d, %Y %H:%M')}",
        f"## Generated from database — DO NOT EDIT MANUALLY",
        ""
    ]
    
    # Current state
    if state:
        lines.append("## CURRENT STATE")
        for key, value in state.items():
            if isinstance(value, (dict, list)):
                lines.append(f"### {key.replace('_', ' ').title()}")
                lines.append(f"```json\n{json.dumps(value, indent=2)}\n```")
            else:
                lines.append(f"- **{key.replace('_', ' ').title()}:** {value}")
        lines.append("")
    
    # Active insights (PROVEN first, then EMERGING)
    if active_insights:
        proven = [i for i in active_insights if i['confidence'] == 'PROVEN']
        emerging = [i for i in active_insights if i['confidence'] == 'EMERGING']
        
        if proven:
            lines.append("## PROVEN INSIGHTS (trust these)")
            for i in proven:
                lines.append(f"- ✅ [{i['domain']}] {i['insight']}")
                if i['evidence']:
                    # Only show first line of evidence to keep context lean
                    first_evidence = i['evidence'].split('\n')[0][:200]
                    lines.append(f"  Evidence: {first_evidence}")
            lines.append("")
        
        if emerging:
            lines.append("## EMERGING INSIGHTS (monitor, not yet proven)")
            for i in emerging[:15]:  # Limit to avoid bloat
                lines.append(f"- 🔄 [{i['domain']}] {i['insight']} (validated {i['validations']}x)")
            lines.append("")
    
    # Disproven (avoid repeating mistakes)
    if disproven:
        lines.append("## DISPROVEN — DO NOT REPEAT THESE")
        for i in disproven:
            lines.append(f"- ❌ [{i['domain']}] {i['insight']}")
        lines.append("")
    
    # Recent events
    if recent_events:
        lines.append("## RECENT EVENTS (last 48 hours)")
        for e in recent_events[:20]:
            severity_icon = {'INFO': 'ℹ️', 'NOTABLE': '📌', 'IMPORTANT': '⚡', 'CRITICAL': '🚨'}
            icon = severity_icon.get(e['severity'], 'ℹ️')
            lines.append(f"- {icon} [{e['created_at'][:16]}] {e['title']}")
        lines.append("")
    
    # Write the file
    context_path = BASE_DIR / "agents" / agent / "state" / "CONTEXT.md"
    os.makedirs(context_path.parent, exist_ok=True)
    context_path.write_text("\n".join(lines))
    
    return context_path


def regenerate_all_contexts():
    """Regenerate CONTEXT.md for all agents."""
    agents_dir = BASE_DIR / "agents"
    for agent_dir in agents_dir.iterdir():
        if agent_dir.is_dir() and (agent_dir / "AGENT.md").exists():
            regenerate_context_md(agent_dir.name)


# ═══════════════════════════════════════════════════════════════════════════════
# LEARNING LOOP — The automated cycle
# ═══════════════════════════════════════════════════════════════════════════════

def run_learning_cycle(agent: str, analysis_result: str, claude_extracted_insights: list):
    """
    Process the output of an agent's analysis through the learning loop.
    
    This is called AFTER Claude generates a response. The orchestrator
    asks Claude to extract structured insights from its own output,
    then feeds them here.
    
    Expected format for claude_extracted_insights:
    [
        {
            "insight": "Social proof ads outperform discount ads by 2x",
            "domain": "meta_ads",
            "evidence": "Campaign X: 7.78x ROAS vs Campaign Y: 3.2x ROAS",
            "confidence": "EMERGING",
            "validates_existing": null,  # or insight_id if validates something
            "contradicts_existing": null  # or insight_id if contradicts something
        }
    ]
    """
    for item in claude_extracted_insights:
        # Check if this validates or contradicts an existing insight
        if item.get('validates_existing'):
            validate_insight(item['validates_existing'], item.get('evidence'))
        elif item.get('contradicts_existing'):
            contradict_insight(item['contradicts_existing'], item.get('evidence'))
        else:
            # New insight
            add_insight(
                agent=agent,
                domain=item.get('domain', 'general'),
                insight=item['insight'],
                evidence=item.get('evidence'),
                source=f"analysis_{datetime.now().strftime('%Y%m%d')}",
                tags=item.get('tags', []),
                confidence=item.get('confidence', 'EMERGING')
            )
    
    # Log the cycle
    log_cycle(
        agent=agent,
        cycle_type="ANALYSIS",
        title=f"Analysis cycle {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        description=analysis_result[:500],
        output_data={"insights_processed": len(claude_extracted_insights)}
    )
    
    # Regenerate the agent's context file from updated database
    regenerate_context_md(agent)


# ═══════════════════════════════════════════════════════════════════════════════
# INSIGHT EXTRACTION PROMPT — Ask Claude to extract structured learnings
# ═══════════════════════════════════════════════════════════════════════════════

INSIGHT_EXTRACTION_PROMPT = """
After completing your main task, extract any insights or learnings from your analysis.

Return a JSON array of insights. Each insight should be:
{
    "insight": "A clear, specific, actionable statement of what was learned",
    "domain": "the topic area (e.g., meta_ads, email, geopolitics, nutrition, bjj)",
    "evidence": "What specific data or observation supports this",
    "confidence": "EMERGING (first time observed) or PROVEN (seen 3+ times)",
    "tags": ["relevant", "tags", "for", "cross-referencing"]
}

Rules:
- Only extract GENUINE insights, not restatements of known facts
- Be specific: "GLM social proof ads get 7.78x ROAS" not "social proof works"
- Include the evidence that supports each insight
- If nothing new was learned, return an empty array: []

Return ONLY the JSON array, no other text.
"""


# ═══════════════════════════════════════════════════════════════════════════════
# CLI INTERFACE
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Learning Loop Engine")
        print("Commands:")
        print("  init                          — Initialize database")
        print("  insights <agent>              — Show active insights")
        print("  disproven <agent>             — Show disproven insights")
        print("  events [hours]                — Show recent events")
        print("  metrics <agent> <metric>      — Show metric trend")
        print("  regen <agent>                 — Regenerate CONTEXT.md")
        print("  regen-all                     — Regenerate all CONTEXT.md files")
        print("  stats                         — Database statistics")
        sys.exit(0)
    
    cmd = sys.argv[1]
    
    if cmd == "init":
        conn = get_db()
        print(f"Database initialized at {DB_PATH}")
        conn.close()
    
    elif cmd == "insights":
        agent = sys.argv[2] if len(sys.argv) > 2 else None
        if not agent:
            print("Usage: insights <agent>")
            sys.exit(1)
        insights = get_active_insights(agent)
        for i in insights:
            print(f"[{i['confidence']}] ({i['confidence_score']:.1f}) {i['insight']}")
            if i['evidence']:
                print(f"  → {i['evidence'][:100]}")
    
    elif cmd == "disproven":
        agent = sys.argv[2]
        for i in get_disproven_insights(agent):
            print(f"❌ {i['insight']}")
    
    elif cmd == "events":
        hours = int(sys.argv[2]) if len(sys.argv) > 2 else 24
        for e in get_recent_events(hours):
            print(f"[{e['severity']}] {e['agent']}: {e['title']}")
    
    elif cmd == "regen":
        agent = sys.argv[2]
        path = regenerate_context_md(agent)
        print(f"Regenerated: {path}")
    
    elif cmd == "regen-all":
        regenerate_all_contexts()
        print("All CONTEXT.md files regenerated from database.")
    
    elif cmd == "stats":
        conn = get_db()
        for table in ['insights', 'cycles', 'decisions', 'events', 'metrics', 'agent_state']:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"{table:20s}: {count:>6,} rows")
        conn.close()
