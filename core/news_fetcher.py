#!/usr/bin/env python3
"""
News Fetcher -- Pulls real-time headlines from RSS feeds.
Used by the orchestrator to inject live data into agent prompts
before calling Claude API (which has no internet access).

No API keys required -- uses public RSS feeds.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

# --- RSS Feed Sources ---
# Organised by topic. Each agent's scan can pull relevant feeds.

FEEDS = {
    # Geopolitics & World News
    "bbc_world": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "aljazeera": "https://www.aljazeera.com/xml/rss/all.xml",
    "guardian_world": "https://www.theguardian.com/world/rss",
    "ap_news": "https://feedx.net/rss/ap.xml",

    # Middle East specific
    "bbc_middle_east": "https://feeds.bbci.co.uk/news/world/middle_east/rss.xml",
    "guardian_middle_east": "https://www.theguardian.com/world/middleeast/rss",

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
    "nzherald": "https://rss.nzherald.co.nz/rss/xml/nzhrsecnews.xml",
    "stuff_national": "https://www.stuff.co.nz/rss/national",
}

# Which feeds each agent should use for scans
AGENT_FEEDS = {
    "global-events": [
        "bbc_world", "aljazeera", "guardian_world", "ap_news",
        "bbc_middle_east", "guardian_middle_east",
        "bbc_business",
    ],
    "dbh-marketing": [
        "bbc_business", "cnbc",
        "rnz_news",
    ],
    "new-business": [
        "techcrunch", "ars_technica",
        "cnbc",
    ],
    "creative-projects": [
        "techcrunch", "ars_technica", "verge",
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


def fetch_news_for_agent(agent_name: str, max_per_feed: int = 8) -> str:
    """
    Fetch all relevant news feeds for an agent and format as a text block
    that can be injected into the agent's prompt.

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
            all_items.extend(items)

    if not all_items:
        return ""

    # Format into a prompt-friendly block
    lines = [
        f"=== LIVE NEWS FEED (fetched {datetime.now().strftime('%Y-%m-%d %H:%M NZST')}) ===",
        f"Total headlines: {len(all_items)} from {len(feed_keys)} sources",
        "",
    ]

    # Group by source
    by_source = {}
    for item in all_items:
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
