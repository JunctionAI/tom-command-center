#!/usr/bin/env python3
"""
Thought Leader Scraper -- Ingests content from top AI/business thought leaders.

Monitors YouTube channels, Twitter/X feeds, and blogs via RSS.
Stores content in SQLite, extracts insights via Claude API,
and formats briefings for agent injection.

Sources: YouTube RSS, Nitter RSS proxies, blog RSS feeds.
Storage: data/thought_leaders.db (SQLite, WAL mode)

Usage:
    python -m core.thought_leader_scraper scan      # Fetch new content
    python -m core.thought_leader_scraper extract    # Extract insights from unprocessed
    python -m core.thought_leader_scraper brief      # Show current brief
    python -m core.thought_leader_scraper leaders    # List tracked leaders
"""

import json
import logging
import os
import re
import sqlite3
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Resolve paths relative to this file's location (works in Docker + local)
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "thought_leaders.db"

# ─── LEADER REGISTRY ────────────────────────────────────────────────────────
#
# Each leader has:
#   name:        Display name
#   handle:      Twitter/X handle (without @)
#   focus:       What they're known for
#   tags:        Default tags for insight categorisation
#   youtube_channel_id:  YouTube channel ID for RSS feed (needs lookup)
#   twitter_rss: Nitter/RSS proxy URL for Twitter content
#   blog_rss:    Blog RSS feed URL if available
#
# YouTube RSS format: https://www.youtube.com/feeds/videos.xml?channel_id=CHANNEL_ID
# To find a channel ID: go to the channel page, view page source, search for "channelId"

LEADERS = {
    "liam_ottley": {
        "name": "Liam Ottley",
        "handle": "liamottley",
        "focus": "AIOS methodology, AI agencies, Morningside AI",
        "tags": ["architecture", "automation", "ai_tools"],
        "youtube_channel_id": "UCui4jxDaMb53Gdh-AZUTPAg",  # Verified -- Liam Ottley
        "twitter_rss": None,  # Nitter proxies are unreliable; add when stable
        "blog_rss": None,
    },
    "greg_isenberg": {
        "name": "Greg Isenberg",
        "handle": "gregisenberg",
        "focus": "AI startups, business models, community building",
        "tags": ["business_model", "scaling", "ai_tools"],
        "youtube_channel_id": "UCPjNBjflYl0-HQtUvOx0Ibw",  # Verified -- Greg Isenberg
        "twitter_rss": None,
        "blog_rss": None,
    },
    "alex_hormozi": {
        "name": "Alex Hormozi",
        "handle": "AlexHormozi",
        "focus": "Business scaling, offers, acquisition strategies",
        "tags": ["scaling", "business_model", "personal_brand"],
        "youtube_channel_id": "UCUyDOdBWhC1MCxEjC46d-zw",  # Verified -- Alex Hormozi
        "twitter_rss": None,
        "blog_rss": None,
    },
    "pieter_levels": {
        "name": "Pieter Levels",
        "handle": "levelsio",
        "focus": "Solo founder, AI products, nomad business, shipping fast",
        "tags": ["ai_tools", "business_model", "automation"],
        "youtube_channel_id": None,  # Pieter doesn't have a primary YouTube channel
        "twitter_rss": None,
        "blog_rss": "https://levels.io/rss/",
    },
    "sahil_bloom": {
        "name": "Sahil Bloom",
        "handle": "SahilBloom",
        "focus": "Growth frameworks, mental models, personal development",
        "tags": ["scaling", "personal_brand", "business_model"],
        "youtube_channel_id": None,
        "twitter_rss": None,
        "blog_rss": None,
    },
    "sam_altman": {
        "name": "Sam Altman",
        "handle": "sama",
        "focus": "AGI direction, OpenAI, AI industry leadership",
        "tags": ["ai_tools", "architecture", "scaling"],
        "youtube_channel_id": None,
        "twitter_rss": None,
        "blog_rss": None,  # blog.samaltman.com has no RSS feed
    },
    "andrej_karpathy": {
        "name": "Andrej Karpathy",
        "handle": "karpathy",
        "focus": "AI technical direction, neural nets, AI education",
        "tags": ["ai_tools", "architecture"],
        "youtube_channel_id": "UCXUPKJO5MZQN11PqgIvyuvQ",  # TODO: verify -- Andrej Karpathy
        "twitter_rss": None,
        "blog_rss": None,
    },
    "naval_ravikant": {
        "name": "Naval Ravikant",
        "handle": "naval",
        "focus": "Leverage, wealth creation, startups, philosophy",
        "tags": ["scaling", "business_model", "personal_brand"],
        "youtube_channel_id": None,
        "twitter_rss": None,
        "blog_rss": "https://nav.al/feed",
    },
    "patrick_bet_david": {
        "name": "Patrick Bet-David",
        "handle": "patrickbetdavid",
        "focus": "Business strategy, entrepreneurship, Valuetainment",
        "tags": ["business_model", "scaling", "personal_brand"],
        "youtube_channel_id": "UCGX7nGXpz-CmO_Arg-cgJ7A",  # TODO: verify -- Valuetainment
        "twitter_rss": None,
        "blog_rss": None,
    },
    "y_combinator": {
        "name": "Y Combinator",
        "handle": "ycombinator",
        "focus": "Startup patterns, fundraising, product-market fit",
        "tags": ["business_model", "scaling", "ai_tools"],
        "youtube_channel_id": "UCcefcZRL2oaA_uBNeo5UOWg",  # TODO: verify -- Y Combinator
        "twitter_rss": None,
        "blog_rss": "https://www.ycombinator.com/blog/rss/",
    },
}

# Valid insight tags
VALID_TAGS = [
    "architecture",     # System design, agent architecture, infrastructure
    "automation",       # Workflow automation, process improvements
    "business_model",   # Revenue models, pricing, offers
    "scaling",          # Growth strategies, operational scaling
    "ai_tools",         # New AI tools, models, techniques
    "personal_brand",   # Content creation, audience building
]

# User-Agent for HTTP requests
USER_AGENT = "TomCommandCenter/1.0 (Thought Leader Intelligence)"


# ─── DATABASE ────────────────────────────────────────────────────────────────

class ThoughtLeaderDB:
    """SQLite database for thought leader content and extracted insights."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        """Create tables if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS leaders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                handle TEXT,
                focus TEXT,
                tags TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_scan_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS content_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                leader_key TEXT NOT NULL,
                source_type TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT UNIQUE NOT NULL,
                published_at TIMESTAMP,
                summary TEXT,
                processed BOOLEAN DEFAULT 0,
                fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (leader_key) REFERENCES leaders(key)
            );

            CREATE TABLE IF NOT EXISTS extracted_insights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content_item_id INTEGER NOT NULL,
                leader_key TEXT NOT NULL,
                insight TEXT NOT NULL,
                applicability TEXT,
                suggested_improvement TEXT,
                tags TEXT DEFAULT '[]',
                relevance_score REAL DEFAULT 0.5,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (content_item_id) REFERENCES content_items(id),
                FOREIGN KEY (leader_key) REFERENCES leaders(key)
            );

            CREATE INDEX IF NOT EXISTS idx_content_leader ON content_items(leader_key);
            CREATE INDEX IF NOT EXISTS idx_content_processed ON content_items(processed);
            CREATE INDEX IF NOT EXISTS idx_content_fetched ON content_items(fetched_at);
            CREATE INDEX IF NOT EXISTS idx_content_published ON content_items(published_at);
            CREATE INDEX IF NOT EXISTS idx_insights_leader ON extracted_insights(leader_key);
            CREATE INDEX IF NOT EXISTS idx_insights_created ON extracted_insights(created_at);
            CREATE INDEX IF NOT EXISTS idx_insights_tags ON extracted_insights(tags);
        """)
        self.conn.commit()
        self._seed_leaders()

    def _seed_leaders(self):
        """Insert leaders from the registry if not already present."""
        existing = self.conn.execute("SELECT key FROM leaders").fetchall()
        existing_keys = {r["key"] for r in existing}

        for key, info in LEADERS.items():
            if key not in existing_keys:
                self.conn.execute(
                    """INSERT INTO leaders (key, name, handle, focus, tags)
                       VALUES (?, ?, ?, ?, ?)""",
                    (key, info["name"], info["handle"], info["focus"],
                     json.dumps(info["tags"]))
                )
        self.conn.commit()

    def add_content_item(self, leader_key: str, source_type: str,
                         title: str, url: str, published_at: str = None,
                         summary: str = None) -> Optional[int]:
        """
        Add a content item. Returns the item ID, or None if it already exists.
        Uses url as the unique key to prevent duplicates.
        """
        try:
            cursor = self.conn.execute(
                """INSERT INTO content_items
                   (leader_key, source_type, title, url, published_at, summary)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (leader_key, source_type, title, url, published_at,
                 summary[:500] if summary else None)
            )
            self.conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            # Duplicate URL -- already fetched
            return None

    def get_unprocessed_items(self, limit: int = 20) -> list:
        """Get content items that haven't been processed for insight extraction."""
        rows = self.conn.execute(
            """SELECT ci.*, l.name as leader_name, l.focus as leader_focus
               FROM content_items ci
               JOIN leaders l ON ci.leader_key = l.key
               WHERE ci.processed = 0
               ORDER BY ci.fetched_at DESC
               LIMIT ?""",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_processed(self, content_item_id: int):
        """Mark a content item as processed."""
        self.conn.execute(
            "UPDATE content_items SET processed = 1 WHERE id = ?",
            (content_item_id,)
        )
        self.conn.commit()

    def add_insight(self, content_item_id: int, leader_key: str,
                    insight: str, applicability: str = None,
                    suggested_improvement: str = None,
                    tags: list = None, relevance_score: float = 0.5) -> int:
        """Add an extracted insight."""
        cursor = self.conn.execute(
            """INSERT INTO extracted_insights
               (content_item_id, leader_key, insight, applicability,
                suggested_improvement, tags, relevance_score)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (content_item_id, leader_key, insight, applicability,
             suggested_improvement, json.dumps(tags or []), relevance_score)
        )
        self.conn.commit()
        return cursor.lastrowid

    def get_recent_insights(self, hours: int = 48, min_relevance: float = 0.0) -> list:
        """Get insights from the last N hours."""
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        rows = self.conn.execute(
            """SELECT ei.*, l.name as leader_name, ci.title as content_title,
                      ci.url as content_url, ci.source_type
               FROM extracted_insights ei
               JOIN leaders l ON ei.leader_key = l.key
               JOIN content_items ci ON ei.content_item_id = ci.id
               WHERE ei.created_at > ? AND ei.relevance_score >= ?
               ORDER BY ei.relevance_score DESC, ei.created_at DESC""",
            (since, min_relevance)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_improvement_suggestions(self, hours: int = 48) -> list:
        """Get actionable improvement suggestions from recent insights."""
        since = (datetime.now() - timedelta(hours=hours)).isoformat()
        rows = self.conn.execute(
            """SELECT ei.*, l.name as leader_name, ci.title as content_title,
                      ci.url as content_url
               FROM extracted_insights ei
               JOIN leaders l ON ei.leader_key = l.key
               JOIN content_items ci ON ei.content_item_id = ci.id
               WHERE ei.created_at > ?
                 AND ei.suggested_improvement IS NOT NULL
                 AND ei.suggested_improvement != ''
               ORDER BY ei.relevance_score DESC""",
            (since,)
        ).fetchall()
        return [dict(r) for r in rows]

    def update_leader_scan_time(self, leader_key: str):
        """Update the last_scan_at timestamp for a leader."""
        self.conn.execute(
            "UPDATE leaders SET last_scan_at = ? WHERE key = ?",
            (datetime.now().isoformat(), leader_key)
        )
        self.conn.commit()

    def get_leaders(self) -> list:
        """Get all tracked leaders with their stats."""
        rows = self.conn.execute(
            """SELECT l.*,
                      (SELECT COUNT(*) FROM content_items WHERE leader_key = l.key) as content_count,
                      (SELECT COUNT(*) FROM extracted_insights WHERE leader_key = l.key) as insight_count
               FROM leaders l
               ORDER BY l.name"""
        ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self) -> dict:
        """Get overall database statistics."""
        stats = {}
        stats["leaders"] = self.conn.execute(
            "SELECT COUNT(*) FROM leaders"
        ).fetchone()[0]
        stats["total_content"] = self.conn.execute(
            "SELECT COUNT(*) FROM content_items"
        ).fetchone()[0]
        stats["unprocessed_content"] = self.conn.execute(
            "SELECT COUNT(*) FROM content_items WHERE processed = 0"
        ).fetchone()[0]
        stats["total_insights"] = self.conn.execute(
            "SELECT COUNT(*) FROM extracted_insights"
        ).fetchone()[0]
        stats["recent_insights_48h"] = self.conn.execute(
            "SELECT COUNT(*) FROM extracted_insights WHERE created_at > ?",
            ((datetime.now() - timedelta(hours=48)).isoformat(),)
        ).fetchone()[0]
        return stats

    def close(self):
        """Close the database connection."""
        self.conn.close()


# ─── RSS FETCHING ────────────────────────────────────────────────────────────

def _clean_html(text: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    if not text:
        return ""
    clean = re.sub(r'<[^>]+>', '', text)
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()


def _get_text(element, tag: str, default: str = '') -> str:
    """Get text content from an XML element by tag."""
    el = element.find(tag)
    return el.text.strip() if el is not None and el.text else default


def _get_text_ns(element, tag: str, ns: dict, default: str = '') -> str:
    """Get text content from a namespaced XML element."""
    el = element.find(tag, ns)
    return el.text.strip() if el is not None and el.text else default


def fetch_rss_feed(feed_url: str, max_items: int = 10, timeout: int = 15) -> list:
    """
    Fetch and parse an RSS or Atom feed.
    Returns list of dicts with: title, link, published, summary.
    Handles both RSS 2.0 and Atom feed formats.
    """
    items = []

    try:
        req = urllib.request.Request(feed_url, headers={
            'User-Agent': USER_AGENT
        })
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = response.read()

        root = ET.fromstring(data)

        # Try RSS 2.0 first
        for item in root.findall('.//item')[:max_items]:
            entry = {
                'title': _get_text(item, 'title'),
                'link': _get_text(item, 'link'),
                'published': _get_text(item, 'pubDate'),
                'summary': _clean_html(_get_text(item, 'description', '')),
            }
            if entry['title']:
                items.append(entry)

        # Try Atom if no RSS items found
        if not items:
            ns = {'atom': 'http://www.w3.org/2005/Atom'}

            # Also try YouTube's media namespace
            yt_ns = {
                'atom': 'http://www.w3.org/2005/Atom',
                'media': 'http://search.yahoo.com/mrss/',
                'yt': 'http://www.youtube.com/xml/schemas/2015',
            }

            for entry_el in root.findall('.//atom:entry', ns)[:max_items]:
                link_el = entry_el.find('atom:link', ns)
                # YouTube uses media:group/media:description for summaries
                media_group = entry_el.find('media:group', yt_ns)
                summary = ''
                if media_group is not None:
                    desc_el = media_group.find('media:description', yt_ns)
                    if desc_el is not None and desc_el.text:
                        summary = desc_el.text.strip()
                if not summary:
                    summary = _clean_html(
                        _get_text_ns(entry_el, 'atom:summary', ns) or
                        _get_text_ns(entry_el, 'atom:content', ns) or ''
                    )

                entry = {
                    'title': _get_text_ns(entry_el, 'atom:title', ns),
                    'link': link_el.get('href', '') if link_el is not None else '',
                    'published': (
                        _get_text_ns(entry_el, 'atom:published', ns) or
                        _get_text_ns(entry_el, 'atom:updated', ns)
                    ),
                    'summary': summary,
                }
                if entry['title']:
                    items.append(entry)

    except urllib.error.URLError as e:
        logger.warning(f"Network error fetching {feed_url}: {e}")
    except ET.ParseError as e:
        logger.warning(f"XML parse error for {feed_url}: {e}")
    except Exception as e:
        logger.warning(f"Failed to fetch {feed_url}: {e}")

    return items


def _build_youtube_rss(channel_id: str) -> str:
    """Build a YouTube RSS feed URL from a channel ID."""
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


# ─── CONTENT SCANNING ───────────────────────────────────────────────────────

def scan_leader(leader_key: str, leader_info: dict, db: ThoughtLeaderDB) -> int:
    """
    Scan all configured feeds for a single leader.
    Returns the number of new content items found.
    """
    new_items = 0
    name = leader_info["name"]

    # YouTube RSS
    yt_id = leader_info.get("youtube_channel_id")
    if yt_id:
        feed_url = _build_youtube_rss(yt_id)
        logger.info(f"Scanning YouTube for {name}...")
        items = fetch_rss_feed(feed_url, max_items=10)
        for item in items:
            item_id = db.add_content_item(
                leader_key=leader_key,
                source_type="youtube",
                title=item['title'],
                url=item['link'],
                published_at=item.get('published'),
                summary=item.get('summary', '')[:500],
            )
            if item_id is not None:
                new_items += 1
                logger.debug(f"  New: {item['title'][:60]}")

    # Twitter/X RSS (via Nitter proxy or similar)
    twitter_rss = leader_info.get("twitter_rss")
    if twitter_rss:
        logger.info(f"Scanning Twitter/X for {name}...")
        items = fetch_rss_feed(twitter_rss, max_items=15)
        for item in items:
            item_id = db.add_content_item(
                leader_key=leader_key,
                source_type="twitter",
                title=item['title'][:200],
                url=item['link'],
                published_at=item.get('published'),
                summary=item.get('summary', '')[:500],
            )
            if item_id is not None:
                new_items += 1

    # Blog RSS
    blog_rss = leader_info.get("blog_rss")
    if blog_rss:
        logger.info(f"Scanning blog for {name}...")
        items = fetch_rss_feed(blog_rss, max_items=10)
        for item in items:
            item_id = db.add_content_item(
                leader_key=leader_key,
                source_type="blog",
                title=item['title'],
                url=item['link'],
                published_at=item.get('published'),
                summary=item.get('summary', '')[:500],
            )
            if item_id is not None:
                new_items += 1

    db.update_leader_scan_time(leader_key)
    return new_items


def run_thought_leader_scan(db: ThoughtLeaderDB = None) -> str:
    """
    Main entry point for scheduled task.
    Scans all leaders for new content.
    Returns a summary string suitable for logging or agent injection.
    """
    if db is None:
        db = ThoughtLeaderDB()
        close_db = True
    else:
        close_db = False

    total_new = 0
    results = []

    for key, info in LEADERS.items():
        try:
            new_count = scan_leader(key, info, db)
            total_new += new_count
            if new_count > 0:
                results.append(f"  {info['name']}: {new_count} new items")
        except Exception as e:
            logger.error(f"Error scanning {info['name']}: {e}")
            results.append(f"  {info['name']}: ERROR -- {str(e)[:80]}")

    summary_lines = [
        f"Thought Leader Scan Complete -- {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"Total new items: {total_new}",
    ]
    if results:
        summary_lines.append("")
        summary_lines.extend(results)

    stats = db.get_stats()
    summary_lines.append("")
    summary_lines.append(f"DB totals: {stats['total_content']} content items, "
                         f"{stats['unprocessed_content']} unprocessed, "
                         f"{stats['total_insights']} insights extracted")

    if close_db:
        db.close()

    summary = "\n".join(summary_lines)
    logger.info(summary)
    return summary


# ─── INSIGHT EXTRACTION (Claude API) ────────────────────────────────────────

EXTRACTION_SYSTEM_PROMPT = """You are an intelligence analyst for Tom's Command Center, a multi-agent AI system.
Your job is to extract actionable insights from thought leader content.

Tom runs Deep Blue Health (NZ supplement brand), uses a 9-agent AI system on Telegram,
and is building towards full business autonomy with AI leverage.

For each piece of content, extract:
1. Key insights (1-3 bullet points)
2. Applicability to Tom's system (how could this improve his agent architecture, business, or operations?)
3. Specific improvement suggestions (concrete, implementable ideas)
4. Relevance score (0.0-1.0, where 1.0 = directly applicable right now)

Respond in JSON format:
{
    "insights": [
        {
            "insight": "Key insight text",
            "applicability": "How this applies to Tom's system",
            "suggested_improvement": "Specific actionable improvement or null",
            "tags": ["tag1", "tag2"],
            "relevance_score": 0.7
        }
    ]
}

Valid tags: architecture, automation, business_model, scaling, ai_tools, personal_brand

Focus on insights that are:
- Actionable (not just interesting observations)
- Relevant to AI-first solo operators
- Applicable to multi-agent systems, DTC e-commerce, or personal brand building
- Specific enough to implement

If the content has no actionable insights for Tom, return {"insights": []}."""


def extract_insights_from_content(items: list, db: ThoughtLeaderDB) -> int:
    """
    Process unprocessed content items through Claude for insight extraction.
    Returns the number of insights extracted.

    Uses the same Anthropic client pattern as the orchestrator.
    """
    try:
        import anthropic
    except ImportError:
        logger.error("anthropic package not installed -- run: pip install anthropic")
        return 0

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set -- cannot extract insights")
        return 0

    client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env var
    total_insights = 0

    for item in items:
        content_text = _format_content_for_extraction(item)

        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1500,
                system=EXTRACTION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content_text}]
            )
            response_text = response.content[0].text

            # Parse JSON response
            # Handle case where Claude wraps JSON in markdown code block
            json_match = re.search(r'\{[\s\S]*\}', response_text)
            if not json_match:
                logger.warning(f"No JSON found in extraction response for item #{item['id']}")
                db.mark_processed(item['id'])
                continue

            data = json.loads(json_match.group())
            insights = data.get("insights", [])

            for insight_data in insights:
                tags = insight_data.get("tags", [])
                # Validate tags
                tags = [t for t in tags if t in VALID_TAGS]

                db.add_insight(
                    content_item_id=item['id'],
                    leader_key=item['leader_key'],
                    insight=insight_data.get("insight", ""),
                    applicability=insight_data.get("applicability"),
                    suggested_improvement=insight_data.get("suggested_improvement"),
                    tags=tags,
                    relevance_score=float(insight_data.get("relevance_score", 0.5)),
                )
                total_insights += 1

            db.mark_processed(item['id'])
            logger.info(f"Extracted {len(insights)} insights from: {item['title'][:60]}")

        except json.JSONDecodeError as e:
            logger.warning(f"JSON parse error for item #{item['id']}: {e}")
            db.mark_processed(item['id'])
        except Exception as e:
            logger.error(f"Extraction error for item #{item['id']}: {e}")
            # Don't mark as processed on API errors -- retry next time

    return total_insights


def _format_content_for_extraction(item: dict) -> str:
    """Format a content item into a prompt for Claude extraction."""
    lines = [
        f"Leader: {item.get('leader_name', 'Unknown')}",
        f"Focus area: {item.get('leader_focus', 'Unknown')}",
        f"Source: {item.get('source_type', 'Unknown')}",
        f"Title: {item.get('title', 'Untitled')}",
    ]

    if item.get('published_at'):
        lines.append(f"Published: {item['published_at']}")

    if item.get('summary'):
        lines.append(f"\nContent/Description:\n{item['summary']}")
    else:
        lines.append("\n(No description available -- extract what you can from the title)")

    if item.get('url'):
        lines.append(f"\nURL: {item['url']}")

    return "\n".join(lines)


def run_insight_extraction(db: ThoughtLeaderDB = None, limit: int = 20) -> str:
    """
    Main entry point for insight extraction.
    Processes unprocessed content items.
    Returns a summary string.
    """
    if db is None:
        db = ThoughtLeaderDB()
        close_db = True
    else:
        close_db = False

    items = db.get_unprocessed_items(limit=limit)
    if not items:
        msg = "No unprocessed content items to extract insights from."
        logger.info(msg)
        if close_db:
            db.close()
        return msg

    logger.info(f"Processing {len(items)} unprocessed content items...")
    total = extract_insights_from_content(items, db)

    summary = (
        f"Insight Extraction Complete -- {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"Processed: {len(items)} content items\n"
        f"Insights extracted: {total}"
    )

    if close_db:
        db.close()

    logger.info(summary)
    return summary


# ─── BRIEFING INTEGRATION ───────────────────────────────────────────────────

# Mapping from tags to briefing sections
TAG_TO_SECTION = {
    "architecture": "System Improvements",
    "automation": "System Improvements",
    "business_model": "Business Strategy",
    "scaling": "Business Strategy",
    "ai_tools": "AI Tools & Tech",
    "personal_brand": "Business Strategy",
}


def format_thought_leader_brief(db: ThoughtLeaderDB = None,
                                 hours: int = 48) -> str:
    """
    Format recent insights into a briefing for agent injection.
    Groups by relevance category: System Improvements, Business Strategy, AI Tools & Tech.
    Only shows insights from the last `hours` hours.

    Returns formatted text suitable for prepending to agent context.
    """
    if db is None:
        db = ThoughtLeaderDB()
        close_db = True
    else:
        close_db = False

    insights = db.get_recent_insights(hours=hours, min_relevance=0.3)

    if not insights:
        if close_db:
            db.close()
        return ""

    # Group insights by section
    sections = {
        "System Improvements": [],
        "Business Strategy": [],
        "AI Tools & Tech": [],
    }

    for insight in insights:
        tags = json.loads(insight.get("tags", "[]"))
        # Determine section from primary tag
        section = "Business Strategy"  # default
        for tag in tags:
            if tag in TAG_TO_SECTION:
                section = TAG_TO_SECTION[tag]
                break
        sections[section].append(insight)

    # Format output
    lines = [
        f"=== THOUGHT LEADER INTELLIGENCE (Last {hours}h) ===",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M NZST')}",
        f"Total insights: {len(insights)}",
        "",
    ]

    for section_name, section_insights in sections.items():
        if not section_insights:
            continue

        lines.append(f"--- {section_name} ---")
        for ins in section_insights[:5]:  # Cap at 5 per section
            score_bar = _relevance_bar(ins.get("relevance_score", 0.5))
            lines.append(f"  {score_bar} [{ins['leader_name']}] {ins['insight']}")
            if ins.get('applicability'):
                lines.append(f"       Applies: {ins['applicability']}")
            if ins.get('suggested_improvement'):
                lines.append(f"       Action: {ins['suggested_improvement']}")
            source_info = f"{ins.get('source_type', '?')}: {ins.get('content_title', '?')[:50]}"
            lines.append(f"       Source: {source_info}")
            lines.append("")
        lines.append("")

    if close_db:
        db.close()

    return "\n".join(lines)


def get_improvement_suggestions(db: ThoughtLeaderDB = None,
                                 hours: int = 48) -> str:
    """
    Returns actionable system improvements extracted from thought leader content.
    Formatted for direct agent consumption.
    """
    if db is None:
        db = ThoughtLeaderDB()
        close_db = True
    else:
        close_db = False

    suggestions = db.get_improvement_suggestions(hours=hours)

    if not suggestions:
        if close_db:
            db.close()
        return ""

    lines = [
        "=== SUGGESTED IMPROVEMENTS (from Thought Leaders) ===",
        "",
    ]

    for i, sug in enumerate(suggestions[:10], 1):
        score_bar = _relevance_bar(sug.get("relevance_score", 0.5))
        lines.append(f"{i}. {score_bar} {sug['suggested_improvement']}")
        lines.append(f"   Source: {sug['leader_name']} -- {sug.get('content_title', 'Unknown')[:50]}")
        if sug.get('content_url'):
            lines.append(f"   URL: {sug['content_url']}")
        lines.append("")

    if close_db:
        db.close()

    return "\n".join(lines)


def _relevance_bar(score: float) -> str:
    """Convert a 0.0-1.0 relevance score to a visual indicator."""
    if score >= 0.8:
        return "[HIGH]"
    elif score >= 0.5:
        return "[MED]"
    else:
        return "[LOW]"


# ─── CLI ─────────────────────────────────────────────────────────────────────

def print_usage():
    """Print CLI usage information."""
    print("Thought Leader Scraper")
    print("=" * 50)
    print("Commands:")
    print("  python -m core.thought_leader_scraper scan      -- Fetch new content from all leaders")
    print("  python -m core.thought_leader_scraper extract    -- Extract insights from unprocessed content")
    print("  python -m core.thought_leader_scraper brief      -- Show current thought leader brief")
    print("  python -m core.thought_leader_scraper leaders    -- List tracked leaders and stats")
    print("  python -m core.thought_leader_scraper stats      -- Show database statistics")
    print("  python -m core.thought_leader_scraper suggest    -- Show improvement suggestions")
    print()
    print("Typical workflow:")
    print("  1. scan     -- Pull latest content")
    print("  2. extract  -- Run Claude on new content")
    print("  3. brief    -- View formatted intelligence")


if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    if len(sys.argv) < 2:
        print_usage()
        sys.exit(0)

    cmd = sys.argv[1]
    db = ThoughtLeaderDB()

    try:
        if cmd == "scan":
            print(run_thought_leader_scan(db))

        elif cmd == "extract":
            limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20
            print(run_insight_extraction(db, limit=limit))

        elif cmd == "brief":
            hours = int(sys.argv[2]) if len(sys.argv) > 2 else 48
            brief = format_thought_leader_brief(db, hours=hours)
            if brief:
                print(brief)
            else:
                print("No recent insights available. Run 'scan' then 'extract' first.")

        elif cmd == "leaders":
            leaders = db.get_leaders()
            print(f"Tracked Thought Leaders ({len(leaders)})")
            print("=" * 70)
            for leader in leaders:
                last_scan = leader.get('last_scan_at', 'Never')
                if last_scan and last_scan != 'Never':
                    last_scan = last_scan[:16]
                print(f"  {leader['name']:25s} @{leader['handle'] or 'n/a':20s}")
                print(f"    Focus: {leader['focus']}")
                print(f"    Content: {leader['content_count']} items | "
                      f"Insights: {leader['insight_count']} | "
                      f"Last scan: {last_scan}")

                # Show configured sources
                info = LEADERS.get(leader['key'], {})
                sources = []
                if info.get('youtube_channel_id'):
                    sources.append("YouTube")
                if info.get('twitter_rss'):
                    sources.append("Twitter/X")
                if info.get('blog_rss'):
                    sources.append("Blog")
                print(f"    Sources: {', '.join(sources) if sources else '(none configured)'}")
                print()

        elif cmd == "stats":
            stats = db.get_stats()
            print("Thought Leader Database Statistics")
            print("=" * 40)
            print(f"  Leaders tracked:      {stats['leaders']:>6d}")
            print(f"  Total content items:  {stats['total_content']:>6d}")
            print(f"  Unprocessed items:    {stats['unprocessed_content']:>6d}")
            print(f"  Total insights:       {stats['total_insights']:>6d}")
            print(f"  Recent insights (48h):{stats['recent_insights_48h']:>6d}")

        elif cmd == "suggest":
            hours = int(sys.argv[2]) if len(sys.argv) > 2 else 48
            suggestions = get_improvement_suggestions(db, hours=hours)
            if suggestions:
                print(suggestions)
            else:
                print("No improvement suggestions available. Run 'scan' then 'extract' first.")

        else:
            print(f"Unknown command: {cmd}")
            print()
            print_usage()

    finally:
        db.close()
