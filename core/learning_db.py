#!/usr/bin/env python3
"""
Learning Database + Context Generator

The institutional memory of Tom's Command Center.
- Logs insights, decisions, outcomes, patterns, metrics
- Generates fresh CONTEXT.md for each agent from structured data
- Handles insight promotion pipeline
"""

import sqlite3
import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

BASE_DIR = Path.home() / "tom-command-center"
DB_PATH = BASE_DIR / "data" / "learning.db"


class LearningDB:
    """Structured learning database — the source of truth."""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
    
    def _init_schema(self):
        """Create tables if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS insights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL,
                category TEXT NOT NULL,
                content TEXT NOT NULL,
                evidence TEXT,
                confidence TEXT DEFAULT 'medium',
                tags TEXT,
                source TEXT DEFAULT 'observation',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                promoted_to_playbook BOOLEAN DEFAULT 0
            );
            
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL,
                decision TEXT NOT NULL,
                rationale TEXT,
                expected_outcome TEXT,
                actual_outcome TEXT,
                status TEXT DEFAULT 'active',
                insight_ids TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                resolved_at TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                value REAL NOT NULL,
                period TEXT DEFAULT 'daily',
                context TEXT,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE TABLE IF NOT EXISTS patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL,
                pattern TEXT NOT NULL,
                occurrences INTEGER DEFAULT 1,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                insight_ids TEXT,
                status TEXT DEFAULT 'emerging'
            );
            
            CREATE TABLE IF NOT EXISTS interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL,
                trigger TEXT NOT NULL,
                task TEXT,
                input_summary TEXT,
                output_summary TEXT,
                insights_generated TEXT,
                decisions_made TEXT,
                tokens_used INTEGER,
                model_used TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            
            CREATE INDEX IF NOT EXISTS idx_insights_agent ON insights(agent);
            CREATE INDEX IF NOT EXISTS idx_insights_created ON insights(created_at);
            CREATE INDEX IF NOT EXISTS idx_metrics_agent_name ON metrics(agent, metric_name);
            CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status);
        """)
        self.conn.commit()
    
    # ─── INSIGHT OPERATIONS ──────────────────────────────────────────────
    
    def log_insight(self, agent: str, category: str, content: str,
                    evidence: str = None, confidence: str = "medium",
                    tags: str = None, source: str = "observation") -> int:
        """Log a new insight. Returns the insight ID."""
        cursor = self.conn.execute(
            """INSERT INTO insights (agent, category, content, evidence, confidence, tags, source)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (agent, category, content, evidence, confidence, tags, source)
        )
        self.conn.commit()
        
        # Check for pattern formation
        self._check_patterns(agent, content, tags, cursor.lastrowid)
        
        return cursor.lastrowid
    
    def get_recent_insights(self, agent: str, days: int = 30, limit: int = 20) -> list:
        """Get recent insights for an agent."""
        since = (datetime.now() - timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            """SELECT * FROM insights WHERE agent = ? AND created_at > ? 
               ORDER BY created_at DESC LIMIT ?""",
            (agent, since, limit)
        ).fetchall()
        return [dict(r) for r in rows]
    
    def get_high_confidence_insights(self, agent: str) -> list:
        """Get proven/high-confidence insights for an agent."""
        rows = self.conn.execute(
            """SELECT * FROM insights WHERE agent = ? AND confidence IN ('high', 'proven')
               ORDER BY created_at DESC""",
            (agent,)
        ).fetchall()
        return [dict(r) for r in rows]
    
    # ─── DECISION OPERATIONS ─────────────────────────────────────────────
    
    def log_decision(self, agent: str, decision: str, rationale: str = None,
                     expected_outcome: str = None, insight_ids: str = None) -> int:
        """Log a decision. Returns the decision ID."""
        cursor = self.conn.execute(
            """INSERT INTO decisions (agent, decision, rationale, expected_outcome, insight_ids)
               VALUES (?, ?, ?, ?, ?)""",
            (agent, decision, rationale, expected_outcome, insight_ids)
        )
        self.conn.commit()
        return cursor.lastrowid
    
    def resolve_decision(self, decision_id: int, actual_outcome: str, 
                         status: str = "completed"):
        """Record the outcome of a decision."""
        self.conn.execute(
            """UPDATE decisions SET actual_outcome = ?, status = ?, resolved_at = ?
               WHERE id = ?""",
            (actual_outcome, status, datetime.now().isoformat(), decision_id)
        )
        self.conn.commit()
    
    def get_active_decisions(self, agent: str) -> list:
        """Get active decisions for an agent."""
        rows = self.conn.execute(
            """SELECT * FROM decisions WHERE agent = ? AND status = 'active'
               ORDER BY created_at DESC""",
            (agent,)
        ).fetchall()
        return [dict(r) for r in rows]
    
    # ─── METRIC OPERATIONS ───────────────────────────────────────────────
    
    def log_metric(self, agent: str, metric_name: str, value: float,
                   period: str = "daily", context: str = None):
        """Log a metric value."""
        self.conn.execute(
            """INSERT INTO metrics (agent, metric_name, value, period, context)
               VALUES (?, ?, ?, ?, ?)""",
            (agent, metric_name, value, period, context)
        )
        self.conn.commit()
    
    def get_metric_trend(self, agent: str, metric_name: str, days: int = 30) -> list:
        """Get metric trend over time."""
        since = (datetime.now() - timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            """SELECT value, recorded_at, context FROM metrics 
               WHERE agent = ? AND metric_name = ? AND recorded_at > ?
               ORDER BY recorded_at ASC""",
            (agent, metric_name, since)
        ).fetchall()
        return [dict(r) for r in rows]
    
    def get_latest_metrics(self, agent: str) -> dict:
        """Get the latest value for each metric an agent tracks."""
        rows = self.conn.execute(
            """SELECT metric_name, value, recorded_at, context FROM metrics 
               WHERE agent = ? AND id IN (
                   SELECT MAX(id) FROM metrics WHERE agent = ? GROUP BY metric_name
               )""",
            (agent, agent)
        ).fetchall()
        return {r["metric_name"]: {"value": r["value"], "recorded_at": r["recorded_at"], 
                                    "context": r["context"]} for r in rows}
    
    # ─── PATTERN OPERATIONS ──────────────────────────────────────────────
    
    def _check_patterns(self, agent: str, content: str, tags: str, insight_id: int):
        """Check if this insight forms or strengthens a pattern."""
        # Simple pattern detection: look for similar recent insights
        if tags:
            tag_list = [t.strip() for t in tags.split(",")]
            for tag in tag_list:
                similar = self.conn.execute(
                    """SELECT COUNT(*) as cnt FROM insights 
                       WHERE agent = ? AND tags LIKE ? AND created_at > ?""",
                    (agent, f"%{tag}%", 
                     (datetime.now() - timedelta(days=30)).isoformat())
                ).fetchone()
                
                if similar and similar["cnt"] >= 3:
                    # Check if pattern already exists
                    existing = self.conn.execute(
                        """SELECT id, occurrences, insight_ids FROM patterns 
                           WHERE agent = ? AND pattern LIKE ? AND status != 'integrated'""",
                        (agent, f"%{tag}%")
                    ).fetchone()
                    
                    if existing:
                        new_ids = f"{existing['insight_ids']},{insight_id}"
                        self.conn.execute(
                            """UPDATE patterns SET occurrences = occurrences + 1, 
                               last_seen = ?, insight_ids = ?
                               WHERE id = ?""",
                            (datetime.now().isoformat(), new_ids, existing["id"])
                        )
                    else:
                        self.conn.execute(
                            """INSERT INTO patterns (agent, pattern, insight_ids)
                               VALUES (?, ?, ?)""",
                            (agent, f"Recurring theme: {tag} (auto-detected)", 
                             str(insight_id))
                        )
        self.conn.commit()
    
    def get_emerging_patterns(self, agent: str) -> list:
        """Get patterns that are forming but not yet confirmed."""
        rows = self.conn.execute(
            """SELECT * FROM patterns WHERE agent = ? AND status IN ('emerging', 'confirmed')
               ORDER BY occurrences DESC""",
            (agent,)
        ).fetchall()
        return [dict(r) for r in rows]
    
    def promote_pattern(self, pattern_id: int, new_status: str):
        """Promote a pattern through the pipeline."""
        valid_statuses = ['emerging', 'confirmed', 'actionable', 'integrated']
        if new_status in valid_statuses:
            self.conn.execute(
                "UPDATE patterns SET status = ? WHERE id = ?",
                (new_status, pattern_id)
            )
            self.conn.commit()
    
    # ─── INTERACTION LOG ─────────────────────────────────────────────────
    
    def log_interaction(self, agent: str, trigger: str, task: str = None,
                       input_summary: str = None, output_summary: str = None,
                       insights_generated: str = None, decisions_made: str = None,
                       tokens_used: int = None, model_used: str = None):
        """Log an agent interaction for audit trail."""
        self.conn.execute(
            """INSERT INTO interactions 
               (agent, trigger, task, input_summary, output_summary, 
                insights_generated, decisions_made, tokens_used, model_used)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (agent, trigger, task, input_summary, output_summary,
             insights_generated, decisions_made, tokens_used, model_used)
        )
        self.conn.commit()
    
    # ─── CROSS-AGENT QUERIES ─────────────────────────────────────────────
    
    def get_all_recent_insights(self, days: int = 7) -> list:
        """Get recent insights across ALL agents (for Oracle briefing)."""
        since = (datetime.now() - timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            """SELECT * FROM insights WHERE created_at > ?
               ORDER BY created_at DESC""",
            (since,)
        ).fetchall()
        return [dict(r) for r in rows]
    
    def get_cross_domain_connections(self) -> list:
        """Find insights with overlapping tags across different agents."""
        rows = self.conn.execute(
            """SELECT a.agent as agent_a, b.agent as agent_b, 
                      a.content as insight_a, b.content as insight_b,
                      a.tags as tags_a, b.tags as tags_b
               FROM insights a, insights b
               WHERE a.agent != b.agent 
                 AND a.tags IS NOT NULL AND b.tags IS NOT NULL
                 AND a.created_at > ? AND b.created_at > ?
               LIMIT 20""",
            ((datetime.now() - timedelta(days=14)).isoformat(),
             (datetime.now() - timedelta(days=14)).isoformat())
        ).fetchall()
        
        # Simple tag overlap detection
        connections = []
        for r in rows:
            tags_a = set(t.strip() for t in (r["tags_a"] or "").split(","))
            tags_b = set(t.strip() for t in (r["tags_b"] or "").split(","))
            overlap = tags_a & tags_b - {""}
            if overlap:
                connections.append({
                    "agents": [r["agent_a"], r["agent_b"]],
                    "overlapping_tags": list(overlap),
                    "insights": [r["insight_a"], r["insight_b"]]
                })
        
        return connections
    
    def close(self):
        self.conn.close()


# ─── CONTEXT GENERATOR ──────────────────────────────────────────────────────

class ContextGenerator:
    """
    Generates fresh CONTEXT.md files from the database.
    This replaces the flat-file state management.
    """
    
    def __init__(self, db: LearningDB = None):
        self.db = db or LearningDB()
    
    def generate_context(self, agent: str) -> str:
        """Generate a complete CONTEXT.md for an agent from the database."""
        sections = []
        now = datetime.now()
        
        sections.append(f"# CONTEXT.md — {agent} (Auto-generated)")
        sections.append(f"## Generated: {now.strftime('%B %d, %Y %H:%M NZST')}")
        
        # Active decisions
        decisions = self.db.get_active_decisions(agent)
        if decisions:
            sections.append("\n## ACTIVE DECISIONS")
            for d in decisions[:10]:
                sections.append(f"- **{d['decision']}**")
                if d['rationale']:
                    sections.append(f"  Rationale: {d['rationale']}")
                if d['expected_outcome']:
                    sections.append(f"  Expected: {d['expected_outcome']}")
        
        # Latest metrics
        metrics = self.db.get_latest_metrics(agent)
        if metrics:
            sections.append("\n## CURRENT METRICS")
            for name, data in metrics.items():
                sections.append(f"- {name}: {data['value']} (as of {data['recorded_at'][:10]})")
        
        # Recent insights (last 14 days)
        recent = self.db.get_recent_insights(agent, days=14, limit=10)
        if recent:
            sections.append("\n## RECENT INSIGHTS (Last 14 days)")
            for i in recent:
                conf_emoji = {"low": "⬜", "medium": "🟨", "high": "🟩", "proven": "✅"}.get(
                    i['confidence'], "⬜")
                sections.append(f"- {conf_emoji} [{i['category']}] {i['content']}")
        
        # Proven insights (always include)
        proven = self.db.get_high_confidence_insights(agent)
        if proven:
            sections.append("\n## PROVEN INSIGHTS (High confidence)")
            for i in proven[:15]:
                sections.append(f"- ✅ {i['content']}")
                if i['evidence']:
                    sections.append(f"  Evidence: {i['evidence']}")
        
        # Emerging patterns
        patterns = self.db.get_emerging_patterns(agent)
        if patterns:
            sections.append("\n## EMERGING PATTERNS")
            for p in patterns:
                status_emoji = {"emerging": "🔵", "confirmed": "🟡", "actionable": "🟠"}.get(
                    p['status'], "⚪")
                sections.append(f"- {status_emoji} {p['pattern']} (seen {p['occurrences']}x)")
        
        return "\n".join(sections)
    
    def generate_all(self):
        """Regenerate CONTEXT.md for all agents."""
        agents_dir = BASE_DIR / "agents"
        for agent_dir in sorted(agents_dir.iterdir()):
            if agent_dir.is_dir() and (agent_dir / "AGENT.md").exists():
                context = self.generate_context(agent_dir.name)
                state_dir = agent_dir / "state"
                state_dir.mkdir(exist_ok=True)
                (state_dir / "CONTEXT.md").write_text(context)
                print(f"Generated context for {agent_dir.name}")
    
    def generate_oracle_context(self) -> str:
        """Special context for Oracle — cross-agent intelligence."""
        sections = []
        now = datetime.now()
        
        sections.append(f"# CROSS-DOMAIN INTELLIGENCE (Auto-generated)")
        sections.append(f"## Generated: {now.strftime('%B %d, %Y %H:%M NZST')}")
        
        # Recent insights across all agents
        all_insights = self.db.get_all_recent_insights(days=7)
        if all_insights:
            by_agent = {}
            for i in all_insights:
                by_agent.setdefault(i['agent'], []).append(i)
            
            sections.append("\n## THIS WEEK BY DOMAIN")
            for agent, insights in by_agent.items():
                sections.append(f"\n### {agent}")
                for i in insights[:5]:
                    sections.append(f"- {i['content']}")
        
        # Cross-domain connections
        connections = self.db.get_cross_domain_connections()
        if connections:
            sections.append("\n## CROSS-DOMAIN CONNECTIONS")
            for c in connections[:5]:
                sections.append(f"- {' ↔ '.join(c['agents'])}: "
                              f"Shared themes: {', '.join(c['overlapping_tags'])}")
        
        return "\n".join(sections)


# ─── INSIGHT EXTRACTOR ───────────────────────────────────────────────────────

class InsightExtractor:
    """
    Extracts structured insights from agent responses.
    Called after every agent interaction.
    """
    
    @staticmethod
    def extract_from_response(agent: str, response: str, db: LearningDB):
        """
        Parse agent response for structured data markers.
        
        Agents are instructed to include markers in their responses:
        [INSIGHT: category | content | confidence | tags]
        [DECISION: decision | rationale | expected_outcome]
        [METRIC: name | value | context]
        """
        import re
        
        # Extract insights
        insight_pattern = r'\[INSIGHT:\s*([^|]+)\|([^|]+)\|([^|]+)\|([^\]]+)\]'
        for match in re.finditer(insight_pattern, response):
            category = match.group(1).strip()
            content = match.group(2).strip()
            confidence = match.group(3).strip()
            tags = match.group(4).strip()
            db.log_insight(agent, category, content, confidence=confidence, tags=tags)
        
        # Extract decisions
        decision_pattern = r'\[DECISION:\s*([^|]+)\|([^|]+)\|([^\]]+)\]'
        for match in re.finditer(decision_pattern, response):
            decision = match.group(1).strip()
            rationale = match.group(2).strip()
            expected = match.group(3).strip()
            db.log_decision(agent, decision, rationale, expected)
        
        # Extract metrics
        metric_pattern = r'\[METRIC:\s*([^|]+)\|([^|]+)\|?([^\]]*)\]'
        for match in re.finditer(metric_pattern, response):
            name = match.group(1).strip()
            try:
                value = float(match.group(2).strip())
                context = match.group(3).strip() if match.group(3) else None
                db.log_metric(agent, name, value, context=context)
            except ValueError:
                pass
    
    @staticmethod
    def clean_response(response: str) -> str:
        """Remove extraction markers from the response before sending to Telegram."""
        import re
        response = re.sub(r'\[INSIGHT:[^\]]+\]', '', response)
        response = re.sub(r'\[DECISION:[^\]]+\]', '', response)
        response = re.sub(r'\[METRIC:[^\]]+\]', '', response)
        response = re.sub(r'\[STATE UPDATE:[^\]]+\]', '', response)
        return response.strip()


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    
    db = LearningDB()
    gen = ContextGenerator(db)
    
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        
        if cmd == "init":
            print("Database initialised at:", DB_PATH)
            print("Tables created.")
        
        elif cmd == "generate":
            if len(sys.argv) > 2:
                agent = sys.argv[2]
                context = gen.generate_context(agent)
                print(context)
            else:
                gen.generate_all()
        
        elif cmd == "oracle":
            context = gen.generate_oracle_context()
            print(context)
        
        elif cmd == "stats":
            for table in ['insights', 'decisions', 'metrics', 'patterns', 'interactions']:
                count = db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                print(f"{table:15s}: {count:>6d} rows")
        
        elif cmd == "test":
            # Add some test data
            db.log_insight("dbh-marketing", "performance", 
                          "GLM emails with social proof subject lines get 48%+ open rates",
                          evidence="Last 3 campaigns", confidence="proven",
                          tags="email,social-proof,glm")
            db.log_metric("dbh-marketing", "email_open_rate", 48.5)
            db.log_decision("dbh-marketing", 
                          "Use social proof in all GLM campaign subjects",
                          rationale="Proven 48%+ open rate pattern",
                          expected_outcome="Sustained 45%+ open rates")
            print("Test data added. Run 'generate dbh-marketing' to see context.")
        
        else:
            print(f"Unknown command: {cmd}")
    else:
        print("Learning Database CLI")
        print("Commands:")
        print("  python learning_db.py init              — Initialise database")
        print("  python learning_db.py generate [agent]  — Generate CONTEXT.md (all or specific)")
        print("  python learning_db.py oracle            — Generate Oracle cross-domain context")
        print("  python learning_db.py stats             — Show row counts")
        print("  python learning_db.py test              — Add test data")
    
    db.close()
