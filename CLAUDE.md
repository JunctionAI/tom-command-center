# CLAUDE.md — Tom's Command Center
## Multi-Agent Telegram Intelligence System
**Version:** 1.0 | **Created:** March 1, 2026

---

## WHAT THIS IS
A network of specialised AI agents that communicate with Tom via separate Telegram group chats. Each agent has its own identity, knowledge stack, and schedule. No agent "forgets" because identity lives in files, not in session memory.

## ARCHITECTURE
One Telegram bot (@TomCommandBot). Multiple Telegram group chats. Each group = one domain.
When a message arrives or a scheduled task fires, the system:
1. Identifies which agent/channel it's for
2. Reads that agent's AGENT.md (identity + instructions)
3. Reads that agent's skills/ folder (domain expertise)
4. Reads that agent's playbooks/ folder (proven patterns)
5. Reads that agent's state/CONTEXT.md (what's happening now)
6. Calls Claude API with full context + the message/task
7. Posts response to the correct Telegram group
8. Updates state/CONTEXT.md with any new information

## AGENTS

| Channel | Agent Name | Telegram Group | Schedule |
|---------|-----------|---------------|----------|
| 🌍 Global Events | Atlas | global-events | Every 6hrs + breaking alerts |
| 💊 DBH Marketing | Meridian | dbh-marketing | Daily 9am brief + on-demand |
| 🐕 Pure Pets | Scout | pure-pets | Daily 9am brief + on-demand |
| 🏢 New Business | Venture | new-business | Daily 9am brief + on-demand |
| 🏋️ Health & Fitness | Titan | health-fitness | Daily 6am + meal/training reminders |
| 👥 Social | Compass | social | Weekly Sunday plan + nudges |
| 🎬 Creative Projects | Lens | creative-projects | Model release alerts + on-demand |
| 📊 Daily Briefing | Oracle | daily-briefing | Daily 7am master summary |
| 🤖 Command Center | Nexus | command-center | On-demand, admin commands |

## KNOWLEDGE HIERARCHY (same as AIOS)
When information conflicts, follow this priority:
1. **Playbooks** — proven with real data. Trust them.
2. **State/Intelligence** — current. May update playbook assumptions.
3. **Skills** — general best practice. Framework, adapt to specifics.
4. **General knowledge** — only when no specific data exists.

## FOLDER STRUCTURE
```
~/tom-command-center/
├── CLAUDE.md                    ← You are here
├── config/
│   ├── telegram.json            ← Bot token, chat IDs, user ID
│   ├── schedules.json           ← All cron schedules
│   └── api-keys.json            ← Claude API, other services
├── core/
│   ├── orchestrator.py          ← Main loop: receives msgs, routes to agents
│   ├── telegram_handler.py      ← Send/receive Telegram messages
│   ├── scheduler.py             ← Cron-based task triggering
│   └── context_manager.py       ← Loads agent brain before each call
├── scripts/
│   ├── setup_telegram.sh        ← One-time bot setup
│   └── deploy.sh                ← Start the system
├── agents/
│   ├── global-events/
│   │   ├── AGENT.md             ← Identity + instructions
│   │   ├── skills/              ← Domain expertise files
│   │   ├── playbooks/           ← Proven patterns
│   │   ├── intelligence/        ← Periodic research dumps
│   │   └── state/
│   │       └── CONTEXT.md       ← Current state, running knowledge
│   ├── dbh-marketing/
│   │   ├── AGENT.md
│   │   ├── skills/              ← Copies of DBH AIOS skills
│   │   ├── playbooks/           ← Copies of DBH AIOS playbooks
│   │   └── state/CONTEXT.md
│   ├── pure-pets/               ← Same structure
│   ├── new-business/
│   ├── health-fitness/
│   ├── social/
│   ├── creative-projects/
│   ├── daily-briefing/
│   └── command-center/
```

## HOW TO ADD A NEW AGENT
1. Create folder: `agents/new-agent-name/`
2. Create AGENT.md with identity, instructions, knowledge hierarchy
3. Add relevant skills/ and playbooks/
4. Create state/CONTEXT.md with initial state
5. Create Telegram group chat, add bot, note chat ID
6. Add to config/telegram.json
7. Add schedule to config/schedules.json
8. Restart orchestrator

## WORKING RULES
- Every agent reads its full brain stack before EVERY response
- State files are updated after meaningful interactions
- Skills are READ-ONLY (updated manually when expertise improves)
- Playbooks evolve monthly with real data
- Context/state evolves continuously
- No agent should ever say "I don't remember" — if it's not in the files, it was never recorded
