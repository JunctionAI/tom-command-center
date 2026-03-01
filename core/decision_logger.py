#!/usr/bin/env python3
"""
Decision Logger -- Structured Decision Memory for Agents

Solves the "agent forgets what it decided at step 3 when it gets to step 10" problem.

The learning_db stores decisions as flat text with no lineage tracking.
This module adds:
  - Structured decision records with reasoning, alternatives, confidence
  - Decision chains that link related decisions over time
  - Contradiction detection (flags when a new decision reverses a recent one)
  - Context injection so agents see their own recent decisions in every prompt
  - Verification loop so outcomes get tracked against predictions

Markers in agent responses (enhanced format):
  [DECISION: type|title|reasoning|confidence]

  type:       strategy | tactical | operational | creative | financial
  title:      Short description of what was decided
  reasoning:  Why this was the right call
  confidence: 0.0 to 1.0

Examples:
  [DECISION: tactical|Pause GLM Meta campaign|ROAS dropped below 2x for 3 days|0.85]
  [DECISION: strategy|Shift 30% of Meta budget to email|Email ROAS consistently 5x+ vs Meta 3x|0.7]
  [DECISION: financial|Cap Meta daily spend at $150|Overspend risk with declining ROAS|0.9]

Data lives at data/decisions.db (separate from learning.db to avoid schema conflicts).
"""

import sqlite3
import json
import os
import re
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Resolve paths relative to this file's location (works in Docker + local)
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "decisions.db"

# ---- Constants ----

DECISION_TYPES = ("strategy", "tactical", "operational", "creative", "financial")

# Domain keywords used to auto-detect domain from decision title/reasoning.
# Maps keyword -> domain label for grouping related decisions.
DOMAIN_KEYWORDS = {
    "meta":         "advertising",
    "google ads":   "advertising",
    "facebook":     "advertising",
    "ad ":          "advertising",
    "ads ":         "advertising",
    "roas":         "advertising",
    "campaign":     "advertising",
    "email":        "email_marketing",
    "klaviyo":      "email_marketing",
    "flow":         "email_marketing",
    "subject line": "email_marketing",
    "shopify":      "ecommerce",
    "product":      "product",
    "inventory":    "product",
    "stock":        "product",
    "price":        "pricing",
    "discount":     "pricing",
    "budget":       "finance",
    "spend":        "finance",
    "cost":         "finance",
    "revenue":      "finance",
    "margin":       "finance",
    "brand":        "brand",
    "design":       "brand",
    "creative":     "brand",
    "content":      "content",
    "social":       "content",
    "tiktok":       "content",
    "seo":          "content",
    "tariff":       "geopolitics",
    "regulation":   "geopolitics",
    "competitor":   "competitive",
    "market":       "competitive",
}

# Agents in the system (matches event_bus.py)
AGENT_DISPLAY = {
    "global-events":     "Atlas",
    "dbh-marketing":     "Meridian",
    "pure-pets":         "Scout",
    "new-business":      "Venture",
    "health-fitness":    "Titan",
    "social":            "Compass",
    "creative-projects": "Lens",
    "daily-briefing":    "Oracle",
    "command-center":    "Nexus",
    "strategic-advisor": "PREP",
}


class DecisionLogger:
    """SQLite-backed structured decision memory."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    # ──────────────────────────────────────────────────────────────────
    #  Schema
    # ──────────────────────────────────────────────────────────────────

    def _init_schema(self):
        """Create tables if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent TEXT NOT NULL,
                domain TEXT NOT NULL,
                decision_type TEXT NOT NULL,
                title TEXT NOT NULL,
                reasoning TEXT,
                alternatives_considered TEXT,
                confidence REAL DEFAULT 0.5,
                context_used TEXT DEFAULT '[]',
                outcome TEXT,
                outcome_notes TEXT,
                status TEXT DEFAULT 'active',
                verified_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS decision_chains (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chain_name TEXT NOT NULL,
                description TEXT,
                domain TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS chain_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chain_id INTEGER NOT NULL,
                decision_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                dependency_type TEXT NOT NULL DEFAULT 'builds_on',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (chain_id) REFERENCES decision_chains(id),
                FOREIGN KEY (decision_id) REFERENCES decisions(id),
                UNIQUE(chain_id, decision_id)
            );

            CREATE INDEX IF NOT EXISTS idx_decisions_agent ON decisions(agent);
            CREATE INDEX IF NOT EXISTS idx_decisions_domain ON decisions(domain);
            CREATE INDEX IF NOT EXISTS idx_decisions_type ON decisions(decision_type);
            CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status);
            CREATE INDEX IF NOT EXISTS idx_decisions_created ON decisions(created_at);
            CREATE INDEX IF NOT EXISTS idx_chain_links_chain ON chain_links(chain_id);
            CREATE INDEX IF NOT EXISTS idx_chain_links_decision ON chain_links(decision_id);
            CREATE INDEX IF NOT EXISTS idx_chains_domain ON decision_chains(domain);
        """)
        self.conn.commit()

    # ──────────────────────────────────────────────────────────────────
    #  Log Decisions
    # ──────────────────────────────────────────────────────────────────

    def log_decision(self, agent: str, domain: str, decision_type: str,
                     title: str, reasoning: str = None,
                     alternatives_considered: str = None,
                     confidence: float = 0.5,
                     context_used: list = None) -> int:
        """
        Log a structured decision. Returns the decision ID.

        Args:
            agent:         Agent folder name (e.g. "dbh-marketing").
            domain:        Topic domain (e.g. "advertising", "email_marketing").
            decision_type: One of DECISION_TYPES.
            title:         Short description of the decision.
            reasoning:     Why this was the right call.
            alternatives_considered: What else was considered and rejected.
            confidence:    0.0 to 1.0 -- how confident the agent is.
            context_used:  List of context sources that fed the decision.

        Returns:
            The decision ID.
        """
        decision_type = decision_type.lower()
        if decision_type not in DECISION_TYPES:
            logger.warning(
                f"Unknown decision type '{decision_type}', defaulting to 'operational'"
            )
            decision_type = "operational"

        confidence = max(0.0, min(1.0, confidence))
        context_json = json.dumps(context_used or [])

        cursor = self.conn.execute(
            """INSERT INTO decisions
               (agent, domain, decision_type, title, reasoning,
                alternatives_considered, confidence, context_used)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (agent, domain, decision_type, title, reasoning,
             alternatives_considered, confidence, context_json)
        )
        self.conn.commit()
        decision_id = cursor.lastrowid

        logger.info(
            f"Decision #{decision_id} logged: [{decision_type}] {title} "
            f"by {AGENT_DISPLAY.get(agent, agent)} (confidence={confidence:.0%})"
        )

        # Auto-chain: look for related decisions in the same domain
        self._auto_chain(decision_id, agent, domain, title)

        return decision_id

    # ──────────────────────────────────────────────────────────────────
    #  Decision Chains
    # ──────────────────────────────────────────────────────────────────

    def create_chain(self, chain_name: str, description: str = None,
                     domain: str = None) -> int:
        """Create a new decision chain. Returns the chain ID."""
        cursor = self.conn.execute(
            """INSERT INTO decision_chains (chain_name, description, domain)
               VALUES (?, ?, ?)""",
            (chain_name, description, domain)
        )
        self.conn.commit()
        return cursor.lastrowid

    def add_to_chain(self, chain_id: int, decision_id: int,
                     dependency_type: str = "builds_on") -> bool:
        """
        Add a decision to an existing chain.

        dependency_type: builds_on | contradicts | supersedes
        """
        valid_deps = ("builds_on", "contradicts", "supersedes")
        if dependency_type not in valid_deps:
            dependency_type = "builds_on"

        # Determine position (next in sequence)
        row = self.conn.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 AS next_pos FROM chain_links WHERE chain_id = ?",
            (chain_id,)
        ).fetchone()
        position = row["next_pos"] if row else 1

        try:
            self.conn.execute(
                """INSERT OR IGNORE INTO chain_links
                   (chain_id, decision_id, position, dependency_type)
                   VALUES (?, ?, ?, ?)""",
                (chain_id, decision_id, position, dependency_type)
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            logger.warning(
                f"Decision #{decision_id} already in chain #{chain_id}"
            )
            return False

    def get_decision_chain(self, domain: str) -> list:
        """
        Get the full reasoning history for a domain.

        Returns decisions in chronological order with chain context,
        showing how thinking evolved over time.
        """
        # Find all chains for this domain
        chains = self.conn.execute(
            """SELECT dc.id, dc.chain_name, dc.description
               FROM decision_chains dc
               WHERE dc.domain = ?
               ORDER BY dc.created_at ASC""",
            (domain,)
        ).fetchall()

        results = []
        for chain in chains:
            chain_data = dict(chain)

            # Get all decisions in this chain, ordered by position
            links = self.conn.execute(
                """SELECT d.*, cl.position, cl.dependency_type
                   FROM chain_links cl
                   JOIN decisions d ON d.id = cl.decision_id
                   WHERE cl.chain_id = ?
                   ORDER BY cl.position ASC""",
                (chain["id"],)
            ).fetchall()

            chain_data["decisions"] = []
            for link in links:
                decision = dict(link)
                decision["context_used"] = json.loads(decision["context_used"])
                chain_data["decisions"].append(decision)

            results.append(chain_data)

        # Also include unchained decisions for this domain
        unchained = self.conn.execute(
            """SELECT d.* FROM decisions d
               WHERE d.domain = ?
                 AND d.id NOT IN (
                     SELECT decision_id FROM chain_links
                 )
               ORDER BY d.created_at ASC""",
            (domain,)
        ).fetchall()

        if unchained:
            unchained_list = []
            for row in unchained:
                decision = dict(row)
                decision["context_used"] = json.loads(decision["context_used"])
                unchained_list.append(decision)
            results.append({
                "id": None,
                "chain_name": f"Standalone decisions ({domain})",
                "description": "Decisions not yet linked to a chain",
                "decisions": unchained_list,
            })

        return results

    def get_recent_decisions(self, agent: str = None, days: int = 7,
                             limit: int = 20) -> list:
        """
        Get recent decisions, optionally filtered by agent.

        Returns decisions ordered by most recent first.
        """
        since = (datetime.now() - timedelta(days=days)).isoformat()

        if agent:
            rows = self.conn.execute(
                """SELECT * FROM decisions
                   WHERE agent = ? AND created_at > ?
                   ORDER BY created_at DESC LIMIT ?""",
                (agent, since, limit)
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT * FROM decisions
                   WHERE created_at > ?
                   ORDER BY created_at DESC LIMIT ?""",
                (since, limit)
            ).fetchall()

        results = []
        for row in rows:
            decision = dict(row)
            decision["context_used"] = json.loads(decision["context_used"])
            results.append(decision)
        return results

    def check_contradiction(self, agent: str, domain: str,
                            new_title: str, new_reasoning: str = None,
                            lookback_days: int = 14) -> list:
        """
        Check if a new decision contradicts recent decisions in the same domain.

        Uses keyword overlap heuristics -- not perfect, but catches obvious
        reversals like "increase budget" vs "decrease budget" or
        "pause campaign" vs "resume campaign".

        Returns list of potentially contradicting decisions with explanation.
        """
        since = (datetime.now() - timedelta(days=lookback_days)).isoformat()

        recent = self.conn.execute(
            """SELECT * FROM decisions
               WHERE domain = ? AND status = 'active' AND created_at > ?
               ORDER BY created_at DESC LIMIT 20""",
            (domain, since)
        ).fetchall()

        if not recent:
            return []

        # Contradiction signal words -- pairs of opposites
        opposite_pairs = [
            ("increase", "decrease"),
            ("raise", "lower"),
            ("start", "stop"),
            ("pause", "resume"),
            ("enable", "disable"),
            ("expand", "reduce"),
            ("more", "less"),
            ("add", "remove"),
            ("launch", "cancel"),
            ("scale up", "scale down"),
            ("boost", "cut"),
        ]

        new_text = f"{new_title} {new_reasoning or ''}".lower()
        contradictions = []

        for row in recent:
            existing = dict(row)
            existing_text = f"{existing['title']} {existing['reasoning'] or ''}".lower()

            # Check each pair -- if new text has one word and existing has its opposite
            for word_a, word_b in opposite_pairs:
                if (word_a in new_text and word_b in existing_text) or \
                   (word_b in new_text and word_a in existing_text):
                    # Additional check: they should share at least one domain keyword
                    # to avoid false positives across unrelated topics
                    new_words = set(new_text.split())
                    existing_words = set(existing_text.split())
                    shared = new_words & existing_words
                    # Filter out very common words
                    shared -= {"the", "a", "an", "to", "for", "is", "in",
                               "of", "and", "or", "on", "at", "by", "with"}
                    if len(shared) >= 2:
                        contradictions.append({
                            "existing_decision": existing,
                            "signal": f"'{word_a}' vs '{word_b}'",
                            "shared_terms": list(shared)[:5],
                        })
                        break  # One contradiction signal per decision is enough

        return contradictions

    # ──────────────────────────────────────────────────────────────────
    #  Decision Verification
    # ──────────────────────────────────────────────────────────────────

    def verify_decision(self, decision_id: int, outcome: str,
                        notes: str = None) -> bool:
        """
        Mark a past decision with its actual outcome.

        outcome: 'positive', 'negative', 'neutral', 'mixed'
        """
        valid_outcomes = ("positive", "negative", "neutral", "mixed")
        if outcome.lower() not in valid_outcomes:
            logger.warning(f"Unknown outcome '{outcome}', using 'neutral'")
            outcome = "neutral"

        updated = self.conn.execute(
            """UPDATE decisions
               SET outcome = ?, outcome_notes = ?, status = 'verified',
                   verified_at = ?
               WHERE id = ?""",
            (outcome, notes, datetime.now().isoformat(), decision_id)
        ).rowcount

        self.conn.commit()

        if updated:
            logger.info(f"Decision #{decision_id} verified: {outcome}")

            # If negative, check chain and flag the chain as needing review
            if outcome == "negative":
                self._flag_chain_for_review(decision_id)

            return True
        else:
            logger.warning(f"Decision #{decision_id} not found for verification")
            return False

    def get_unverified_decisions(self, days: int = 14) -> list:
        """
        Get decisions that are old enough to verify but haven't been.

        These should be injected into weekly review prompts so agents
        check whether their past decisions actually worked.
        """
        # Decisions that are at least 3 days old (enough time for results)
        # but less than `days` days old (don't look too far back)
        min_age = (datetime.now() - timedelta(days=days)).isoformat()
        max_age = (datetime.now() - timedelta(days=3)).isoformat()

        rows = self.conn.execute(
            """SELECT * FROM decisions
               WHERE status = 'active'
                 AND created_at > ?
                 AND created_at < ?
               ORDER BY created_at ASC""",
            (min_age, max_age)
        ).fetchall()

        results = []
        for row in rows:
            decision = dict(row)
            decision["context_used"] = json.loads(decision["context_used"])
            # Calculate age for display
            created = datetime.fromisoformat(decision["created_at"])
            age_days = (datetime.now() - created).days
            decision["age_days"] = age_days
            results.append(decision)

        return results

    # ──────────────────────────────────────────────────────────────────
    #  Context Injection (for agent prompts)
    # ──────────────────────────────────────────────────────────────────

    def format_decisions_for_agent(self, agent_name: str,
                                   limit: int = 10) -> str:
        """
        Format recent decisions for injection into an agent's prompt.

        This is the key integration point -- called by the orchestrator
        when building the agent brain, so the agent sees what it
        (and related agents) recently decided.
        """
        decisions = self.get_recent_decisions(agent=agent_name, days=7,
                                              limit=limit)

        if not decisions:
            return ""

        agent_display = AGENT_DISPLAY.get(agent_name, agent_name)

        lines = []
        lines.append("=== RECENT DECISIONS (Your Decision Memory) ===")
        lines.append(
            f"These are decisions you ({agent_display}) made recently. "
            f"Build on them, don't repeat or contradict them without "
            f"explicit reasoning."
        )
        lines.append("")

        for d in decisions:
            age = self._format_age(d["created_at"])
            conf_bar = self._confidence_bar(d["confidence"])

            lines.append(
                f"-- Decision #{d['id']} [{d['decision_type'].upper()}] "
                f"({age}) --"
            )
            lines.append(f"  Title:      {d['title']}")
            if d.get("reasoning"):
                lines.append(f"  Reasoning:  {d['reasoning']}")
            lines.append(f"  Confidence: {conf_bar} ({d['confidence']:.0%})")
            lines.append(f"  Domain:     {d['domain']}")
            if d.get("outcome"):
                lines.append(
                    f"  Outcome:    {d['outcome']}"
                    f"{' -- ' + d['outcome_notes'] if d.get('outcome_notes') else ''}"
                )
            lines.append("")

        # Also inject unverified decisions that need checking
        unverified = self.get_unverified_decisions(days=14)
        agent_unverified = [u for u in unverified if u["agent"] == agent_name]

        if agent_unverified:
            lines.append("--- DECISIONS NEEDING VERIFICATION ---")
            lines.append(
                "These decisions are old enough to check. Did they work? "
                "Use [VERIFY: decision_id|outcome|notes] to record results."
            )
            lines.append(
                "  outcome: positive | negative | neutral | mixed"
            )
            lines.append("")
            for u in agent_unverified[:5]:
                lines.append(
                    f"  #{u['id']} ({u['age_days']}d ago): {u['title']}"
                )
            lines.append("")

        return "\n".join(lines)

    def format_decision_chain_for_brief(self, domain: str) -> str:
        """
        Format a full decision chain for PREP/Oracle briefings.

        Shows how thinking evolved over time in a specific domain,
        so PREP can see the complete reasoning trail.
        """
        chains = self.get_decision_chain(domain)

        if not chains:
            return ""

        lines = []
        lines.append(f"=== DECISION CHAIN: {domain.upper()} ===")
        lines.append(
            f"Full reasoning history for the '{domain}' domain, "
            f"showing how decisions built on each other."
        )
        lines.append("")

        for chain in chains:
            chain_label = chain.get("chain_name", "Unnamed chain")
            lines.append(f"--- Chain: {chain_label} ---")
            if chain.get("description"):
                lines.append(f"  {chain['description']}")
            lines.append("")

            for d in chain.get("decisions", []):
                dep_type = d.get("dependency_type", "")
                dep_marker = ""
                if dep_type == "contradicts":
                    dep_marker = " [REVERSAL]"
                elif dep_type == "supersedes":
                    dep_marker = " [REPLACED PREVIOUS]"

                agent_display = AGENT_DISPLAY.get(d["agent"], d["agent"])
                lines.append(
                    f"  {d.get('position', '?')}. [{d['decision_type'].upper()}]"
                    f"{dep_marker} {d['title']}"
                )
                lines.append(f"     By: {agent_display} | {d['created_at'][:10]}")
                if d.get("reasoning"):
                    lines.append(f"     Why: {d['reasoning']}")
                if d.get("outcome"):
                    lines.append(
                        f"     Result: {d['outcome']}"
                        f"{' -- ' + d['outcome_notes'] if d.get('outcome_notes') else ''}"
                    )
                lines.append("")

        return "\n".join(lines)

    def format_all_domains_summary(self, days: int = 14) -> str:
        """
        Format a cross-domain decision summary for Oracle/PREP.

        Groups recent decisions by domain and shows the overall
        direction of decision-making.
        """
        since = (datetime.now() - timedelta(days=days)).isoformat()

        rows = self.conn.execute(
            """SELECT * FROM decisions
               WHERE created_at > ?
               ORDER BY domain, created_at DESC""",
            (since,)
        ).fetchall()

        if not rows:
            return ""

        # Group by domain
        by_domain = {}
        for row in rows:
            d = dict(row)
            d["context_used"] = json.loads(d["context_used"])
            by_domain.setdefault(d["domain"], []).append(d)

        lines = []
        lines.append(f"=== DECISION LANDSCAPE (Last {days} days) ===")
        lines.append("")

        for domain, decisions in sorted(by_domain.items()):
            verified = [d for d in decisions if d["status"] == "verified"]
            positive = [d for d in verified if d.get("outcome") == "positive"]
            negative = [d for d in verified if d.get("outcome") == "negative"]

            lines.append(
                f"--- {domain.upper()} ({len(decisions)} decisions) ---"
            )
            if verified:
                lines.append(
                    f"  Verified: {len(verified)} "
                    f"({len(positive)} positive, {len(negative)} negative)"
                )

            for d in decisions[:3]:
                agent_display = AGENT_DISPLAY.get(d["agent"], d["agent"])
                status_marker = ""
                if d.get("outcome") == "positive":
                    status_marker = " [WORKED]"
                elif d.get("outcome") == "negative":
                    status_marker = " [FAILED]"
                lines.append(
                    f"  - {d['title']}{status_marker} ({agent_display})"
                )

            if len(decisions) > 3:
                lines.append(f"  ... and {len(decisions) - 3} more")
            lines.append("")

        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────
    #  Parse from Agent Responses
    # ──────────────────────────────────────────────────────────────────

    def extract_decisions_from_response(self, agent_name: str,
                                        response: str) -> list:
        """
        Parse enhanced [DECISION: type|title|reasoning|confidence] markers
        from an agent response, create structured records, and auto-chain.

        Also handles the legacy 3-field format from learning_db:
          [DECISION: decision|rationale|expected_outcome]

        Returns list of created decision IDs.
        """
        decision_ids = []

        # Enhanced 4-field format: [DECISION: type|title|reasoning|confidence]
        enhanced_pattern = (
            r'\[DECISION:\s*'
            r'(strategy|tactical|operational|creative|financial)'
            r'\|([^|]+)\|([^|]+)\|([^\]]+)\]'
        )

        for match in re.finditer(enhanced_pattern, response, re.IGNORECASE):
            decision_type = match.group(1).strip().lower()
            title = match.group(2).strip()
            reasoning = match.group(3).strip()
            confidence_str = match.group(4).strip()

            try:
                confidence = float(confidence_str)
            except ValueError:
                confidence = 0.5

            domain = self._detect_domain(title, reasoning)

            decision_id = self.log_decision(
                agent=agent_name,
                domain=domain,
                decision_type=decision_type,
                title=title,
                reasoning=reasoning,
                confidence=confidence,
                context_used=["agent_response"],
            )
            decision_ids.append(decision_id)

        # Legacy 3-field format: [DECISION: decision|rationale|expected_outcome]
        # Only match lines NOT already matched by the enhanced pattern.
        # Enhanced pattern requires type to be one of the known types, so
        # anything else is legacy format.
        legacy_pattern = r'\[DECISION:\s*([^|]+)\|([^|]+)\|([^\]]+)\]'
        enhanced_starts = {m.start() for m in re.finditer(enhanced_pattern,
                                                          response,
                                                          re.IGNORECASE)}

        for match in re.finditer(legacy_pattern, response):
            if match.start() in enhanced_starts:
                continue  # Already handled by enhanced pattern

            title = match.group(1).strip()
            reasoning = match.group(2).strip()
            expected = match.group(3).strip()

            domain = self._detect_domain(title, reasoning)
            decision_type = self._infer_type(title, reasoning)

            decision_id = self.log_decision(
                agent=agent_name,
                domain=domain,
                decision_type=decision_type,
                title=title,
                reasoning=f"{reasoning} (Expected: {expected})",
                confidence=0.5,
                context_used=["agent_response_legacy"],
            )
            decision_ids.append(decision_id)

        # Also extract verification markers:
        #   [VERIFY: decision_id|outcome|notes]
        verify_pattern = r'\[VERIFY:\s*(\d+)\|([^|]+)\|([^\]]*)\]'
        for match in re.finditer(verify_pattern, response):
            dec_id = int(match.group(1))
            outcome = match.group(2).strip().lower()
            notes = match.group(3).strip() if match.group(3) else None
            self.verify_decision(dec_id, outcome, notes)

        return decision_ids

    @staticmethod
    def clean_decision_markers(response: str) -> str:
        """Remove decision markers from response before sending to Telegram."""
        # The enhanced format (redundant with learning_db cleanup for safety)
        response = re.sub(
            r'\[DECISION:\s*(?:strategy|tactical|operational|creative|financial)'
            r'\|[^\]]+\]',
            '', response, flags=re.IGNORECASE
        )
        # Verification markers
        response = re.sub(r'\[VERIFY:\s*[^\]]+\]', '', response)
        return response

    # ──────────────────────────────────────────────────────────────────
    #  Stats & Diagnostics
    # ──────────────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get decision logger statistics."""
        stats = {}
        stats["total_decisions"] = self.conn.execute(
            "SELECT COUNT(*) FROM decisions"
        ).fetchone()[0]
        stats["active_decisions"] = self.conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE status = 'active'"
        ).fetchone()[0]
        stats["verified_decisions"] = self.conn.execute(
            "SELECT COUNT(*) FROM decisions WHERE status = 'verified'"
        ).fetchone()[0]
        stats["total_chains"] = self.conn.execute(
            "SELECT COUNT(*) FROM decision_chains"
        ).fetchone()[0]
        stats["total_links"] = self.conn.execute(
            "SELECT COUNT(*) FROM chain_links"
        ).fetchone()[0]

        # By type
        for dt in DECISION_TYPES:
            stats[f"type_{dt}"] = self.conn.execute(
                "SELECT COUNT(*) FROM decisions WHERE decision_type = ?",
                (dt,)
            ).fetchone()[0]

        # By outcome (verified only)
        for outcome in ("positive", "negative", "neutral", "mixed"):
            stats[f"outcome_{outcome}"] = self.conn.execute(
                "SELECT COUNT(*) FROM decisions WHERE outcome = ?",
                (outcome,)
            ).fetchone()[0]

        # By agent (last 14 days)
        cutoff = (datetime.now() - timedelta(days=14)).isoformat()
        rows = self.conn.execute(
            """SELECT agent, COUNT(*) as cnt FROM decisions
               WHERE created_at > ? GROUP BY agent ORDER BY cnt DESC""",
            (cutoff,)
        ).fetchall()
        stats["recent_by_agent"] = {
            AGENT_DISPLAY.get(r["agent"], r["agent"]): r["cnt"]
            for r in rows
        }

        # By domain (last 14 days)
        rows = self.conn.execute(
            """SELECT domain, COUNT(*) as cnt FROM decisions
               WHERE created_at > ? GROUP BY domain ORDER BY cnt DESC""",
            (cutoff,)
        ).fetchall()
        stats["recent_by_domain"] = {r["domain"]: r["cnt"] for r in rows}

        return stats

    # ──────────────────────────────────────────────────────────────────
    #  Internal Helpers
    # ──────────────────────────────────────────────────────────────────

    def _detect_domain(self, title: str, reasoning: str = None) -> str:
        """
        Auto-detect the domain from the decision title and reasoning
        using keyword matching.
        """
        text = f"{title} {reasoning or ''}".lower()

        # Score each domain by keyword matches
        domain_scores = {}
        for keyword, domain in DOMAIN_KEYWORDS.items():
            if keyword in text:
                domain_scores[domain] = domain_scores.get(domain, 0) + 1

        if domain_scores:
            # Return the domain with the most keyword hits
            return max(domain_scores, key=domain_scores.get)

        return "general"

    def _infer_type(self, title: str, reasoning: str = None) -> str:
        """
        Infer the decision type from content when not explicitly specified
        (legacy format).
        """
        text = f"{title} {reasoning or ''}".lower()

        if any(w in text for w in ("budget", "spend", "cost", "price",
                                    "revenue", "margin", "invest")):
            return "financial"
        if any(w in text for w in ("brand", "design", "creative", "logo",
                                    "visual", "content")):
            return "creative"
        if any(w in text for w in ("strategy", "long-term", "direction",
                                    "pivot", "vision", "roadmap")):
            return "strategy"
        if any(w in text for w in ("campaign", "launch", "test", "a/b",
                                    "experiment", "target")):
            return "tactical"

        return "operational"

    def _auto_chain(self, decision_id: int, agent: str, domain: str,
                    title: str):
        """
        Automatically link a new decision to an existing chain
        if there are recent related decisions in the same domain.
        """
        # Look for existing chains in this domain
        existing_chain = self.conn.execute(
            """SELECT dc.id, dc.chain_name
               FROM decision_chains dc
               WHERE dc.domain = ?
               ORDER BY dc.created_at DESC LIMIT 1""",
            (domain,)
        ).fetchone()

        # Look for recent decisions in the same domain (last 30 days)
        recent = self.conn.execute(
            """SELECT id, title FROM decisions
               WHERE domain = ? AND id != ?
                 AND created_at > ?
               ORDER BY created_at DESC LIMIT 5""",
            (domain, decision_id,
             (datetime.now() - timedelta(days=30)).isoformat())
        ).fetchall()

        if not recent:
            return  # No related decisions, nothing to chain

        if existing_chain:
            chain_id = existing_chain["id"]
        else:
            # Create a new chain for this domain
            chain_id = self.create_chain(
                chain_name=f"{domain} decisions",
                description=(
                    f"Auto-created chain tracking decisions in the "
                    f"{domain} domain"
                ),
                domain=domain,
            )
            # Add the most recent existing decision to the chain too
            self.add_to_chain(chain_id, recent[0]["id"], "builds_on")

        # Determine dependency type
        contradictions = self.check_contradiction(
            agent, domain, title
        )
        if contradictions:
            dep_type = "contradicts"
            logger.warning(
                f"Decision #{decision_id} CONTRADICTS recent decision(s) "
                f"in domain '{domain}': "
                f"{[c['signal'] for c in contradictions]}"
            )
        else:
            dep_type = "builds_on"

        self.add_to_chain(chain_id, decision_id, dep_type)

    def _flag_chain_for_review(self, decision_id: int):
        """
        When a decision has a negative outcome, flag the chain
        so PREP/Oracle know to re-examine the reasoning trail.
        """
        # Find chains containing this decision
        chains = self.conn.execute(
            """SELECT chain_id FROM chain_links
               WHERE decision_id = ?""",
            (decision_id,)
        ).fetchall()

        for chain_row in chains:
            chain_id = chain_row["chain_id"]
            # Update the chain description to flag review needed
            current = self.conn.execute(
                "SELECT description FROM decision_chains WHERE id = ?",
                (chain_id,)
            ).fetchone()
            if current:
                desc = current["description"] or ""
                if "[REVIEW NEEDED]" not in desc:
                    desc = f"[REVIEW NEEDED] {desc}"
                    self.conn.execute(
                        "UPDATE decision_chains SET description = ? WHERE id = ?",
                        (desc, chain_id)
                    )
                    self.conn.commit()
                    logger.info(
                        f"Chain #{chain_id} flagged for review after "
                        f"negative outcome on decision #{decision_id}"
                    )

    @staticmethod
    def _format_age(created_at_str: str) -> str:
        """Format decision age as human-readable string."""
        try:
            created = datetime.fromisoformat(created_at_str)
            delta = datetime.now() - created
            total_seconds = int(delta.total_seconds())
            if total_seconds < 0:
                return "just now"
            if total_seconds < 3600:
                return f"{total_seconds // 60}m ago"
            elif total_seconds < 86400:
                return f"{total_seconds // 3600}h ago"
            else:
                days = total_seconds // 86400
                return f"{days}d ago"
        except (ValueError, TypeError):
            return "unknown"

    @staticmethod
    def _confidence_bar(confidence: float) -> str:
        """Render confidence as a visual bar."""
        filled = int(confidence * 10)
        return "[" + "#" * filled + "-" * (10 - filled) + "]"

    def close(self):
        """Close the database connection."""
        self.conn.close()


# ──────────────────────────────────────────────────────────────────────
#  CLI
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    dl = DecisionLogger()

    def print_usage():
        print("Decision Logger CLI")
        print("=" * 60)
        print("Commands:")
        print("  python decision_logger.py init")
        print("      -- Initialise database")
        print("  python decision_logger.py log <agent> <type> <title> [reasoning] [confidence]")
        print("      -- Log a decision manually")
        print("  python decision_logger.py recent [agent] [days]")
        print("      -- Show recent decisions")
        print("  python decision_logger.py chain <domain>")
        print("      -- Show decision chain for a domain")
        print("  python decision_logger.py inject <agent>")
        print("      -- Show context injection text for an agent")
        print("  python decision_logger.py brief <domain>")
        print("      -- Show full chain brief for PREP")
        print("  python decision_logger.py landscape [days]")
        print("      -- Show cross-domain decision summary")
        print("  python decision_logger.py unverified [days]")
        print("      -- Show decisions needing verification")
        print("  python decision_logger.py verify <id> <outcome> [notes]")
        print("      -- Verify a decision outcome")
        print("  python decision_logger.py stats")
        print("      -- Show statistics")
        print("  python decision_logger.py test")
        print("      -- Add test data")
        print()
        print(f"Decision types: {', '.join(DECISION_TYPES)}")
        print(f"Agents: {', '.join(AGENT_DISPLAY.keys())}")

    if len(sys.argv) < 2:
        print_usage()
        dl.close()
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "init":
        print(f"Database initialised at: {DB_PATH}")
        stats = dl.get_stats()
        print(f"Decisions: {stats['total_decisions']}")
        print(f"Chains: {stats['total_chains']}")

    elif cmd == "log":
        if len(sys.argv) < 5:
            print("Usage: python decision_logger.py log <agent> <type> <title> [reasoning] [confidence]")
            print(f"Types: {', '.join(DECISION_TYPES)}")
            dl.close()
            sys.exit(1)
        agent = sys.argv[2]
        dtype = sys.argv[3]
        title = sys.argv[4]
        reasoning = sys.argv[5] if len(sys.argv) > 5 else None
        confidence = float(sys.argv[6]) if len(sys.argv) > 6 else 0.5
        domain = dl._detect_domain(title, reasoning)
        did = dl.log_decision(agent, domain, dtype, title, reasoning,
                              confidence=confidence)
        print(f"Decision #{did} logged: [{dtype}] {title} (domain={domain})")

    elif cmd == "recent":
        agent = sys.argv[2] if len(sys.argv) > 2 else None
        days = int(sys.argv[3]) if len(sys.argv) > 3 else 7
        decisions = dl.get_recent_decisions(agent=agent, days=days)
        if not decisions:
            label = f"for {AGENT_DISPLAY.get(agent, agent)}" if agent else ""
            print(f"No decisions {label} in the last {days} days")
        else:
            label = (
                f"for {AGENT_DISPLAY.get(agent, agent)}" if agent
                else "(all agents)"
            )
            print(f"Recent decisions {label} (last {days} days):")
            print("-" * 60)
            for d in decisions:
                agent_display = AGENT_DISPLAY.get(d["agent"], d["agent"])
                print(
                    f"  #{d['id']:>4d} [{d['decision_type']:>11s}] "
                    f"{d['title']}"
                )
                print(
                    f"         {agent_display} | {d['domain']} | "
                    f"confidence={d['confidence']:.0%} | {d['status']}"
                )
                if d.get("reasoning"):
                    reason_preview = (d["reasoning"][:80] + "..."
                                      if len(d["reasoning"]) > 80
                                      else d["reasoning"])
                    print(f"         Why: {reason_preview}")
                print()

    elif cmd == "chain":
        if len(sys.argv) < 3:
            print("Usage: python decision_logger.py chain <domain>")
            dl.close()
            sys.exit(1)
        domain = sys.argv[2]
        text = dl.format_decision_chain_for_brief(domain)
        if text:
            print(text)
        else:
            print(f"No decision chain found for domain '{domain}'")

    elif cmd == "inject":
        if len(sys.argv) < 3:
            print("Usage: python decision_logger.py inject <agent>")
            dl.close()
            sys.exit(1)
        agent = sys.argv[2]
        text = dl.format_decisions_for_agent(agent)
        if text:
            print(text)
        else:
            display = AGENT_DISPLAY.get(agent, agent)
            print(f"(No recent decisions for {display})")

    elif cmd == "brief":
        if len(sys.argv) < 3:
            print("Usage: python decision_logger.py brief <domain>")
            dl.close()
            sys.exit(1)
        domain = sys.argv[2]
        text = dl.format_decision_chain_for_brief(domain)
        if text:
            print(text)
        else:
            print(f"No decision chain for '{domain}'")

    elif cmd == "landscape":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 14
        text = dl.format_all_domains_summary(days)
        if text:
            print(text)
        else:
            print(f"No decisions in the last {days} days")

    elif cmd == "unverified":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 14
        decisions = dl.get_unverified_decisions(days)
        if not decisions:
            print(f"No unverified decisions in the last {days} days")
        else:
            print(f"Unverified decisions ({len(decisions)} total):")
            print("-" * 60)
            for d in decisions:
                agent_display = AGENT_DISPLAY.get(d["agent"], d["agent"])
                print(
                    f"  #{d['id']:>4d} ({d['age_days']}d ago) [{d['decision_type']}] "
                    f"{d['title']}"
                )
                print(f"         {agent_display} | {d['domain']}")
                print()

    elif cmd == "verify":
        if len(sys.argv) < 4:
            print("Usage: python decision_logger.py verify <id> <outcome> [notes]")
            print("Outcomes: positive | negative | neutral | mixed")
            dl.close()
            sys.exit(1)
        dec_id = int(sys.argv[2])
        outcome = sys.argv[3]
        notes = sys.argv[4] if len(sys.argv) > 4 else None
        success = dl.verify_decision(dec_id, outcome, notes)
        if success:
            print(f"Decision #{dec_id} verified: {outcome}")
        else:
            print(f"Decision #{dec_id} not found")

    elif cmd == "stats":
        stats = dl.get_stats()
        print("Decision Logger Statistics")
        print("=" * 40)
        print(f"  Total decisions:    {stats['total_decisions']:>6d}")
        print(f"  Active:             {stats['active_decisions']:>6d}")
        print(f"  Verified:           {stats['verified_decisions']:>6d}")
        print(f"  Chains:             {stats['total_chains']:>6d}")
        print(f"  Chain links:        {stats['total_links']:>6d}")
        print()
        print("By type:")
        for dt in DECISION_TYPES:
            count = stats.get(f"type_{dt}", 0)
            print(f"  {dt:15s}     {count:>6d}")
        print()
        print("By outcome (verified):")
        for outcome in ("positive", "negative", "neutral", "mixed"):
            count = stats.get(f"outcome_{outcome}", 0)
            print(f"  {outcome:15s}     {count:>6d}")
        if stats.get("recent_by_agent"):
            print()
            print("Recent decisions by agent (last 14 days):")
            for agent_disp, cnt in stats["recent_by_agent"].items():
                print(f"  {agent_disp:20s} {cnt:>4d}")
        if stats.get("recent_by_domain"):
            print()
            print("Recent decisions by domain (last 14 days):")
            for domain, cnt in stats["recent_by_domain"].items():
                print(f"  {domain:20s} {cnt:>4d}")

    elif cmd == "test":
        print("Adding test decision data...")
        print()

        # Decision 1: Tactical campaign decision
        d1 = dl.log_decision(
            agent="dbh-marketing",
            domain="advertising",
            decision_type="tactical",
            title="Pause GLM Meta campaign -- ROAS below 2x for 3 days",
            reasoning=(
                "Campaign ROAS dropped from 5.4x to 2.1x over 3 days. "
                "Creative fatigue likely. Pausing to prevent further waste "
                "while new creatives are developed."
            ),
            alternatives_considered=(
                "Could reduce budget instead of pausing, but 2.1x ROAS "
                "is below breakeven. Could also swap creatives without "
                "pausing, but no new creatives are ready."
            ),
            confidence=0.85,
            context_used=["meta_ads_data", "daily_brief", "roas_trend"],
        )
        print(f"  #{d1}: Pause GLM Meta campaign")

        # Decision 2: Strategy shift (builds on #1)
        d2 = dl.log_decision(
            agent="dbh-marketing",
            domain="advertising",
            decision_type="strategy",
            title="Shift 30% of Meta budget to email campaigns",
            reasoning=(
                "Email ROAS consistently 5x+ while Meta declining. "
                "Klaviyo campaigns have lower CAC and higher retention. "
                "This builds on the decision to pause GLM Meta."
            ),
            confidence=0.7,
            context_used=["email_performance", "meta_roas_decline",
                          "cac_comparison"],
        )
        print(f"  #{d2}: Shift budget to email")

        # Decision 3: Financial
        d3 = dl.log_decision(
            agent="dbh-marketing",
            domain="finance",
            decision_type="financial",
            title="Cap Meta daily spend at $150 until new creatives prove out",
            reasoning=(
                "Current $250/day is burning cash at 2.1x ROAS. "
                "$150/day limits exposure while we test new angles."
            ),
            confidence=0.9,
            context_used=["daily_spend_report", "roas_trend"],
        )
        print(f"  #{d3}: Cap Meta spend")

        # Decision 4: Creative
        d4 = dl.log_decision(
            agent="creative-projects",
            domain="brand",
            decision_type="creative",
            title="Test UGC-style video ads for GLM",
            reasoning=(
                "Polished brand ads are fatiguing. UGC-style content "
                "performs 40% better CTR on competitor benchmarks. "
                "Low production cost to test."
            ),
            alternatives_considered=(
                "Professional reshoot ($2-5k) or AI-generated video. "
                "UGC is fastest and cheapest to test."
            ),
            confidence=0.65,
            context_used=["competitor_analysis", "creative_fatigue_data"],
        )
        print(f"  #{d4}: Test UGC video ads")

        # Decision 5: Operational
        d5 = dl.log_decision(
            agent="dbh-marketing",
            domain="email_marketing",
            decision_type="operational",
            title="Send replenishment reminders at day 25 post-purchase",
            reasoning=(
                "30-day supply products. Day 25 gives 5 days buffer. "
                "Win-back flows show 2x higher conversion when sent "
                "before product runs out."
            ),
            confidence=0.75,
            context_used=["product_consumption_data", "klaviyo_flow_data"],
        )
        print(f"  #{d5}: Replenishment reminder timing")

        print()
        print("Test data added. Try:")
        print("  python decision_logger.py recent dbh-marketing")
        print("  python decision_logger.py chain advertising")
        print("  python decision_logger.py inject dbh-marketing")
        print("  python decision_logger.py landscape")
        print("  python decision_logger.py stats")

    else:
        print(f"Unknown command: {cmd}")
        print()
        print_usage()

    dl.close()
