#!/usr/bin/env python3
"""
News Fetcher -- Pulls real-time headlines from RSS feeds.
Used by the orchestrator to inject live data into agent prompts
before calling Claude API (which has no internet access).

No API keys required -- uses public RSS feeds.
"""

import logging
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
HEADLINE_HISTORY_FILE = BASE_DIR / "data" / "headline_history.json"

# --- RSS Feed Sources ---
# Organised by topic. Each agent's scan can pull relevant feeds.

FEEDS = {
    # Geopolitics & World News
    "bbc_world": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "aljazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "guardian_world": "https://www.theguardian.com/world/rss",
    "ap_news": "https://feedx.net/rss/ap.xml",
    "reuters_world": "https://www.reutersagency.com/feed/?best-topics=world",

    # Technology & AI
    "techcrunch": "https://techcrunch.com/feed/",
    "ars_technica": "https://feeds.arstechnica.com/arstechnica/index",
    "verge": "https://www.theverge.com/rss/index.xml",

    # Business & Markets
    "cnbc": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "bbc_business": "https://feeds.bbci.co.uk/news/business/rss.xml",
    "ft_world": "https://www.ft.com/rss/home/uk",

    # NZ specific
    "rnz_news": "https://www.rnz.co.nz/rss/national.xml",
    "rnz_political": "https://www.rnz.co.nz/rss/political.xml",
    "nzherald": "https://rss.nzherald.co.nz/rss/xml/nzhrsecnews.xml",
    "stuff_national": "https://www.stuff.co.nz/rss/national",
    "stuff_business": "https://www.stuff.co.nz/rss/business",
    "interest_nz": "https://www.interest.co.nz/rss.xml",

    # Science & Health
    "bbc_science": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    "guardian_science": "https://www.theguardian.com/science/rss",
    "nature_news": "https://www.nature.com/nature.rss",

    # Power, Finance & Investigative Journalism (for Medici)
    "guardian_politics": "https://www.theguardian.com/politics/rss",
    "guardian_economics": "https://www.theguardian.com/business/economics/rss",
    "guardian_finance": "https://www.theguardian.com/money/rss",
    "propublica": "https://www.propublica.org/feeds/propublica/main",
    "intercept": "https://theintercept.com/feed/?rss",
    "icij": "https://www.icij.org/feed/",
    "ft_markets": "https://www.ft.com/rss/markets",
    "bloomberg_markets": "https://feeds.bloomberg.com/markets/news.rss",
    "wsj_markets": "https://feeds.wsj.com/wsj/xml/rss/3_7031.xml",
    "cnbc_finance": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10000664",
    "politico": "https://www.politico.com/rss/politicopicks.xml",
    "axios": "https://api.axios.com/feed/",
}

# Which feeds each agent should use for scans
AGENT_FEEDS = {
    "global-events": [
        "bbc_world", "aljazeera", "guardian_world", "ap_news",
        "bbc_business", "cnbc",
        "rnz_news", "rnz_political", "nzherald", "stuff_national", "interest_nz",
        "bbc_science", "guardian_science",
        "techcrunch",
    ],
    "dbh-marketing": [
        "bbc_business", "cnbc",
        "rnz_news",
    ],
    "health-science": [
        "techcrunch", "ars_technica",
        "cnbc",
    ],
    "creative-projects": [
        "techcrunch", "ars_technica", "verge",
    ],
    "medici": [
        "guardian_politics", "guardian_economics", "guardian_finance",
        "propublica", "intercept", "icij",
        "ft_markets", "bloomberg_markets", "wsj_markets", "cnbc_finance",
        "politico", "axios",
        "bbc_world", "reuters_world",
    ],
    "daily-briefing": [
        "bbc_world", "ap_news",
        "bbc_business",
        "rnz_news",
        "techcrunch",
    ],
}


def fetch_feed(feed_url: str, max_items: int = 10, timeout: int = 10) -> list:
    """
    Fetch and parse an RSS feed. Returns list of dicts with title, link, published, summary.
    """
    import urllib.request
    import urllib.error

    items = []
    try:
        req = urllib.request.Request(feed_url, headers={
            'User-Agent': 'TomCommandCenter/1.0 (News Aggregator)'
        })
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = response.read()

        root = ET.fromstring(data)

        # Handle both RSS 2.0 and Atom feeds
        # RSS 2.0
        for item in root.findall('.//item')[:max_items]:
            entry = {
                'title': _get_text(item, 'title'),
                'link': _get_text(item, 'link'),
                'published': _get_text(item, 'pubDate'),
                'summary': _clean_html(_get_text(item, 'description', '')),
            }
            if entry['title']:
                items.append(entry)

        # Atom (if no RSS items found)
        if not items:
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            for entry_el in root.findall('.//atom:entry', ns)[:max_items]:
                link_el = entry_el.find('atom:link', ns)
                entry = {
                    'title': _get_text_ns(entry_el, 'title', ns),
                    'link': link_el.get('href', '') if link_el is not None else '',
                    'published': _get_text_ns(entry_el, 'updated', ns),
                    'summary': _clean_html(_get_text_ns(entry_el, 'summary', ns) or ''),
                }
                if entry['title']:
                    items.append(entry)

    except Exception as e:
        logger.warning(f"Failed to fetch {feed_url}: {e}")

    return items


def _get_text(element, tag, default=''):
    """Get text from an XML element."""
    el = element.find(tag)
    return el.text.strip() if el is not None and el.text else default


def _get_text_ns(element, tag, ns, default=''):
    """Get text from an XML element with namespace."""
    el = element.find(f'atom:{tag}', ns)
    return el.text.strip() if el is not None and el.text else default


def _clean_html(text: str) -> str:
    """Strip HTML tags from text."""
    import re
    clean = re.sub(r'<[^>]+>', '', text)
    clean = re.sub(r'\s+', ' ', clean)
    return clean.strip()[:300]  # Limit summary length


def _headline_hash(title: str) -> str:
    """Hash a headline for dedup. Normalises whitespace and case."""
    normalised = " ".join(title.lower().split())
    return hashlib.md5(normalised.encode()).hexdigest()[:12]


def _load_headline_history() -> dict:
    """Load previously sent headline hashes. Structure: {date_str: [hashes]}"""
    try:
        if HEADLINE_HISTORY_FILE.exists():
            return json.loads(HEADLINE_HISTORY_FILE.read_text(encoding='utf-8'))
    except Exception:
        pass
    return {}


def _save_headline_history(history: dict):
    """Save headline history, keeping only last 3 days."""
    # Prune old entries
    cutoff = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    pruned = {k: v for k, v in history.items() if k >= cutoff}
    try:
        HEADLINE_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HEADLINE_HISTORY_FILE.write_text(json.dumps(pruned), encoding='utf-8')
    except Exception as e:
        logger.warning(f"Failed to save headline history: {e}")


def fetch_news_for_agent(agent_name: str, max_per_feed: int = 8, deduplicate: bool = True) -> str:
    """
    Fetch all relevant news feeds for an agent and format as a text block
    that can be injected into the agent's prompt.

    If deduplicate=True, filters out headlines that were already sent in the
    last 3 days, ensuring Tom only sees genuinely new stories.

    Returns a formatted string of headlines + summaries.
    """
    feed_keys = AGENT_FEEDS.get(agent_name, [])
    if not feed_keys:
        return ""

    all_items = []
    for key in feed_keys:
        url = FEEDS.get(key)
        if url:
            items = fetch_feed(url, max_items=max_per_feed)
            for item in items:
                item['source'] = key
                item['hash'] = _headline_hash(item['title'])
            all_items.extend(items)

    if not all_items:
        return ""

    # Deduplication: filter out headlines sent in previous days
    new_items = all_items
    if deduplicate:
        history = _load_headline_history()
        # Collect all hashes from previous days (not today — today's haven't been sent yet)
        today_str = datetime.now().strftime("%Y-%m-%d")
        seen_hashes = set()
        for date_key, hashes in history.items():
            if date_key != today_str:
                seen_hashes.update(hashes)

        new_items = [item for item in all_items if item['hash'] not in seen_hashes]

        # Save today's hashes (all fetched, not just new — so they're deduped tomorrow)
        today_hashes = history.get(today_str, [])
        today_hashes.extend(item['hash'] for item in all_items)
        history[today_str] = list(set(today_hashes))
        _save_headline_history(history)

        logger.info(f"News dedup: {len(all_items)} total, {len(new_items)} new, "
                     f"{len(all_items) - len(new_items)} filtered as repeats")

    if not new_items:
        return f"=== NEWS: No new headlines since yesterday ({len(all_items)} filtered as repeats) ==="

    # Format into a prompt-friendly block
    lines = [
        f"=== NEW HEADLINES ONLY (fetched {datetime.now().strftime('%Y-%m-%d %H:%M NZST')}) ===",
        f"New: {len(new_items)} headlines | Filtered: {len(all_items) - len(new_items)} repeats from yesterday",
        "",
    ]

    # Group by source
    by_source = {}
    for item in new_items:
        by_source.setdefault(item['source'], []).append(item)

    for source, items in by_source.items():
        lines.append(f"--- {source} ---")
        for item in items:
            lines.append(f"- {item['title']}")
            if item['summary']:
                lines.append(f"  {item['summary'][:200]}")
        lines.append("")

    return "\n".join(lines)


def fetch_headlines_only(agent_name: str, max_per_feed: int = 5) -> str:
    """
    Lighter version -- just headlines, no summaries.
    Good for daily briefings where you want breadth not depth.
    """
    feed_keys = AGENT_FEEDS.get(agent_name, [])
    if not feed_keys:
        return ""

    all_headlines = []
    for key in feed_keys:
        url = FEEDS.get(key)
        if url:
            items = fetch_feed(url, max_items=max_per_feed)
            for item in items:
                all_headlines.append(f"[{key}] {item['title']}")

    if not all_headlines:
        return ""

    header = f"=== HEADLINES ({datetime.now().strftime('%Y-%m-%d %H:%M')}) ==="
    return header + "\n" + "\n".join(all_headlines)


# --- Keyword Search in Headlines ---

def search_headlines(keywords: list, agent_name: str = None, max_per_feed: int = 10) -> str:
    """
    Fetch feeds and filter for headlines matching any of the keywords.
    Useful for targeted monitoring (e.g., "Iran", "oil", "Hormuz").
    """
    feed_keys = AGENT_FEEDS.get(agent_name, list(FEEDS.keys())) if agent_name else list(FEEDS.keys())

    matches = []
    for key in feed_keys:
        url = FEEDS.get(key)
        if url:
            items = fetch_feed(url, max_items=max_per_feed)
            for item in items:
                text = f"{item['title']} {item.get('summary', '')}".lower()
                if any(kw.lower() in text for kw in keywords):
                    matches.append(f"[{key}] {item['title']}")
                    if item.get('summary'):
                        matches.append(f"  {item['summary'][:200]}")

    if not matches:
        return f"No headlines matching: {', '.join(keywords)}"

    header = f"=== MATCHING HEADLINES for [{', '.join(keywords)}] ==="
    return header + "\n" + "\n".join(matches)


# --- CLI ---

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "agent" and len(sys.argv) > 2:
            agent = sys.argv[2]
            print(fetch_news_for_agent(agent))

        elif cmd == "headlines" and len(sys.argv) > 2:
            agent = sys.argv[2]
            print(fetch_headlines_only(agent))

        elif cmd == "search" and len(sys.argv) > 2:
            keywords = sys.argv[2:]
            print(search_headlines(keywords))

        elif cmd == "feed" and len(sys.argv) > 2:
            feed_key = sys.argv[2]
            url = FEEDS.get(feed_key)
            if url:
                items = fetch_feed(url)
                for item in items:
                    print(f"- {item['title']}")
                    if item['summary']:
                        print(f"  {item['summary'][:150]}")
            else:
                print(f"Unknown feed: {feed_key}")
                print(f"Available: {', '.join(FEEDS.keys())}")

        elif cmd == "list":
            print("Available feeds:")
            for key, url in FEEDS.items():
                print(f"  {key:25s} {url}")
            print("\nAgent feed mappings:")
            for agent, keys in AGENT_FEEDS.items():
                print(f"  {agent}: {', '.join(keys)}")

        else:
            print("Usage:")
            print("  python news_fetcher.py agent <agent-name>    -- Full news for agent")
            print("  python news_fetcher.py headlines <agent-name> -- Headlines only")
            print("  python news_fetcher.py search <keyword> ...   -- Search all feeds")
            print("  python news_fetcher.py feed <feed-key>        -- Single feed")
            print("  python news_fetcher.py list                   -- List all feeds")
    else:
        # Default: show Atlas news
        print(fetch_news_for_agent("global-events"))
