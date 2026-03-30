# What I Need to Complete Tane's Agent

## From the intake form:
- Full name + age + height/weight
- Primary health goals (what do they most want to change?)
- Medical history: conditions, medications, injuries
- Mental health history (any diagnoses, treatment, hospitalizations?)
- Substance history (frank — alcohol, cannabis, anything else, current status)
- Current supplement stack
- Diet: restrictions, intolerances, typical daily eating
- Exercise: current routine, injuries, training history
- Sleep: hours, quality, issues
- Wearables: Apple Watch / Garmin / Oura / none?
- Blood work: existing results to upload? Or never tested?
- Communication style: direct/blunt vs warm/encouraging?

## From Telegram setup (manual steps for Tom):
- Create Telegram group "Nova — Tane" + add bot
- Get chat ID (negative number): add @RawDataBot to group briefly
- Get Tane's Telegram user ID: forward message from Tane to @userinfobot

## Then I fill in:
1. agents/nova/AGENT.md — replace all [FILL: ...] with real data
2. agents/nova/state/CURRENT_PLAN.md — write Phase 1 plan
3. agents/nova/state/CONTEXT.md — initial state
4. agents/nova/prompts/*.md — customise 3 check-in prompts
5. config/telegram.json — add chat ID + agent name
6. config/telegram.json — add Tane's user ID to authorized_users
7. config/schedules.json — add 4 tasks (3 check-ins + weekly report)
8. core/orchestrator.py — uncomment the 2 "nova"/"tane" lines

## Time to complete once I have the form: ~45 min
