# THE OPERATOR'S GUIDE
## How to Run, Feed, and Improve Your AI Operating System
**For:** Tom Hall-Taylor
**System:** Tom's Command Center (11 agents, 27 cron tasks, 37 modules)
**Updated:** March 3, 2026

---

## WHY THIS GUIDE EXISTS

You built a machine that runs 27 automated tasks per day. It reads data, makes decisions, writes to platforms, and talks to you through Telegram. But a machine is only as good as the operator running it.

This guide teaches you:
- How your agents actually remember things (and where the gaps are)
- How to give feedback that sticks
- How to keep the system sharp over time
- What to do every day, week, and month
- How to spot when something's going wrong

Read this once. Reference it when you need to. The system compounds -- but only if you do your part.

---

## MODULE 1: HOW AGENT MEMORY WORKS

### The Brain Stack (What Agents Read Before Every Response)

Every time an agent responds -- scheduled task or your message -- it loads its "brain" in this order:

```
1. AGENT.md          -- Who am I? What are my rules?
2. knowledge.md      -- What have I learned about Tom over time?
3. yesterday's log   -- Quick summary of yesterday's interactions
4. training/*.md     -- Deep domain knowledge, mental models
5. playbooks/*.md    -- PROVEN patterns with real DBH data
6. skills/*.md       -- General best practices
7. intelligence/*.md -- Latest research (newest first)
8. CONTEXT.md        -- What's happening RIGHT NOW
9. shared/strategy/  -- 90-day execution plan (PREP, Oracle, Meridian, Beacon only)
10. pending events   -- Cross-agent events waiting to be consumed
```

**Priority rule:** If a playbook says "X works" and a skill says "Y works", the playbook wins. Playbooks are PROVEN with your data. Skills are general knowledge.

### The Three Memory Systems

**1. CONTEXT.md (Short-Term Memory)**

Location: `agents/{agent-name}/state/CONTEXT.md`

This is the agent's "working memory". It has two zones:
- **FOUNDATION** (top section) -- manually written by you or Claude Code. Contains the agent's current understanding of the world. Things like revenue baselines, current goals, key preferences, active campaigns.
- **LIVE UPDATES** (bottom section, after `## LIVE UPDATES`) -- automatically populated from `[STATE UPDATE:]` markers in agent responses. Rolling window of the last 20 updates. Old ones drop off.

**What this means for you:**
- The FOUNDATION section is yours to maintain. When reality changes (new campaign launched, revenue shifted, goal updated), update the foundation.
- The LIVE UPDATES section manages itself. Agents append here automatically after every meaningful conversation.
- If CONTEXT.md gets stale, the agent operates on old assumptions.

**2. intelligence.db (Long-Term Memory)**

Location: `data/intelligence.db`

This is the structured learning database. Stores:
- **Insights** with confidence levels (EMERGING -> PROVEN -> DISPROVEN)
- **Events** from cross-agent communication
- **Metrics** tracked over time
- **ROAS data** from nightly verification
- **Citation checks** from Perplexity monitoring
- **Auto-optimizer actions** with undo capability

**What this means for you:**
- This database accumulates automatically. You don't touch it directly.
- Over time, it gets smarter. Insights that prove true 3+ times become PROVEN.
- Insights that fail twice become DISPROVEN.
- When an agent says something with confidence, it's because the database backs it up.

**3. event_bus.db (Cross-Agent Communication)**

Location: `data/event_bus.db`

When one agent discovers something another agent should know, it emits an event. Example: Meridian detects a campaign performing badly -> publishes `campaign.performance_drop` -> Oracle picks it up in the morning briefing.

**What this means for you:**
- You don't manage this. It's fully automatic.
- If you notice agents aren't coordinating, check if the right agent is subscribed to the right event patterns.
- Default subscriptions: PREP and Oracle see everything. Meridian sees campaign/customer/inventory events.

---

## MODULE 2: HOW TO GIVE FEEDBACK THAT STICKS

### Rule #1: Reply in the Right Channel

Every agent has its own Telegram channel. Reply in the channel where you saw the message.

- Got a bad morning brief from Meridian? Reply in **dbh-marketing**.
- PREP gave bad strategic advice? Reply in **strategic-advisor**.
- Auto-optimizer made a bad decision? Reply in **command-center** with `undo <id>`.

The agent receives your message with its full brain loaded. It will process your feedback, update its state, and adjust.

### Rule #2: Be Specific About What's Wrong

Bad: "That was wrong"
Good: "The revenue number you quoted was $34K but Shopify shows $41K. Always use Shopify as source of truth for revenue."

Bad: "Don't do that again"
Good: "Never suggest discounting Marine Collagen below $49. Our margin doesn't support it."

Why: Specific feedback becomes a `[STATE UPDATE:]` that persists. Vague feedback gets lost.

### Rule #3: Tell the Agent to Remember

If something is important enough to persist, say so explicitly:

"Remember this: Tom's workout time is ALWAYS after 7:30pm. Never suggest morning workouts."

"Save this permanently: Sea Cucumber is our #1 product by revenue, not GLM."

"Update your context: We launched the Pure Pets campaign on March 15 at $20/day."

The agent will emit a `[STATE UPDATE:]` marker, which gets stored in CONTEXT.md and intelligence.db.

### Rule #4: Correct the Foundation When Reality Shifts

The FOUNDATION section of CONTEXT.md doesn't update itself. When big things change, you have two options:

**Option A: Tell the agent directly in Telegram**
"Update your foundation: our monthly revenue baseline is now $50K not $40K. Repeat customer rate is 22%."

**Option B: Edit CONTEXT.md directly via Claude Code**
Open a Claude Code session and edit `agents/{agent}/state/CONTEXT.md`. Change the FOUNDATION section. Next time the agent wakes, it reads the new version.

**When to do this:**
- Revenue baseline shifts significantly
- New campaign launches
- Team changes (new designer, lost a channel)
- Strategy pivots (new product focus, new market)
- Personal changes that affect agents (new workout schedule, new social goals)

### Rule #5: Use Nexus for System-Wide Commands

The command-center channel (Nexus) is your admin panel:

- `status` -- See all agent health
- `integrations` -- Check which APIs are connected
- `run dbh-marketing` -- Force Meridian to run its morning brief NOW
- `run evening-reading` -- Force ASI to deliver tonight's reading
- `briefs` -- See all auto-generated design briefs
- `undo 15` -- Undo auto-optimizer action #15
- `citations` -- Check if DBH is showing up in AI answers

---

## MODULE 3: YOUR DAILY ROUTINE

### Morning (5 minutes)

1. **Check Telegram** -- you'll have messages from Oracle (7am), PREP (7:30am), and Meridian (9am)
2. **Scan the Oracle brief first** -- this is the cross-domain summary. It tells you what matters today.
3. **Check Meridian's brief** -- this has the numbers. Revenue, ROAS, email performance, Asana tasks.
4. **Reply to anything that needs correction** -- if a number is wrong, a priority is off, or an opportunity was missed, reply in that channel.
5. **Check Asana** -- auto-created tasks from the rule engine will be there. Action or dismiss.

### During the Day (as needed)

- **If you have a creative idea or campaign thought**, message Meridian. If the insight is strong enough, the system auto-generates a design brief for Roie.
- **If you need strategic analysis**, message PREP. It uses Opus and has full context.
- **If you want a reading or life perspective**, message ASI.
- **If you want to check on the world**, message Atlas.

### Evening (2 minutes)

1. **8:30pm: ASI delivers your evening reading.** This is a deep-thought piece from your knowledge engine (120+ concepts across philosophy, psychology, strategy, science, creativity). Read it. Respond if it sparks something. ASI learns what resonates.
2. **The overnight chain fires automatically.** By morning, you'll have fresh data, new articles, updated ROAS, and customer intelligence.

### Monday (30-60 minutes)

1. **Tony report arrives at 7am.** Check ~/dbh-aios/reports/tony-reports/
2. **Review the report.** Edit anything that needs adjusting. The data is real (pulled from Shopify, Meta, Klaviyo) but the narrative may need your touch.
3. **Email to Tony.** Copy-paste or attach.
4. **Review Meridian's weekly review** (9am). This has week-over-week trends.
5. **Make scale/hold/kill decisions** on Meta campaigns based on verified ROAS.
6. **Check auto-optimizer actions** from the past week. Undo anything you disagree with.

---

## MODULE 4: HOW TO KEEP THE SYSTEM SHARP

### Weekly: Review Beacon's SEO Output

Beacon generates one article per night. They pile up in:
- Shopify admin -> Blog posts (as drafts)
- ~/dbh-aios/reports/seo-articles/ (as markdown files)

**Your job:**
1. Open Shopify admin, go to Blog Posts
2. Review the last 7 drafts
3. Publish the good ones (aim for 5-7 per week)
4. Delete the weak ones
5. If Beacon keeps generating bad content for a specific topic, message Nexus or update Beacon's CONTEXT.md with guidance

### Weekly: Spot-Check Agent Intelligence

Pick one agent per week. Read its CONTEXT.md. Ask yourself:
- Is the FOUNDATION still accurate?
- Are the LIVE UPDATES making sense?
- Is the agent learning or just repeating?

If it's stale, update the foundation section.

### Monthly: Playbook Update Ritual

At the end of each month, run this with Claude Code:

1. Pull 30 days of campaign performance data
2. Read current playbook versions (~/dbh-aios/playbooks/)
3. Identify: new patterns emerged, beliefs confirmed, beliefs disproven
4. Update playbook sections with new evidence
5. Write CHANGELOG entry with date and data source

Rules:
- Never delete disproven hypotheses -- they prevent repeating mistakes
- Every claim must reference a specific campaign with real numbers
- Move EMERGING -> PROVEN only when validated 3+ times
- Move EMERGING -> DISPROVEN if test fails twice

### Monthly: Strategy Brief Update

When the 90-day plan evolves (campaign launched, revenue milestone hit, pivot made):

1. Open `agents/shared/strategy/90-day-brief.md`
2. Update the relevant section
3. Save. Done. All four strategic agents (PREP, Oracle, Meridian, Beacon) see it immediately.

---

## MODULE 5: UNDERSTANDING THE INTELLIGENCE PIPELINE

### How Data Flows Through the System

```
SHOPIFY/KLAVIYO/META/GOOGLE ADS (raw data)
        |
        v
DATA_FETCHER.PY (pulls and formats)
        |
        v
ORCHESTRATOR.PY (injects into agent prompts)
        |
        v
CLAUDE API (agent generates response with full brain)
        |
        v
PROCESS_RESPONSE_LEARNING (extracts markers from response)
        |
        |---> [STATE UPDATE:] -> CONTEXT.md (rolling 20 updates)
        |                     -> intelligence.db (long-term)
        |
        |---> [EVENT:] -> event_bus.db -> consumed by other agents
        |
        |---> [INSIGHT:] -> learning.db + intelligence.db
        |
        |---> [TASK:] -> Asana task auto-created
        |
        |---> [BRIEF:] -> brief_generator -> briefs.db + Asana task for Roie
        |
        v
TELEGRAM (cleaned response sent to you)
```

### How Agents Learn Over Time

1. Agent processes data and generates response
2. Orchestrator extracts structured markers from response
3. Insights stored with EMERGING confidence
4. Next time agent sees similar data, it references stored insight
5. If the insight holds, it gets validated (confidence increases)
6. After 3+ validations, insight becomes PROVEN
7. Proven insights get referenced in playbook updates
8. Playbooks are loaded before every response
9. The system gets smarter every cycle

### How Cross-Agent Events Work

Example flow:
1. Meridian's morning brief detects ROAS dropping on GLM campaign
2. Meridian emits: `[EVENT: campaign.performance_drop|IMPORTANT|GLM ROAS dropped to 1.8x]`
3. Event published to event_bus.db
4. Oracle's next briefing picks it up via subscription
5. Oracle mentions it in the master briefing: "Meridian flagged GLM ROAS decline"
6. PREP also sees it (subscribed to all events) and factors it into strategic advice
7. Creative-Projects (Lens) sees it and may flag if new creative is needed

---

## MODULE 6: WHEN THINGS GO WRONG

### Agent Gives Stale Information

**Symptom:** Meridian quotes last month's numbers. Oracle doesn't know about a campaign you launched yesterday.

**Fix:** The agent's CONTEXT.md is outdated. Message the agent directly: "Update your context: [what changed]." Or edit CONTEXT.md in Claude Code.

### Agent Contradicts Itself

**Symptom:** Meridian recommends discounting on Monday, then says discounting is disproven on Wednesday.

**Fix:** Check the playbook. If the playbook says discounting is disproven, the agent should follow it. If the contradiction is between the playbook and fresh data, it's time for a playbook update. The new data might be revealing a context-dependent truth (e.g., discounting works for new customers but not VIPs).

### Auto-Optimizer Makes a Bad Decision

**Symptom:** Budget was scaled up on a campaign you know is about to fatigue.

**Fix:**
1. Go to command-center Telegram channel
2. Type: `undo <action_id>` (the notification included the ID)
3. Message Meridian: "Don't scale [campaign name] -- creative is fatiguing. Hold until new creative is ready."
4. The system stores this as a state update

### ROAS Tracker Flags a False Positive

**Symptom:** Campaign auto-paused but you know the ROAS dip was temporary (e.g., weekend dip on a weekday-focused product).

**Fix:**
1. Resume the campaign manually in Meta Ads Manager
2. Message Meridian: "GLM campaign ROAS dipped due to weekend. Resume it. Don't auto-pause on weekend-only dips."
3. Consider updating the rule: currently pauses after 3 consecutive days below 2x. If weekends consistently cause dips, we can exclude weekends from the count.

### Agent Doesn't Respond

**Symptom:** You message an agent and get nothing back.

**Fix:**
1. Check Nexus: `status` -- see if the system is running
2. Check Nexus: `integrations` -- see if APIs are connected
3. Check Railway logs for errors
4. If it's a brain loading failure, you'll get a specific error message. Check that the agent's AGENT.md exists.

### Tony Report Has Wrong Numbers

**Symptom:** Revenue figure in the Tony report doesn't match Shopify.

**Fix:**
1. DON'T send it to Tony yet
2. Check Shopify admin for the real number
3. Edit the report file manually: ~/dbh-aios/reports/tony-reports/tony-report-latest.md
4. Message PREP: "Tony report had revenue wrong. Shopify shows $X not $Y. Make sure you're using the injected data, not estimating."
5. Send the corrected version

---

## MODULE 7: THE AGENT ROSTER

### Who to Talk To When

**"I need today's DBH numbers"** -> Meridian (dbh-marketing)
**"What should we do about X strategic issue?"** -> PREP (strategic-advisor)
**"What's happening in the world?"** -> Atlas (global-events)
**"Did any AI models drop?"** -> Lens (creative-projects)
**"What should I train today?"** -> Titan (health-fitness)
**"Who should I catch up with?"** -> Compass (social)
**"I want a deep thought or lesson"** -> ASI (evening-reading)
**"System command or status check"** -> Nexus (command-center)
**"New business opportunity analysis"** -> Venture (new-business)

### Agents That Write to External Systems

- **Meridian** -> triggers Meta budget changes, Klaviyo events, Shopify tags, Asana tasks
- **Beacon** -> writes Shopify blog drafts
- **Auto-optimizer** -> adjusts Meta budgets, selects A/B winners, drafts Klaviyo campaigns
- **Rule engine** -> creates Asana tasks
- **Brief generator** -> creates briefs in briefs.db + Asana tasks for Roie

### Agents That Only Read and Advise

- Atlas, Lens, Venture, Titan, Compass, ASI, Oracle -- these agents read data and give you intelligence. They don't write to any external system. They influence decisions through events and recommendations.

---

## MODULE 8: MAINTAINING QUALITY OVER TIME

### The Three Things That Decay

1. **CONTEXT.md foundations** -- reality shifts faster than files get updated
2. **Playbooks** -- patterns that were PROVEN last quarter may not work this quarter
3. **Strategy brief** -- the 90-day plan is a living document, not a static one

### Your Quality Maintenance Schedule

**Daily (2 min):** Scan briefings. Correct any wrong facts by replying.

**Weekly (15 min):** Pick one agent. Read its CONTEXT.md. Ask: "Is this still true?" Update if not.

**Fortnightly (30 min):** Review Beacon output. Publish good articles. Note topics that need improvement.

**Monthly (2 hrs with Claude Code):**
1. Playbook update ritual (pull data, update PROVEN/EMERGING/DISPROVEN)
2. Strategy brief update (90-day-brief.md)
3. Check learning DB stats: `db stats` in Nexus
4. Review auto-optimizer action history
5. Update CONTEXT.md foundations for key agents (Meridian, PREP, Beacon)

**Quarterly (half day with Claude Code):**
1. Full playbook review -- are formulas still working?
2. Agent roster review -- do we need new agents? Are any redundant?
3. Skill file updates -- has the platform landscape changed?
4. CPA:LTV deep dive -- is customer quality improving?
5. Review intelligence.db insights -- which EMERGING insights should be promoted?

---

## MODULE 9: HOW TO ADD NEW KNOWLEDGE

### Adding a New Skill to an Agent

1. Write the skill as a markdown file
2. Save to `agents/{agent}/skills/new-skill.md`
3. Next time the agent wakes, it reads the new skill automatically

### Adding a New Playbook

1. Write the playbook with PROVEN/EMERGING/DISPROVEN sections
2. Save to `agents/{agent}/playbooks/new-playbook.md`
3. Every claim must reference specific campaign data

### Updating the Strategy

1. Edit `agents/shared/strategy/90-day-brief.md`
2. All four strategic agents see it immediately

### Adding a New Agent

1. Create folder: `agents/new-agent/`
2. Create AGENT.md (identity + instructions)
3. Add skills/ and playbooks/ folders
4. Create state/CONTEXT.md with initial state
5. Create Telegram group chat, add bot, note chat ID
6. Add to config/telegram.json
7. Add schedule to config/schedules.json
8. Restart orchestrator on Railway

---

## MODULE 10: THE PHILOSOPHY

### Why This Works

Traditional business: hire people -> manage people -> people manage processes -> processes produce results.

Your model: build intelligence -> intelligence manages processes -> processes produce results -> results improve intelligence.

The bottleneck isn't execution. It's the quality of the intelligence driving execution. That's why:
- Playbooks matter more than skills (proven > theoretical)
- CONTEXT.md matters more than AGENT.md (current state > static identity)
- Your corrections matter more than the system's defaults (you see reality, it sees data)

### The Compounding Effect

Every time you correct an agent, it learns.
Every campaign that runs teaches the playbooks something.
Every month, the system knows more than it did last month.
Every night, Beacon publishes another article building your organic moat.
Every order enriches the customer intelligence database.

The system doesn't just run. It gets better. But only if you feed it truth.

### Your One Rule

**When you know something the system doesn't, tell it.**

That's it. That's the whole job. The rest is automated.

---

*Built by Tom Hall-Taylor with Claude Code, March 2026. 11 agents, 27 scheduled tasks, 37 modules, 27,185 lines of code. The machine runs. The operator makes it excellent.*
