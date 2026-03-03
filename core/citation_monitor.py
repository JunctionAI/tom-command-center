#!/usr/bin/env python3
"""
Citation Monitor -- AI Answer Engine Optimization (AEO) Tracking

Monitors whether Deep Blue Health (deepbluehealth.co.nz) appears in AI chatbot
responses when users ask supplement-related queries. This is the measurement
layer for the AEO strategy -- if DBH isn't being cited by Perplexity, ChatGPT,
and Google AI Overviews, the content strategy needs to change.

Tracks:
  - DBH brand mention rate across target queries
  - Which competitors ARE being mentioned (and where DBH is not)
  - Source URLs that AI engines cite (content gap identification)
  - Sentiment of mentions (positive/neutral/negative)
  - Trend over time (improving or declining visibility)

Data lives at data/intelligence.db (citation_checks table), WAL mode.
Uses Perplexity API (sonar model) for cost-effective monitoring.

What can be done WITHOUT human approval (SAFE):
  - Run citation checks against AI platforms
  - Store results in database
  - Generate reports, trends, and gap analysis
  - Format for agent briefings

What NEEDS human approval:
  - Nothing -- this is read-only monitoring

Usage:
    python -m core.citation_monitor run          # Run all queries against Perplexity
    python -m core.citation_monitor report       # Weekly citation report
    python -m core.citation_monitor report 30    # 30-day citation report
    python -m core.citation_monitor gaps         # Gap analysis (competitors cited, DBH not)
    python -m core.citation_monitor status       # Quick status (last check, mention rate)
"""

import json
import logging
import os
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Resolve paths relative to this file's location (works in Docker + local)
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "intelligence.db"

# Rate limit between Perplexity API calls (seconds)
QUERY_DELAY = 2.0

# User-Agent for HTTP requests
USER_AGENT = "TomCommandCenter/1.0 (Citation Monitor)"


def _utcnow() -> datetime:
    """Timezone-aware UTC now (avoids deprecated datetime.utcnow)."""
    return datetime.now(timezone.utc)


class CitationMonitor:
    """Monitor Deep Blue Health mentions in AI answer engines."""

    # Target queries -- supplement queries a NZ customer would ask an AI chatbot.
    # These are the queries DBH SHOULD appear in if AEO strategy is working.
    MONITOR_QUERIES = [
        "best green lipped mussel supplement new zealand",
        "best joint supplement nz",
        "marine collagen new zealand",
        "best deer velvet supplement",
        "sea cucumber supplement benefits",
        "best propolis supplement nz",
        "colostrum supplement new zealand",
        "green lipped mussel vs fish oil",
        "best supplements for joint pain nz",
        "manuka honey health benefits supplement",
    ]

    # Brand terms to search for in AI responses (case-insensitive)
    BRAND_TERMS = [
        "deep blue health",
        "deepbluehealth",
        "dbh",
        "deepbluehealth.co.nz",
    ]

    # Competitor brands to track (who IS being mentioned when DBH is not)
    COMPETITOR_TERMS = [
        "healthpost",
        "go healthy",
        "good health",
        "nutra-life",
        "clinicians",
    ]

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        self.api_key = os.environ.get("PERPLEXITY_API_KEY")
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        """Create citation_checks table if it doesn't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS citation_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                engine TEXT NOT NULL DEFAULT 'perplexity',
                response_text TEXT,
                dbh_mentioned INTEGER DEFAULT 0,
                competitor_mentions TEXT DEFAULT '[]',
                sources TEXT DEFAULT '[]',
                sentiment TEXT DEFAULT 'neutral',
                checked_at TEXT NOT NULL,
                batch_id TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_citation_checked_at
                ON citation_checks(checked_at);

            CREATE INDEX IF NOT EXISTS idx_citation_query_engine
                ON citation_checks(query, engine);
        """)
        self.conn.commit()

    # ===================================================================
    # DETECTION HELPERS
    # ===================================================================

    def _detect_brand_mention(self, text: str) -> bool:
        """Check if any DBH brand term appears in the response text."""
        text_lower = text.lower()
        for term in self.BRAND_TERMS:
            if term in text_lower:
                return True
        return False

    def _detect_competitor_mentions(self, text: str) -> list:
        """Find which competitor brands are mentioned in the response."""
        text_lower = text.lower()
        found = []
        for comp in self.COMPETITOR_TERMS:
            if comp in text_lower:
                found.append(comp)
        return found

    def _assess_sentiment(self, text: str) -> str:
        """
        Basic sentiment assessment of DBH mentions.
        Returns 'positive', 'neutral', or 'negative'.

        Uses keyword heuristics -- good enough for monitoring.
        Claude-based sentiment analysis can be layered on later.
        """
        text_lower = text.lower()

        # Only assess sentiment if DBH is actually mentioned
        if not self._detect_brand_mention(text_lower):
            return "neutral"

        positive_signals = [
            "recommended", "popular", "trusted", "well-known", "reputable",
            "high quality", "top rated", "best", "excellent", "premium",
            "highly rated", "good reputation", "established",
        ]
        negative_signals = [
            "avoid", "not recommended", "poor quality", "complaints",
            "overpriced", "questionable", "controversial", "concerns",
            "warning", "be cautious", "side effects",
        ]

        pos_count = sum(1 for s in positive_signals if s in text_lower)
        neg_count = sum(1 for s in negative_signals if s in text_lower)

        if pos_count > neg_count:
            return "positive"
        elif neg_count > pos_count:
            return "negative"
        return "neutral"

    def _extract_sources(self, response_data: dict) -> list:
        """Extract source URLs from Perplexity response if available."""
        sources = []
        try:
            # Perplexity returns citations in the response
            citations = response_data.get("citations", [])
            if citations:
                sources = list(citations)

            # Also extract URLs from markdown links in content
            choices = response_data.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                try:
                    import re
                    urls = re.findall(r'\[.*?\]\((https?://[^\s\)]+)\)', content)
                    for url in urls:
                        if url not in sources:
                            sources.append(url)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Could not extract sources: {e}")

        return sources

    # ===================================================================
    # PERPLEXITY API
    # ===================================================================

    def check_perplexity(self, query: str) -> dict:
        """
        Query Perplexity API and check if DBH is mentioned.

        Uses the sonar model (fast, cost-effective for monitoring).
        Standard OpenAI-compatible chat completions format.

        Returns dict with:
            engine, query, response, dbh_mentioned,
            competitors_found, sources, sentiment
        """
        if not self.api_key:
            logger.error("PERPLEXITY_API_KEY not set. Cannot run citation check.")
            return {
                "engine": "perplexity",
                "query": query,
                "response": "",
                "dbh_mentioned": False,
                "competitors_found": [],
                "sources": [],
                "sentiment": "neutral",
                "error": "API key not configured",
            }

        payload = json.dumps({
            "model": "sonar",
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a helpful assistant. Answer the question "
                        "thoroughly, mentioning specific brands and products "
                        "where relevant. Include New Zealand brands if applicable."
                    ),
                },
                {
                    "role": "user",
                    "content": query,
                },
            ],
            "temperature": 0.1,
            "max_tokens": 1024,
        }).encode("utf-8")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }

        req = urllib.request.Request(
            "https://api.perplexity.ai/chat/completions",
            data=payload,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            response_text = ""
            choices = data.get("choices", [])
            if choices:
                response_text = choices[0].get("message", {}).get("content", "")

            dbh_mentioned = self._detect_brand_mention(response_text)
            competitors = self._detect_competitor_mentions(response_text)
            sentiment = self._assess_sentiment(response_text)
            sources = self._extract_sources(data)

            result = {
                "engine": "perplexity",
                "query": query,
                "response": response_text,
                "dbh_mentioned": dbh_mentioned,
                "competitors_found": competitors,
                "sources": sources,
                "sentiment": sentiment,
            }

            logger.info(
                f"Citation check: '{query[:50]}...' -- "
                f"DBH={'YES' if dbh_mentioned else 'NO'}, "
                f"competitors={competitors}"
            )

            return result

        except urllib.error.HTTPError as e:
            error_body = ""
            try:
                error_body = e.read().decode("utf-8")
            except Exception:
                pass
            logger.error(f"Perplexity API error {e.code} for query '{query}': {error_body}")
            return {
                "engine": "perplexity",
                "query": query,
                "response": "",
                "dbh_mentioned": False,
                "competitors_found": [],
                "sources": [],
                "sentiment": "neutral",
                "error": f"HTTP {e.code}: {error_body[:200]}",
            }
        except Exception as e:
            logger.error(f"Perplexity request failed for query '{query}': {e}")
            return {
                "engine": "perplexity",
                "query": query,
                "response": "",
                "dbh_mentioned": False,
                "competitors_found": [],
                "sources": [],
                "sentiment": "neutral",
                "error": str(e),
            }

    # ===================================================================
    # DATABASE PERSISTENCE
    # ===================================================================

    def _save_check(self, result: dict, batch_id: str):
        """Save a citation check result to the database."""
        try:
            self.conn.execute(
                """
                INSERT INTO citation_checks
                    (query, engine, response_text, dbh_mentioned,
                     competitor_mentions, sources, sentiment, checked_at, batch_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result["query"],
                    result["engine"],
                    result["response"],
                    1 if result["dbh_mentioned"] else 0,
                    json.dumps(result["competitors_found"]),
                    json.dumps(result["sources"]),
                    result["sentiment"],
                    _utcnow().isoformat(),
                    batch_id,
                ),
            )
            self.conn.commit()
        except Exception as e:
            logger.error(f"Failed to save citation check: {e}")

    # ===================================================================
    # MAIN CHECK RUNNER
    # ===================================================================

    def check_all_queries(self) -> str:
        """
        Run all monitor queries against Perplexity.
        Returns a formatted summary string suitable for Telegram.
        """
        if not self.api_key:
            return (
                "CITATION MONITOR ERROR\n"
                "PERPLEXITY_API_KEY not set. Cannot run citation checks.\n"
                "Set the environment variable and retry."
            )

        batch_id = _utcnow().strftime("%Y%m%d_%H%M%S")
        results = []
        mentioned_count = 0
        total_competitors = {}

        for i, query in enumerate(self.MONITOR_QUERIES):
            # Rate limit between calls
            if i > 0:
                time.sleep(QUERY_DELAY)

            result = self.check_perplexity(query)
            self._save_check(result, batch_id)
            results.append(result)

            if result["dbh_mentioned"]:
                mentioned_count += 1

            for comp in result["competitors_found"]:
                total_competitors[comp] = total_competitors.get(comp, 0) + 1

        # Build summary
        mention_rate = (mentioned_count / len(results) * 100) if results else 0

        lines = [
            "AI CITATION MONITOR -- CHECK COMPLETE",
            f"Batch: {batch_id}",
            f"Engine: Perplexity (sonar)",
            f"Queries checked: {len(results)}",
            f"DBH mentioned: {mentioned_count}/{len(results)} ({mention_rate:.0f}%)",
            "",
            "PER-QUERY RESULTS",
        ]

        for r in results:
            status = "CITED" if r["dbh_mentioned"] else "NOT CITED"
            error_note = f" [ERROR: {r['error'][:60]}]" if r.get("error") else ""
            lines.append(f"  [{status}] {r['query']}")
            if r["competitors_found"]:
                comps = ", ".join(r["competitors_found"])
                lines.append(f"    Competitors mentioned: {comps}")
            if r.get("sentiment") != "neutral" and r["dbh_mentioned"]:
                lines.append(f"    Sentiment: {r['sentiment']}")
            if error_note:
                lines.append(f"    {error_note}")

        if total_competitors:
            lines.append("")
            lines.append("COMPETITOR VISIBILITY")
            for comp, count in sorted(total_competitors.items(), key=lambda x: -x[1]):
                lines.append(f"  {comp}: mentioned in {count}/{len(results)} queries")

        # Identify gaps (competitors mentioned, DBH not)
        gaps = [
            r for r in results
            if not r["dbh_mentioned"] and r["competitors_found"]
        ]
        if gaps:
            lines.append("")
            lines.append("CONTENT GAPS (competitors cited, DBH not)")
            for g in gaps:
                lines.append(f"  '{g['query']}' -- {', '.join(g['competitors_found'])} cited instead")

        lines.append("")
        lines.append("Next step: Run 'report' for trend analysis over time.")

        return "\n".join(lines)

    # ===================================================================
    # REPORTING
    # ===================================================================

    def get_citation_report(self, days: int = 7) -> str:
        """
        Get citation tracking report for the last N days.
        Shows mention rate, per-query breakdown, competitor frequency, and trend.
        """
        cutoff = (_utcnow() - timedelta(days=days)).isoformat()
        prev_cutoff = (_utcnow() - timedelta(days=days * 2)).isoformat()

        # Current period
        rows = self.conn.execute(
            """
            SELECT query, dbh_mentioned, competitor_mentions, sentiment, checked_at
            FROM citation_checks
            WHERE checked_at >= ?
            ORDER BY checked_at DESC
            """,
            (cutoff,),
        ).fetchall()

        # Previous period (for trend comparison)
        prev_rows = self.conn.execute(
            """
            SELECT query, dbh_mentioned, competitor_mentions
            FROM citation_checks
            WHERE checked_at >= ? AND checked_at < ?
            ORDER BY checked_at DESC
            """,
            (prev_cutoff, cutoff),
        ).fetchall()

        if not rows:
            return (
                f"CITATION REPORT -- Last {days} days\n"
                "No citation checks found for this period.\n"
                "Run 'python -m core.citation_monitor run' to start monitoring."
            )

        # Current period stats
        total_checks = len(rows)
        mentioned = sum(1 for r in rows if r["dbh_mentioned"])
        mention_rate = (mentioned / total_checks * 100) if total_checks else 0

        # Previous period stats (for trend)
        prev_total = len(prev_rows)
        prev_mentioned = sum(1 for r in prev_rows if r["dbh_mentioned"])
        prev_rate = (prev_mentioned / prev_total * 100) if prev_total else 0

        # Trend
        if prev_total == 0:
            trend = "No prior data for comparison"
        elif mention_rate > prev_rate:
            trend = f"IMPROVING (+{mention_rate - prev_rate:.0f}pp vs previous {days} days)"
        elif mention_rate < prev_rate:
            trend = f"DECLINING ({mention_rate - prev_rate:.0f}pp vs previous {days} days)"
        else:
            trend = "STABLE (same as previous period)"

        # Per-query breakdown (most recent check per query)
        query_latest = {}
        for r in rows:
            q = r["query"]
            if q not in query_latest:
                query_latest[q] = r

        # Competitor frequency across all checks
        comp_counts = {}
        for r in rows:
            try:
                comps = json.loads(r["competitor_mentions"])
            except (json.JSONDecodeError, TypeError):
                comps = []
            for c in comps:
                comp_counts[c] = comp_counts.get(c, 0) + 1

        # Sentiment breakdown (only for checks where DBH was mentioned)
        sentiments = {"positive": 0, "neutral": 0, "negative": 0}
        for r in rows:
            if r["dbh_mentioned"]:
                s = r["sentiment"] if r["sentiment"] in sentiments else "neutral"
                sentiments[s] += 1

        # Build report
        lines = [
            f"AI CITATION REPORT -- Last {days} Days",
            f"Period: {cutoff[:10]} to {_utcnow().strftime('%Y-%m-%d')}",
            f"Total checks: {total_checks}",
            "",
            "OVERALL DBH VISIBILITY",
            f"  Mention rate: {mention_rate:.0f}% ({mentioned}/{total_checks} checks)",
            f"  Trend: {trend}",
        ]

        if mentioned > 0:
            lines.append(
                f"  Sentiment: {sentiments['positive']} positive, "
                f"{sentiments['neutral']} neutral, "
                f"{sentiments['negative']} negative"
            )

        lines.append("")
        lines.append("PER-QUERY STATUS (most recent check)")
        for query in sorted(query_latest.keys()):
            r = query_latest[query]
            status = "CITED" if r["dbh_mentioned"] else "NOT CITED"
            lines.append(f"  [{status}] {query}")

        if comp_counts:
            lines.append("")
            lines.append("COMPETITOR CITATION FREQUENCY")
            for comp, count in sorted(comp_counts.items(), key=lambda x: -x[1]):
                pct = (count / total_checks * 100)
                lines.append(f"  {comp}: {count} mentions ({pct:.0f}% of checks)")

        lines.append("")
        lines.append("STRATEGIC IMPLICATIONS")
        if mention_rate >= 50:
            lines.append("  DBH has strong AI visibility. Focus on maintaining position.")
        elif mention_rate >= 20:
            lines.append("  DBH has moderate AI visibility. Increase structured content (FAQ, schema).")
        else:
            lines.append("  DBH has low AI visibility. Priority: llms.txt, DietarySupplement schema,")
            lines.append("  structured FAQ pages, and authoritative backlinks.")

        if comp_counts:
            top_comp = max(comp_counts, key=comp_counts.get)
            lines.append(f"  Top competitor in AI results: {top_comp} ({comp_counts[top_comp]} mentions)")
            lines.append("  Study their content structure for clues on what AI engines prefer.")

        return "\n".join(lines)

    # ===================================================================
    # GAP ANALYSIS
    # ===================================================================

    def get_gap_analysis(self) -> str:
        """
        Identify queries where competitors are mentioned but DBH is not.
        These are content opportunities for the Beacon SEO agent.
        Uses data from the last 14 days for a meaningful sample.
        """
        cutoff = (_utcnow() - timedelta(days=14)).isoformat()

        rows = self.conn.execute(
            """
            SELECT query, dbh_mentioned, competitor_mentions, sources
            FROM citation_checks
            WHERE checked_at >= ?
            ORDER BY checked_at DESC
            """,
            (cutoff,),
        ).fetchall()

        if not rows:
            return (
                "GAP ANALYSIS\n"
                "No citation data available. Run checks first.\n"
                "Command: python -m core.citation_monitor run"
            )

        # Aggregate: most recent result per query
        query_data = {}
        for r in rows:
            q = r["query"]
            if q not in query_data:
                try:
                    comps = json.loads(r["competitor_mentions"])
                except (json.JSONDecodeError, TypeError):
                    comps = []
                try:
                    sources = json.loads(r["sources"])
                except (json.JSONDecodeError, TypeError):
                    sources = []
                query_data[q] = {
                    "dbh_mentioned": bool(r["dbh_mentioned"]),
                    "competitors": comps,
                    "sources": sources,
                }

        # Categorise queries
        gaps = {
            q: d for q, d in query_data.items()
            if not d["dbh_mentioned"] and d["competitors"]
        }
        misses = {
            q: d for q, d in query_data.items()
            if not d["dbh_mentioned"] and not d["competitors"]
        }
        wins = {
            q: d for q, d in query_data.items()
            if d["dbh_mentioned"]
        }

        lines = [
            "AI CITATION GAP ANALYSIS",
            f"Data from last 14 days ({len(query_data)} queries tracked)",
            "",
        ]

        if gaps:
            lines.append(f"HIGH PRIORITY GAPS ({len(gaps)} queries)")
            lines.append("Competitors are being cited but DBH is not.")
            lines.append("These need targeted content pages with structured data.")
            lines.append("")
            for q, d in gaps.items():
                lines.append(f"  Query: \"{q}\"")
                lines.append(f"  Competitors cited: {', '.join(d['competitors'])}")
                if d["sources"]:
                    lines.append(f"  Sources AI used: {', '.join(d['sources'][:3])}")
                lines.append("")

        if misses:
            lines.append(f"CONTENT VOIDS ({len(misses)} queries)")
            lines.append("Nobody is being cited well. First-mover advantage opportunity.")
            lines.append("")
            for q, d in misses.items():
                lines.append(f"  Query: \"{q}\"")
                if d["sources"]:
                    lines.append(f"  Sources AI referenced: {', '.join(d['sources'][:3])}")
                lines.append("")

        if wins:
            lines.append(f"CURRENT WINS ({len(wins)} queries)")
            lines.append("DBH is being cited. Protect and reinforce these.")
            lines.append("")
            for q, d in wins.items():
                comp_note = f" (also: {', '.join(d['competitors'])})" if d["competitors"] else ""
                lines.append(f"  Query: \"{q}\"{comp_note}")

        lines.append("")
        lines.append("RECOMMENDED ACTIONS FOR BEACON (SEO AGENT)")
        if gaps:
            lines.append(f"  1. Create dedicated landing pages for {len(gaps)} gap queries")
            lines.append("  2. Add DietarySupplement schema markup to product pages")
            lines.append("  3. Build FAQ sections answering these exact queries")
            lines.append("  4. Implement llms.txt at deepbluehealth.co.nz/llms.txt")
        if misses:
            idx = 5 if gaps else 1
            lines.append(f"  {idx}. Publish authoritative content for {len(misses)} void queries")
            lines.append(f"  {idx + 1}. Target featured snippets on Google for these terms")
        if not gaps and not misses:
            lines.append("  No gaps found. DBH is being cited across all tracked queries.")
            lines.append("  Focus on expanding the query list and maintaining quality.")

        return "\n".join(lines)

    # ===================================================================
    # STATUS
    # ===================================================================

    def get_status(self) -> str:
        """Quick status: last check time and current mention rate."""
        row = self.conn.execute(
            "SELECT checked_at FROM citation_checks ORDER BY checked_at DESC LIMIT 1"
        ).fetchone()

        if not row:
            return (
                "CITATION MONITOR STATUS\n"
                "No checks have been run yet.\n"
                "Run: python -m core.citation_monitor run"
            )

        last_check = row["checked_at"]

        # Last 7 days stats
        cutoff = (_utcnow() - timedelta(days=7)).isoformat()
        stats = self.conn.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(dbh_mentioned) as mentioned
            FROM citation_checks
            WHERE checked_at >= ?
            """,
            (cutoff,),
        ).fetchone()

        total = stats["total"] or 0
        mentioned = stats["mentioned"] or 0
        rate = (mentioned / total * 100) if total else 0

        return (
            f"CITATION MONITOR STATUS\n"
            f"Last check: {last_check}\n"
            f"7-day stats: {mentioned}/{total} checks with DBH cited ({rate:.0f}%)\n"
            f"Queries tracked: {len(self.MONITOR_QUERIES)}\n"
            f"Perplexity API: {'configured' if self.api_key else 'NOT SET'}"
        )

    # ===================================================================
    # BRIEFING FORMAT (for agent injection)
    # ===================================================================

    def format_for_briefing(self) -> str:
        """
        Concise citation summary for Oracle/PREP/Meridian morning briefings.
        Line-by-line format (no tables per Tom's preference).
        """
        try:
            row = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM citation_checks"
            ).fetchone()

            if not row or row["cnt"] == 0:
                return "AI Citations: No data yet (run citation check first)"

            # Last 7 days stats
            cutoff = (_utcnow() - timedelta(days=7)).isoformat()
            stats = self.conn.execute(
                """SELECT COUNT(*) as total, SUM(dbh_mentioned) as found
                   FROM citation_checks WHERE checked_at >= ?""",
                (cutoff,),
            ).fetchone()

            last_check = self.conn.execute(
                "SELECT MAX(checked_at) as last_at FROM citation_checks"
            ).fetchone()

            lines = ["AI Citation Monitoring:"]

            if stats["total"] and stats["total"] > 0:
                found = stats["found"] or 0
                rate = (found / stats["total"] * 100)
                lines.append(f"  - Citation rate (7d): {found}/{stats['total']} ({rate:.0f}%)")
            else:
                lines.append("  - No checks in last 7 days")

            if last_check and last_check["last_at"]:
                lines.append(f"  - Last check: {last_check['last_at'][:16]}")

            # Top cited queries
            top_cited = self.conn.execute(
                """SELECT query FROM citation_checks
                   WHERE checked_at >= ? AND dbh_mentioned = 1
                   GROUP BY query
                   ORDER BY COUNT(*) DESC
                   LIMIT 3""",
                (cutoff,),
            ).fetchall()

            if top_cited:
                lines.append("  - Cited in:")
                for row in top_cited:
                    lines.append(f"    - \"{row['query']}\"")

            return "\n".join(lines)

        except Exception as e:
            return f"AI Citations: Unavailable ({str(e)})"

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()


# ===================================================================
# TOP-LEVEL FUNCTIONS (called by orchestrator)
# ===================================================================


def run_citation_check() -> str:
    """Top-level function called by orchestrator scheduled task."""
    monitor = CitationMonitor()
    try:
        return monitor.check_all_queries()
    finally:
        monitor.close()


def get_weekly_citation_report() -> str:
    """Called by Tony report generator or weekly Meridian brief."""
    monitor = CitationMonitor()
    try:
        return monitor.get_citation_report(days=7)
    finally:
        monitor.close()


def get_gap_analysis() -> str:
    """Called by Beacon SEO agent for content planning."""
    monitor = CitationMonitor()
    try:
        return monitor.get_gap_analysis()
    finally:
        monitor.close()


# ===================================================================
# CLI
# ===================================================================


def main():
    """CLI entry point for standalone testing and cron."""
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    commands = {
        "run": "Run all citation checks against Perplexity",
        "report": "Show 7-day citation report (or specify days: report 30)",
        "gaps": "Show gap analysis (content opportunities)",
        "status": "Quick status check",
    }

    if len(sys.argv) < 2 or sys.argv[1] not in commands:
        print("Citation Monitor -- AI Answer Engine Optimization Tracker")
        print("Deep Blue Health (deepbluehealth.co.nz)")
        print()
        print("Commands:")
        for cmd, desc in commands.items():
            print(f"  {cmd:10s}  {desc}")
        print()
        print("Usage: python -m core.citation_monitor <command>")
        print()
        print(f"Database: {DB_PATH}")
        print(f"Perplexity API: {'configured' if os.environ.get('PERPLEXITY_API_KEY') else 'NOT SET'}")
        print()
        print(f"Monitored queries ({len(CitationMonitor.MONITOR_QUERIES)}):")
        for q in CitationMonitor.MONITOR_QUERIES:
            print(f"  - {q}")
        sys.exit(1)

    command = sys.argv[1]
    monitor = CitationMonitor()

    try:
        if command == "run":
            print(monitor.check_all_queries())

        elif command == "report":
            days = 7
            if len(sys.argv) > 2:
                try:
                    days = int(sys.argv[2])
                except ValueError:
                    pass
            print(monitor.get_citation_report(days=days))

        elif command == "gaps":
            print(monitor.get_gap_analysis())

        elif command == "status":
            print(monitor.get_status())

    finally:
        monitor.close()


if __name__ == "__main__":
    main()
