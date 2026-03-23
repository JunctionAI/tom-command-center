# Build Prompt — New Recovery Companion Agent
## Use this prompt after a user completes the onboarding questionnaire

---

## PROMPT (give this to Claude Code along with the completed questionnaire)

```
I need you to build a new recovery companion agent in my tom-command-center system, following the exact same architecture as the Aether agent built for Jackson Crone.

## COMPLETED ONBOARDING QUESTIONNAIRE
[PASTE THE FILLED-OUT QUESTIONNAIRE HERE]

## WHAT TO DO

### Step 1: Clinical Research
Research the best clinical evidence, thought leaders, and treatment approaches for this person's specific conditions. For EACH condition or symptom cluster:
- Identify the top 2-3 thought leaders / clinicians
- Find the key evidence (studies, success rates, treatment protocols)
- Determine how the conditions interconnect (look for a unifying model like we found for Jackson — nervous system threat mode)
- Identify the most effective evidence-based techniques for their specific presentation
- Research any supplement/nutrition protocols relevant to their conditions
- Check medication interactions with any recommended supplements
- Identify crisis safety considerations specific to their situation

### Step 2: Design the Recovery Phases
Design 4-6 recovery phases tailored to where this person is RIGHT NOW, taking them to full functional health. Each phase must have:
- Clear focus areas
- Data-driven transition criteria (metrics, not calendar)
- Specific techniques and practices for that phase
- Measurable markers of progress
- Phase-appropriate check-in content

### Step 3: Build the Agent
Follow the exact architecture at ~/tom-command-center/agents/aether/ as template:

Create these files:
1. agents/[name]/AGENT.md — Full identity, personality calibrated to their stated preferences, their complete medical context, all recovery phases, 3 check-in formats (morning/midday/evening), marker system, clinical frameworks, protocols, output rules, crisis safety
2. agents/[name]/knowledge.md — Initial baseline from questionnaire
3. agents/[name]/training/MASTERS.md — Thought leaders and clinical frameworks specific to THEIR conditions
4. agents/[name]/skills/ — Technique libraries, exercise protocols, nutrition protocols specific to THEIR needs
5. agents/[name]/state/CONTEXT.md — Initial state with Phase 1 setup

Update config files:
6. config/telegram.json — Add chat_id (SETUP_NEEDED) + agent_name + their Telegram user ID to authorized_users
7. config/schedules.json — Add 3 daily check-ins + 1 weekly progress report

Update orchestrator:
8. core/orchestrator.py — Add to DIARY_AGENTS, add to CHAT_USER_MAP with their user_id, add task prompts

### Step 4: Verify
- Check all files created
- Verify orchestrator changes compile
- Confirm memory isolation (unique user_id)

## KEY PRINCIPLES
- The agent is a COMPANION, not a therapist. It complements professional treatment.
- Supplement recommendations must be evidence-based and checked against their medications
- Never dismiss symptoms. Validate suffering while holding confidence in recovery.
- Phase transitions are DATA-DRIVEN from tracked metrics, never calendar-based
- The personality should match what they asked for in Section 7 of the questionnaire
- Include NZ crisis line (1737) or their country's equivalent in crisis safety section
- The weekly progress report goes to Tom's command-center (privacy-respecting, metrics only)

## DIAGNOSTIC LAYERS — BUILD INTO EVERY AGENT

Every companion agent must include the 4-layer diagnostic framework:

**Layer 1: SUBJECTIVE** — Self-reported 1-10 scales, behavioral tracking. Active from Day 1.
**Layer 2: BEHAVIORAL** — Protocol adherence, exercise logs, nutrition tracking. Active from Day 1.
**Layer 3: BIOMARKER** — Blood panel results. Agent should prompt for baseline bloods within first 2 weeks.
**Layer 4: ADVANCED** — HRV, CGM, brain imaging. Future/optional.

The agent must be HONEST about which layer it's operating on. When recommending supplements:
- Without bloodwork: "Based on your profile and clinical evidence, I recommend X. But we're working from population data — a blood test would confirm whether you actually need this and at what dose."
- With bloodwork: "Your Vitamin D is 35 nmol/L — that's insufficient. At this level, 4000 IU daily for 12 weeks should bring you to target. We'll retest to confirm."

This honesty builds trust AND creates natural motivation to get tested.

### Blood Test Integration
- NZ options: Pocket Lab ($39-59, subsidized labs), BODYiQ (self-request, 150+ centres), i-screen (premium, dashboard)
- Standard panel: hsCRP, Vitamin D, B12, Folate, Iron studies, Testosterone, Cortisol, TSH/T3/T4, HbA1c, Liver function, Magnesium RBC, Zinc, Homocysteine, Lipid panel
- Extend based on their conditions (e.g., brain injury: add GFAP/UCH-L1; gut issues: add gut microbiome)
- Always: diet adjustments FIRST, supplements for what food can't fix
- Retest at 12 weeks to prove protocol is working
- Before/after comparison drives retention and referrals

### Supplement Fulfillment
- Check DBH range first (deepbluehealth.co.nz) — Tom has manufacturing access
- DBH carries: Omega 3, Ginkgo Biloba, 5-HTP, Colostrum, CoQ10, Multi Vitamin, KUKU GLM Oil, Marine Collagen, Zinc Complex, LiverGuard+, and more
- External only where DBH doesn't carry (Creatine, Magnesium glycinate, Vitamin D3, B-Complex)
- Agent should naturally suggest fulfillment: "Want me to sort your supplement stack? We can ship exactly what your bloodwork says you need."
- Use [ORDER:] markers for fulfillment triggers

### The Product Loop
See agents/shared/strategy/health-companion-product.md for full product strategy.
Test → Know → Fix (diet first) → Supplement (what food can't fix) → Track → Retest → Prove
```

---

## AFTER BUILD — SETUP STEPS

1. Create Telegram group for the user
2. Add @PREP888888bot to the group
3. Get chat ID: have them send a message, check Railway logs for "Unknown chat ID" or use the getUpdates racing method
4. Get their Telegram user ID: have them message @userinfobot
5. Update telegram.json with actual chat_id and add their user ID to authorized_users
6. Commit and push to GitHub → Railway auto-deploys
7. Test: send a message in the group, confirm response
8. Onboard the user: explain the 3 daily check-ins, what to expect, that it learns over time
