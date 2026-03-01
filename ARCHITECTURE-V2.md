# ARCHITECTURE V2 — Learning Loop + World-Class Training
## From Specialist Agents to Best-in-World Thinkers

---

## THE LEARNING LOOP

### Problem with V1
CONTEXT.md is a flat file. Over time it becomes a dump. No structure. No way to 
query "what worked in February?" or "what's our average email open rate trending?"

### Solution: Structured Learning Database

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   EXECUTE    │────▶│   MEASURE    │────▶│   LOG TO DB  │
│  (Agent acts) │     │  (Outcomes)  │     │ (Structured) │
└──────────────┘     └──────────────┘     └──────┬───────┘
       ▲                                         │
       │                                         ▼
┌──────┴───────┐     ┌──────────────┐     ┌──────────────┐
│   DECIDE     │◀────│ AGENT READS  │◀────│  GENERATE    │
│  (Strategy)  │     │ Fresh state  │     │ CONTEXT.md   │
└──────────────┘     └──────────────┘     └──────────────┘
```

**The database stores:**
- INSIGHTS: What we learned (tagged by domain, date, confidence)
- DECISIONS: What we decided and why (linked to insights)
- OUTCOMES: What happened (linked to decisions)
- PATTERNS: Recurring observations (auto-detected or manually flagged)
- METRICS: Time-series data (KPIs, performance numbers)

**Before every agent response:**
1. Query database for relevant recent insights
2. Query database for active decisions and their status
3. Query database for current metrics
4. Compile into fresh CONTEXT.md
5. Agent reads compiled context + its training (AGENT.md + skills + playbooks)

**After every agent response:**
1. Extract any new insights from the response
2. Log decisions made
3. Update metric tracking
4. Flag patterns if threshold met

### Database Schema (SQLite — simple, portable, no server needed)

```sql
-- Core learning log
CREATE TABLE insights (
    id INTEGER PRIMARY KEY,
    agent TEXT NOT NULL,           -- which agent generated this
    category TEXT NOT NULL,        -- 'performance', 'market', 'creative', 'process'
    content TEXT NOT NULL,         -- the actual insight
    evidence TEXT,                 -- what data supports this
    confidence TEXT DEFAULT 'medium', -- low/medium/high/proven
    tags TEXT,                     -- comma-separated tags
    source TEXT,                   -- 'observation', 'test_result', 'external', 'analysis'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    promoted_to_playbook BOOLEAN DEFAULT FALSE
);

-- Decisions and their rationale
CREATE TABLE decisions (
    id INTEGER PRIMARY KEY,
    agent TEXT NOT NULL,
    decision TEXT NOT NULL,        -- what was decided
    rationale TEXT,                -- why (links to insight IDs)
    expected_outcome TEXT,         -- what we think will happen
    actual_outcome TEXT,           -- what actually happened (filled later)
    status TEXT DEFAULT 'active',  -- active/completed/reversed/failed
    insight_ids TEXT,              -- comma-separated insight IDs that informed this
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP
);

-- Time-series metrics
CREATE TABLE metrics (
    id INTEGER PRIMARY KEY,
    agent TEXT NOT NULL,
    metric_name TEXT NOT NULL,     -- 'email_open_rate', 'meta_roas', 'weight_kg'
    value REAL NOT NULL,
    period TEXT,                   -- 'daily', 'weekly', 'monthly'
    context TEXT,                  -- any relevant context
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Patterns (promoted insights)
CREATE TABLE patterns (
    id INTEGER PRIMARY KEY,
    agent TEXT NOT NULL,
    pattern TEXT NOT NULL,         -- description of recurring pattern
    occurrences INTEGER DEFAULT 1,
    first_seen TIMESTAMP,
    last_seen TIMESTAMP,
    insight_ids TEXT,              -- which insights form this pattern
    status TEXT DEFAULT 'emerging' -- emerging/confirmed/actionable/integrated
);

-- Agent interaction log (for learning loop tracking)
CREATE TABLE interactions (
    id INTEGER PRIMARY KEY,
    agent TEXT NOT NULL,
    trigger TEXT NOT NULL,         -- 'scheduled', 'message', 'command'
    task TEXT,                     -- task name if scheduled
    input_summary TEXT,            -- what triggered the response
    output_summary TEXT,           -- key points of the response
    insights_generated TEXT,       -- IDs of insights created
    decisions_made TEXT,           -- IDs of decisions logged
    tokens_used INTEGER,
    model_used TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### Insight Promotion Pipeline

```
RAW OBSERVATION
     │ (logged with low/medium confidence)
     ▼
RECURRING PATTERN (seen 3+ times)
     │ (auto-flagged, confidence raised)
     ▼
VALIDATED INSIGHT (backed by data)
     │ (Tom reviews or auto-validates if metric confirms)
     ▼
PLAYBOOK ENTRY (proven, repeatable)
     │ (written into agent's playbooks/ folder)
     ▼
TRAINING UPDATE (changes how agent thinks)
```

This means the system literally gets smarter over time. Not through 
vague "memory" but through structured, queryable, promotable knowledge.

---

## WORLD-CLASS TRAINING ARCHITECTURE

### The Principle
Most AI agents are given a job title and told to "be helpful."

Tom's agents are trained with the distilled wisdom of the best minds in each domain. 
Each agent's skills/ folder contains not just "how to do X" but "how the best in the 
world THINK about X."

### Training Stack Per Agent

```
agents/[agent]/
├── AGENT.md                  ← Identity + operational instructions
├── skills/
│   ├── 00-MENTAL-MODELS.md   ← Core thinking frameworks for this domain
│   ├── 01-FIRST-PRINCIPLES.md ← The foundational truths of this field
│   ├── 02-[DOMAIN-SKILL].md  ← Technical skills (existing skill files)
│   └── ...
├── training/                  ← NEW: Deep domain training
│   ├── MASTERS.md            ← Key thinkers, their principles, key quotes
│   ├── FRAMEWORKS.md         ← Decision frameworks from the masters
│   ├── ANTI-PATTERNS.md      ← What the best AVOID (as important as what they do)
│   └── CASE-STUDIES.md       ← Real examples of excellence (and failure)
├── playbooks/                 ← Proven patterns from our own data
├── intelligence/              ← Periodic research updates
└── state/CONTEXT.md           ← Current state (now DB-generated)
```

### How Training Gets Loaded

The orchestrator loads training/ files as part of the brain stack:
```
AGENT.md → training/ (how to think) → playbooks/ (what's proven) → skills/ (how to do) → state/ (what's happening)
```

Training files are READ-ONLY and updated only through deliberate research sessions.
They represent the foundational knowledge the agent builds all decisions on.

### Training Quality Standard

Each MASTERS.md should include:
- Who are the 5-10 most respected minds in this domain?
- What are their core principles (not summaries — the actual operating principles)?
- What mental models do they use for decisions?
- What do they disagree on? (agents should know the debates, not just one view)
- Key quotes that capture the essence of their thinking

Each FRAMEWORKS.md should include:
- The 3-5 most powerful decision frameworks in this domain
- When to use each framework
- How to combine them
- Common mistakes in applying them

Each ANTI-PATTERNS.md should include:
- The most common mistakes in this domain
- What separates amateurs from masters
- Cognitive biases specific to this field
- Historical examples of failure from ignoring these

---

## AGENT TRAINING RESEARCH PLAN

### Atlas (Global Events)
**Masters:** George Friedman (geopolitical forecasting), Ray Dalio (macro cycles), 
Peter Zeihan (demographics/geography), George Kennan (strategic analysis), 
Ian Bremmer (political risk), Nassim Taleb (black swans/anti-fragility)
**Frameworks:** DIME (Diplomatic-Information-Military-Economic), Scenario planning, 
Second/third order effects analysis, Signal vs noise filtering
**Core training Q:** How do the best geopolitical analysts separate signal from noise?

### Meridian (DBH Marketing)
**Masters:** David Ogilvy (advertising), Claude Hopkins (scientific advertising), 
Eugene Schwartz (breakthrough advertising), Gary Halbert (direct response), 
Seth Godin (permission marketing), Byron Sharp (How Brands Grow)
**Frameworks:** AIDA, PAS (Problem-Agitate-Solve), Awareness ladder (Schwartz), 
Brand salience (Sharp), Direct response metrics hierarchy
**Core training Q:** What separates copy that converts from copy that doesn't?

### Scout (Pure Pets)
**Masters:** Same marketing masters as Meridian PLUS pet industry specialists,
DTC brand builders (Emily Weiss/Glossier model), subscription model experts
**Frameworks:** Customer lifetime value optimization, UGC content flywheel,
Emotional storytelling framework, Before/after transformation narrative
**Core training Q:** What makes pet parents buy AND keep buying?

### Venture (New Business)
**Masters:** Charlie Munger (mental models/decision-making), Peter Thiel (zero to one), 
Jim Collins (Good to Great), Ray Dalio (Principles), Ben Horowitz (The Hard Thing),
Eric Ries (Lean Startup), Hamilton Helmer (7 Powers)
**Frameworks:** 7 Powers (moat analysis), Jobs to be Done, Lean validation,
First principles decomposition, Inversion thinking, Pre-mortem analysis
**Core training Q:** How do the best founders identify and validate opportunities?

### Titan (Health & Fitness)
**Masters:** Dr Andy Galpin (exercise science), Dr Peter Attia (longevity),
Dr Layne Norton (nutrition science), John Danaher (BJJ strategy/systems),
Dr Andrew Huberman (neuroscience/performance), Pavel Tsatsouline (strength)
**Frameworks:** Progressive overload, Periodisation, Energy systems training,
Flexible dieting (IIFYM), Recovery-Adaptation-Supercompensation cycle,
BJJ positional hierarchy
**Core training Q:** What does evidence-based peak performance actually require?

### Compass (Social)
**Masters:** Dale Carnegie (human connection), Esther Perel (relationships),
Brené Brown (vulnerability/connection), Adam Grant (give and take),
Robin Dunbar (social networks/Dunbar's number)
**Frameworks:** Dunbar layers (5-15-50-150), Relationship investment model,
Quality time vs quantity, Reciprocity principles
**Core training Q:** What does the science say about maintaining meaningful relationships?

### Lens (Creative Projects)
**Masters:** Ed Catmull (Creativity Inc/Pixar), Robert Rodriguez (Rebel Without a Crew), 
Walter Murch (film editing/In the Blink of an Eye), Christopher Nolan (practical + innovation),
Hayao Miyazaki (vision + craftsmanship), Casey Neistat (content + storytelling)
**Frameworks:** Story circle (Dan Harmon), Hero's journey adaptation for short-form,
Visual storytelling principles, Rapid prototyping creative workflow,
Constraint-as-creativity (Rodriguez method)
**Core training Q:** How do the best filmmakers tell stories with limited resources?

### Oracle (Daily Briefing)
**Masters:** Military intelligence briefing doctrine, McKinsey pyramid principle,
Barbara Minto (structured communication), Edward Tufte (data presentation)
**Frameworks:** BLUF (Bottom Line Up Front), Pyramid structure,
Prioritisation matrices, Signal-to-noise ratio optimisation
**Core training Q:** How do you compress maximum insight into minimum reading time?

### Nexus (Command Center)
**Masters:** Systems thinking (Donella Meadows), DevOps/SRE principles (Google SRE book),
Mission control (NASA operations), Boyd's OODA loop
**Frameworks:** OODA loop, Systems leverage points, Monitoring & alerting hierarchy,
Graceful degradation
**Core training Q:** How do the best operations systems maintain reliability and awareness?

---

## IMPLEMENTATION ORDER

### Phase 1: Build the database + context generator (THIS WEEK)
- Set up SQLite database with schema above
- Build context_generator.py (queries DB → generates CONTEXT.md)
- Modify orchestrator to use DB instead of flat file updates
- Migrate existing CONTEXT.md data into database

### Phase 2: Research and build training files (THIS WEEK + NEXT)
- For each agent, research the masters and their principles
- Distill into MASTERS.md, FRAMEWORKS.md, ANTI-PATTERNS.md
- This is the most valuable work — take time, do it properly
- Each training file should be 2000-4000 words of concentrated wisdom

### Phase 3: Build the insight extraction pipeline (WEEK 2)
- After each agent response, auto-extract insights
- Log to database with proper tagging
- Build pattern detection (simple: count similar insights)
- Build promotion pipeline (insight → pattern → playbook)

### Phase 4: Close the loop (WEEK 2-3)
- Dashboard/reporting on learning velocity
- Automated playbook generation from validated patterns
- Cross-agent insight sharing (Atlas insight impacts Meridian strategy)

---

## THE COMPOUND EFFECT

After 90 days of this system:
- Each agent has 90+ days of structured insights
- Patterns have been identified and validated
- Playbooks have been written from real data
- Training has been refined based on what actually works
- The gap between these agents and generic AI assistants is massive

After 1 year:
- You have an institutional knowledge base no competitor can replicate
- Every playbook is backed by YOUR data, not generic best practice
- The agents think with the mental models of the best minds in each field
- AND they have a year of contextualised experience in YOUR business

This is the moat. Not the technology. The accumulated, structured, compounding knowledge.
