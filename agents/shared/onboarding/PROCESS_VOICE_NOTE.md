# Process Voice Note — Build a New Companion Agent
## Give this prompt to Claude Code along with the transcribed voice note

---

```
I need you to build a new companion agent for my tom-command-center system.

## USER'S VOICE NOTE TRANSCRIPT
[PASTE TRANSCRIPT HERE]

## WHAT TO DO

### Step 1: Research their situation
Based on what they shared, do clinical research for their specific goals and any conditions mentioned:
- Best evidence-based approaches for their stated goals
- If they mentioned conditions: top thought leaders, treatment approaches, how things interconnect
- Relevant nutrition science for their goals (body recomp, energy, sleep, brain health, etc.)
- Exercise programming principles for where they're at
- Supplement evidence (only if relevant — don't prescribe supplements to healthy people without bloodwork)
- Check medication interactions if they mentioned any meds

### Step 2: Design their plan
Build a personalised plan based on where they ARE, not where you wish they were:
- If they gave diet details: build a meal framework that improves on what they're already doing
- If they gave training details: build a program that progresses from their current level
- If they're starting from scratch: start simple, build complexity over weeks
- Always include: sleep protocol, hydration, movement baseline
- Set realistic phase progression (Phase 1 = foundation, Phase 2+ = build)

### Step 3: Build the agent files
Follow the architecture at ~/tom-command-center/agents/forge/ as the gold standard template.

Read these files first to understand the patterns:
- agents/forge/AGENT.md (identity structure)
- agents/forge/knowledge.md (learning template)
- agents/forge/state/CONTEXT.md (tracking structure)
- agents/forge/state/CURRENT_PLAN.md (plan format — especially ACTIVE CONSTRAINTS)
- agents/forge/skills/nutrition-protocol.md (principles-only format)
- agents/forge/skills/exercise-protocol.md (principles-only format)

Create ALL of these files:

1. agents/[name]/AGENT.md
   - Identity section (name the agent something that fits — not generic)
   - User profile (everything from voice note)
   - Medical context (if any — skip if healthy)
   - Knowledge hierarchy (same as Forge)
   - Working instructions calibrated to their stated preferences
   - 3 check-in formats (morning/midday/evening)
   - Crisis safety section with NZ crisis line (1737)

2. agents/[name]/knowledge.md
   - Baseline from voice note
   - Known patterns section (empty — will fill via learning)
   - What works / doesn't (from what they shared)
   - Memory rules

3. agents/[name]/state/CONTEXT.md
   - Phase 1 setup
   - Tracking templates
   - Empty live updates section

4. agents/[name]/state/CURRENT_PLAN.md
   - ACTIVE CONSTRAINTS section (critical — food eliminations, injuries, equipment limits, device status, preferences)
   - Meal plan OR "to be built conversationally in first week"
   - Training split OR "to be built conversationally"
   - Supplement stack (only what they're already taking + evidence-based additions)
   - Include CURRENT TRAINING SPLIT section with day-by-day schedule (needed for constraint checker)

5. agents/[name]/skills/ (3+ files, PRINCIPLES ONLY — no specific numbers)
   - nutrition-protocol.md (science behind their diet approach)
   - exercise-protocol.md (science behind their training approach)
   - [condition-specific].md if relevant (e.g., brain-recovery.md, stress-management.md)
   - HEADER ON EVERY SKILLS FILE: "REFERENCE ONLY — NO SPECIFIC NUMBERS. User's ACTUAL plan is in state/CURRENT_PLAN.md"

6. agents/[name]/training/MASTERS.md
   - Thought leaders relevant to their goals
   - Clinical frameworks

### Step 4: Config changes

7. config/telegram.json — Add:
   - chat_ids: "agent-name": "SETUP_NEEDED"
   - agent_names: "agent-name": "Display Name"

8. config/schedules.json — Add 3 daily check-ins:
   - morning_checkin at their preferred morning time
   - midday_checkin at their preferred midday time
   - evening_checkin at their preferred evening time

9. core/orchestrator.py:
   - Add to CHAT_USER_MAP: "agent-name": "firstname"
   - The constraint checker, auto-evolve, ASMR memory, and time injection will work automatically

### Step 5: Verify
- Syntax check orchestrator.py
- Confirm all files created
- Confirm CURRENT_PLAN.md has ACTIVE CONSTRAINTS section (constraint checker needs this)
- Confirm CURRENT_PLAN.md has CURRENT TRAINING SPLIT with day headers (schedule checker needs this)

## KEY PRINCIPLES
- This is a COMPANION, not a medical device. It complements professional care.
- Skills files = principles ONLY. All specifics go in CURRENT_PLAN.md.
- CURRENT_PLAN.md is the SOLE source of truth. If skills conflict with plan, plan wins.
- Don't assume problems. If someone's healthy, the agent optimises — it doesn't diagnose.
- The agent should feel magical from day 1 — knowledgeable, specific, personal.
- Match their communication style exactly (pushed hard vs gentle, brief vs detailed).
- The first check-in should NOT dump a 2000-word plan. Start by connecting, learning, building trust.
- Blood test integration: within first 2 weeks, naturally suggest baseline bloods if appropriate.
- Supplement fulfillment: only after bloodwork confirms need OR for evidence-based basics.

## DIAGNOSTIC HONESTY
The agent must be transparent about what it knows vs doesn't:
- Without bloodwork: "Based on your goals and the research, I recommend X. A blood test would confirm if this is exactly right for you."
- With bloodwork: "Your Vitamin D is 35 — insufficient. Here's exactly what to do."
This builds trust and creates natural motivation to get tested.
```
