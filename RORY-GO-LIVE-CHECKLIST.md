# Rory Coach — Go-Live Checklist

**First send:** Sunday 2026-04-26, 9am NZ (auto via Railway cron)
**Status as of 2026-04-24:** Code shipped, Asana tasks pushed, awaiting env vars

---

## What's DONE (no action needed)

- ✅ Agent code deployed to Railway (auto-deploy from `main` commit `e21f564`)
- ✅ Schedule wired: `0 9 * * 0` Pacific/Auckland
- ✅ Orchestrator handler registered
- ✅ Both Rory emails in config: `roryjj24@gmail.com` + `roryjj@outlook.com`
- ✅ Full pipeline: IG pull → per-post Gemini video analysis → pillar classification → competitor Gemini → Opus synthesis → multi-recipient email
- ✅ State compounding baked in
- ✅ 7 Asana tasks in **Junction AI — Ops & Growth**
- ✅ Follow-up message drafted + copied to clipboard

---

## 3 THINGS YOU NEED TO DO (in priority order)

### 1. SEND THE FOLLOW-UP MESSAGE (2 min)
**Clipboard is loaded.** Just paste into WhatsApp/iMessage to Rory.

Contents also at: `clients/rory-okeefe/drafts/2026-04-24-session-2-followup.md`

### 2. SET UP GMAIL SMTP APP PASSWORD (5 min)
**Without this, brief generates Sunday but can't send.**

- Open: https://myaccount.google.com/apppasswords (2FA must be on)
- App name: "Junction Rory Coach"
- Copy the 16-char password (no spaces)
- Railway dashboard → tom-command-center service → Variables:
  - `SMTP_EMAIL` = your Gmail (e.g. `halltaylor.tom@gmail.com`)
  - `SMTP_APP_PASSWORD` = the 16-char password
- Save — Railway auto-redeploys in ~60s

**Verify locally:**
```bash
cd ~/tom-command-center
export SMTP_EMAIL="your@gmail.com"
export SMTP_APP_PASSWORD="your16charpw"
python3 -m core.email_sender
```
If you see `SMTP credentials valid.` — you're good.

### 3. (OPTIONAL — for better first brief) GET RORY'S IG TOKEN (15 min)
**Without this, Sunday brief still works** — it just asks you to paste his stats via `--notes` flag.

With the token, pipeline auto-pulls his IG data + runs Gemini on every post.

- Add him as tester on existing Meta App, OR create new app for `@rory247okeeffe`
- Generate long-lived access token (60 days)
- Edit `config/rory-config.json`:
  - `rory_ig_user_id`
  - `rory_ig_access_token`
- Commit + push

Can punt to next week. Don't let this block Sunday.

---

## SATURDAY NIGHT SANITY CHECK

Run this to see what Sunday's brief will look like:

```bash
cd ~/tom-command-center && python3 -m core.rory_coach --dry-run \
  --notes "Week Apr 21-27: 200K reach, +56 net followers (78 new, 22 unfollows),
  now 3,082 followers. Top: switch-kick technique 6K views / 120 saves overnight.
  Runner-up: class girls candid 27K. Principal skit: decent engagement, low reach.
  Pillars hit: 2x meme, 2x class-candid, 1x technique, 0x camp-insight."
```

Output goes to: `agents/rory-coach/state/briefs/2026-04-26-weekly.md`

If voice is off, edit: `agents/rory-coach/prompts/weekly-brief.md`

---

## SUNDAY 9AM — WHAT TO EXPECT

- Railway orchestrator fires at 9am NZ
- You get a Telegram notification to command-center channel: "Rory weekly brief — sent" (or "FAILED" with error)
- Both Rory inboxes get the email
- Archive lands at `agents/rory-coach/state/briefs/2026-04-26-weekly.md`

**If it fails:** fallback manual run
```bash
cd ~/tom-command-center && python3 -m core.rory_coach --send --notes "<stats>"
```

---

## CONFIG FILES REFERENCE

- `~/tom-command-center/config/rory-config.json` — recipients, pillars, pipeline toggles, fight date, competitor URLs
- `~/tom-command-center/config/schedules.json` — cron schedule
- `~/tom-command-center/agents/rory-coach/AGENT.md` — brain (pillars, voice rules, workflow)
- `~/tom-command-center/agents/rory-coach/prompts/weekly-brief.md` — Opus synthesis prompt
- `~/tom-command-center/agents/rory-coach/state/` — briefs archive, analyses, baselines

---

## ASANA TASK LINKS (all in Junction AI — Ops & Growth)

- [Send session-2 follow-up](https://app.asana.com/1/1208616230518223/project/1213980903578955/task/1214247712839447) — today
- [SMTP App Password setup](https://app.asana.com/1/1208616230518223/project/1213980903578955/task/1214247712840972) — Apr 25
- [IG Graph API token](https://app.asana.com/1/1208616230518223/project/1213980903578955/task/1214247776397855) — Apr 26
- [Competitor URLs for Sunday](https://app.asana.com/1/1208616230518223/project/1213980903578955/task/1214247513796679) — Apr 26
- [Saturday dry-run](https://app.asana.com/1/1208616230518223/project/1213980903578955/task/1214247750321959) — Apr 26
- [First live Sunday send monitor](https://app.asana.com/1/1208616230518223/project/1213980903578955/task/1214247513796080) — Apr 26
- [Post-send feedback check](https://app.asana.com/1/1208616230518223/project/1213980903578955/task/1214247776469446) — Apr 29
- [Schedule session 3](https://app.asana.com/1/1208616230518223/project/1213980903578955/task/1214247513848012) — Apr 28
