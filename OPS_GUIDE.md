# OPS GUIDE -- Tom's Command Center
**Last updated: March 2, 2026**

Your system is live. 9 agents, 14 scheduled tasks, 4 databases, and a learning loop that gets smarter every day. This is how to use it all.

---

## YOUR DAILY RHYTHM

Everything runs on NZST. You don't trigger any of this -- it fires automatically.

| Time | What Happens | Where to Check |
|------|-------------|----------------|
| 6:00am | **Titan** delivers training + meal plan | `health-fitness` channel |
| 6:00am | **Atlas** world scan #1 (also 12pm, 6pm, midnight) | `global-events` channel |
| 7:00am | **Oracle** master briefing -- revenue, tasks, macro, cross-domain connections | `daily-briefing` channel |
| 7:30am | **PREP** strategic briefing -- sees ALL agent states, challenges your priorities | `strategic-advisor` channel |
| 8:00am | **Lens** AI model scan #1 (also 2pm, 8pm, 2am) | `creative-projects` channel |
| 9:00am | **Meridian** DBH morning ops brief -- yesterday's numbers, today's actions | `dbh-marketing` channel |
| 9:00am | **Venture** new business morning brief | `new-business` channel |
| 10:00pm | **Replenishment scan** -- fires Klaviyo reorder events for customers due to restock | `dbh-marketing` channel (status message) |
| 11:00pm | **Intelligence sync** -- today's orders persisted to customer DB | `dbh-marketing` channel (status message) |

**Weekly extras:**
- **Sunday 8am** -- Atlas weekly deep dive (picks the biggest developing story)
- **Sunday 10am** -- Compass weekly social plan
- **Monday 8am** -- PREP weekly strategic review
- **Monday 9am** -- Meridian weekly performance review (full 7-day data)
- **Wednesday 12pm** -- Compass mid-week social check-in

**Your morning routine:** Wake up. Check `daily-briefing` (Oracle). Check `strategic-advisor` (PREP). Those two messages give you the complete picture. Then skim `dbh-marketing` (Meridian) if you want the tactical detail.

---

## YOUR 9 AGENTS -- WHAT TO ASK EACH ONE

### Oracle (daily-briefing)
**The full picture.** Reads every other agent's state, pulls Shopify/Klaviyo/Meta data, cross-references Asana tasks. Delivers a Presidential Daily Brief style morning summary.

Ask it:
- "What drove yesterday's sales?"
- "Are we on track for the 90-day plan?"
- "What's overdue in Asana?"

### PREP (strategic-advisor)
**Your CEO brain.** Runs on Opus (the best model). Sees ALL agent states plus live performance data every time you talk to it. Knows your full life story, your patterns, your financial position. Will challenge you when you're off track.

Ask it:
- "I'm thinking about launching X. Pressure test this."
- "Should I increase Meta spend or shift budget to email?"
- "I'm spiralling on too many projects. What do I cut?"
- "Run the numbers on [any financial decision]."
- See the dedicated PREP section below.

### Meridian (dbh-marketing)
**DBH marketing ops.** Loaded with all playbooks, the 3 proven formulas (Trust+Social Proof = 7.78x ROAS, Exclusivity+Scarcity = 8.45x ROAS, Gift Psychology = 77.1% open rate), and current campaign data.

Ask it:
- "Draft an email for [product] using Trust+Social Proof formula"
- "What's our best-performing Meta creative this week?"
- "Write copy for a GLM retargeting ad -- supplement compliance"
- "Which customers are due for reorder this week?"
- Send it a screenshot of Klaviyo stats for instant analysis

### Atlas (global-events)
**Geopolitical radar.** Scans 16 RSS feeds every 6 hours. Monitors NZD, shipping routes, trade policy, health regulation, and anything that could affect DBH.

Ask it:
- "What's happening with NZ supplement regulations?"
- "Any tariff changes affecting our supply chain?"
- "Summarise the biggest global risk to DBH right now"

### Venture (new-business)
**Opportunity scanner.** Tracks tech/startup landscape, potential new business models, emerging trends.

Ask it:
- "What's the latest on blood testing DTC models?"
- "Any AI health startups worth watching?"
- "Evaluate this business idea: [pitch]"

### Titan (health-fitness)
**Your personal trainer.** Delivers training and meal plans daily at 6am.

Ask it:
- "I only have 30 minutes today. Adjust."
- "Meal prep plan for the next 3 days"
- "I'm feeling run down -- adjust training intensity"

### Compass (social)
**Social life manager.** Tracks your network, plans social activities, flags overdue catch-ups.

Ask it:
- "When did I last see [person]?"
- "Plan something for this weekend"
- "Who should I be connecting with more?"

### Lens (creative-projects)
**AI model radar.** Scans for new AI model releases every 6 hours, especially video generation models that could handle action sequences.

Ask it:
- "What new video AI models launched this week?"
- "Compare Sora vs Runway vs Kling for [use case]"
- "Any models that can handle fight choreography yet?"

### Nexus (command-center)
**System admin.** Special commands only -- not a conversational agent.

Commands you can send:
- `status` -- shows all agent states and learning DB stats
- `run dbh-marketing` -- manually triggers any agent's morning brief
- `db stats` -- shows learning database row counts
- `test feeds` -- diagnostic: tests every data feed connection (Shopify, Klaviyo, Meta, Asana, Slack, RSS, Order Intelligence)

---

## WHAT'S NEW (March 2026 Build)

Everything below was built in the last session. Here is what each piece does.

**Customer Intelligence DB** -- Every night at 11pm, all Shopify orders are fetched and persisted to `data/customer_intelligence.db`. Tracks per-customer purchase history, product preferences, order frequency, LTV trajectory, and channel attribution. This data is injected into Oracle, Meridian, and PREP briefings automatically. The DB gets richer every single day.

**Replenishment Tracker** -- Fires at 10pm daily. Scans the customer DB, calculates when each customer's supply runs out (based on product-specific consumption rates -- GLM 18000 = 60 days, Collagen = 30 days, etc.), and fires `replenishment_due` events to Klaviyo for customers approaching reorder time. You need a Klaviyo flow triggered by this custom event to complete the loop.

**Cross-Agent Event Bus** -- SQLite-backed pub/sub at `data/event_bus.db`. When Meridian detects a ROAS drop, it publishes `campaign.performance_drop`. PREP and Lens automatically receive that event in their next prompt. Events auto-expire after 48 hours. Subscriptions are pattern-matched (e.g., Meridian subscribes to `campaign.*`, `customer.*`, `inventory.*`).

**Decision Logger** -- Separate DB at `data/decisions.db`. Tracks structured decisions with type (strategy/tactical/operational/creative/financial), reasoning chains, confidence scores, and domain tags. Detects contradictions when a new decision reverses a recent one. Recent decisions are injected into every agent prompt so they remember what was already decided.

**Exception Router** -- The autonomous immune system at `data/exceptions.db`. Detects problems (low stock, ROAS drops, budget overspend, churn risk) and runs auto-resolution playbooks before escalating to you. Each exception tracks: detection, auto-resolution attempts, escalation criteria, and resolution deadline. Open exceptions are injected into morning briefings with forced resolution recommendations.

**Design Pipeline** -- End-to-end creative production from insight to live ad. Tracks brief creation, designer assignment (Roie or AI tools like Pencil/Creatify/Flair), design stages, and connects performance back to the original brief for learning. Pipeline status is injected into Meridian and PREP briefings.

**Notification Router** -- Severity-based message delivery (built, not yet wired to replace direct sends). Four levels: CRITICAL (bypasses 10pm-6am DND), IMPORTANT (normal), NOTABLE (silent), INFO (batched hourly). Queue is SQLite-backed so nothing is lost on restart.

**Write-Back Clients** -- Five API clients built and ready:
- `shopify_writer.py` -- Tag customers, add order notes, adjust inventory, create discount codes
- `klaviyo_writer.py` -- Update profiles, manage lists, fire custom events, trigger flows
- `meta_ads_writer.py` -- Pause/resume campaigns, adjust budgets, manage audiences
- `asana_writer.py` -- Create tasks from agent markers, with auto-priority and due dates
- `xero_client.py` -- OAuth 2.0 auth, P&L reports, invoice creation

---

## HOW THE LEARNING LOOP WORKS

This is the core of why the system gets smarter over time.

1. **Agent responds** to a scheduled task or your message
2. **Orchestrator scans** the response for structured markers (see below)
3. **Markers are extracted** and stored in the appropriate database (learning.db, decisions.db, event_bus.db)
4. **Markers are stripped** from the response before it hits your Telegram
5. **Next time that agent wakes up**, the orchestrator injects recent insights, decisions, and events back into its prompt
6. **The agent sees what it (and others) learned** and builds on it

The databases accumulate. Day 1 has minimal context. Day 30 has patterns. Day 90 has proven playbooks. You never have to do anything -- just use the system and it learns.

The interaction itself is also logged: which agent, what triggered it (scheduled/message/photo), input summary, output summary. This builds a complete audit trail.

---

## MARKERS YOUR AGENTS USE

Agents embed these in their responses. The orchestrator intercepts them before you see the message.

| Marker | Stored In | What It Does |
|--------|-----------|-------------|
| `[INSIGHT: category\|content\|evidence]` | learning.db | Captures observations. Promoted from EMERGING to PROVEN over time. |
| `[METRIC: name\|value\|context]` | learning.db | Tracks numerical data points for trend analysis. |
| `[DECISION: type\|title\|reasoning\|confidence]` | decisions.db | Logs structured decisions with reasoning chains. Types: strategy, tactical, operational, creative, financial. Confidence: 0.0-1.0. |
| `[VERIFY: decision_id\|positive/negative\|outcome]` | decisions.db | Confirms or denies past decisions. Closes the feedback loop. |
| `[EVENT: type\|SEVERITY\|payload]` | event_bus.db | Publishes cross-agent events. Other subscribed agents receive it on next wake-up. |
| `[TASK: title\|priority\|description]` | Asana (via API) | Auto-creates Asana tasks. Priority maps to due date: urgent=1d, high=3d, medium=7d, low=14d. |
| `[STATE UPDATE: info]` | agent's state/CONTEXT.md | Persists new information to the agent's state file for future sessions. |

Severity levels for events: CRITICAL, IMPORTANT, NOTABLE, INFO.

---

## WHAT'S WIRED vs WHAT'S WAITING

### Fully Wired and Running
- All 9 agents with full brain loading (AGENT.md + training + skills + playbooks + intelligence + state)
- 14 scheduled tasks across all agents (daily + weekly)
- Learning loop: insight/metric/decision extraction from every response
- Customer intelligence DB: auto-accumulates nightly at 11pm
- Replenishment tracker: fires Klaviyo events at 10pm daily
- Cross-agent event bus: agents publish and receive events automatically
- Decision logger: tracks reasoning chains, injects into agent prompts
- Exception router: detects and auto-resolves, injected into briefings
- Design pipeline: status injected into briefings
- Asana auto-task creation from [TASK:] markers
- Voice message transcription (Whisper)
- Photo/image analysis (Claude Vision)
- Live data injection: Shopify, Klaviyo, Meta, RSS, Asana, Slack, order intelligence

### Built But Not Yet Wired
- **Notification router** -- Built and tested. Needs to replace direct `send_telegram()` calls in the orchestrator. Once wired: CRITICAL messages bypass DND, INFO messages get batched hourly.
- **Write-back clients (Shopify, Klaviyo, Meta, Asana, Xero)** -- The API clients exist and are fully coded. But agents currently advise you to take action; they don't take action themselves. Wiring these means agents could auto-tag customers, auto-pause low-ROAS ads, auto-trigger Klaviyo flows. Each has clear guardrails: safe operations (tagging, notes) run autonomously; risky operations (spending money, creating discounts) require your approval.
- **Xero OAuth** -- Client is built but needs a one-time manual OAuth flow to authenticate.
- **Thought leader scraper** -- Planned, not yet built. Would auto-scrape AI thought leaders and inject summaries into relevant agents.

---

## QUICK WINS -- THINGS TO TRY TODAY

1. **Send `test feeds` to Nexus.** See which data connections are live. Fix any that show `[FAIL]` or `[--]`.

2. **Send `status` to Nexus.** See all agent states, last update times, and learning DB stats.

3. **Ask PREP a strategic question.** Try: "Given DBH's current performance, what's the single highest-leverage thing I should do this week?" It will pull live data from all agents.

4. **Send Meridian a screenshot.** Take a screenshot of your Klaviyo dashboard or Meta Ads Manager and send it to the `dbh-marketing` channel. It will analyse it against your playbook benchmarks.

5. **Ask Meridian for a campaign draft.** Try: "Draft a reorder email for GLM customers using Trust+Social Proof formula. Subject line, preview text, body copy."

6. **Voice message any agent.** Talk to PREP, Oracle, or Meridian via voice note. It transcribes with Whisper and responds.

7. **Ask Oracle to explain attribution.** Send: "Break down yesterday's revenue by channel. What actually drove each sale?"

8. **Send `db stats` to Nexus.** Check how many insights, decisions, metrics, and patterns have accumulated. Watch this number grow daily.

9. **Ask PREP to run the numbers.** Try: "What's my monthly burn rate vs revenue? How many months of runway do I have? What revenue target do I need to hit by June?"

10. **Trigger a manual briefing.** Send `run global-events` to Nexus to get a fresh world scan right now.

---

## MAXIMISING PREP (CEO Agent)

PREP is your most powerful agent. It runs on Opus (not Sonnet like the others). Every time you message it, it loads ALL agent states plus live Shopify/Klaviyo/Meta data. It knows your full history -- bitcoin at 17, ZURU, Vietnam, Junction AI, DBH, the overspend on Alternate.

**How to get the most from PREP:**

**Strategic decisions:** Don't ask "what should I do?" -- give it the decision and ask it to pressure test. "I want to invest $5K in Meta ads for Pure Pets launch. Challenge this." It will run the numbers and tell you if you're being delusional or smart.

**Cross-domain synthesis:** PREP sees things no single agent can. Ask: "Atlas flagged a tariff change on supplements from China. How does this affect our GLM supply chain pricing and what should I do about it?" It connects the macro to the micro.

**Financial discipline:** PREP has standing orders to be your CFO first, CEO second. It will flag overspending unprompted. Lean into this: "Review my last month of spending decisions. Where was I disciplined and where was I reckless?"

**Pattern interruption:** PREP knows your tendencies -- shiny object syndrome, grand vision without execution, all-or-nothing thinking. When you're excited about something new, run it through PREP first. It will tell you if this is a real opportunity or another Junction AI.

**Decision verification:** After you make a big call, tell PREP. It logs the decision with reasoning. A week later, ask: "How did my decision to [X] play out? Was the reasoning sound?" This is how you build a track record of calibrated judgment.

**Weekly review ritual:** Every Monday morning, after reading Oracle and PREP's scheduled briefings, send PREP: "Reflecting on last week -- what worked, what didn't, what should I do differently this week?" This is your most valuable 5 minutes.

**What NOT to do with PREP:** Don't use it for quick tactical tasks (use Meridian for marketing ops, Atlas for news). PREP's strength is connecting dots across domains and challenging your thinking. Every message costs more (Opus) -- use it for things that matter.
