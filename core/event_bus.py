#!/usr/bin/env python3
"""
Cross-Agent Event Bus -- Persistent, SQLite-backed

The nervous system of Tom's Command Center.
When one agent discovers something important, it publishes an event.
Other agents that care about that event type receive it automatically
in their next context injection.

Events flow between agents without human intervention:
  Meridian detects a campaign ROAS drop -> publishes campaign.performance_drop
  PREP receives it on next wake-up -> adjusts creative recommendations
  Lens receives it -> flags which creatives may need refreshing

Markers in agent responses:
  [EVENT: campaign.performance_drop|IMPORTANT|{"campaign":"GLM March","roas":2.1,"prev_roas":5.4}]

Design:
  - SQLite at data/event_bus.db (persistent across restarts)
  - Subscription table with wildcard pattern matching (campaign.*)
  - Auto-expiry at 48 hours
  - JSON payload for arbitrary structured data
  - processed_by tracks which agents have consumed each event
"""

import sqlite3
import json
import os
import re
import fnmatch
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Resolve paths relative to this file's location (works in Docker + local)
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "event_bus.db"

# ---- Constants ----

SEVERITIES = ("CRITICAL", "IMPORTANT", "NOTABLE", "INFO")

# Standard event types and their typical source -> consumer mappings.
# These are documented here for reference; actual routing is driven by the
# subscriptions table so new types can be added at runtime.
STANDARD_EVENT_TYPES = {
    "campaign.performance_drop":   {"source": "dbh-marketing",     "consumers": ["dbh-marketing", "creative-projects"]},
    "campaign.performance_spike":  {"source": "dbh-marketing",     "consumers": ["dbh-marketing", "creative-projects"]},
    "market.tariff_change":        {"source": "global-events",     "consumers": ["dbh-marketing"]},
    "market.competitor_move":      {"source": "global-events",     "consumers": ["dbh-marketing", "new-business"]},
    "customer.vip_milestone":      {"source": "order-intelligence","consumers": ["dbh-marketing"]},
    "customer.churn_risk":         {"source": "order-intelligence","consumers": ["dbh-marketing"]},
    "inventory.low_stock":         {"source": "shopify",           "consumers": ["dbh-marketing"]},
    "content.brief_ready":         {"source": "dbh-marketing",     "consumers": ["creative-projects"]},
    "system.error":                {"source": "*",                 "consumers": ["command-center"]},
}

# All 9 agents in the system (folder names)
ALL_AGENTS = [
    "global-events",       # Atlas
    "dbh-marketing",       # Meridian
    "pure-pets",           # Scout
    "new-business",        # Venture
    "health-fitness",      # Titan
    "social",              # Compass
    "creative-projects",   # Lens
    "daily-briefing",      # Oracle
    "command-center",      # Nexus
]

# Agent display names for readable output
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
}

# Default subscriptions: which event patterns each agent listens to.
# Patterns use fnmatch-style wildcards: * matches anything.
DEFAULT_SUBSCRIPTIONS = {
    "global-events":     ["system.error"],
    "dbh-marketing":     [
        "campaign.*",
        "market.*",
        "customer.*",
        "inventory.*",
    ],
    "pure-pets":         ["inventory.*", "customer.*"],
    "new-business":      ["market.competitor_move", "market.*"],
    "health-fitness":    [],
    "social":            [],
    "creative-projects": [
        "campaign.performance_drop",
        "campaign.performance_spike",
        "content.brief_ready",
    ],
    "daily-briefing":    ["*"],  # Oracle sees everything
    "command-center":    ["system.*"],
}


class EventBus:
    """SQLite-backed cross-agent event bus."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    # ---- Schema ----

    def _init_schema(self):
        """Create tables if they don't exist, then seed default subscriptions."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_agent TEXT NOT NULL,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'INFO',
                payload TEXT DEFAULT '{}',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed_by TEXT DEFAULT '[]',
                status TEXT DEFAULT 'pending'
            );

            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name TEXT NOT NULL,
                event_pattern TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(agent_name, event_pattern)
            );

            CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
            CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
            CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
            CREATE INDEX IF NOT EXISTS idx_events_severity ON events(severity);
            CREATE INDEX IF NOT EXISTS idx_subs_agent ON subscriptions(agent_name);
        """)
        self.conn.commit()
        self._seed_default_subscriptions()

    def _seed_default_subscriptions(self):
        """Insert default subscriptions if the table is empty."""
        count = self.conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0]
        if count > 0:
            return  # Already seeded

        for agent_name, patterns in DEFAULT_SUBSCRIPTIONS.items():
            for pattern in patterns:
                self.conn.execute(
                    "INSERT OR IGNORE INTO subscriptions (agent_name, event_pattern) VALUES (?, ?)",
                    (agent_name, pattern)
                )
        self.conn.commit()
        logger.info(f"Seeded default subscriptions for {len(DEFAULT_SUBSCRIPTIONS)} agents")

    # ---- Publish ----

    def publish(self, source_agent: str, event_type: str, severity: str,
                payload: dict = None) -> int:
        """
        Publish an event onto the bus.

        Args:
            source_agent: The agent folder name that generated the event.
            event_type:   Dotted event type string (e.g. "campaign.performance_drop").
            severity:     One of CRITICAL, IMPORTANT, NOTABLE, INFO.
            payload:      Arbitrary JSON-serialisable dict.

        Returns:
            The event ID.
        """
        severity = severity.upper()
        if severity not in SEVERITIES:
            logger.warning(f"Unknown severity '{severity}', defaulting to INFO")
            severity = "INFO"

        payload_json = json.dumps(payload or {})

        cursor = self.conn.execute(
            """INSERT INTO events (source_agent, event_type, severity, payload)
               VALUES (?, ?, ?, ?)""",
            (source_agent, event_type, severity, payload_json)
        )
        self.conn.commit()
        event_id = cursor.lastrowid

        # Determine which agents will receive this
        subscribers = self._get_subscribers_for_type(event_type)
        # Exclude the source agent from its own events
        subscribers = [s for s in subscribers if s != source_agent]

        source_display = AGENT_DISPLAY.get(source_agent, source_agent)
        sub_display = ", ".join(AGENT_DISPLAY.get(s, s) for s in subscribers) or "(none)"
        logger.info(
            f"EVENT #{event_id} published: [{severity}] {event_type} "
            f"from {source_display} -> {sub_display}"
        )

        return event_id

    # ---- Consume ----

    def get_pending_events(self, agent_name: str) -> list[dict]:
        """
        Get all pending events that match this agent's subscriptions
        and have NOT yet been processed by this agent.

        Auto-expires events older than 48 hours as a side effect.
        """
        self._expire_old_events()

        # Get this agent's subscription patterns
        patterns = self._get_patterns_for_agent(agent_name)
        if not patterns:
            return []

        # Fetch all pending events
        rows = self.conn.execute(
            """SELECT * FROM events WHERE status = 'pending'
               ORDER BY
                 CASE severity
                   WHEN 'CRITICAL' THEN 0
                   WHEN 'IMPORTANT' THEN 1
                   WHEN 'NOTABLE' THEN 2
                   WHEN 'INFO' THEN 3
                 END,
                 created_at DESC"""
        ).fetchall()

        results = []
        for row in rows:
            event = dict(row)
            # Check if this event matches any of the agent's patterns
            if not self._matches_any_pattern(event["event_type"], patterns):
                continue
            # Check if the agent already processed it
            processed_by = json.loads(event["processed_by"])
            if agent_name in processed_by:
                continue
            # Don't deliver an agent's own events to itself
            if event["source_agent"] == agent_name:
                continue
            # Deserialise payload for caller convenience
            event["payload"] = json.loads(event["payload"])
            event["processed_by"] = processed_by
            results.append(event)

        return results

    def mark_processed(self, event_id: int, agent_name: str):
        """
        Mark an event as processed by a specific agent.
        If all subscribers have processed it, set status to 'processed'.
        """
        row = self.conn.execute(
            "SELECT processed_by, event_type FROM events WHERE id = ?",
            (event_id,)
        ).fetchone()
        if not row:
            logger.warning(f"Event #{event_id} not found for mark_processed")
            return

        processed_by = json.loads(row["processed_by"])
        if agent_name not in processed_by:
            processed_by.append(agent_name)

        # Check if all subscribers have now processed it
        subscribers = self._get_subscribers_for_type(row["event_type"])
        all_processed = all(s in processed_by for s in subscribers)
        new_status = "processed" if all_processed else "pending"

        self.conn.execute(
            "UPDATE events SET processed_by = ?, status = ? WHERE id = ?",
            (json.dumps(processed_by), new_status, event_id)
        )
        self.conn.commit()

    # ---- Context Injection ----

    def inject_pending_events(self, agent_name: str) -> str:
        """
        Generate formatted text to inject into an agent's context
        before the Claude API call. This is called by the orchestrator
        when building the agent brain.

        Returns empty string if no pending events.
        """
        events = self.get_pending_events(agent_name)
        if not events:
            return ""

        agent_display = AGENT_DISPLAY.get(agent_name, agent_name)
        lines = []
        lines.append("=== PENDING EVENTS (Cross-Agent Alerts) ===")
        lines.append(f"The following events were published by other agents and are awaiting your attention.")
        lines.append(f"After processing, acknowledge each with: [EVENT_ACK: <event_id>]")
        lines.append("")

        for event in events:
            source_display = AGENT_DISPLAY.get(event["source_agent"], event["source_agent"])
            age = self._format_age(event["created_at"])
            lines.append(f"--- Event #{event['id']} [{event['severity']}] ---")
            lines.append(f"Type:   {event['event_type']}")
            lines.append(f"From:   {source_display}")
            lines.append(f"Age:    {age}")
            if event["payload"]:
                payload_str = json.dumps(event["payload"], indent=2)
                lines.append(f"Data:   {payload_str}")
            lines.append("")

        lines.append(f"Total: {len(events)} pending event(s) for {agent_display}")
        lines.append("When you have considered an event, include [EVENT_ACK: <id>] in your response.")
        lines.append("")

        return "\n".join(lines)

    # ---- Subscription Management ----

    def subscribe(self, agent_name: str, event_pattern: str):
        """Add a subscription for an agent."""
        self.conn.execute(
            "INSERT OR IGNORE INTO subscriptions (agent_name, event_pattern) VALUES (?, ?)",
            (agent_name, event_pattern)
        )
        self.conn.commit()
        logger.info(f"Subscribed {agent_name} to '{event_pattern}'")

    def unsubscribe(self, agent_name: str, event_pattern: str):
        """Remove a subscription for an agent."""
        self.conn.execute(
            "DELETE FROM subscriptions WHERE agent_name = ? AND event_pattern = ?",
            (agent_name, event_pattern)
        )
        self.conn.commit()
        logger.info(f"Unsubscribed {agent_name} from '{event_pattern}'")

    def get_subscriptions(self, agent_name: str = None) -> list[dict]:
        """Get subscriptions, optionally filtered by agent."""
        if agent_name:
            rows = self.conn.execute(
                "SELECT * FROM subscriptions WHERE agent_name = ? ORDER BY event_pattern",
                (agent_name,)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM subscriptions ORDER BY agent_name, event_pattern"
            ).fetchall()
        return [dict(r) for r in rows]

    # ---- Event Marker Extraction ----

    @staticmethod
    def extract_events_from_response(agent_name: str, response: str, bus: "EventBus") -> list[int]:
        """
        Parse agent response for event markers and publish them.

        Marker format:
          [EVENT: event_type|severity|payload_json]

        Examples:
          [EVENT: campaign.performance_drop|IMPORTANT|{"campaign":"GLM March","roas":2.1}]
          [EVENT: system.error|CRITICAL|{"error":"Shopify API timeout"}]

        Returns list of published event IDs.
        """
        event_pattern = r'\[EVENT:\s*([^|]+)\|([^|]+)\|([^\]]+)\]'
        event_ids = []

        for match in re.finditer(event_pattern, response):
            event_type = match.group(1).strip()
            severity = match.group(2).strip()
            payload_raw = match.group(3).strip()

            try:
                payload = json.loads(payload_raw)
            except json.JSONDecodeError:
                # If payload isn't valid JSON, wrap it as a message
                payload = {"message": payload_raw}

            try:
                event_id = bus.publish(agent_name, event_type, severity, payload)
                event_ids.append(event_id)
            except Exception as e:
                logger.error(f"Failed to publish event from marker: {e}")

        return event_ids

    @staticmethod
    def extract_acks_from_response(agent_name: str, response: str, bus: "EventBus") -> list[int]:
        """
        Parse agent response for event acknowledgement markers.

        Marker format:
          [EVENT_ACK: <event_id>]

        Returns list of acknowledged event IDs.
        """
        ack_pattern = r'\[EVENT_ACK:\s*(\d+)\]'
        acked = []

        for match in re.finditer(ack_pattern, response):
            event_id = int(match.group(1))
            try:
                bus.mark_processed(event_id, agent_name)
                acked.append(event_id)
            except Exception as e:
                logger.error(f"Failed to ack event #{event_id}: {e}")

        return acked

    @staticmethod
    def clean_event_markers(response: str) -> str:
        """Remove event markers from response before sending to Telegram."""
        response = re.sub(r'\[EVENT:[^\]]+\]', '', response)
        response = re.sub(r'\[EVENT_ACK:\s*\d+\]', '', response)
        return response.strip()

    # ---- Stats & Diagnostics ----

    def get_stats(self) -> dict:
        """Get event bus statistics."""
        stats = {}
        stats["total_events"] = self.conn.execute(
            "SELECT COUNT(*) FROM events"
        ).fetchone()[0]
        stats["pending_events"] = self.conn.execute(
            "SELECT COUNT(*) FROM events WHERE status = 'pending'"
        ).fetchone()[0]
        stats["processed_events"] = self.conn.execute(
            "SELECT COUNT(*) FROM events WHERE status = 'processed'"
        ).fetchone()[0]
        stats["expired_events"] = self.conn.execute(
            "SELECT COUNT(*) FROM events WHERE status = 'expired'"
        ).fetchone()[0]
        stats["total_subscriptions"] = self.conn.execute(
            "SELECT COUNT(*) FROM subscriptions"
        ).fetchone()[0]

        # Events by severity
        for sev in SEVERITIES:
            stats[f"events_{sev.lower()}"] = self.conn.execute(
                "SELECT COUNT(*) FROM events WHERE severity = ?",
                (sev,)
            ).fetchone()[0]

        # Events by source agent (last 48h)
        cutoff = (datetime.now() - timedelta(hours=48)).isoformat()
        rows = self.conn.execute(
            """SELECT source_agent, COUNT(*) as cnt FROM events
               WHERE created_at > ? GROUP BY source_agent ORDER BY cnt DESC""",
            (cutoff,)
        ).fetchall()
        stats["recent_by_source"] = {
            AGENT_DISPLAY.get(r["source_agent"], r["source_agent"]): r["cnt"]
            for r in rows
        }

        return stats

    def get_recent_events(self, limit: int = 20) -> list[dict]:
        """Get the most recent events for display."""
        rows = self.conn.execute(
            """SELECT * FROM events ORDER BY created_at DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        results = []
        for row in rows:
            event = dict(row)
            event["payload"] = json.loads(event["payload"])
            event["processed_by"] = json.loads(event["processed_by"])
            results.append(event)
        return results

    # ---- Internal Helpers ----

    def _get_patterns_for_agent(self, agent_name: str) -> list[str]:
        """Get all subscription patterns for an agent."""
        rows = self.conn.execute(
            "SELECT event_pattern FROM subscriptions WHERE agent_name = ?",
            (agent_name,)
        ).fetchall()
        return [r["event_pattern"] for r in rows]

    def _get_subscribers_for_type(self, event_type: str) -> list[str]:
        """Get all agents subscribed to a given event type."""
        rows = self.conn.execute(
            "SELECT DISTINCT agent_name, event_pattern FROM subscriptions"
        ).fetchall()
        subscribers = set()
        for row in rows:
            if self._pattern_matches(row["event_pattern"], event_type):
                subscribers.add(row["agent_name"])
        return sorted(subscribers)

    @staticmethod
    def _pattern_matches(pattern: str, event_type: str) -> bool:
        """
        Check if a subscription pattern matches an event type.
        Uses fnmatch-style wildcards:
          "campaign.*"    matches "campaign.performance_drop"
          "*"             matches everything
          "system.error"  matches only "system.error"
        """
        return fnmatch.fnmatch(event_type, pattern)

    @staticmethod
    def _matches_any_pattern(event_type: str, patterns: list[str]) -> bool:
        """Check if event_type matches any pattern in the list."""
        return any(fnmatch.fnmatch(event_type, p) for p in patterns)

    def _expire_old_events(self, max_age_hours: int = 48):
        """Mark events older than max_age_hours as expired."""
        cutoff = (datetime.now() - timedelta(hours=max_age_hours)).isoformat()
        updated = self.conn.execute(
            "UPDATE events SET status = 'expired' WHERE status = 'pending' AND created_at < ?",
            (cutoff,)
        ).rowcount
        if updated:
            self.conn.commit()
            logger.info(f"Expired {updated} events older than {max_age_hours}h")

    @staticmethod
    def _format_age(created_at_str: str) -> str:
        """Format event age as human-readable string."""
        try:
            created = datetime.fromisoformat(created_at_str)
            delta = datetime.now() - created
            total_seconds = int(delta.total_seconds())
            if total_seconds < 60:
                return f"{total_seconds}s ago"
            elif total_seconds < 3600:
                return f"{total_seconds // 60}m ago"
            elif total_seconds < 86400:
                return f"{total_seconds // 3600}h {(total_seconds % 3600) // 60}m ago"
            else:
                return f"{total_seconds // 86400}d {(total_seconds % 86400) // 3600}h ago"
        except (ValueError, TypeError):
            return "unknown"

    def close(self):
        """Close the database connection."""
        self.conn.close()


# ---- CLI ----

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    bus = EventBus()

    def print_usage():
        print("Event Bus CLI")
        print("=" * 50)
        print("Commands:")
        print("  python event_bus.py init                          -- Initialise database + default subscriptions")
        print("  python event_bus.py publish <agent> <type> <sev> [payload_json]")
        print("                                                    -- Publish an event")
        print("  python event_bus.py pending <agent>               -- Show pending events for an agent")
        print("  python event_bus.py inject <agent>                -- Show context injection text for an agent")
        print("  python event_bus.py ack <event_id> <agent>        -- Mark event as processed by agent")
        print("  python event_bus.py subs [agent]                  -- Show subscriptions (all or specific)")
        print("  python event_bus.py subscribe <agent> <pattern>   -- Add subscription")
        print("  python event_bus.py unsubscribe <agent> <pattern> -- Remove subscription")
        print("  python event_bus.py stats                         -- Show event bus statistics")
        print("  python event_bus.py recent [limit]                -- Show recent events")
        print("  python event_bus.py test                          -- Publish sample events for testing")
        print()
        print("Standard event types:")
        for etype, info in STANDARD_EVENT_TYPES.items():
            source_display = AGENT_DISPLAY.get(info["source"], info["source"])
            consumer_displays = ", ".join(AGENT_DISPLAY.get(c, c) for c in info["consumers"])
            print(f"  {etype:35s} {source_display} -> {consumer_displays}")
        print()
        print("Agent names:", ", ".join(ALL_AGENTS))

    if len(sys.argv) < 2:
        print_usage()
        bus.close()
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "init":
        print(f"Database initialised at: {DB_PATH}")
        subs = bus.get_subscriptions()
        print(f"Subscriptions: {len(subs)} active")
        agents_with_subs = set(s["agent_name"] for s in subs)
        for agent in ALL_AGENTS:
            agent_subs = [s["event_pattern"] for s in subs if s["agent_name"] == agent]
            display = AGENT_DISPLAY.get(agent, agent)
            if agent_subs:
                print(f"  {display:20s} ({agent}): {', '.join(agent_subs)}")
            else:
                print(f"  {display:20s} ({agent}): (no subscriptions)")

    elif cmd == "publish":
        if len(sys.argv) < 5:
            print("Usage: python event_bus.py publish <source_agent> <event_type> <severity> [payload_json]")
            print("Example: python event_bus.py publish dbh-marketing campaign.performance_drop IMPORTANT '{\"campaign\":\"GLM\",\"roas\":2.1}'")
            bus.close()
            sys.exit(1)
        source = sys.argv[2]
        etype = sys.argv[3]
        sev = sys.argv[4]
        payload = json.loads(sys.argv[5]) if len(sys.argv) > 5 else {}
        event_id = bus.publish(source, etype, sev, payload)
        print(f"Published event #{event_id}: [{sev}] {etype} from {source}")

    elif cmd == "pending":
        if len(sys.argv) < 3:
            print("Usage: python event_bus.py pending <agent_name>")
            bus.close()
            sys.exit(1)
        agent = sys.argv[2]
        events = bus.get_pending_events(agent)
        display = AGENT_DISPLAY.get(agent, agent)
        if not events:
            print(f"No pending events for {display} ({agent})")
        else:
            print(f"Pending events for {display} ({agent}): {len(events)}")
            print("-" * 60)
            for e in events:
                source_display = AGENT_DISPLAY.get(e["source_agent"], e["source_agent"])
                print(f"  #{e['id']} [{e['severity']}] {e['event_type']}")
                print(f"    From: {source_display} | Created: {e['created_at']}")
                if e["payload"]:
                    print(f"    Payload: {json.dumps(e['payload'])}")
                print()

    elif cmd == "inject":
        if len(sys.argv) < 3:
            print("Usage: python event_bus.py inject <agent_name>")
            bus.close()
            sys.exit(1)
        agent = sys.argv[2]
        text = bus.inject_pending_events(agent)
        if text:
            print(text)
        else:
            display = AGENT_DISPLAY.get(agent, agent)
            print(f"(No pending events for {display})")

    elif cmd == "ack":
        if len(sys.argv) < 4:
            print("Usage: python event_bus.py ack <event_id> <agent_name>")
            bus.close()
            sys.exit(1)
        event_id = int(sys.argv[2])
        agent = sys.argv[3]
        bus.mark_processed(event_id, agent)
        print(f"Event #{event_id} marked as processed by {agent}")

    elif cmd == "subs":
        agent = sys.argv[2] if len(sys.argv) > 2 else None
        subs = bus.get_subscriptions(agent)
        if agent:
            display = AGENT_DISPLAY.get(agent, agent)
            print(f"Subscriptions for {display} ({agent}):")
        else:
            print("All subscriptions:")
        print("-" * 50)
        current_agent = None
        for s in subs:
            if s["agent_name"] != current_agent:
                current_agent = s["agent_name"]
                display = AGENT_DISPLAY.get(current_agent, current_agent)
                print(f"\n  {display} ({current_agent}):")
            print(f"    - {s['event_pattern']}")

    elif cmd == "subscribe":
        if len(sys.argv) < 4:
            print("Usage: python event_bus.py subscribe <agent_name> <event_pattern>")
            bus.close()
            sys.exit(1)
        bus.subscribe(sys.argv[2], sys.argv[3])
        print(f"Subscribed {sys.argv[2]} to '{sys.argv[3]}'")

    elif cmd == "unsubscribe":
        if len(sys.argv) < 4:
            print("Usage: python event_bus.py unsubscribe <agent_name> <event_pattern>")
            bus.close()
            sys.exit(1)
        bus.unsubscribe(sys.argv[2], sys.argv[3])
        print(f"Unsubscribed {sys.argv[2]} from '{sys.argv[3]}'")

    elif cmd == "stats":
        stats = bus.get_stats()
        print("Event Bus Statistics")
        print("=" * 40)
        print(f"  Total events:     {stats['total_events']:>6d}")
        print(f"  Pending:          {stats['pending_events']:>6d}")
        print(f"  Processed:        {stats['processed_events']:>6d}")
        print(f"  Expired:          {stats['expired_events']:>6d}")
        print(f"  Subscriptions:    {stats['total_subscriptions']:>6d}")
        print()
        print("By severity:")
        for sev in SEVERITIES:
            count = stats.get(f"events_{sev.lower()}", 0)
            print(f"  {sev:12s}      {count:>6d}")
        if stats["recent_by_source"]:
            print()
            print("Recent events by source (last 48h):")
            for source, cnt in stats["recent_by_source"].items():
                print(f"  {source:20s} {cnt:>4d}")

    elif cmd == "recent":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        events = bus.get_recent_events(limit)
        if not events:
            print("No events in the database.")
        else:
            print(f"Last {len(events)} events:")
            print("-" * 70)
            for e in events:
                source_display = AGENT_DISPLAY.get(e["source_agent"], e["source_agent"])
                processed_display = ", ".join(
                    AGENT_DISPLAY.get(a, a) for a in e["processed_by"]
                ) or "(none)"
                print(
                    f"  #{e['id']:>4d} [{e['severity']:>9s}] {e['status']:>9s} | "
                    f"{e['event_type']:35s} | {source_display}"
                )
                if e["payload"]:
                    print(f"         Payload: {json.dumps(e['payload'])}")
                print(f"         Processed by: {processed_display}")
                print(f"         Created: {e['created_at']}")
                print()

    elif cmd == "test":
        print("Publishing sample events for testing...")
        print()

        # Simulate: Atlas detects a tariff change
        e1 = bus.publish(
            "global-events", "market.tariff_change", "IMPORTANT",
            {"country": "US", "tariff": "25% on NZ supplements",
             "effective_date": "2026-04-01", "impact": "Direct cost increase for US-bound shipments"}
        )
        print(f"  #{e1}: Atlas detected US tariff change")

        # Simulate: Meridian sees a campaign ROAS drop
        e2 = bus.publish(
            "dbh-marketing", "campaign.performance_drop", "IMPORTANT",
            {"campaign": "GLM March Promo", "current_roas": 2.1,
             "previous_roas": 5.4, "drop_pct": -61, "channel": "meta"}
        )
        print(f"  #{e2}: Meridian detected campaign ROAS drop")

        # Simulate: Order Intelligence flags a VIP milestone
        e3 = bus.publish(
            "order-intelligence", "customer.vip_milestone", "NOTABLE",
            {"customer_email": "vip@example.com", "milestone": "10th_order",
             "lifetime_value": 2450.00, "favourite_products": ["Marine Collagen", "Joint Formula"]}
        )
        print(f"  #{e3}: Order Intelligence flagged VIP milestone")

        # Simulate: Shopify low stock alert
        e4 = bus.publish(
            "shopify", "inventory.low_stock", "CRITICAL",
            {"product": "Marine Collagen 300g", "sku": "MC-300",
             "current_stock": 12, "daily_velocity": 4.2, "days_remaining": 2.9}
        )
        print(f"  #{e4}: Shopify low stock alert")

        # Simulate: Meridian creates a creative brief
        e5 = bus.publish(
            "dbh-marketing", "content.brief_ready", "INFO",
            {"brief_type": "email_campaign", "campaign": "April Flash Sale",
             "template": "exclusive_access_countdown", "deadline": "2026-03-10"}
        )
        print(f"  #{e5}: Meridian created a creative brief")

        # Simulate: System error
        e6 = bus.publish(
            "dbh-marketing", "system.error", "CRITICAL",
            {"error": "Klaviyo API rate limit exceeded", "endpoint": "/campaigns",
             "retry_after": 300}
        )
        print(f"  #{e6}: System error from Meridian")

        print()
        print("Test events published. Try:")
        print("  python event_bus.py pending dbh-marketing")
        print("  python event_bus.py inject creative-projects")
        print("  python event_bus.py pending daily-briefing")
        print("  python event_bus.py stats")

    else:
        print(f"Unknown command: {cmd}")
        print()
        print_usage()

    bus.close()
