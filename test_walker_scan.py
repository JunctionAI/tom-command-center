"""
Walker Capital — Manual test scan.
Runs today's discovery scan, screens all candidates, sends brief to both Telegrams.
Usage: python test_walker_scan.py
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime

# Load .env
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
PERPLEXITY  = os.environ.get("PERPLEXITY_API_KEY", "")
CONFIG_PATH = Path(__file__).parent / "config" / "telegram.json"

with open(CONFIG_PATH) as f:
    tg = json.load(f)

CHAT_TOM   = tg["chat_ids"]["walker-capital-tom"]
CHAT_TRENT = tg["chat_ids"]["walker-capital-trent"]

if not BOT_TOKEN:
    sys.exit("❌ TELEGRAM_BOT_TOKEN missing from .env")
if not PERPLEXITY:
    sys.exit("❌ PERPLEXITY_API_KEY missing from .env — add it and retry")


# ── Telegram sender ──────────────────────────────────────────────────────────
import requests

def send(chat_id: str, text: str):
    """Send message to a Telegram chat."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    # Telegram has 4096 char limit — chunk if needed
    for i in range(0, len(text), 4000):
        chunk = text[i:i+4000]
        r = requests.post(url, json={"chat_id": chat_id, "text": chunk})
        if not r.ok:
            logger.error(f"Telegram error {r.status_code}: {r.text[:200]}")
        else:
            logger.info(f"Sent to {chat_id}: {len(chunk)} chars")

def send_both(text: str):
    send(CHAT_TOM,   text)
    send(CHAT_TRENT, text)


# ── Run scan ─────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent))

from core.walker_screener import run_discovery_scan, run_quantitative_screen, generate_research_brief
from core.walker_pipeline_db import initialise_db, add_company, advance_stage, update_catalyst, get_pipeline_summary

initialise_db()

logger.info("=== WALKER CAPITAL — TEST SCAN ===")
logger.info("Running Stage 1: Discovery...")

candidates = run_discovery_scan()
logger.info(f"Found {len(candidates)} candidates")

if not candidates:
    send_both("⚠️ WALKER CAPITAL — TEST\nDiscovery scan returned no candidates. Check Perplexity API key.")
    sys.exit()

passed  = []
watchlist = []
rejected  = []

for c in candidates:
    if not c.get("ticker") or not c.get("name"):
        continue

    logger.info(f"Screening {c['ticker']}...")
    result = run_quantitative_screen(c["ticker"], c["exchange"], c["name"])

    if result.get("screen_passed"):
        passed.append({**c, **result})
    elif result.get("watchlist"):
        watchlist.append({**c, **result})
    else:
        rejected.append({**c, **result})

logger.info(f"Screening complete — passed={len(passed)}, watchlist={len(watchlist)}, rejected={len(rejected)}")

# ── Build Telegram summary message ──────────────────────────────────────────
segment_label = {"A": "Mature", "B": "Growth"}
catalyst_label = {3: "Strong", 2: "Moderate", 1: "Weak", 0: "None"}

lines = [
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    "🏦 WALKER CAPITAL",
    f"Daily Scan — {datetime.now().strftime('%a %d %b %Y')}",
    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    "",
    f"Scanned {len(candidates)} companies today.",
    f"{len(passed)} passed screening  |  {len(watchlist)} watchlisted  |  {len(rejected)} rejected",
    "",
]

if passed:
    lines.append(f"✅ INTO PIPELINE ({len(passed)})")
    lines.append("─────────────────────────────────────")
    for p in passed:
        seg = segment_label.get(p.get('segment',''), p.get('segment',''))
        cat_score = p.get('catalyst_score', 0)
        cat = catalyst_label.get(cat_score, str(cat_score))
        gaps = p.get('data_gaps', [])
        lines.append(f"{p['name']} — {p['ticker']} ({p['exchange']})")
        lines.append(f"  {seg} company  |  Catalyst: {cat} ({cat_score}/3)")
        lines.append(f"  {p.get('catalyst_description','')[:120]}")
        if gaps:
            lines.append(f"  ⚠️ Data gaps: {', '.join(gaps)} — verify at Stage 4")
        lines.append("")

if watchlist:
    lines.append(f"👁 WATCHLIST ({len(watchlist)})")
    lines.append("─────────────────────────────────────")
    for w in watchlist:
        lines.append(f"{w['name']} — {w['ticker']}")
        lines.append(f"  Weak catalyst — monitoring for improvement")
        lines.append("")

if rejected:
    lines.append(f"❌ REJECTED ({len(rejected)})")
    lines.append("─────────────────────────────────────")
    for r in rejected:
        lines.append(f"{r['name']} — {r['ticker']}")
        lines.append(f"  {r.get('screen_reason','')[:120]}")
        lines.append("")

lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
if passed:
    tickers = ", ".join([p['ticker'] for p in passed])
    lines.append(f"Running full research briefs on: {tickers}")
    lines.append("Results coming through now...")
else:
    lines.append("No companies passed today. Next scan tomorrow 7am.")
lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

# Local debug summary
print("\n=== SCREENING RESULTS ===")
for c in candidates:
    ticker = c.get("ticker","?")
    name = c.get("name","?")
    match = next((x for x in passed + watchlist + rejected if x.get("ticker") == ticker), None)
    if match:
        status = "PASS" if match in passed else ("WATCH" if match in watchlist else "FAIL")
        print(f"{status} | {name} ({ticker}) | {match.get('screen_reason','')}")
print("========================\n")

send_both("\n".join(lines))

# ── Stage 3: Deep research on passed companies ────────────────────────────────
for p in passed:
    logger.info(f"Generating research brief for {p['ticker']}...")
    brief = generate_research_brief(
        ticker=p["ticker"],
        exchange=p["exchange"],
        name=p["name"],
        sector=p.get("sector", ""),
        catalyst_description=p.get("catalyst_description", ""),
        comparable_companies=p.get("comparable_companies", []),
    )

    if brief.get("brief_text"):
        # Save to DB
        try:
            company_id = add_company(
                ticker=p["ticker"], name=p["name"], exchange=p["exchange"],
                sector=p.get("sector",""), segment=p.get("segment","A"),
                discovery_thesis=p.get("discovery_thesis",""),
            )
            if company_id:
                advance_stage(company_id, "SCREENED")
                update_catalyst(company_id, p.get("catalyst_score",0), p.get("catalyst_description",""))
                advance_stage(company_id, "RESEARCHED")
                logger.info(f"Saved {p['ticker']} to pipeline DB")
            else:
                logger.info(f"{p['ticker']} already in pipeline — skipping DB update")
        except Exception as db_err:
            logger.warning(f"DB save error for {p['ticker']}: {db_err}")

        # Send research brief — one clean message per company
        seg = segment_label.get(p.get('segment',''), p.get('segment','?'))
        cat_score = p.get('catalyst_score', 0)

        brief_lines = [
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"🔍 RESEARCH BRIEF",
            f"{p['name']} ({p['ticker']} · {p['exchange']})",
            f"Stage 3 complete  |  {seg}  |  Catalyst {cat_score}/3",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]

        sections = [
            ("catalyst_detail",   "📌 THE CATALYST"),
            ("competitive_edge",  "🥇 WHY AHEAD OF COMPETITORS"),
            ("bear_case",         "⚠️ BEAR CASE"),
            ("competitive_position", "🏆 COMPETITIVE POSITION"),
            ("management_quality",   "👤 MANAGEMENT"),
        ]
        for section_key, label in sections:
            content = brief.get(section_key, "").strip()
            if content:
                brief_lines.append(label)
                # Trim to readable length, end on a full sentence
                trimmed = content[:500]
                if len(content) > 500 and ". " in trimmed:
                    trimmed = trimmed[:trimmed.rfind(". ")+1]
                brief_lines.append(trimmed)
                brief_lines.append("")

        brief_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        brief_lines.append("STAGE 3 COMPLETE — Research brief saved.")
        brief_lines.append("")
        brief_lines.append("Ready for Stage 4+5+7: Full valuation → Risk → Memo.")
        brief_lines.append(f'Reply: Value {p["ticker"]}')
        brief_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        send_both("\n".join(brief_lines))
    else:
        send_both(f"⚠️ Research brief failed for {p['ticker']}: {brief.get('error','unknown error')}")

logger.info("=== TEST SCAN COMPLETE ===")
print("\n✅ Done — check both Telegram channels.")
