# SCOUT Setup — Final Wiring Steps

**Status:** Agent files created. Configuration integration in progress.

## What's Done ✅
- AGENT.md (identity, personality, scheduled tasks)
- knowledge.md (top 100 creators list, scraping strategy)
- state/CONTEXT.md (ideas database schema)
- core/scout_scraper.py (scraper framework)
- state/IDEAS_DATABASE.md (populated with Liam Otley ideas)

## What's Needed — User Action ⚠️

### Step 1: Create Telegram Group
1. Create new Telegram group: "🔍 SCOUT — Ecosystem Ideas"
2. Add @TomCommandBot to the group
3. Copy the group chat ID (e.g., `-5123456789`)

### Step 2: Add to Configs
Once you have the chat ID, add SCOUT to:

**config/telegram.json** — Add to `chat_ids`:
```
"scout": "[YOUR_CHAT_ID]"
```

And to `agent_names`:
```
"scout": "Scout"
```

**config/schedules.json** — Already added:
```
{
  "agent": "scout",
  "task": "daily_scan",
  "cron": "0 5 * * *",
  "description": "SCOUT ecosystem ideas scan (5am daily)"
}
```

**core/orchestrator.py** — Already added to AGENT_DISPLAY:
```
"scout": "Scout"
```

### Step 3: Deploy
Once configs are updated:
```
git add .
git commit -m "Wire SCOUT ecosystem agent into system"
git push origin main
# Railway auto-deploys
```

## What SCOUT Does (Daily 5am)
1. Scrapes top 100 AI creators across platforms
2. Extracts novel ideas
3. Scores by applicability/effort/ROI
4. Detects patterns (trending ideas)
5. Posts findings to SCOUT Telegram channel
6. Updates IDEAS_DATABASE.md
7. Recommends top 3 implementations for the week

## First Run Expected Ideas
Liam Otley's 5 ideas already in database:
- Data Audit Framework
- Model Finder + Registry
- Implementation Runner
- Whisper Flow
- AI Engineering Pipeline

SCOUT will continue scanning daily and adding new creator ideas.
