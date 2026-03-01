# Tom's Command Center -- Complete Automation Map
## Process Diagram & Data Flow Architecture
**Generated:** 2026-03-01

---

## SYSTEM OVERVIEW

```
                         ┌─────────────────────────────────────┐
                         │        TOM (Telegram App)            │
                         │   Text / Voice / Photos / Commands   │
                         └──────────────┬──────────────────────┘
                                        │
                                        ▼
                    ┌───────────────────────────────────────────┐
                    │          TELEGRAM BOT API                  │
                    │      @TomCommandBot (long-polling)         │
                    └──────────────┬────────────────────────────┘
                                   │
              ┌────────────────────┴─────────────────────┐
              │                                          │
              ▼                                          ▼
    ┌──────────────────┐                      ┌──────────────────┐
    │   SCHEDULER       │                      │   MESSAGE ROUTER  │
    │  (APScheduler)    │                      │  (Telegram Poll)  │
    │  Background Thread│                      │  Main Thread      │
    └────────┬─────────┘                      └────────┬─────────┘
             │                                          │
             │  Cron triggers                           │  chat_id → agent
             ▼                                          ▼
    ┌─────────────────────────────────────────────────────────────┐
    │                      ORCHESTRATOR                           │
    │                                                             │
    │  1. Identify agent from chat_id / schedule                  │
    │  2. Load agent brain (AGENT.md + skills + playbooks + state)│
    │  3. Inject live data (APIs, feeds, cross-agent state)       │
    │  4. Call Claude API (Sonnet or Opus)                        │
    │  5. Extract learning markers from response                  │
    │  6. Update learning DB + state/CONTEXT.md                   │
    │  7. Post response to correct Telegram group                 │
    └─────────────────────────────────────────────────────────────┘
```

---

## DAILY SCHEDULE (NZST)

```
TIME   AGENT          TASK                    DATA SOURCES INJECTED
─────  ─────────────  ──────────────────────  ─────────────────────────────
06:00  Titan          Morning protocol        Training templates
06:00  Atlas          World scan (1 of 4)     16 RSS feeds
07:00  Oracle         Master briefing         ALL agent states + Shopify +
                                              Klaviyo + Meta + Asana + Slack
                                              + Order intelligence + news
07:30  PREP           CEO strategic briefing  ALL agent states + performance
                                              data + order intelligence +
                                              customer DB summary + news
08:00  Lens           AI model scan (1 of 4)  Tech RSS feeds
09:00  Meridian       DBH morning ops         Shopify + Klaviyo + Meta +
                                              Asana + Order intelligence +
                                              customer DB summary
09:00  Venture        New biz morning brief   Tech news feeds
12:00  Atlas          World scan (2 of 4)     16 RSS feeds
14:00  Lens           AI model scan (2 of 4)  Tech RSS feeds
18:00  Atlas          World scan (3 of 4)     16 RSS feeds
20:00  Lens           AI model scan (3 of 4)  Tech RSS feeds
23:00  Meridian       Intelligence sync       Shopify orders → DB (silent)
00:00  Atlas          World scan (4 of 4)     16 RSS feeds
02:00  Lens           AI model scan (4 of 4)  Tech RSS feeds
```

### Weekly Schedule
```
DAY       TIME   AGENT      TASK
────────  ─────  ─────────  ──────────────────────────────
Sunday    08:00  Atlas      Weekly deep dive analysis
Sunday    10:00  Compass    Weekly social plan
Monday    08:00  PREP       Weekly strategic review (7-day data)
Monday    09:00  Meridian   Weekly performance review (7-day data)
Wednesday 12:00  Compass    Midweek social check-in
```

---

## AGENT NETWORK

```
┌───────────────────────────────────────────────────────────────┐
│                     STRATEGIC LAYER                            │
│  ┌─────────┐  ┌──────────┐                                    │
│  │  PREP   │  │  Oracle   │   ← See ALL other agent states    │
│  │  (CEO)  │  │ (Briefing)│   ← Get all data integrations     │
│  │ Opus 4.6│  │ Sonnet4.6 │   ← Cross-domain synthesis        │
│  └────┬────┘  └─────┬─────┘                                   │
│       │              │                                         │
│       └──────┬───────┘  reads state from all agents below      │
│              ▼                                                 │
├───────────────────────────────────────────────────────────────┤
│                     OPERATIONAL LAYER                          │
│                                                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐      │
│  │ Meridian │  │ Venture  │  │  Atlas   │  │   Lens   │      │
│  │ DBH Mktg │  │ New Biz  │  │ Geopolit │  │ AI/Creat │      │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘      │
│                                                                │
├───────────────────────────────────────────────────────────────┤
│                     PERSONAL LAYER                             │
│                                                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                    │
│  │  Titan   │  │ Compass  │  │  Nexus   │                    │
│  │ Health   │  │ Social   │  │ Admin/Cmd│                    │
│  └──────────┘  └──────────┘  └──────────┘                    │
└───────────────────────────────────────────────────────────────┘
```

---

## DATA INTEGRATION MAP

```
                    EXTERNAL APIs
    ┌────────────────────────────────────────┐
    │                                        │
    │  ┌──────────┐  ┌──────────┐           │
    │  │ Shopify  │  │ Klaviyo  │           │
    │  │ Orders   │  │ Campaigns│           │
    │  │ Products │  │ Flows    │           │
    │  └────┬─────┘  └────┬─────┘           │
    │       │              │                 │
    │  ┌────┴──────────────┴────┐           │
    │  │   data_fetcher.py      │           │
    │  │   Performance summary  │           │
    │  └────────────┬───────────┘           │
    │               │                        │
    │  ┌────────────┴───────────┐           │
    │  │ order_intelligence.py  │           │
    │  │ Per-order attribution  │           │
    │  │ + Customer profiling   │           │
    │  │ + Klaviyo cross-ref    │           │
    │  │ + Meta cross-ref       │           │
    │  └────────────┬───────────┘           │
    │               │                        │
    │               ▼                        │
    │  ┌────────────────────────┐           │
    │  │ customer_intelligence  │           │
    │  │        .db             │           │
    │  │ ┌──────────────────┐  │           │
    │  │ │ customers table  │  │           │
    │  │ │ orders table     │  │           │
    │  │ │ insights table   │  │           │
    │  │ └──────────────────┘  │           │
    │  └────────────────────────┘           │
    │                                        │
    │  ┌──────────┐  ┌──────────┐           │
    │  │ Meta Ads │  │  Asana   │           │
    │  │ Spend    │  │  Tasks   │           │
    │  │ ROAS     │  │  Status  │           │
    │  └──────────┘  └──────────┘           │
    │                                        │
    │  ┌──────────┐  ┌──────────┐           │
    │  │  Slack   │  │ 16 RSS   │           │
    │  │ Activity │  │  Feeds   │           │
    │  │ Comps    │  │ News     │           │
    │  └──────────┘  └──────────┘           │
    │                                        │
    │  ┌──────────┐                          │
    │  │ OpenAI   │  Voice transcription     │
    │  │ Whisper  │  (on-demand)             │
    │  └──────────┘                          │
    └────────────────────────────────────────┘
```

---

## LEARNING & INTELLIGENCE LOOP

```
    Agent Response
         │
         ▼
    ┌─────────────────────┐
    │ Extract markers:     │
    │ [INSIGHT: ...]       │
    │ [DECISION: ...]      │
    │ [METRIC: ...]        │
    │ [STATE UPDATE: ...]  │
    └─────────┬───────────┘
              │
              ▼
    ┌─────────────────────────────────────┐
    │         LEARNING DATABASES           │
    │                                      │
    │  intelligence.db                     │
    │  ├── insights (confidence tracking)  │
    │  │   EMERGING → PROVEN (3+ valid)    │
    │  │          → DISPROVEN (2+ contra)  │
    │  ├── cycles (analyse→execute→measure)│
    │  ├── decisions (rationale + outcomes)│
    │  ├── events (timeline)               │
    │  └── metrics (quantitative tracking) │
    │                                      │
    │  customer_intelligence.db            │
    │  ├── customers (LTV, segments, prefs)│
    │  ├── orders (attribution, products)  │
    │  └── insights (periodic summaries)   │
    └─────────┬───────────────────────────┘
              │
              ▼
    ┌─────────────────────────┐
    │ regenerate_context_md() │
    │ Rebuild state/CONTEXT.md│
    │ from database contents  │
    └─────────┬───────────────┘
              │
              ▼
    Next agent call loads
    updated CONTEXT.md
    → Intelligence compounds
```

---

## ATTRIBUTION ENGINE FLOW

```
    Shopify Order Arrives
         │
         ▼
    ┌──────────────────────┐
    │ Parse order metadata  │
    │ • referring_site      │
    │ • landing_site URL    │
    │ • UTM params          │
    │ • discount codes      │
    │ • fbclid / gclid      │
    └─────────┬────────────┘
              │
              ▼
    ┌──────────────────────────────────────────┐
    │         ATTRIBUTION WATERFALL             │
    │                                           │
    │  1. Email/Klaviyo? (utm_source, referrer) │
    │  2. Meta Ads? (fbclid, utm_source=fb/ig)  │
    │  3. Google Ads? (gclid, utm_medium=cpc)   │
    │  4. Google Organic? (google ref, no paid) │
    │  5. Other referral? (has referring site)   │
    │  6. Discount code hint? (code keywords)   │
    │  7. Direct / Unknown (no signals)         │
    │                                           │
    │  Confidence: HIGH / MEDIUM / LOW          │
    └─────────┬─────────────────────────────────┘
              │
         ┌────┴────┐
         ▼         ▼
    ┌─────────┐  ┌──────────────────┐
    │ Klaviyo │  │ Meta Graph API   │
    │ API     │  │ Active campaigns │
    │ Recent  │  │ Spend data       │
    │ sends   │  └────────┬─────────┘
    └────┬────┘           │
         │    Cross-reference
         └────────┬───────┘
                  ▼
    ┌──────────────────────────────┐
    │ Build customer profile       │
    │ • Segment (New→VIP)          │
    │ • LTV + AOV + tenure         │
    │ • Health categories           │
    │ • Purchase history (from DB) │
    │ • Channel history (from DB)  │
    └──────────────┬───────────────┘
                   │
                   ▼
    ┌──────────────────────────────┐
    │ Persist to DB + format for   │
    │ Claude analysis instructions │
    │ → Psychology per customer    │
    │ → Journey stage              │
    │ → Next best action           │
    │ → Loyalty program ideas      │
    │ → Cross-channel insights     │
    └──────────────────────────────┘
```

---

## MESSAGE HANDLING FLOWS

```
TEXT MESSAGE:
  Tom types in Telegram group
  → Orchestrator identifies agent from chat_id
  → Loads full brain stack
  → Calls Claude Sonnet (or Opus for PREP)
  → Learning loop extracts insights
  → Posts response to same group

VOICE MESSAGE:
  Tom sends voice note
  → Download OGG from Telegram API
  → Send to OpenAI Whisper → transcript
  → Prefix "[Voice message]"
  → Route as text message (same flow above)

PHOTO/SCREENSHOT:
  Tom sends image
  → Download highest-res version
  → Encode to base64
  → Call Claude Vision API with agent brain
  → Same response + learning flow

COMMANDS (Nexus channel):
  "status"     → Show all agent states + last activity
  "db stats"   → Learning database statistics
  "test feeds" → Diagnostic test of ALL integrations
  "run {agent}"→ Trigger agent's morning brief immediately
```

---

## ENVIRONMENT VARIABLES

| Variable | Service | Used By |
|----------|---------|---------|
| ANTHROPIC_API_KEY | Claude API | All agents |
| TELEGRAM_BOT_TOKEN | Telegram Bot | Orchestrator |
| TELEGRAM_OWNER_ID | Telegram Auth | Security |
| OPENAI_API_KEY | Whisper | Voice transcription |
| SHOPIFY_STORE_URL | Shopify | Meridian, Oracle, PREP |
| SHOPIFY_ACCESS_TOKEN | Shopify | Meridian, Oracle, PREP |
| KLAVIYO_API_KEY | Klaviyo | Meridian, Oracle, PREP |
| META_ACCESS_TOKEN | Meta Ads | Meridian, Oracle, PREP |
| META_AD_ACCOUNT_ID | Meta Ads | Meridian, Oracle, PREP |
| ASANA_ACCESS_TOKEN | Asana | Oracle, Meridian |
| ASANA_PROJECT_ID | Asana | Oracle, Meridian |
| ASANA_WORKSPACE_ID | Asana | Oracle, Meridian |
| SLACK_BOT_TOKEN | Slack | Oracle, Meridian |
| SLACK_CHANNEL_IDS | Slack | Oracle, Meridian |

---

## CURRENT AUTOMATION COUNT

| Category | Count |
|----------|-------|
| Scheduled daily tasks | 9 (+ 4x Atlas + 4x Lens = 17 total runs/day) |
| Scheduled weekly tasks | 5 |
| Data integrations | 8 (Shopify, Klaviyo, Meta, Asana, Slack, RSS, Whisper, Claude) |
| Active agents | 9 |
| Database tables | 12 across 3 databases |
| RSS feeds | 16 |
| Total daily API calls | ~30-40 (Claude + data sources + Telegram) |
