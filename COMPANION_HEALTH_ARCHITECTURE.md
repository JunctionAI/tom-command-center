# Companion Agent Health Intelligence Architecture
## How the System Works — Technical + Strategic Overview

**Version:** 1.0 | **Built:** April 2026
**Agents:** Aether (Jackson), Apex (Tom), Forge (Tyler), Nova (Tane)

---

## What This Is

A health companion system that sits in the gap between a GP appointment and doing nothing. Not a medical device. Not a chatbot that gives generic advice. A personalised health intelligence layer that:

- Knows each user deeply (conditions, medications, history, goals, patterns)
- Applies a sophisticated multi-perspective reasoning framework to any health question
- Knows when it's out of its depth and escalates correctly
- Gets smarter with every conversation
- Costs roughly $0.04–$0.06 per interaction

The closest analogy is a knowledgeable friend who happens to have read everything Peter Attia, Andrew Huberman, Rhonda Patrick, and a Cochrane reviewer have ever published — and who has your full medical history in front of them every time you talk.

---

## The Four Intelligence Layers

Every companion agent conversation passes through four layers in sequence, before Claude even generates a response.

```
MESSAGE ARRIVES
      ↓
[Layer 1] ESCALATION ENGINE     ← Safety floor. Pure regex. No LLM cost.
      ↓ (if no emergency)
[Layer 2] CONTEXT ENRICHMENT    ← Vault + Medical Graph + Thought Leaders injected
      ↓
[Layer 3] BRAIN LOADING         ← Identity + User Memory + Health Brief + Current Plan
      ↓
[Layer 4] REASONING FRAMEWORK   ← Multi-perspective decision algorithm applied
      ↓
CLAUDE GENERATES RESPONSE
```

---

## Layer 1: Escalation Engine

**File:** `core/escalation_engine.py`
**Cost:** $0 (regex only, no API call)

The first thing that happens on every message. Runs before Claude sees anything.

Four tiers:

**Tier 1 — Emergency**
Patterns: chest pain with radiation, can't breathe, stroke symptoms (FAST), suicidal ideation with plan, seizure, anaphylaxis, overdose, unconscious.
Action: Hard override. Claude is never called. Agent sends emergency message directly. Log entry written. Example response: *"🚨 What you've described sounds like a medical emergency. Call 111 NOW..."*

**Tier 2 — Urgent GP (24-48 hours)**
Patterns: blood in stool/urine/vomit, sudden severe headache, unexplained weight loss >5kg, sudden vision change, prolonged fever, jaundice, new lump.
Action: Claude responds normally, but a mandatory suffix is appended that the agent cannot override: *"⚠️ What you've described is something a GP should look at within 24-48 hours. Please don't put this off."*

**Tier 3 — Routine GP (within 2 weeks)**
Patterns: symptoms persisting >2 weeks, medication interaction concern, new symptoms in someone with existing diagnosis, recurring episodes.
Action: Agent responds, mandatory soft flag appended: *"📋 Worth getting this checked with a GP if it's still going on in two weeks."*

**Tier 4 — Specialist flag**
Patterns: cardiologist/endocrinologist/neurologist/rheumatologist keywords with symptom context.
Action: Agent notes specialist value without alarming.

All Tier 1-2 events are logged to `escalation_log` in SQLite with timestamp, pattern, and message excerpt — creating an audit trail.

---

## Layer 2: Context Enrichment

**Cost:** $0 (all retrieval, no LLM)

Three data sources injected into the agent's brain on every health-relevant message:

### 2a. Obsidian Vault Search
**File:** `core/vault_indexer.py` → `format_search_for_agent()`
**Index:** `data/vault_index.db` (FTS5 full-text search, 212 notes, 328K words)

The Obsidian vault contains first-principles health knowledge — psychology, neuroscience, nutrition, performance. On every companion message, the vault is queried with keywords from the message. Top 3 relevant notes are injected into the agent brain as:
```
=== VAULT KNOWLEDGE: 'sleep anxiety' ===
[relevant note excerpts with context]
```

This means the agent has access to curated foundational knowledge without it being hardcoded into the prompt.

### 2b. Medical Knowledge Graph
**File:** `core/medical_knowledge_graph.py`
**Database:** Neo4j AuraDB (separate from user memory graph)
**Ontology:** `data/medical_ontology_seed.json`

A structured health ontology with five node types:

- `KCondition` — 50 conditions (metabolic, mental, gut, hormonal, neurological, autoimmune, environmental, nutritional, sleep, pain, reproductive, musculoskeletal)
- `KIntervention` — evidence-tiered treatments (supplements, lifestyle, dietary, therapeutic, pharmaceutical)
- `KEvidence` — evidence quality per condition→intervention link
- `KRedFlag` — symptoms that escalate (links to escalation tiers)
- `KSpecialist` — specialist types + when to refer + NZ resources

Relationship types:
```
(KCondition)-[:TREATED_BY]->(KIntervention)
(KCondition)-[:RED_FLAG]->(KRedFlag)
(KIntervention)-[:SUPPORTED_BY]->(KEvidence)
(KCondition)-[:REFER_TO]->(KSpecialist)
(KIntervention)-[:INTERACTS_WITH]->(KIntervention)   ← drug-supplement interactions
(KCondition)-[:RELATED_TO]->(KCondition)             ← cross-system connections
```

The cross-system connections are where this gets genuinely powerful. Examples of what's mapped:
- Dysbiosis → Major Depression (gut-brain axis)
- Insulin Resistance → PCOS (upstream driver)
- Adrenal Dysregulation ↔ Insomnia (bidirectional)
- Leaky Gut → Hashimoto's Thyroiditis (possible trigger)
- Post-Concussion Syndrome → ADHD (acquired comorbid)
- Chronic Inflammation → Major Depression (neuroinflammation)

When a keyword is extracted from the message, the graph returns: matching conditions, their evidence-ranked interventions, relevant red flags, cross-system related conditions, and any high-risk drug-supplement interactions. This is injected as:
```
=== MEDICAL KNOWLEDGE GRAPH ===
Relevant conditions: [conditions with conventional + functional description]
Evidence-based interventions: [Tier A/B first, with mechanism and dose]
Red flags: [with urgency tier and action]
Cross-system connections: [related conditions the agent should consider]
```

### 2c. Health Thought Leaders
**File:** `core/thought_leader_scraper.py`
**Leaders:** Peter Attia, Andrew Huberman, Rhonda Patrick, Zoe Harcombe, Gary Taubes (+ 10 AI/business leaders for Tom's system work)

Scraped via YouTube/RSS, processed through Claude to extract insights. Health-tagged insights (tagged `health_companion`) are injected as recent field thinking. Scraped at 5am daily via cron.

---

## Layer 3: Brain Loading

**File:** `core/orchestrator.py` → `load_agent_brain()`

Every conversation, the agent loads its full brain stack in this order:

```
1. Current date/time (authoritative — never infer from file timestamps)
2. AGENT.md — identity, medical context, personality, protocols for THIS user
3. HEALTH_BRIEF.md — Personal Health Intelligence Brief (if generated)
4. CURRENT_PLAN.md — what the user is actually doing right now
5. knowledge.md — learned patterns over time
6. Session diary — last 7 days of check-in logs (for continuity)
7. User memory — permanent facts from SQLite + Neo4j graph (conditions, medications, goals, history, patterns)
8. Skills files — domain-specific protocols (templates only, CURRENT_PLAN.md overrides)
9. State/CONTEXT.md — current phase, recent progress
```

The **Personal Health Intelligence Brief** (`state/HEALTH_BRIEF.md`) is the key structured layer — generated once at setup via `/analyze-health-intake`, it contains:
- Condition map with multi-system overlaps
- Medication/supplement audit with interaction flags
- Root cause hypothesis (unifying upstream driver)
- Current intervention ladder position
- Priority order with evidence rationale
- First conversation focus
- Red flags from intake

The **user memory** layer (SQLite + Neo4j) gives the agent a continuously growing picture of this specific person — facts extracted after every conversation via Haiku, deduplicated, confidence-scored, and loaded every session. Over time this becomes the most important layer: *Jackson does not tolerate cold exposure well. Tyler's HRV responds strongly to sleep before workouts. Tane's back is consistently worse on high-stress work days.*

---

## Layer 4: The Reasoning Framework

**File:** `agents/shared/health-reasoning.md`

Loaded by all four companion agents at the start of every session. This is the synthesised intelligence from 10 expert perspectives — not applied at runtime (no extra API calls), but baked into how the agents think.

### The 6-Axis Decision Algorithm

Every non-trivial health question is processed through:

**Axis 1 — Urgency:** Does this need immediate action? (escalation engine handles, but framework reinforces)

**Axis 2 — Knowability:** Can this be narrowed to a likely cause, or is it genuinely ambiguous?
- High knowability → respond with confidence
- Medium knowability → ask 1-2 targeted clarifying questions first
- Low knowability → structure the investigation, don't speculate to diagnosis

**Axis 3 — Intervention Ladder:** Work upward from lowest intervention:
```
Level 0: Sleep / circadian rhythm / light exposure
Level 1: Stress regulation / nervous system (breath work, cold, Zone 2)
Level 2: Movement (type matters: Zone 2 vs strength vs HIIT vs mobility)
Level 3: Nutrition (food quality, blood sugar stability, anti-inflammatory)
Level 4: Targeted supplementation (evidence-tiered A→D)
Level 5: Functional investigation (private labs, stool tests, hormone panels)
Level 6: GP consultation
Level 7: Specialist
```

The framework knows which conditions short-circuit the ladder (e.g., bipolar, Addison's, eating disorders, psychosis → go directly to Level 6; never suggest lifestyle approaches as primary).

**Axis 4 — Evidence Quality:** Always signals confidence level:
- "The RCT evidence is strong here..." (Tier A)
- "The research is promising but not definitive yet..." (Tier B)
- "There's genuine expert disagreement on this..." (contested)
- "Conventional medicine says X; functional medicine argues Y; the honest answer is..." (spectrum)

The framework also holds the conventional/functional threshold distinction — e.g., TSH "normal range" is 0.5-4.5 but optimal is 1-2.5. The agent can navigate both views and explain the difference without undermining trust in the person's GP.

**Axis 5 — Individual Modifiers:** Always checks before finalising:
- Existing conditions (contraindications)
- Current medications (CYP450 interactions, nutrient depletions caused by medications)
- Genetic variants if known (MTHFR, APOE4, COMT, HFE)
- Age, sex, life stage
- Practical constraints (cost, access, lifestyle)

Key drug-supplement interactions embedded in the framework:
- St John's Wort + SSRIs → serotonin syndrome (contraindicated)
- St John's Wort + warfarin/OCP → critical interactions
- High-dose omega-3 + anticoagulants → bleeding risk
- Vitamin K2 + warfarin → antagonism
- Medication-induced depletions: statins→CoQ10, PPIs→B12/Mg/Zn, OCP→B6/folate/zinc

**Axis 6 — Tracking:** Sets realistic timelines, tracks what improvement looks like, knows when to escalate to next level.

### The Clarifying Question Protocol

Before a substantive health recommendation for a non-trivial question:
1. How long has this been going on?
2. What have you already tried?
3. Are you on any medications or supplements?

Never more than 2 questions at once. If the person has already given the context, skip probing. The agent arrives equipped — not starting from scratch.

### The Multi-System Connection Map

Embedded in the framework: the key cross-system axes that single-specialty thinking misses.

- **Gut-Brain Axis:** 95% of serotonin produced in the gut. Dysbiosis drives depression, anxiety, cognitive impairment. Leaky gut drives systemic inflammation that crosses the blood-brain barrier.
- **Sleep-Everything Axis:** Glymphatic clearance, hormonal regulation, memory consolidation, immune function, cortisol rhythm — all sleep-dependent. Fix sleep before adding complexity.
- **Inflammation-Everything Axis:** Chronic low-grade inflammation underpins cardiovascular disease, depression, Alzheimer's, cancer, autoimmune, chronic fatigue. Addressable through lifestyle before medication.
- **Metabolic-Mental Axis:** Insulin resistance impairs brain glucose metabolism. Depression, brain fog, and anxiety all have significant metabolic components.
- **HPA-Everything Axis:** Chronic stress → sustained cortisol → suppressed immune function, disrupted sleep, increased visceral fat, impaired prefrontal function, reduced testosterone, disrupted thyroid conversion.
- **Thyroid-Everything Axis:** Thyroid hormone regulates metabolism in every cell. Subclinical hypothyroidism (technically "normal" TSH) causes fatigue, depression, brain fog, weight gain. Standard GP test (TSH only) misses T3/T4 conversion issues and antibodies.

---

## The Intake → Brief → Conversation Flow

### Step 1: Questionnaire Setup
Tom and the user fill out a health intake questionnaire. This is uploaded to the agent's files as `onboarding/QUESTIONNAIRE.md` or `AGENT.md` context.

### Step 2: Intake Analysis (one-time, at setup)
Tom sends `/analyze-health-intake <agent>` to Nexus.

The system:
1. Reads all intake files (AGENT.md, knowledge.md, QUESTIONNAIRE.md, CONTEXT.md)
2. Loads the full health-reasoning.md framework
3. Runs a Sonnet analysis pass applying the full intake analysis protocol
4. Generates a **Personal Health Intelligence Brief** with:
   - Condition map (all conditions + systems + multi-system overlaps)
   - Medication/supplement audit (interactions, nutrient depletions)
   - Root cause hypothesis (unifying upstream driver)
   - Intervention ladder position (what's been tried, what hasn't)
   - Priority order with evidence rationale
   - First conversation focus
   - Red flags
5. Saves to `agents/<agent>/state/HEALTH_BRIEF.md`
6. Seeds key facts into permanent memory (SQLite + Neo4j)

### Step 3: Every Conversation
The agent arrives with:
- The user's full medical context (from AGENT.md — written by Tom at setup)
- The structured health brief (generated from intake analysis)
- The current plan (what they're actually doing right now)
- 7 days of diary/session logs (continuity)
- Permanent memory of everything learned in previous conversations
- Vault knowledge relevant to this message
- Medical graph data relevant to this message
- Health thought leader insights (if available)
- The full reasoning framework

The agent doesn't ask "tell me about yourself." It already knows. It asks one or two targeted questions when it needs to, then applies the decision algorithm to give a specific, calibrated, evidence-based response.

### Step 4: After Every Conversation
The Haiku extraction pipeline automatically runs and:
- Extracts new facts from the conversation
- Deduplicates against existing facts
- Stores permanently in SQLite
- Syncs to Neo4j graph
- Updates user's fact store (used in every future conversation)

Over time, the agent's knowledge of this person compounds. Facts like *"Tane's back is worse after consecutive high-stress work days. Zone 2 walking for 30 minutes reduces flare frequency. Ibuprofen causes gut issues for him."* These aren't re-derived — they're remembered.

---

## What the 10 Expert Perspectives Contributed

The `health-reasoning.md` framework was synthesised from these lenses — they're not runtime agents, they're baked-in perspectives:

- **Clinical Evidence (Cochrane lens):** Evidence hierarchy, NNT thinking, when to trust RCTs vs. mechanistic reasoning, when absence of evidence ≠ evidence of absence
- **Functional Medicine:** Root cause over symptom management. The 5 root dysfunction areas (gut, mitochondria, inflammation, toxicity, stress/hormones). Timeline investigation.
- **Neuroscience (Huberman/Attia):** Brain-body bidirectionality. HPA axis dysregulation as epidemic. Sleep as non-negotiable. Gut-brain axis. BDNF and exercise.
- **Metabolic Health (Taubes/Bikman/Lustig):** Insulin resistance as root of most chronic modern disease. Fasting insulin > fasting glucose. Metabolic flexibility as health marker. Zone 2 as highest ROI metabolic intervention.
- **Nutritional Science (Rhonda Patrick/Harcombe):** Micronutrient deficiency as underappreciated driver. Bioavailability matters as much as dose. Food first but therapeutic doses justified. Common NZ deficiencies.
- **Pharmacology:** CYP450 interactions. Medication-induced nutrient depletions. Supplement quality variation. Bioavailability differences by form.
- **Health Psychology:** Behaviour change complexity. Motivational interviewing principles. Environment design > willpower. Health anxiety as real clinical entity. Trauma history as health determinant.
- **Integrative Medicine:** Mind-body connection is physiology. Allostatic load. Placebo/nocebo as real effects. Knowing which modality for which situation.
- **Traditional Systems (TCM/Ayurveda):** Pattern-based medicine. Adaptogenic herbs with real evidence (ashwagandha, rhodiola). Principles that RCTs are now validating.
- **Population Health / NZ Context:** Pacific health disparities. Te Whare Tapa Whā model (holistic Māori health framework). What NZ GPs will and won't engage with. Pharmac formulary constraints. Access and cost realities.

---

## NZ-Specific Safety Layer

The system is positioned for NZ (and specifically the clinic partnership context with Alfie):

- Never claims diagnostic or treatment capability
- Companion positioning: *"I help you understand and track your health. For medical decisions, your GP is the authority."*
- Emergency: 111
- Mental health crisis: 1737 (text or call, free, 24/7) — hardcoded into all companion agents
- Healthline: 0800 611 116
- All Tier 1-2 escalations logged with timestamp for audit trail
- Health facts stored locally (SQLite + Neo4j AuraDB), never in training data
- Te Whare Tapa Whā framework acknowledged — health is physical, mental, family, and spiritual

---

## Technical Stack Summary

| Component | Technology | Purpose |
|-----------|------------|---------|
| Agent framework | Python + Anthropic API | Orchestration, Claude calls |
| User memory | SQLite (user_memory.db) | Permanent fact store |
| Graph memory | Neo4j AuraDB | Relationship intelligence, context retrieval |
| Medical ontology | Neo4j AuraDB (separate schema) | Health knowledge graph |
| Vault search | SQLite FTS5 (vault_index.db) | Obsidian knowledge retrieval |
| Thought leaders | SQLite (thought_leaders.db) | Scraped health expert insights |
| Escalation engine | Python regex | Safety floor (no LLM cost) |
| Fact extraction | Claude Haiku | Post-conversation memory update |
| Intake analysis | Claude Sonnet | One-time health brief generation |
| Conversation | Claude Sonnet | Primary agent responses |
| Transport | Telegram Bot API | User interface |
| Deployment | Railway (Docker worker) | Production hosting |

---

## Cost Per Interaction

| Component | Cost |
|-----------|------|
| Escalation check | $0 (regex) |
| Vault query | $0 (local SQLite FTS5) |
| Medical graph query | $0 (Neo4j, local query) |
| Thought leader injection | $0 (pre-scraped) |
| Sonnet response (~4K tokens) | ~$0.04 |
| Haiku fact extraction | ~$0.001 |
| Voice note (OpenAI TTS, if enabled) | ~$0.0045 |
| **Total per conversation** | **~$0.04–0.05** |

The enrichment layers (vault, graph, thought leaders, health brief) add zero marginal cost. They add intelligence by increasing the quality of context, not by adding more Claude calls.

---

## What This Is (and Isn't)

**Is:** A sophisticated, deeply personalised health companion that applies multi-perspective evidence-based reasoning, knows each user's medical context intimately, and gets smarter over time.

**Is:** A system that can genuinely bridge the gap between GP appointments — helping people understand what's happening, what the evidence says about options, when to seek professional input, and how to track improvement.

**Is:** Safe. The escalation engine is non-negotiable and runs before everything else. The system knows what it doesn't know and routes to professionals when it should.

**Is not:** A medical device. Does not diagnose. Does not prescribe. Does not replace a GP for anything requiring diagnosis, prescription, or specialist referral.

**Is not:** Generic. Every companion has a completely different knowledge base for a completely different person. Aether knows Jackson's FND/POTS/PTSD/medication stack. Forge knows Tyler's post-concussion syndrome/dysautonomia/ADHD history. They are not the same system running on different users — they are different agents.

The most accurate description: a knowledgeable, persistent, personalised health companion that has read everything and never forgets anything about you.
