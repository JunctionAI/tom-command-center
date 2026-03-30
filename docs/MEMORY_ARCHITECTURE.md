# Memory Architecture — Companion Agent System

## How It Works Today

### Three-Tier Memory (SQLite, not vector DB)

**Tier 1 — User Facts** (permanent, deduplicated)
- After every conversation, Haiku auto-extracts facts about the user
- Dedup logic: Add / Update / Skip / Merge against existing facts
- ~200-500 facts per active user
- Loaded into every agent prompt as structured context
- Cross-agent: if Titan (training) learns Tyler hates rice, Forge (recovery) sees it too
- Users can `/memory` to see what the agent knows, `/forget` to delete

**Tier 2 — Session Summaries** (30-day rolling)
- Daily Haiku-generated summaries compress conversations into medium-term memory
- Covers the "what happened this week" layer
- Auto-expires after 30 days (facts persist, summaries don't)

**Tier 3 — Recent Messages** (last 10-20 verbatim)
- Raw conversation history for multi-turn context
- The agent remembers what was just said, not just extracted facts

### ASMR — Agentic Search and Memory Retrieval

On top of the three tiers, companion agents (health users) use ASMR — inspired by Supermemory's ~99% SOTA architecture (March 2026).

**Ingestion: 3 parallel observer agents**
- Fact Hunter: Named entities, explicit statements, relationships
- Context Weaver: Patterns, implications, cross-session correlations
- Timeline Tracker: Temporal sequences, event chronology, knowledge updates

**Storage: Structured findings in SQLite**
- 10 knowledge vectors: personal, health, preferences, events, temporal, updates, goals, relationships, patterns, emotional
- Findings linked to source sessions with timestamps
- Supersession tracking (new facts automatically mark old versions as outdated)
- Confidence scoring (explicit facts = 1.0, implied patterns = 0.6-0.8)

**Retrieval: 3 parallel search agents** (run on every user message)
- Direct Seeker: Exact match, literal facts, recency-first
- Inference Engine: Related context, implications, supporting evidence
- Temporal Reasoner: Timeline reconstruction, state change tracking, contradiction resolution

**Result:** Instead of dumping 500 facts into the prompt, ASMR assembles ~15-30 contextually relevant facts per conversation. The agent gets what it needs, not everything it knows.

### Auto-Evolution

Separate from memory. After every user conversation, Haiku checks if the user's plan (CURRENT_PLAN.md) needs updating. Two-step:
1. Detection: "Did the user change their meal plan, training, supplements, or constraints?" (cheap, fast)
2. Rewrite: If yes, regenerate CURRENT_PLAN.md with the change applied (only runs ~10% of the time)

This means the agent's plan stays in sync with the user without manual editing.

---

## Database Schema (SQLite)

```
data/user_memory.db
├── user_facts          — Deduplicated facts (Tier 1)
├── messages            — All messages permanently stored
├── session_summaries   — Daily digests (Tier 2)
├── extraction_log      — Audit trail of what was extracted
├── knowledge_findings  — ASMR structured findings (10 vectors)
└── retrieval_cache     — ASMR assembled context cache
```

No vector embeddings. No external services. Pure SQLite + structured LLM extraction.

---

## Why SQLite, Not Neo4j (Honest Assessment)

### What We Have
- SQLite: single file, zero ops, deploys anywhere, fast reads
- Structured extraction via LLM observers (not keyword matching)
- Supersession tracking (old facts auto-deactivated)
- Works today in production with 3 active users

### Where Neo4j Would Help
- **Relationship queries**: "What people has Tyler mentioned, and how are they connected?" — currently flat, Neo4j makes this a graph traversal
- **Temporal chains**: "Show me the progression of Jackson's energy scores over 3 months" — possible in SQLite but clunky
- **Cross-entity reasoning**: "Tyler's surf schedule affects his sleep which affects his training readiness" — graph edges make this natural
- **Pattern detection at scale**: With 50+ users, finding correlations across user profiles becomes a graph problem

### Where Neo4j Adds Complexity Without Value (at current scale)
- 3 users. Flat fact store with LLM-powered retrieval already achieves high accuracy.
- Neo4j requires: separate service (hosting cost), schema design, query language (Cypher), data migration
- The ASMR search agents already do inference that a graph DB would need explicit edges for
- SQLite is zero-ops. Neo4j is not.

### Recommended Path
1. **Now (3-10 users):** Keep SQLite + ASMR. It works. Focus on product, not infrastructure.
2. **At 50+ users:** If we need cross-user pattern detection (e.g., "users who do X tend to improve faster"), evaluate Neo4j for the analytics/research layer ONLY.
3. **At scale:** Neo4j as a knowledge graph alongside SQLite for per-user memory. Not instead of.

The LLM is doing most of the "graph reasoning" already. Adding a graph DB is an infrastructure choice, not an intelligence upgrade — the intelligence comes from the observer/search agents, not from how data is stored.

---

## Cost Per User

**Per conversation (user sends a message, agent replies):**
- 1 Sonnet call for the response: ~$0.03-0.08 (depends on brain size)
- 3 Haiku observer calls (ASMR extraction): ~$0.003
- 3 Haiku search calls (ASMR retrieval): ~$0.003
- 1 Haiku auto-evolve detection: ~$0.001
- Total per conversation: ~$0.04-0.09

**Per scheduled check-in (agent sends, user hasn't spoken):**
- 1 Sonnet call for the message: ~$0.03-0.08
- No memory extraction (user said nothing new)
- No auto-evolve (no user input to evolve from)
- Total per scheduled task: ~$0.03-0.08

**Daily per user (3 check-ins + 2-3 user replies):**
- ~$0.30-0.60/day
- ~$9-18/month per active user

---

## What Makes This Different

1. **No embeddings, no vector DB** — LLM observers extract structured knowledge, LLM search agents retrieve contextually. The intelligence is in the prompts, not the storage layer.

2. **Supersession tracking** — Facts don't just accumulate. When Tyler says "actually I stopped eating cauliflower rice," the old fact gets marked outdated and the new fact takes precedence. The agent never contradicts itself.

3. **Multi-agent shared memory** — All agents for a user share the same fact store. Training agent learns something → recovery agent knows it next conversation.

4. **Plan auto-evolution** — The user's plan (meal, training, supplements, constraints) stays in sync with their actual life. No manual editing required.

5. **Zero-ops deployment** — SQLite file on a Railway volume. No separate database service. Backup = copy one file.
