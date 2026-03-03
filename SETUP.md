# 🚀 SETUP GUIDE — Tom's Command Center
## From zero to running in 30 minutes

---

## STEP 1: Create the Telegram Bot (5 mins)

1. Open Telegram, search for `@BotFather`
2. Send `/newbot`
3. Name: `Tom's Command Center` (or whatever you like)
4. Username: `TomCommandBot` (must be unique, try variations)
5. Copy the **bot token** — save it

### Get your user ID:
1. Search for `@userinfobot` on Telegram
2. Send it any message
3. It returns your user ID number — save it

### Create the group chats:
For each agent, create a Telegram group:
1. Create new group → name it (e.g., "🌍 Global Events")
2. Add your bot to the group
3. Send a message in the group
4. Visit: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
5. Find the `chat.id` for that group (it's a negative number like `-1001234567890`)
6. Save it

Do this for all 9 channels:
- 🌍 Global Events
- 💊 DBH Marketing
- 🐕 Pure Pets
- 🏢 New Business
- 🏋️ Health & Fitness
- 👥 Social
- 🎬 Creative Projects
- 📊 Daily Briefing
- 🤖 Command Center

### Update config:
Edit `config/telegram.json` with your bot token, user ID, and all chat IDs.

---

## STEP 2: Install Dependencies (2 mins)

```bash
# Python packages
pip install anthropic requests apscheduler

# Set your API key
export ANTHROPIC_API_KEY="sk-ant-your-key-here"

# Or add to ~/.bashrc / ~/.zshrc for persistence:
echo 'export ANTHROPIC_API_KEY="sk-ant-your-key-here"' >> ~/.bashrc
```

---

## STEP 3: Test It (3 mins)

```bash
cd ~/tom-command-center

# Test brain loading — see what an agent "knows"
python core/orchestrator.py test global-events

# Test all agent brain sizes
python core/orchestrator.py brains

# Run a single agent task manually
python core/orchestrator.py run global-events scan

# If Telegram is configured, this will post to the channel.
# If not, it prints to console.
```

---

## STEP 4: Start the System (2 mins)

### Option A: Run both polling + scheduler (recommended for development)
```bash
# Terminal 1: Telegram listener (responds to your messages)
python core/orchestrator.py poll

# Terminal 2: Scheduler (runs timed tasks)
python core/scheduler.py
```

### Option B: Run as background services (production)
```bash
# Using tmux
tmux new-session -d -s command-center-poll 'cd ~/tom-command-center && python core/orchestrator.py poll'
tmux new-session -d -s command-center-sched 'cd ~/tom-command-center && python core/scheduler.py'

# Check they're running
tmux ls
```

### Option C: Systemd services (Linux VPS — most reliable)
```bash
# Create service files — see scripts/deploy.sh
sudo systemctl enable tom-command-poll
sudo systemctl enable tom-command-scheduler
sudo systemctl start tom-command-poll
sudo systemctl start tom-command-scheduler
```

---

## STEP 5: Add DBH Skills (5 mins)

Copy your existing DBH AIOS skill files into the DBH Marketing agent:

```bash
# From your existing ~/dbh-aios/skills/ folder:
cp ~/dbh-aios/skills/dbh-brand-voice.md ~/tom-command-center/agents/dbh-marketing/skills/
cp ~/dbh-aios/skills/dbh-email-marketing.md ~/tom-command-center/agents/dbh-marketing/skills/
cp ~/dbh-aios/skills/meta-ads-supplements-2026.md ~/tom-command-center/agents/dbh-marketing/skills/
cp ~/dbh-aios/skills/meta-ads-dbh.md ~/tom-command-center/agents/dbh-marketing/skills/
cp ~/dbh-aios/skills/google-ads-supplements.md ~/tom-command-center/agents/dbh-marketing/skills/
cp ~/dbh-aios/skills/seo-geo-aeo-2026.md ~/tom-command-center/agents/dbh-marketing/skills/
cp ~/dbh-aios/skills/shopify-developer.md ~/tom-command-center/agents/dbh-marketing/skills/

# Copy playbooks too:
cp ~/dbh-aios/playbooks/*.md ~/tom-command-center/agents/dbh-marketing/playbooks/

# For Pure Pets, copy the relevant subset:
cp ~/dbh-aios/skills/dbh-brand-voice.md ~/tom-command-center/agents/pure-pets/skills/
cp ~/dbh-aios/skills/meta-ads-supplements-2026.md ~/tom-command-center/agents/pure-pets/skills/
cp ~/dbh-aios/skills/meta-ads-dbh.md ~/tom-command-center/agents/pure-pets/skills/

# For New Business:
cp ~/dbh-aios/skills/business-strategy.md ~/tom-command-center/agents/new-business/skills/
cp ~/dbh-aios/skills/market-entry-scoring.md ~/tom-command-center/agents/new-business/skills/
```

---

## STEP 6: Populate Your Data (10 mins)

### Health & Fitness:
Message the Health channel with your current:
- Gym/lifting routine
- Running/cardio schedule
- Dietary preferences/restrictions
- Current goals (cut/bulk/maintain)
- Current weight and target

### Social:
Message the Social channel with:
- Key people in your life (name, relationship, last seen)
- Upcoming birthdays/events
- Preferred social activities

### New Business:
Message the New Business channel with:
- Business concept (when ready)
- Initial milestones
- Research priorities

---

## HOW IT WORKS — THE KEY INSIGHT

Every time any agent responds, it runs this sequence:

```
1. Read AGENT.md         → "I am Atlas, I monitor global events..."
2. Read playbooks/*.md   → "Here's what's proven to work..."
3. Read skills/*.md      → "Here's deep domain expertise..."
4. Read state/CONTEXT.md → "Here's what's happening right now..."
5. Call Claude API        → Full brain loaded, respond to task/message
6. Update CONTEXT.md     → Save anything new learned
```

This is IDENTICAL to your DBH AIOS pattern:
- AGENT.md = CLAUDE.md (session controller)
- playbooks/ = playbooks/ (proven patterns)
- skills/ = skills/ (domain expertise)
- state/CONTEXT.md = intelligence/ (current data)

The agent never "forgets" because it re-reads everything each time.
The agent never "loses identity" because identity is in a file, not in memory.

---

## ADDING A NEW AGENT

1. `mkdir -p ~/tom-command-center/agents/my-new-agent/{skills,playbooks,intelligence,state}`
2. Create `AGENT.md` with identity, personality, scheduled tasks, output format
3. Create `state/CONTEXT.md` with initial state
4. Add relevant skill files to `skills/`
5. Create Telegram group, add bot, get chat ID
6. Update `config/telegram.json` with new chat ID
7. Add schedule to `config/schedules.json` if needed
8. Restart scheduler

---

## COST ESTIMATE

Using Claude Sonnet for routine tasks:
- 9 agents × ~2,000 token brain × ~1,000 token response = ~27K tokens per full cycle
- At $3/M input + $15/M output: ~$0.02 per cycle
- 4 cycles/day (morning briefs + scans): ~$0.08/day
- Monthly: ~$2.50

Using Opus for weekly deep dives: add ~$1/week = $4/month

**Total estimate: ~$6.50/month** for a full personal AI command center.

---

## TROUBLESHOOTING

**Bot not responding?**
- Check `orchestrator.log` for errors
- Verify bot token in `config/telegram.json`
- Make sure bot is added to the group as member
- Check your user ID matches `owner_user_id`

**Agent giving generic responses?**
- Run `python core/orchestrator.py test <agent>` to check brain loading
- Verify skill files exist in the agent's `skills/` folder
- Check AGENT.md has clear instructions

**Scheduled tasks not firing?**
- Check scheduler is running: `tmux ls`
- Verify timezone in `config/schedules.json`
- Check `orchestrator.log` for cron errors
