# Self-Improving Multi-Agent System Research
## For Tom's Command Center: 9-Agent Telegram Bot System
### Compiled: March 1, 2026

---

## TABLE OF CONTENTS
1. [Cross-Agent Event Bus / Shared Context](#1-cross-agent-event-bus--shared-context)
2. [Self-Improving Learning Loops](#2-self-improving-learning-loops)
3. [Persistent Memory Across Sessions](#3-persistent-memory-across-sessions)
4. [Creative Brief Generation System](#4-creative-brief-generation-system)
5. [Designer Output Tracking / AI Design Expansion](#5-designer-output-tracking--ai-design-expansion)
6. [Smart Notification Routing](#6-smart-notification-routing)
7. [Replenishment Reminder Systems](#7-replenishment-reminder-systems)

---

## 1. CROSS-AGENT EVENT BUS / SHARED CONTEXT

### Current State in Your System

Your orchestrator already has the foundation: agents write to `state/CONTEXT.md`, Oracle reads all agent states for cross-domain briefing, and `learning_db.py` has `get_cross_domain_connections()`. But there is **no real-time event bus** -- Agent A cannot trigger Agent B autonomously. Everything is either scheduled (cron) or Tom-initiated (message).

### What Leading Systems Do

**Four established patterns** (from Confluent's research on event-driven multi-agent systems):

1. **Orchestrator-Worker**: Central coordinator assigns tasks, workers report back. You already have this -- the orchestrator routes to agents.

2. **Blackboard Pattern**: A shared knowledge base where agents post and retrieve information freely. Any agent can write, any agent can read. This is the closest match to what your system needs. Your `events` table in `learning_loop.py` is a proto-blackboard.

3. **Hierarchical**: Parent agents delegate to child agents. Oracle -> domain agents is already this pattern.

4. **Market-Based**: Agents bid on tasks. Not relevant for your system.

### Implementation Plan: SQLite-Backed Event Bus

Your system runs on Railway with a single process. You do not need Kafka, Redis, or any external message broker. SQLite with WAL mode is the right tool. Here is the complete implementation:

```python
# core/event_bus.py
"""
SQLite-backed Event Bus for Cross-Agent Communication.

Pattern: Agent A publishes an event -> the event bus persists it ->
Agent B picks it up on its next cycle (or gets triggered immediately
if running in the same process).

This replaces the need for Redis/Kafka in a single-process system.
"""

import sqlite3
import json
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional
from dataclasses import dataclass, field, asdict
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "event_bus.db"


@dataclass
class AgentEvent:
    """A typed event that flows between agents."""
    event_type: str          # e.g., "campaign.launched", "alert.geopolitical", "order.placed"
    source_agent: str        # which agent emitted this
    payload: dict            # structured event data
    severity: str = "INFO"   # INFO | NOTABLE | IMPORTANT | CRITICAL
    target_agents: list = field(default_factory=list)  # empty = broadcast to all
    event_id: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.event_id:
            self.event_id = f"{self.source_agent}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()


class EventBus:
    """
    Persistent event bus backed by SQLite.

    Supports both sync (polling) and async (callback) consumption.
    Events are durable -- they survive process restarts.
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._handlers: Dict[str, List[Callable]] = defaultdict(list)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT UNIQUE NOT NULL,
                event_type TEXT NOT NULL,
                source_agent TEXT NOT NULL,
                target_agents TEXT,          -- JSON array, empty = broadcast
                severity TEXT DEFAULT 'INFO',
                payload TEXT NOT NULL,        -- JSON
                status TEXT DEFAULT 'PENDING', -- PENDING | DELIVERED | PROCESSED | FAILED
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_at TIMESTAMP,
                processed_by TEXT            -- which agent(s) processed it
            );

            -- Subscriptions: which agents listen to which event types
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL,
                event_pattern TEXT NOT NULL,  -- glob pattern: "campaign.*", "alert.*", "*"
                priority INTEGER DEFAULT 0,   -- higher = processed first
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(agent, event_pattern)
            );

            CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
            CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
            CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
            CREATE INDEX IF NOT EXISTS idx_subs_agent ON subscriptions(agent);
        """)
        conn.commit()
        conn.close()

    # --- PUBLISHING ---

    def publish(self, event: AgentEvent) -> str:
        """
        Publish an event to the bus. Persists to SQLite immediately.
        Returns the event_id.

        Example:
            bus.publish(AgentEvent(
                event_type="campaign.results_ready",
                source_agent="dbh-marketing",
                payload={"campaign_id": "march_flash_sale", "roas": 5.2},
                severity="NOTABLE"
            ))
        """
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO events (event_id, event_type, source_agent, target_agents,
                               severity, payload)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            event.event_id,
            event.event_type,
            event.source_agent,
            json.dumps(event.target_agents),
            event.severity,
            json.dumps(event.payload)
        ))
        conn.commit()
        conn.close()

        # Fire in-process handlers immediately
        self._dispatch_sync(event)

        return event.event_id

    # --- SUBSCRIBING ---

    def subscribe(self, agent: str, event_pattern: str, handler: Callable = None,
                  priority: int = 0):
        """
        Subscribe an agent to events matching a pattern.

        Patterns use dot-separated namespaces:
            "campaign.*"      - all campaign events
            "alert.geopolitical" - specific alert type
            "*"               - everything

        If handler is provided, it will be called in-process when matching events fire.
        Otherwise, events accumulate for polling via get_pending_events().
        """
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT OR REPLACE INTO subscriptions (agent, event_pattern, priority)
            VALUES (?, ?, ?)
        """, (agent, event_pattern, priority))
        conn.commit()
        conn.close()

        if handler:
            self._handlers[event_pattern].append((agent, handler))

    # --- CONSUMING ---

    def get_pending_events(self, agent: str, limit: int = 50) -> List[dict]:
        """
        Get events pending for a specific agent.
        Matches against the agent's subscriptions.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Get agent's subscriptions
        subs = conn.execute(
            "SELECT event_pattern FROM subscriptions WHERE agent = ?",
            (agent,)
        ).fetchall()

        if not subs:
            conn.close()
            return []

        # Build query for matching events
        events = []
        for sub in subs:
            pattern = sub['event_pattern']
            if pattern == "*":
                sql_pattern = "%"
            else:
                sql_pattern = pattern.replace("*", "%")

            rows = conn.execute("""
                SELECT * FROM events
                WHERE status = 'PENDING'
                  AND event_type LIKE ?
                  AND source_agent != ?
                  AND (target_agents = '[]' OR target_agents LIKE ?)
                ORDER BY
                    CASE severity
                        WHEN 'CRITICAL' THEN 0
                        WHEN 'IMPORTANT' THEN 1
                        WHEN 'NOTABLE' THEN 2
                        ELSE 3
                    END,
                    created_at ASC
                LIMIT ?
            """, (sql_pattern, agent, f'%"{agent}"%', limit)).fetchall()

            events.extend([dict(r) for r in rows])

        conn.close()

        # Deduplicate by event_id
        seen = set()
        unique = []
        for e in events:
            if e['event_id'] not in seen:
                seen.add(e['event_id'])
                e['payload'] = json.loads(e['payload'])
                unique.append(e)

        return unique

    def mark_processed(self, event_id: str, agent: str):
        """Mark an event as processed by an agent."""
        conn = sqlite3.connect(self.db_path)

        # Get current processed_by
        row = conn.execute(
            "SELECT processed_by FROM events WHERE event_id = ?",
            (event_id,)
        ).fetchone()

        if row:
            current = json.loads(row[0]) if row[0] else []
            current.append(agent)
            conn.execute("""
                UPDATE events
                SET processed_by = ?, processed_at = CURRENT_TIMESTAMP,
                    status = 'PROCESSED'
                WHERE event_id = ?
            """, (json.dumps(current), event_id))

        conn.commit()
        conn.close()

    # --- IN-PROCESS DISPATCH ---

    def _dispatch_sync(self, event: AgentEvent):
        """Fire registered in-process handlers."""
        for pattern, handlers in self._handlers.items():
            if self._matches(event.event_type, pattern):
                for agent, handler in handlers:
                    if agent != event.source_agent:
                        try:
                            handler(event)
                        except Exception as e:
                            print(f"Handler error ({agent}): {e}")

    @staticmethod
    def _matches(event_type: str, pattern: str) -> bool:
        """Check if event_type matches a subscription pattern."""
        if pattern == "*":
            return True
        parts = pattern.split(".")
        type_parts = event_type.split(".")
        for p, t in zip(parts, type_parts):
            if p == "*":
                return True
            if p != t:
                return False
        return len(parts) == len(type_parts)

    # --- HOUSEKEEPING ---

    def cleanup_old_events(self, days: int = 30):
        """Remove processed events older than N days."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            DELETE FROM events
            WHERE status = 'PROCESSED'
              AND created_at < datetime('now', ?)
        """, (f'-{days} days',))
        conn.commit()
        conn.close()

    def get_event_stats(self) -> dict:
        """Get event bus statistics."""
        conn = sqlite3.connect(self.db_path)
        stats = {}
        for status in ['PENDING', 'PROCESSED', 'FAILED']:
            count = conn.execute(
                "SELECT COUNT(*) FROM events WHERE status = ?", (status,)
            ).fetchone()[0]
            stats[status] = count

        # Events by type (last 7 days)
        rows = conn.execute("""
            SELECT event_type, COUNT(*) as cnt
            FROM events
            WHERE created_at > datetime('now', '-7 days')
            GROUP BY event_type
            ORDER BY cnt DESC
        """).fetchall()
        stats['by_type'] = {r[0]: r[1] for r in rows}

        conn.close()
        return stats
```

### Standard Event Types for Your System

Define these across your agent network:

```python
# core/event_types.py
"""
Standard event types for cross-agent communication.
Namespace pattern: domain.action
"""

# --- MARKETING EVENTS ---
CAMPAIGN_LAUNCHED = "campaign.launched"        # Meridian -> Oracle, PREP
CAMPAIGN_RESULTS = "campaign.results_ready"    # Meridian -> Oracle, PREP
CAMPAIGN_ALERT = "campaign.alert"              # Meridian -> Oracle (spend anomaly, ROAS drop)
EMAIL_SENT = "email.sent"                      # Meridian -> Oracle
EMAIL_RESULTS = "email.results_ready"          # Meridian -> Oracle

# --- ORDER EVENTS ---
ORDER_HIGH_VALUE = "order.high_value"          # Meridian -> Oracle (AOV > $X)
ORDER_REPEAT = "order.repeat_customer"         # Meridian -> Oracle, PREP
ORDER_ATTRIBUTION = "order.attribution_gap"    # Meridian -> Oracle (unattributed sale)

# --- GEOPOLITICAL / GLOBAL ---
ALERT_GEOPOLITICAL = "alert.geopolitical"      # Atlas -> Oracle, PREP, Meridian
ALERT_MARKET = "alert.market_disruption"       # Atlas -> PREP, Meridian
TREND_DETECTED = "trend.detected"              # Atlas -> all

# --- BUSINESS ---
OPPORTUNITY_FOUND = "business.opportunity"     # Venture -> PREP, Oracle
COMPETITOR_MOVE = "business.competitor"        # Venture -> Meridian, PREP

# --- HEALTH/FITNESS ---
PROTOCOL_COMPLETE = "fitness.protocol_done"    # Titan -> Oracle
HEALTH_ALERT = "fitness.health_alert"          # Titan -> Oracle

# --- CREATIVE ---
MODEL_RELEASE = "creative.model_release"       # Lens -> Oracle, Meridian
ASSET_READY = "creative.asset_ready"           # Lens -> Meridian

# --- DESIGN ---
BRIEF_GENERATED = "design.brief_generated"     # Meridian -> Lens
DESIGN_SUBMITTED = "design.submitted"          # Manual trigger -> Meridian
DESIGN_FEEDBACK = "design.feedback_ready"      # Meridian -> Lens/Tom

# --- SYSTEM ---
AGENT_ERROR = "system.agent_error"             # any -> command-center
LEARNING_MILESTONE = "system.learning"         # any -> command-center
CONTEXT_STALE = "system.context_stale"         # any -> command-center
```

### Integration with Your Orchestrator

Modify `orchestrator.py` to check the event bus before and after each agent interaction:

```python
# In run_scheduled_task(), after loading brain but before calling Claude:
from core.event_bus import EventBus

bus = EventBus()

# Inject pending events into the agent's context
pending = bus.get_pending_events(agent_name, limit=10)
if pending:
    event_context = "\n=== CROSS-AGENT EVENTS (act on these) ===\n"
    for e in pending:
        event_context += f"[{e['severity']}] From {e['source_agent']}: {e['event_type']}\n"
        event_context += f"  Data: {json.dumps(e['payload'], indent=2)}\n"
    task_prompt += event_context

    # Mark as processed
    for e in pending:
        bus.mark_processed(e['event_id'], agent_name)

# After getting Claude's response, check if the agent wants to emit events:
# Add to the agent's system prompt:
CROSS_AGENT_PROMPT = """
If your analysis produces information another agent should know about, emit an event:
[EVENT: event_type | severity | {"key": "value"} ]

Event types: campaign.launched, campaign.results_ready, alert.geopolitical,
order.high_value, business.opportunity, trend.detected

Severity: INFO, NOTABLE, IMPORTANT, CRITICAL

Only emit events for genuinely significant information. Do not emit events
for routine observations.
"""
```

### Default Subscriptions

```python
# Set up on system startup
AGENT_SUBSCRIPTIONS = {
    "daily-briefing": ["*"],                    # Oracle sees everything
    "strategic-advisor": ["*"],                 # PREP sees everything
    "dbh-marketing": [
        "alert.geopolitical", "alert.market_disruption",
        "business.competitor", "creative.asset_ready",
        "order.*", "design.*"
    ],
    "global-events": [
        "campaign.alert", "business.opportunity",
        "alert.*"
    ],
    "new-business": [
        "trend.detected", "alert.market_disruption",
        "campaign.results_ready"
    ],
    "creative-projects": [
        "creative.*", "design.brief_generated"
    ],
    "command-center": [
        "system.*"
    ]
}
```

---

## 2. SELF-IMPROVING LEARNING LOOPS

### Current State in Your System

Your `learning_loop.py` already implements the core loop: ANALYSE -> INSIGHT -> STRATEGY -> EXECUTE -> MEASURE. It has insight promotion (EMERGING -> PROVEN after 3 validations) and demotion (DISPROVEN after 2 contradictions). `learning_db.py` has pattern detection and an `InsightExtractor`. The foundation is strong.

**What is missing:**
- No automated outcome measurement (predictions are logged but never verified)
- No strategy weight adjustment (all insights treated equally regardless of track record)
- No LLM-as-Judge evaluation of agent output quality
- No closed-loop feedback (agents do not know if their recommendations worked)

### How Production Systems Self-Improve

Based on research from OpenAI's Self-Evolving Agents cookbook, Yohei Nakajima (BabyAGI), and ICML 2025 metacognitive learning research:

#### The Retraining Loop (OpenAI Pattern)

```
1. Agent produces output
2. Output is evaluated (LLM-as-Judge OR human feedback)
3. Score is computed against criteria
4. If score < threshold: diagnose failure, refine prompt/strategy
5. If score > threshold: promote the strategy that worked
6. Loop continues until target quality is reached
```

### Implementation: Self-Improving Agent System

```python
# core/self_improvement.py
"""
Self-Improvement Engine for Tom's Command Center.

Each agent interaction produces an outcome. Over time, the system
learns which strategies, prompts, and patterns produce the best results.

The three improvement loops:
1. IMMEDIATE: LLM-as-Judge scores each response (quality gate)
2. SHORT-TERM: Weekly comparison of predictions vs outcomes
3. LONG-TERM: Monthly strategy weight adjustment based on accumulated data
"""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "self_improvement.db"


class SelfImprovementEngine:
    """
    Tracks agent performance and adjusts strategy weights over time.
    """

    def __init__(self):
        self.db_path = str(DB_PATH)
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
            -- Strategy performance tracking
            CREATE TABLE IF NOT EXISTS strategies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL,
                strategy_name TEXT NOT NULL,     -- e.g., "social_proof_subject_line"
                domain TEXT NOT NULL,            -- e.g., "email_marketing"
                description TEXT,
                weight REAL DEFAULT 1.0,         -- 0.0-2.0, higher = more trusted
                times_used INTEGER DEFAULT 0,
                times_succeeded INTEGER DEFAULT 0,
                times_failed INTEGER DEFAULT 0,
                avg_score REAL DEFAULT 0.0,
                last_used TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(agent, strategy_name)
            );

            -- Individual response evaluations
            CREATE TABLE IF NOT EXISTS evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL,
                interaction_type TEXT,           -- "scheduled", "message", "photo"
                task_type TEXT,                  -- "morning_brief", "scan", etc.
                input_summary TEXT,
                output_summary TEXT,

                -- LLM-as-Judge scores (0.0 to 1.0)
                relevance_score REAL,            -- was it relevant to the task?
                actionability_score REAL,        -- could Tom act on it?
                accuracy_score REAL,             -- was the data/analysis correct?
                insight_quality_score REAL,       -- did it surface non-obvious patterns?
                brevity_score REAL,              -- was it concise enough?
                overall_score REAL,              -- weighted average

                -- Strategy tracking
                strategies_used TEXT,             -- JSON array of strategy names

                -- Judge reasoning
                judge_reasoning TEXT,
                improvement_suggestions TEXT,     -- JSON array

                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- Prediction tracking (for closed-loop learning)
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL,
                prediction TEXT NOT NULL,         -- what was predicted
                domain TEXT,
                confidence REAL DEFAULT 0.5,     -- 0.0-1.0
                prediction_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                verification_date TIMESTAMP,
                was_correct INTEGER,             -- 1 = correct, 0 = wrong, NULL = unverified
                actual_outcome TEXT,
                delta_analysis TEXT              -- what was different from prediction
            );

            -- Prompt evolution tracking
            CREATE TABLE IF NOT EXISTS prompt_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL,
                prompt_section TEXT NOT NULL,    -- which part of the prompt
                version INTEGER DEFAULT 1,
                content TEXT NOT NULL,
                avg_score REAL DEFAULT 0.0,
                sample_count INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_eval_agent ON evaluations(agent);
            CREATE INDEX IF NOT EXISTS idx_eval_score ON evaluations(overall_score);
            CREATE INDEX IF NOT EXISTS idx_pred_unverified ON predictions(was_correct)
                WHERE was_correct IS NULL;
            CREATE INDEX IF NOT EXISTS idx_strategies_agent ON strategies(agent);
        """)
        self.conn.commit()

    # --- EVALUATION (LLM-as-Judge) ---

    def build_judge_prompt(self, agent: str, task_type: str,
                           input_text: str, output_text: str) -> str:
        """
        Build the LLM-as-Judge evaluation prompt.

        This is called AFTER every agent response. A separate, cheap Claude call
        evaluates the response quality. The evaluation is stored and used to
        adjust strategy weights over time.
        """
        return f"""You are an expert evaluator assessing the quality of an AI agent's output.

AGENT: {agent}
TASK TYPE: {task_type}

INPUT (what the agent was asked to do):
{input_text[:1000]}

OUTPUT (what the agent produced):
{output_text[:2000]}

Score each dimension from 0.0 to 1.0:

1. RELEVANCE: Did the response directly address the task? Was it on-topic?
2. ACTIONABILITY: Can the user immediately act on this? Are there clear next steps?
3. ACCURACY: Is the data correct? Are the conclusions well-supported?
4. INSIGHT QUALITY: Did it surface non-obvious patterns or connections? Or just restate known facts?
5. BREVITY: Was it appropriately concise? Not padded with filler?

Also provide:
- IMPROVEMENT: One specific thing that would make this response significantly better
- STRATEGIES_DETECTED: What strategies or patterns did the agent use? (list them)

Return ONLY this JSON:
{{
    "relevance": 0.0,
    "actionability": 0.0,
    "accuracy": 0.0,
    "insight_quality": 0.0,
    "brevity": 0.0,
    "overall": 0.0,
    "improvement": "specific suggestion",
    "strategies_detected": ["strategy1", "strategy2"],
    "reasoning": "brief explanation of scores"
}}"""

    def record_evaluation(self, agent: str, task_type: str,
                          input_summary: str, output_summary: str,
                          scores: dict):
        """Record an evaluation result."""
        self.conn.execute("""
            INSERT INTO evaluations
            (agent, task_type, input_summary, output_summary,
             relevance_score, actionability_score, accuracy_score,
             insight_quality_score, brevity_score, overall_score,
             strategies_used, judge_reasoning, improvement_suggestions)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            agent, task_type,
            input_summary[:500], output_summary[:1000],
            scores.get('relevance', 0),
            scores.get('actionability', 0),
            scores.get('accuracy', 0),
            scores.get('insight_quality', 0),
            scores.get('brevity', 0),
            scores.get('overall', 0),
            json.dumps(scores.get('strategies_detected', [])),
            scores.get('reasoning', ''),
            json.dumps([scores.get('improvement', '')])
        ))
        self.conn.commit()

        # Update strategy weights based on this evaluation
        for strategy in scores.get('strategies_detected', []):
            self._update_strategy_weight(agent, strategy, scores.get('overall', 0.5))

    # --- STRATEGY WEIGHT MANAGEMENT ---

    def _update_strategy_weight(self, agent: str, strategy_name: str, score: float):
        """
        Adjust a strategy's weight based on its latest score.

        The weight adjustment uses exponential moving average:
        - Good score (>0.7): weight increases toward 2.0
        - Average score (0.4-0.7): weight stays stable
        - Poor score (<0.4): weight decreases toward 0.0

        Strategies with weight < 0.3 get flagged for replacement.
        """
        row = self.conn.execute("""
            SELECT weight, times_used, avg_score FROM strategies
            WHERE agent = ? AND strategy_name = ?
        """, (agent, strategy_name)).fetchone()

        if row:
            old_weight = row['weight']
            times_used = row['times_used'] + 1
            # EMA with alpha = 0.3 (recent results matter more)
            new_avg = 0.7 * row['avg_score'] + 0.3 * score

            # Weight adjustment
            if score > 0.7:
                new_weight = min(2.0, old_weight + 0.1)
                succeeded = 1
            elif score < 0.4:
                new_weight = max(0.1, old_weight - 0.15)
                succeeded = 0
            else:
                new_weight = old_weight
                succeeded = 1 if score > 0.5 else 0

            self.conn.execute("""
                UPDATE strategies
                SET weight = ?, times_used = ?, avg_score = ?,
                    times_succeeded = times_succeeded + ?,
                    times_failed = times_failed + ?,
                    last_used = CURRENT_TIMESTAMP
                WHERE agent = ? AND strategy_name = ?
            """, (new_weight, times_used, new_avg,
                  succeeded, 1 - succeeded,
                  agent, strategy_name))
        else:
            # First time seeing this strategy
            self.conn.execute("""
                INSERT INTO strategies (agent, strategy_name, domain, weight,
                                       times_used, avg_score, last_used)
                VALUES (?, ?, 'auto_detected', 1.0, 1, ?, CURRENT_TIMESTAMP)
            """, (agent, strategy_name, score))

        self.conn.commit()

    def get_top_strategies(self, agent: str, domain: str = None,
                           limit: int = 10) -> list:
        """Get the highest-performing strategies for an agent."""
        query = """
            SELECT strategy_name, weight, avg_score, times_used,
                   times_succeeded, times_failed
            FROM strategies
            WHERE agent = ? AND weight > 0.3
        """
        params = [agent]
        if domain:
            query += " AND domain = ?"
            params.append(domain)
        query += " ORDER BY weight * avg_score DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_failing_strategies(self, agent: str) -> list:
        """Get strategies that are underperforming (candidates for replacement)."""
        rows = self.conn.execute("""
            SELECT strategy_name, weight, avg_score, times_used, times_failed
            FROM strategies
            WHERE agent = ? AND weight < 0.5 AND times_used >= 3
            ORDER BY weight ASC
        """, (agent,)).fetchall()
        return [dict(r) for r in rows]

    # --- PREDICTION TRACKING ---

    def log_prediction(self, agent: str, prediction: str,
                       domain: str = None, confidence: float = 0.5) -> int:
        """Log a prediction for later verification."""
        cursor = self.conn.execute("""
            INSERT INTO predictions (agent, prediction, domain, confidence)
            VALUES (?, ?, ?, ?)
        """, (agent, prediction, domain, confidence))
        self.conn.commit()
        return cursor.lastrowid

    def verify_prediction(self, prediction_id: int, was_correct: bool,
                          actual_outcome: str = None):
        """Record whether a prediction was correct."""
        self.conn.execute("""
            UPDATE predictions
            SET was_correct = ?, actual_outcome = ?,
                verification_date = CURRENT_TIMESTAMP,
                delta_analysis = CASE WHEN ? = 0
                    THEN 'Prediction was incorrect. Actual: ' || ?
                    ELSE 'Prediction verified correct.'
                END
            WHERE id = ?
        """, (1 if was_correct else 0, actual_outcome,
              0 if not was_correct else 1, actual_outcome or '',
              prediction_id))
        self.conn.commit()

    def get_prediction_accuracy(self, agent: str, days: int = 90) -> dict:
        """Get prediction accuracy stats for an agent."""
        since = (datetime.now() - timedelta(days=days)).isoformat()

        total = self.conn.execute("""
            SELECT COUNT(*) FROM predictions
            WHERE agent = ? AND was_correct IS NOT NULL AND prediction_date > ?
        """, (agent, since)).fetchone()[0]

        correct = self.conn.execute("""
            SELECT COUNT(*) FROM predictions
            WHERE agent = ? AND was_correct = 1 AND prediction_date > ?
        """, (agent, since)).fetchone()[0]

        unverified = self.conn.execute("""
            SELECT COUNT(*) FROM predictions
            WHERE agent = ? AND was_correct IS NULL AND prediction_date > ?
        """, (agent, since)).fetchone()[0]

        return {
            "total_verified": total,
            "correct": correct,
            "accuracy": correct / total if total > 0 else 0,
            "unverified": unverified
        }

    # --- PERFORMANCE TRENDS ---

    def get_agent_performance_trend(self, agent: str, days: int = 30) -> list:
        """Get daily average scores for an agent over time."""
        rows = self.conn.execute("""
            SELECT date(created_at) as day,
                   AVG(overall_score) as avg_score,
                   COUNT(*) as interactions
            FROM evaluations
            WHERE agent = ? AND created_at > datetime('now', ?)
            GROUP BY date(created_at)
            ORDER BY day ASC
        """, (agent, f'-{days} days')).fetchall()
        return [dict(r) for r in rows]

    def generate_improvement_report(self, agent: str) -> str:
        """
        Generate a self-improvement report for an agent.
        This gets injected into the agent's context to make it aware of
        what is working and what is not.
        """
        top = self.get_top_strategies(agent, limit=5)
        failing = self.get_failing_strategies(agent)
        accuracy = self.get_prediction_accuracy(agent)
        trend = self.get_agent_performance_trend(agent, days=14)

        lines = ["## SELF-IMPROVEMENT STATUS"]

        if trend:
            recent_avg = sum(d['avg_score'] for d in trend[-7:]) / max(len(trend[-7:]), 1)
            older_avg = sum(d['avg_score'] for d in trend[:7]) / max(len(trend[:7]), 1)
            delta = recent_avg - older_avg
            direction = "IMPROVING" if delta > 0.05 else "DECLINING" if delta < -0.05 else "STABLE"
            lines.append(f"Performance trend (14d): {direction} ({delta:+.2f})")
            lines.append(f"Recent average score: {recent_avg:.2f}")

        if top:
            lines.append("\n### Top strategies (USE MORE OF THESE):")
            for s in top:
                win_rate = s['times_succeeded'] / max(s['times_used'], 1)
                lines.append(f"  - {s['strategy_name']}: weight={s['weight']:.1f}, "
                           f"score={s['avg_score']:.2f}, win_rate={win_rate:.0%}")

        if failing:
            lines.append("\n### Failing strategies (STOP USING THESE):")
            for s in failing:
                lines.append(f"  - {s['strategy_name']}: weight={s['weight']:.1f}, "
                           f"failed {s['times_failed']}/{s['times_used']} times")

        if accuracy['total_verified'] > 0:
            lines.append(f"\nPrediction accuracy (90d): {accuracy['accuracy']:.0%} "
                        f"({accuracy['correct']}/{accuracy['total_verified']})")
            if accuracy['unverified'] > 0:
                lines.append(f"  {accuracy['unverified']} predictions still unverified")

        # Recent improvement suggestions (last 5)
        recent_suggestions = self.conn.execute("""
            SELECT improvement_suggestions FROM evaluations
            WHERE agent = ? AND improvement_suggestions IS NOT NULL
            ORDER BY created_at DESC LIMIT 5
        """, (agent,)).fetchall()

        if recent_suggestions:
            lines.append("\n### Recent feedback (act on this):")
            for r in recent_suggestions:
                suggestions = json.loads(r[0])
                for s in suggestions:
                    if s:
                        lines.append(f"  - {s}")

        return "\n".join(lines)
```

### Integration with Orchestrator

Add a lightweight judge call after every agent response:

```python
# In orchestrator.py, after call_claude() returns:
def evaluate_response(agent_name, task_type, input_text, response):
    """Quick LLM-as-Judge evaluation. Uses Haiku for speed/cost."""
    from core.self_improvement import SelfImprovementEngine
    import anthropic

    engine = SelfImprovementEngine()
    judge_prompt = engine.build_judge_prompt(agent_name, task_type, input_text, response)

    # Use cheapest/fastest model for evaluation
    client = anthropic.Anthropic()
    try:
        result = client.messages.create(
            model="claude-haiku-4-5",  # cheap and fast for eval
            max_tokens=500,
            messages=[{"role": "user", "content": judge_prompt}]
        )
        scores = json.loads(result.content[0].text)
        engine.record_evaluation(agent_name, task_type, input_text, response, scores)
    except Exception as e:
        logger.warning(f"Evaluation failed (non-fatal): {e}")
```

### Key Principle: The GEPA Loop

From OpenAI's cookbook and Yohei Nakajima's research, the most effective self-improvement follows the Genetic-Pareto approach:

1. **Sample**: Run the agent on a task
2. **Reflect**: LLM-as-Judge evaluates the output
3. **Propose**: The judge suggests prompt/strategy revisions
4. **Evolve**: Apply the revision, test again
5. **Select**: Keep revisions that improve scores, discard those that do not

The key insight from Anthropic's own research: **longer context windows often make things worse**. Every token competes for attention. The self-improvement system should also track which parts of the agent's brain are actually useful and prune what is not contributing.

---

## 3. PERSISTENT MEMORY ACROSS SESSIONS

### Current State in Your System

You have two parallel memory systems:
1. **`learning_db.py`** (LearningDB class): insights, decisions, metrics, patterns, interactions
2. **`learning_loop.py`**: insights, cycles, decisions, events, metrics, agent_state

Both generate `CONTEXT.md` from their databases. The file-based state is a snapshot; the database is the source of truth. This is the correct architecture.

**What is missing:**
- No session summaries (each conversation starts fresh)
- No memory search (you can query by agent but not semantically)
- No temporal decay (old insights never lose relevance)
- No memory consolidation (similar insights are not merged)
- Two parallel schemas that overlap

### Best Practices from Research

#### Consolidate to One Schema

You should merge `learning_db.py` and `learning_loop.py` into a single system. The `learning_loop.py` schema is more mature. Keep it. Port the pattern detection from `learning_db.py` into it.

#### Add Session Memory

```python
# Add to learning_loop.py schema:

"""
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent TEXT NOT NULL,
    session_type TEXT NOT NULL,          -- "scheduled", "message", "photo"
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    input_summary TEXT,                  -- what triggered the session
    output_summary TEXT,                 -- what was produced
    insights_generated INTEGER DEFAULT 0,
    decisions_made INTEGER DEFAULT 0,
    key_topics TEXT,                     -- JSON array of main topics discussed
    continuation_context TEXT            -- what the next session should know
);

CREATE TABLE IF NOT EXISTS memory_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent TEXT NOT NULL,
    fact TEXT NOT NULL,                  -- concise factual statement
    fact_type TEXT NOT NULL,             -- "preference", "decision", "metric", "relationship", "deadline"
    valid_from TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    valid_until TIMESTAMP,              -- NULL = indefinitely valid
    source_session_id INTEGER,
    supersedes_fact_id INTEGER,         -- if this updates a previous fact
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (source_session_id) REFERENCES sessions(id),
    FOREIGN KEY (supersedes_fact_id) REFERENCES memory_facts(id)
);

CREATE INDEX IF NOT EXISTS idx_facts_agent ON memory_facts(agent);
CREATE INDEX IF NOT EXISTS idx_facts_type ON memory_facts(fact_type);
CREATE INDEX IF NOT EXISTS idx_facts_valid ON memory_facts(valid_until);
"""
```

#### Temporal Validity

The critical pattern from production systems: add `valid_from` and `valid_until` columns to prevent stale knowledge from polluting context.

```python
def get_current_facts(agent: str) -> list:
    """Get only currently valid facts."""
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM memory_facts
        WHERE agent = ?
          AND (valid_until IS NULL OR valid_until > datetime('now'))
          AND id NOT IN (SELECT supersedes_fact_id FROM memory_facts
                         WHERE supersedes_fact_id IS NOT NULL)
        ORDER BY created_at DESC
    """, (agent,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]
```

#### Session Continuation Protocol

After every agent interaction, extract what the next session needs to know:

```python
SESSION_CONTINUATION_PROMPT = """
Before ending this interaction, extract:
1. KEY FACTS: Any new facts learned (decisions made, data points, deadlines)
2. CONTINUATION: If this conversation is mid-stream, what does the next session
   need to know to pick up seamlessly? Write it as if briefing a colleague.
3. EXPIRED FACTS: Any previously known facts that are now outdated or wrong.

Return as JSON:
{
    "new_facts": [
        {"fact": "...", "type": "decision|metric|deadline|preference", "valid_until": null}
    ],
    "continuation": "Brief context for next session...",
    "expired_facts": ["description of fact that is no longer true"]
}
"""
```

#### Memory Consolidation (Weekly)

Run weekly to merge similar insights and reduce context bloat:

```python
def consolidate_memory(agent: str):
    """
    Weekly consolidation:
    1. Merge similar insights into single proven insights
    2. Archive insights older than 90 days with no validations
    3. Promote patterns with 5+ occurrences to playbook candidates
    4. Update CONTEXT.md with leaner, higher-signal content
    """
    conn = get_db()

    # Archive stale emerging insights (>60 days, no validations)
    conn.execute("""
        UPDATE insights
        SET confidence = 'ARCHIVED'
        WHERE agent = ?
          AND confidence = 'EMERGING'
          AND validations = 0
          AND created_at < datetime('now', '-60 days')
    """, (agent,))

    # Auto-promote insights with 5+ validations
    conn.execute("""
        UPDATE insights
        SET confidence = 'PROVEN', confidence_score = MIN(1.0, confidence_score + 0.1)
        WHERE agent = ?
          AND confidence = 'EMERGING'
          AND validations >= 5
    """, (agent,))

    conn.commit()
    conn.close()

    # Regenerate context with leaner data
    regenerate_context_md(agent)
```

#### Full-Text Search Without a Vector DB

For your scale (hundreds to low thousands of records), SQLite FTS5 is sufficient. You do not need a vector database.

```python
# Add to schema:
"""
CREATE VIRTUAL TABLE IF NOT EXISTS insights_fts USING fts5(
    insight, evidence, tags,
    content='insights',
    content_rowid='id'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS insights_ai AFTER INSERT ON insights BEGIN
    INSERT INTO insights_fts(rowid, insight, evidence, tags)
    VALUES (new.id, new.insight, new.evidence, new.tags);
END;
"""

def search_insights(query: str, agent: str = None, limit: int = 10) -> list:
    """Full-text search across all insights."""
    conn = get_db()
    sql = """
        SELECT insights.*, rank
        FROM insights_fts
        JOIN insights ON insights.id = insights_fts.rowid
        WHERE insights_fts MATCH ?
    """
    params = [query]
    if agent:
        sql += " AND insights.agent = ?"
        params.append(agent)
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]
```

---

## 4. CREATIVE BRIEF GENERATION SYSTEM

### What Makes an Elite Creative Brief

Based on the Ogilvy DO Brief methodology (the gold standard in advertising):

**Core questions every brief must answer:**
1. **Business objective**: What business result do we need?
2. **Who are we talking to**: Specific audience segment, not demographics
3. **Current behavior**: What do they do/think now?
4. **Desired behavior**: What do we want them to do/think after?
5. **Single-minded proposition**: ONE compelling reason to act (not three)
6. **Evidence**: Why should they believe us?
7. **Mandatories**: Brand guidelines, legal requirements, format specs
8. **Success measure**: How do we know it worked?
9. **Timeline and budget**: When and how much

### Auto-Generated Brief System for Your Agents

```python
# core/brief_generator.py
"""
Creative Brief Generator.

Reads from:
- DBH playbooks (proven patterns + ROAS data)
- Campaign intelligence DB (what has worked)
- Brand voice guidelines
- Current campaign calendar

Produces:
- Structured briefs that Roie can execute from immediately
- Design specs (dimensions, platform requirements)
- Copy direction with proven hooks
"""

import json
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class BriefGenerator:
    """Generate creative briefs from strategy + data + brand guidelines."""

    BRIEF_TEMPLATE = """
# CREATIVE BRIEF: {campaign_name}
## Generated: {date} | Status: READY FOR DESIGN

---

### 1. BUSINESS OBJECTIVE
{business_objective}

### 2. TARGET AUDIENCE
**Segment:** {audience_segment}
**Current state:** {current_behavior}
**Desired state:** {desired_behavior}
**Why they should care:** {relevance_hook}

### 3. SINGLE-MINDED PROPOSITION
> {proposition}

### 4. EVIDENCE / SUPPORT
{evidence}

### 5. CREATIVE DIRECTION
**Proven formula being used:** {formula_name} (historical ROAS: {formula_roas})
**Tone:** {tone}
**Visual direction:** {visual_direction}

### 6. COPY DIRECTION
**Headline options (ranked by predicted performance):**
{headline_options}

**Body copy framework:**
{body_copy_framework}

**CTA:** {cta}

### 7. DELIVERABLES
{deliverables_table}

### 8. DESIGN SPECS
{design_specs}

### 9. BRAND MANDATORIES
{brand_mandatories}

### 10. TIMELINE
- Brief to designer: {brief_date}
- First draft due: {draft_date}
- Feedback round: {feedback_date}
- Final assets due: {final_date}
- Launch date: {launch_date}

### 11. SUCCESS METRICS
{success_metrics}

### 12. REFERENCE / INSPIRATION
{references}

---
*Brief generated by Meridian (DBH Marketing Intelligence)*
*Formula source: {formula_source}*
"""

    # Standard deliverable specs per platform
    PLATFORM_SPECS = {
        "meta_feed": {
            "dimensions": "1080x1080 (square) or 1080x1350 (4:5)",
            "format": "Static image or 15-30s video",
            "text_limit": "125 chars primary, 30 chars headline",
            "file_types": "JPG, PNG, MP4",
            "notes": "Less than 20% text on image for maximum reach"
        },
        "meta_stories": {
            "dimensions": "1080x1920 (9:16)",
            "format": "Static or 15s video",
            "text_limit": "Keep text minimal, use stickers/polls",
            "file_types": "JPG, PNG, MP4",
            "notes": "Safe zone: keep key elements in center 1080x1420"
        },
        "email_hero": {
            "dimensions": "600px wide (responsive), hero image 600x400",
            "format": "HTML email with image",
            "text_limit": "Subject: 50 chars, preview: 90 chars",
            "file_types": "JPG, PNG, GIF",
            "notes": "Dark mode compatible. Test at 3 widths."
        },
        "email_banner": {
            "dimensions": "600x200 banner",
            "format": "Static image",
            "text_limit": "Minimal -- used as visual header",
            "file_types": "JPG, PNG",
            "notes": "Brand colours, simple messaging"
        },
        "shopify_banner": {
            "dimensions": "1920x600 desktop, 750x420 mobile",
            "format": "Static image",
            "text_limit": "Headline + subhead + CTA button",
            "file_types": "JPG, PNG",
            "notes": "Must work at both desktop and mobile sizes"
        }
    }

    # DBH's 5 proven formulas (from campaign analysis)
    PROVEN_FORMULAS = {
        "exclusive_access_countdown": {
            "name": "Exclusive Access + Countdown",
            "roas": "7.2x",
            "pattern": "Create urgency through limited-time exclusive access",
            "copy_hooks": [
                "Early access: {hours} hours only",
                "Members-only: your exclusive window closes at midnight",
                "You're getting this before anyone else"
            ],
            "visual_direction": "Bold countdown timer, exclusive badge/seal, dark premium background"
        },
        "event_announcement": {
            "name": "Event Announcement",
            "roas": "6.8x",
            "pattern": "Tie product to a specific event or occasion",
            "copy_hooks": [
                "{Event} is coming -- are you ready?",
                "The official {event} health pack",
                "Everything you need for {event}"
            ],
            "visual_direction": "Event-themed imagery, lifestyle context, seasonal colours"
        },
        "social_proof_testimonial": {
            "name": "Testimonial / Social Proof",
            "roas": "6.1x",
            "pattern": "Lead with customer results and social validation",
            "copy_hooks": [
                "'{quote}' -- {customer_name}, verified buyer",
                "{X} customers chose this last month",
                "See why {demographic} trust {product}"
            ],
            "visual_direction": "Customer photo/UGC, star ratings, before/after, quote overlay"
        },
        "day_of_product_grid": {
            "name": "Day-of Announcement + Product Grid",
            "roas": "5.9x",
            "pattern": "Launch day urgency with visual product showcase",
            "copy_hooks": [
                "IT'S HERE. {sale_name} starts NOW",
                "Shop the full collection -- today only",
                "Your complete {category} solution"
            ],
            "visual_direction": "Product grid layout, clean white background, price/discount badges"
        },
        "final_deadline_countdown": {
            "name": "Final Deadline + Countdown",
            "roas": "5.8x",
            "pattern": "Last-chance urgency with clear deadline",
            "copy_hooks": [
                "FINAL HOURS: {offer} ends at midnight",
                "Last chance -- this won't come back",
                "Closing in {hours}: your {discount}% is about to expire"
            ],
            "visual_direction": "Red/urgent colour palette, countdown timer, crossed-out prices"
        }
    }

    def generate_brief(self, campaign_name: str, formula_key: str,
                       business_objective: str, audience_segment: str,
                       platforms: list, launch_date: str,
                       additional_context: dict = None) -> str:
        """
        Generate a complete creative brief.

        Args:
            campaign_name: Name of the campaign
            formula_key: Which proven formula to use
            business_objective: What business result we need
            audience_segment: Who we are targeting
            platforms: List of platforms (meta_feed, email_hero, etc.)
            launch_date: When this launches
            additional_context: Any extra information
        """
        formula = self.PROVEN_FORMULAS.get(formula_key, self.PROVEN_FORMULAS["social_proof_testimonial"])

        # Build deliverables table
        deliverables = "| Platform | Dimensions | Format |\n|----------|-----------|--------|\n"
        design_specs = ""
        for platform in platforms:
            spec = self.PLATFORM_SPECS.get(platform, {})
            deliverables += f"| {platform} | {spec.get('dimensions', 'TBD')} | {spec.get('format', 'TBD')} |\n"
            design_specs += f"\n**{platform}:**\n"
            for key, val in spec.items():
                design_specs += f"  - {key}: {val}\n"

        # Build headline options from formula hooks
        headlines = ""
        for i, hook in enumerate(formula['copy_hooks'], 1):
            headlines += f"{i}. {hook}\n"

        context = additional_context or {}

        return self.BRIEF_TEMPLATE.format(
            campaign_name=campaign_name,
            date=datetime.now().strftime("%B %d, %Y"),
            business_objective=business_objective,
            audience_segment=audience_segment,
            current_behavior=context.get('current_behavior', 'Aware of brand but not purchasing / lapsed buyer'),
            desired_behavior=context.get('desired_behavior', 'Click through and purchase during campaign window'),
            relevance_hook=context.get('relevance_hook', 'Health optimization is a daily decision'),
            proposition=context.get('proposition', f'DBH gives you {business_objective.lower()} with zero risk'),
            evidence=context.get('evidence', 'Proven results from 133+ campaigns, 5.42x blended ROAS'),
            formula_name=formula['name'],
            formula_roas=formula['roas'],
            tone=context.get('tone', 'Direct, trustworthy, health-expert. Not salesy.'),
            visual_direction=formula['visual_direction'],
            headline_options=headlines,
            body_copy_framework=context.get('body_copy', 'Hook -> Problem -> Solution -> Evidence -> CTA'),
            cta=context.get('cta', 'Shop Now / Get Yours / Start Today'),
            deliverables_table=deliverables,
            design_specs=design_specs,
            brand_mandatories=context.get('mandatories',
                '- DBH logo (top right)\n- Brand colours: Navy (#1B365D), Gold (#C5A572)\n'
                '- Font: Clean sans-serif\n- No health claims without evidence\n'
                '- Disclaimer text where required'),
            brief_date=datetime.now().strftime("%B %d, %Y"),
            draft_date=context.get('draft_date', 'TBD'),
            feedback_date=context.get('feedback_date', 'TBD'),
            final_date=context.get('final_date', 'TBD'),
            launch_date=launch_date,
            success_metrics=context.get('success_metrics',
                '- ROAS target: 5.0x+\n- CTR target: 1.5%+\n'
                '- Email open rate: 40%+\n- Conversion rate: 2%+'),
            references=context.get('references', 'See playbooks for pattern examples'),
            formula_source=f"DBH Campaign Analysis (133 campaigns, pattern: {formula['name']})"
        )
```

### Integration: Auto-Brief from Meridian's Analysis

When Meridian identifies that a campaign needs to launch, it can auto-generate the brief:

```python
# In the agent's response processing, detect brief triggers:
BRIEF_TRIGGER_PROMPT = """
If your analysis concludes that a new campaign should be launched,
generate a brief trigger:
[BRIEF: campaign_name | formula_key | business_objective | audience | platforms | launch_date]

Example:
[BRIEF: March Flash Sale | exclusive_access_countdown | Drive $5K revenue in 48 hours |
lapsed-buyers-60d | meta_feed,email_hero | 2026-03-15]
"""
```

---

## 5. DESIGNER OUTPUT TRACKING / AI DESIGN EXPANSION

### Tracking Roie's Output

```python
# Add to learning_loop.py or a new core/design_tracker.py

"""
CREATE TABLE IF NOT EXISTS design_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brief_id TEXT,                       -- links to the creative brief
    designer TEXT DEFAULT 'roie',
    task_description TEXT NOT NULL,
    platform TEXT,                       -- meta_feed, email_hero, etc.
    status TEXT DEFAULT 'BRIEFED',       -- BRIEFED | IN_PROGRESS | SUBMITTED | REVISION | APPROVED | LIVE

    -- Timing metrics
    briefed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    first_draft_at TIMESTAMP,
    approved_at TIMESTAMP,

    -- Quality metrics
    revision_rounds INTEGER DEFAULT 0,
    feedback_notes TEXT,                 -- JSON array of feedback given

    -- Performance (filled after launch)
    campaign_roas REAL,
    campaign_ctr REAL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Design capacity dashboard query:
-- SELECT designer,
--        COUNT(*) as total_tasks,
--        AVG(julianday(first_draft_at) - julianday(briefed_at)) as avg_turnaround_days,
--        AVG(revision_rounds) as avg_revisions,
--        AVG(campaign_roas) as avg_roas
-- FROM design_tasks
-- WHERE approved_at IS NOT NULL
-- GROUP BY designer;
"""
```

### Key Metrics to Track

| Metric | Formula | Target |
|--------|---------|--------|
| Turnaround Time | first_draft_at - briefed_at | < 3 business days |
| Revision Rounds | COUNT of feedback loops | < 2 rounds |
| Brief-to-Live | approved_at - briefed_at | < 5 business days |
| Design Win Rate | tasks where ROAS > target / total tasks | > 60% |
| Throughput | tasks approved per week | 3-5/week |

### AI Design Expansion Strategy

For a solo operator with one designer, the priority order for AI design augmentation:

**Tier 1 -- Immediate (use now):**
- **Canva Pro with Brand Kit**: Upload DBH brand guidelines (colours, fonts, logo). Use Canva's template system for email banners, social posts. Roie focuses on hero creative; Canva handles variants.
- **AI Image Generation for Concepts**: Use DALL-E or Midjourney to generate 8-12 concept images per brief. Send these as "direction" to Roie rather than starting from scratch.

**Tier 2 -- Near-term (set up this quarter):**
- **Figma Plugin "Design with AI Agent"**: Generates design variants within Figma using AI, maintaining brand consistency through Figma's design system.
- **Canva API for Batch Variants**: Programmatically generate size variants from one master design. One Instagram post automatically becomes a Story, an email banner, and a website banner.

**Tier 3 -- Future (when volume justifies):**
- **AdCreative.ai or The Brief AI**: Platforms that generate complete ad creatives from a brief. Quality is sufficient for B-tier campaigns (retargeting, reminder ads) while Roie handles A-tier hero creative.
- **Figma-to-Code Automation**: Tools like Anima or Builder.io that convert Figma designs directly to Shopify sections, eliminating the design-to-development bottleneck.

### Practical Implementation: AI-Augmented Design Pipeline

```
BRIEF GENERATED (by Meridian)
    |
    v
AI CONCEPT GENERATION (8-12 variants via DALL-E/Midjourney)
    |
    v
TOM SELECTS TOP 3 CONCEPTS
    |
    v
ROIE EXECUTES HERO CREATIVE (Figma, using concept as direction)
    |
    v
AI VARIANT GENERATION (Canva API creates size variants)
    |
    v
TOM APPROVES
    |
    v
LIVE (auto-track performance in design_tasks table)
```

This pipeline lets one designer (Roie) produce the output of 3-4 designers by focusing human effort on the creative decisions while AI handles repetition.

---

## 6. SMART NOTIFICATION ROUTING

### Current State

Your system sends every message to the relevant Telegram group with no priority differentiation. All messages look the same. Tom gets the same notification for a routine morning brief as he does for a ROAS crash.

### Implementation: Severity-Based Notification Routing

```python
# core/notification_router.py
"""
Smart Notification Routing for Telegram.

Priority levels:
- CRITICAL: Immediate push notification with sound (ROAS crash, system error, breaking news)
- IMPORTANT: Normal notification (performance alerts, opportunities)
- NOTABLE: Silent notification (daily briefs, routine updates)
- INFO: Batched into digest (logged for reference, no individual notification)

Additional features:
- Do Not Disturb hours (configurable per agent)
- Batch digest for low-priority items
- Escalation (INFO items that persist become IMPORTANT)
"""

import json
import sqlite3
from datetime import datetime, time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class NotificationRouter:
    """Routes notifications based on severity and user preferences."""

    # DND window (NZ timezone)
    DND_START = time(22, 0)   # 10 PM
    DND_END = time(6, 0)      # 6 AM

    # Severity -> Telegram parameters
    SEVERITY_CONFIG = {
        "CRITICAL": {
            "disable_notification": False,
            "prefix": "🚨 CRITICAL",
            "parse_mode": "Markdown",
            "bypass_dnd": True,     # Critical always gets through
            "batch": False
        },
        "IMPORTANT": {
            "disable_notification": False,
            "prefix": "⚡",
            "parse_mode": "Markdown",
            "bypass_dnd": False,
            "batch": False
        },
        "NOTABLE": {
            "disable_notification": True,   # Silent notification
            "prefix": "",
            "parse_mode": "Markdown",
            "bypass_dnd": False,
            "batch": False
        },
        "INFO": {
            "disable_notification": True,
            "prefix": "",
            "parse_mode": "Markdown",
            "bypass_dnd": False,
            "batch": True           # Batched into digest
        }
    }

    def __init__(self):
        self.db_path = str(BASE_DIR / "data" / "notifications.db")
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS notification_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                message TEXT NOT NULL,
                severity TEXT DEFAULT 'NOTABLE',
                status TEXT DEFAULT 'PENDING',    -- PENDING | SENT | BATCHED | SUPPRESSED
                batch_id TEXT,                     -- groups messages for digest
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS notification_prefs (
                agent TEXT PRIMARY KEY,
                dnd_start TEXT DEFAULT '22:00',
                dnd_end TEXT DEFAULT '06:00',
                batch_interval_minutes INTEGER DEFAULT 60,
                min_severity TEXT DEFAULT 'NOTABLE'  -- suppress below this
            );

            CREATE INDEX IF NOT EXISTS idx_notif_status ON notification_queue(status);
        """)
        conn.commit()
        conn.close()

    def send(self, agent: str, chat_id: str, message: str,
             severity: str, bot_token: str):
        """
        Route a notification based on severity and preferences.

        This replaces the direct send_telegram() call in orchestrator.py.
        """
        import requests

        config = self.SEVERITY_CONFIG.get(severity, self.SEVERITY_CONFIG["NOTABLE"])
        now = datetime.now().time()

        # Check DND
        is_dnd = self._is_dnd(now)
        if is_dnd and not config['bypass_dnd']:
            if severity == "INFO":
                self._queue_for_batch(agent, chat_id, message, severity)
                return
            elif severity == "NOTABLE":
                # Delay until DND ends
                self._queue_for_batch(agent, chat_id, message, severity)
                return
            # IMPORTANT during DND: send silently
            config = dict(config)
            config['disable_notification'] = True

        # Batch INFO messages
        if config['batch']:
            self._queue_for_batch(agent, chat_id, message, severity)
            return

        # Add severity prefix
        if config['prefix']:
            message = f"{config['prefix']}\n\n{message}"

        # Send via Telegram
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

        # Handle Telegram's 4096 char limit
        chunks = self._split_message(message)
        for chunk in chunks:
            payload = {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": config.get('parse_mode', 'Markdown'),
                "disable_notification": config['disable_notification']
            }
            try:
                requests.post(url, json=payload, timeout=10)
            except Exception as e:
                print(f"Notification send failed: {e}")

        # Log
        self._log_sent(agent, chat_id, message[:200], severity)

    def _is_dnd(self, current_time: time) -> bool:
        """Check if we are in Do Not Disturb window."""
        if self.DND_START > self.DND_END:
            # DND crosses midnight (e.g., 22:00 - 06:00)
            return current_time >= self.DND_START or current_time < self.DND_END
        else:
            return self.DND_START <= current_time < self.DND_END

    def _queue_for_batch(self, agent: str, chat_id: str,
                         message: str, severity: str):
        """Queue a message for the next batch digest."""
        conn = sqlite3.connect(self.db_path)
        batch_id = datetime.now().strftime("%Y%m%d_%H")  # Hourly batches
        conn.execute("""
            INSERT INTO notification_queue
            (agent, chat_id, message, severity, status, batch_id)
            VALUES (?, ?, ?, ?, 'BATCHED', ?)
        """, (agent, chat_id, message[:2000], severity, batch_id))
        conn.commit()
        conn.close()

    def send_batch_digest(self, bot_token: str):
        """
        Send accumulated batch messages as a single digest.
        Called by the scheduler every 1-2 hours.
        """
        import requests

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        # Get all pending batched messages grouped by chat_id
        rows = conn.execute("""
            SELECT chat_id, agent, message, severity, created_at
            FROM notification_queue
            WHERE status = 'BATCHED'
            ORDER BY created_at ASC
        """).fetchall()

        if not rows:
            conn.close()
            return

        # Group by chat_id
        by_chat = {}
        for r in rows:
            by_chat.setdefault(r['chat_id'], []).append(dict(r))

        for chat_id, messages in by_chat.items():
            digest = f"📋 *Digest* ({len(messages)} items)\n\n"
            for msg in messages:
                short = msg['message'][:150].replace('\n', ' ')
                digest += f"• [{msg['agent']}] {short}\n"

            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            requests.post(url, json={
                "chat_id": chat_id,
                "text": digest,
                "parse_mode": "Markdown",
                "disable_notification": True
            }, timeout=10)

        # Mark all as sent
        conn.execute("""
            UPDATE notification_queue
            SET status = 'SENT', sent_at = CURRENT_TIMESTAMP
            WHERE status = 'BATCHED'
        """)
        conn.commit()
        conn.close()

    def _split_message(self, text: str, max_len: int = 4000) -> list:
        """Split message into Telegram-safe chunks."""
        if len(text) <= max_len:
            return [text]
        return [text[i:i+max_len] for i in range(0, len(text), max_len)]

    def _log_sent(self, agent, chat_id, message, severity):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            INSERT INTO notification_queue
            (agent, chat_id, message, severity, status, sent_at)
            VALUES (?, ?, ?, ?, 'SENT', CURRENT_TIMESTAMP)
        """, (agent, chat_id, message, severity))
        conn.commit()
        conn.close()
```

### Severity Classification

Add this to each agent's response processing:

```python
SEVERITY_CLASSIFICATION_PROMPT = """
Before sending your response, classify its priority:
- CRITICAL: System failure, major ROAS drop (>30%), breaking geopolitical event affecting business
- IMPORTANT: Performance alert, new opportunity, campaign results ready for review
- NOTABLE: Routine briefings, updates, scan results
- INFO: Background observations, minor data points, logging

Add at the start of your response: [SEVERITY: CRITICAL|IMPORTANT|NOTABLE|INFO]
"""
```

---

## 7. REPLENISHMENT REMINDER SYSTEMS

### How Leading DTC Supplement Brands Do It

**AG1 (Athletic Greens):**
- Subscription-first model (30-day auto-ship)
- Pre-charge confirmation emails ("AG1, confirmed")
- Skip/pause options instead of cancel
- Benefit reinforcement in every touchpoint

**Seed Health:**
- 30-day subscription cycle
- Educational content dripped between orders
- Pause/skip/adjust frequency options

### DBH Replenishment System Design

#### Step 1: Product Consumption Rate Table

```python
# Define consumption rates for DBH products
DBH_PRODUCT_CONSUMPTION = {
    # Product name -> days of supply per unit
    "Green Lipped Mussel 18000": {"days_supply": 60, "reminder_day": 50},
    "Green Lipped Mussel 9000": {"days_supply": 30, "reminder_day": 25},
    "Deer Velvet": {"days_supply": 30, "reminder_day": 25},
    "Omega 3 Fish Oil": {"days_supply": 30, "reminder_day": 25},
    "Vitamin D3": {"days_supply": 60, "reminder_day": 50},
    "Collagen Complex": {"days_supply": 30, "reminder_day": 25},
    "Joint Support Complex": {"days_supply": 30, "reminder_day": 25},
    # Pure Pets
    "Pure Pets Joint Care": {"days_supply": 30, "reminder_day": 22},
    "Pure Pets Senior Support": {"days_supply": 30, "reminder_day": 22},
}
```

#### Step 2: Klaviyo Flow Architecture

```
TRIGGER: Placed Order (Fulfilled)
    |
    v
CONDITIONAL SPLIT: Has product X?
    |
    YES --> TIME DELAY: {reminder_day} days
    |           |
    |           v
    |       CONDITIONAL SPLIT: Has purchased since trigger?
    |           |
    |           YES --> EXIT (they already reordered)
    |           NO -->
    |               |
    |               v
    |           EMAIL 1: "Time for your next supply?"
    |               - Personalized with product name
    |               - Shows how many days of supply remaining
    |               - One-click reorder button
    |               |
    |               v
    |           TIME DELAY: 2 days
    |               |
    |               v
    |           CONDITIONAL SPLIT: Has purchased since trigger?
    |               |
    |               YES --> EXIT
    |               NO -->
    |                   |
    |                   v
    |               EMAIL 2: Social proof + urgency
    |                   - "X customers reordered this week"
    |                   - "Don't break your streak"
    |                   |
    |                   v
    |               TIME DELAY: 3 days
    |                   |
    |                   v
    |               EMAIL 3: Incentive offer
    |                   - "10% off your reorder"
    |                   - "Free shipping on your next order"
    |                   - Only if no purchase in flow
    |
    NO --> CHECK NEXT PRODUCT...
```

#### Step 3: Integration with Your Command Center

Track replenishment effectiveness through the learning loop:

```python
# core/replenishment_tracker.py
"""
Replenishment Intelligence.

Tracks:
1. Which products have predictable reorder cycles
2. Which reminder timing works best per product
3. Which email copy/subject drives highest reorder rate
4. Customer-specific consumption patterns (some use more/less)
"""

from core.order_intelligence import get_db

def calculate_customer_reorder_pattern(customer_email: str) -> dict:
    """
    Analyse a customer's actual reorder intervals.
    Returns their real consumption rate vs the default assumption.
    """
    db = get_db()

    orders = db.execute("""
        SELECT o.order_date, o.products
        FROM orders o
        JOIN customers c ON o.customer_id = c.shopify_id
        WHERE c.email = ?
        ORDER BY o.order_date ASC
    """, (customer_email,)).fetchall()

    if len(orders) < 2:
        db.close()
        return {"status": "insufficient_data", "orders": len(orders)}

    # Calculate intervals between orders
    from datetime import datetime
    intervals = []
    for i in range(1, len(orders)):
        d1 = datetime.fromisoformat(orders[i-1][0])
        d2 = datetime.fromisoformat(orders[i][0])
        intervals.append((d2 - d1).days)

    db.close()

    avg_interval = sum(intervals) / len(intervals)

    return {
        "status": "analysed",
        "total_orders": len(orders),
        "avg_reorder_days": round(avg_interval, 1),
        "min_interval": min(intervals),
        "max_interval": max(intervals),
        "optimal_reminder_day": round(avg_interval * 0.8),  # 80% of avg interval
        "intervals": intervals
    }


def get_replenishment_candidates() -> list:
    """
    Find customers who are likely running out of product.
    Called daily by Meridian to flag reorder opportunities.
    """
    db = get_db()

    # Get customers whose last order was N days ago
    # where N is close to their typical reorder interval
    candidates = db.execute("""
        SELECT
            c.email, c.first_name, c.last_name,
            c.total_orders, c.avg_order_value,
            o.order_date as last_order_date,
            o.products as last_products,
            julianday('now') - julianday(o.order_date) as days_since_order
        FROM customers c
        JOIN orders o ON o.customer_id = c.shopify_id
        WHERE o.id = (
            SELECT MAX(id) FROM orders WHERE customer_id = c.shopify_id
        )
        AND c.total_orders >= 2
        AND julianday('now') - julianday(o.order_date) BETWEEN 20 AND 45
        ORDER BY days_since_order DESC
    """).fetchall()

    db.close()

    return [dict(c) for c in candidates]
```

#### Step 4: Email Templates (for Klaviyo)

**Email 1 (Day 25): Gentle Reminder**
```
Subject: "Your {product_name} -- time for a top-up?"
Preview: "Based on your order {days_ago} days ago"

Hi {first_name},

You ordered {product_name} {days_ago} days ago. If you've been
taking it daily as recommended, you're probably getting close to
the end of your supply.

[Reorder {product_name} ->]

Same quality. Same results. Delivered to your door.

{first_name_possessive} health, on autopilot.

Deep Blue Health
```

**Email 2 (Day 27): Social Proof**
```
Subject: "{X} customers reordered this month"
Preview: "Join them -- your supply is running low"

Hi {first_name},

Quick reminder: your {product_name} supply from {order_date}
is running low.

{testimonial_quote}
-- {testimonial_name}, repeat customer

[Reorder Now ->]

P.S. Consistent supplementation is key to results.
Don't break the cycle.
```

**Email 3 (Day 30): Incentive**
```
Subject: "10% off your {product_name} reorder"
Preview: "Because loyal customers deserve better"

Hi {first_name},

We noticed you haven't reordered your {product_name} yet.

Here's 10% off to make it easy:
Code: REORDER10

[Apply Discount & Reorder ->]

Valid for 48 hours. One-time use.

Stay healthy,
Deep Blue Health
```

### Optimal Timing Research

From Klaviyo community data and supplement industry benchmarks:

| Product Supply | Email 1 | Email 2 | Email 3 |
|---------------|---------|---------|---------|
| 30-day supply | Day 25 | Day 27 | Day 30 |
| 60-day supply | Day 50 | Day 54 | Day 58 |
| 90-day supply | Day 75 | Day 80 | Day 85 |

Best send times (from Omnisend research):
- **8 PM**: 59% open rates (highest)
- **2 PM**: 45% open rates
- **5-6 PM**: 40%+ open rates

Best days: Month-start and month-end show peak conversion rates for supplement replenishment.

---

## ARCHITECTURE SUMMARY: THE COMPLETE SELF-IMPROVING SYSTEM

```
                    ┌─────────────────────────────┐
                    │      TELEGRAM INTERFACE      │
                    │   (9 group chats + polling)   │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │    NOTIFICATION ROUTER        │
                    │  (severity + DND + batching)  │
                    └──────────────┬───────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │       ORCHESTRATOR            │
                    │  (routes messages + tasks)    │
                    └──┬───────────┬───────────┬───┘
                       │           │           │
            ┌──────────▼──┐ ┌─────▼─────┐ ┌───▼──────────┐
            │ AGENT BRAIN │ │ EVENT BUS │ │ SELF-IMPROVE │
            │  LOADER     │ │ (SQLite)  │ │   ENGINE     │
            │  (md files) │ │           │ │ (LLM judge)  │
            └─────────────┘ └───────────┘ └──────────────┘
                       │           │           │
                    ┌──▼───────────▼───────────▼───┐
                    │     INTELLIGENCE DATABASE     │
                    │  (learning_loop.py -- SQLite)  │
                    │                               │
                    │  insights | cycles | events   │
                    │  decisions | metrics | state   │
                    │  strategies | evaluations     │
                    │  predictions | sessions       │
                    │  memory_facts | design_tasks  │
                    └───────────────────────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │    CONTEXT GENERATOR          │
                    │  (DB -> CONTEXT.md per agent)  │
                    └──────────────────────────────┘
```

### The Self-Improvement Loop in Practice

```
1. SCHEDULED TASK fires (or Tom sends a message)
2. Orchestrator loads agent brain (AGENT.md + skills + playbooks + CONTEXT.md)
3. Event Bus injects any cross-agent events pending for this agent
4. Self-Improvement Engine injects performance report (top/failing strategies)
5. Claude generates response
6. PARALLEL POST-PROCESSING:
   a. InsightExtractor: pulls structured insights from response
   b. LLM-as-Judge (Haiku): scores response quality -> updates strategy weights
   c. Event parser: detects cross-agent events to publish
   d. Prediction extractor: logs any predictions for later verification
7. NotificationRouter: sends response to Telegram with correct severity
8. Context regenerated from updated database
9. Next cycle starts with richer context
```

### Priority Order of Implementation

Based on impact and your current system state:

| Priority | Component | Effort | Impact |
|----------|-----------|--------|--------|
| 1 | Notification Router (severity-based) | 2-3 hours | Immediate UX improvement |
| 2 | Event Bus (cross-agent communication) | 3-4 hours | Agents become autonomous |
| 3 | LLM-as-Judge evaluation loop | 2-3 hours | Quality measurement begins |
| 4 | Strategy weight tracking | 2-3 hours | Self-improvement starts |
| 5 | Session memory + continuation | 2-3 hours | No more context loss |
| 6 | Creative brief generator | 2-3 hours | Design pipeline accelerates |
| 7 | Replenishment tracker | 3-4 hours | Revenue automation |
| 8 | Design task tracking | 1-2 hours | Designer accountability |
| 9 | Memory consolidation (weekly) | 1-2 hours | Prevents context bloat |
| 10 | Full-text search (FTS5) | 1 hour | Memory becomes queryable |

Total estimated build time: 20-30 hours of focused implementation.

---

## SOURCES

### Cross-Agent Event Bus / Shared Context
- [Four Design Patterns for Event-Driven, Multi-Agent Systems](https://www.confluent.io/blog/event-driven-multi-agent-systems/) -- Confluent
- [LangGraph Multi-Agent Workflows](https://blog.langchain.com/langgraph-multi-agent-workflows/) -- LangChain
- [LangGraph vs CrewAI Comparison](https://xcelore.com/blog/langgraph-vs-crewai/) -- Xcelore
- [Multi-Agent System Architecture Guide for 2026](https://www.clickittech.com/ai/multi-agent-system-architecture/) -- ClickIT
- [MCP & Multi-Agent AI](https://onereach.ai/blog/mcp-multi-agent-ai-collaborative-intelligence/) -- OneReach
- [Building an Event Bus with asyncio in Python](https://oneuptime.com/blog/post/2026-01-25-event-bus-asyncio-python/view)
- [aiosqlite -- asyncio bridge to SQLite](https://github.com/omnilib/aiosqlite)

### Self-Improving Learning Loops
- [Self-Evolving Agents -- OpenAI Cookbook](https://cookbook.openai.com/examples/partners/self_evolving_agents/autonomous_agent_retraining)
- [Better Ways to Build Self-Improving AI Agents](https://yoheinakajima.com/better-ways-to-build-self-improving-ai-agents/) -- Yohei Nakajima
- [Truly Self-Improving Agents Require Intrinsic Metacognitive Learning](https://openreview.net/forum?id=4KhDd0Ozqe) -- ICML 2025
- [Self-Improving AI Agents through Self-Play](https://arxiv.org/abs/2512.02731) -- NeurIPS 2025
- [Mastering Confidence Scoring in AI Agents](https://sparkco.ai/blog/mastering-confidence-scoring-in-ai-agents)
- [LLM-as-a-Judge: Complete Guide](https://www.confident-ai.com/blog/why-llm-as-a-judge-is-the-best-llm-evaluation-method) -- Confident AI

### Persistent Memory Across Sessions
- [Persistent Memory for AI Agents: Comparing Approaches](https://sparkco.ai/blog/persistent-memory-for-ai-agents-comparing-pag-memorymd-and-sqlite-approaches)
- [AI Agent with Multi-Session Memory](https://towardsdatascience.com/ai-agent-with-multi-session-memory/) -- Towards Data Science
- [Local-First RAG Using SQLite for AI Agent Memory](https://www.pingcap.com/blog/local-first-rag-using-sqlite-ai-agent-memory-openclaw/) -- PingCAP
- [Mastering AI Agent Memory Architecture](https://dev.to/oblivionlabz/mastering-ai-agent-memory-architecture-a-deep-dive-into-the-complete-os-for-power-users-2lfb)
- [Claude Memory Tool -- API Docs](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool) -- Anthropic
- [Anthropic Claude Agent SDK -- Multi-Session](https://venturebeat.com/ai/anthropic-says-it-solved-the-long-running-ai-agent-problem-with-a-new-multi) -- VentureBeat

### Creative Brief Generation
- [Ogilvy DO Brief Template](https://www.scribd.com/document/475407107/ogilvy-DO-Brief-template-doc)
- [The Brief AI -- AI-Powered Ad Generation](https://www.thebrief.ai/)
- [Foreplay Briefs -- Performance Marketing](https://www.foreplay.co/briefs)
- [Briefly -- Creative Operations Platform](https://trybriefly.com/)

### Designer Output Tracking
- [Making Metrics Matter -- Design Systems 104](https://www.figma.com/blog/design-systems-104-making-metrics-matter/) -- Figma
- [Design with AI Agent -- Figma Plugin](https://www.figma.com/community/plugin/1589219376862346255/design-with-ai-agent)
- [The Future of Design Systems is Automated](https://www.figma.com/blog/the-future-of-design-systems-is-automated/) -- Figma

### Smart Notification Routing
- [python-telegram-bot -- disable_notification](https://docs.python-telegram-bot.org/telegram.bot.html)
- [Priority Queue in Python](https://docs.python.org/3/library/queue.html)

### Replenishment Reminder Systems
- [How to Create a Replenishment Flow -- Klaviyo](https://help.klaviyo.com/hc/en-us/articles/360003195232)
- [Replenishment Email Best Practices -- Klaviyo Blog](https://www.klaviyo.com/blog/the-email-automation-all-consumable-goods-brands-need-that-many-dont-yet-use)
- [Klaviyo Replenishment Flow: 5 Strategies](https://www.titanmarketingagency.com/articles/klaviyo-replenishment-flow)
- [AG1 Marketing Strategy](https://www.panoramata.co/marketing-strategy-brand/ag1) -- Panoramata
- [7 Replenishment Email Examples](https://www.omnisend.com/blog/replenishment-email/) -- Omnisend
