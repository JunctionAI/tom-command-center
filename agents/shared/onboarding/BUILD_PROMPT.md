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
