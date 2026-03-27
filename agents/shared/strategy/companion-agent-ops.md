# Companion Agent Business — Operational Playbook
## Run it like a business. Progress all sectors simultaneously.
**Last updated:** March 27, 2026

---

## 4 SECTORS (run in parallel, always)

### PRODUCT
The thing itself — making the companion agent work reliably and expand capability.

### OPERATIONS + FINANCE
Infrastructure, costs, systems, documentation — keeping it running and knowing the numbers.

### SALES + GROWTH
Users, demand, capital, partnerships — proving traction and expanding.

### MARKETING + BRAND
Name, positioning, content, how the world sees it — building the story.

---

## CURRENT NEXT ACTIONS

### PRODUCT
- [ ] Review Tyler's March 27 transcript — catch remaining edge cases post-constraint-checker deployment
- [ ] Onboard Tane as User #2 — provision agent folder, CURRENT_PLAN.md, Telegram group, initial conversation
- [ ] Build repeatable onboarding checklist (what steps to provision each new user)
- [ ] Monitor constraint checker logs — is it catching violations? false positives?
- [ ] Blood test interpretation: build into AGENT.md so agents can interpret uploaded results

### OPERATIONS + FINANCE
- [ ] Calculate unit economics: API cost per user per day from Railway logs
- [ ] Document onboarding process end-to-end (not just in Tom's head)
- [ ] Set up daily cost tracking (per-user breakdown)
- [ ] Map out: what breaks at 5 users? 10 users? 50 users?

### SALES + GROWTH
- [ ] Prioritise beta pipeline: Tane → then who? Barnaby, grandpa, auntie — rank by learning value
- [ ] Prep Alfie conversation: active users, retention rate, unit economics, word-of-mouth evidence
- [ ] Tony conversation: DBH supplement box + companion agent bundle — what's the angle?
- [ ] Ask Tyler for a testimonial (what does he tell people about it?)
- [ ] Tom's own blood panel: become User Zero with objective data (Pocket Lab or BODYiQ)

### MARKETING + BRAND
- [ ] Name the product (can't pitch what you can't name)
- [ ] Define positioning statement: what IS this in one sentence?
- [ ] Simple landing page with waitlist
- [ ] First personal brand post: "I built an AI health coach" story
- [ ] Competitive positioning vs NHS tools, generic chatbots, Function Health, Marko

---

## TOM'S WORKFLOW

Open 4 tabs. One per sector. Pick a task from each. Push forward. Repeat.

No fixed day-per-sector. All sectors move simultaneously, like running DBH marketing across SEO + ads + email + web simultaneously.

Claude Code agents handle execution. Tom manages, prioritises, reviews.

---

## AGENT ASSIGNMENTS

**PREP (Strategic Advisor)** → Sales + Growth strategy, investor readiness, Tony alignment
**Oracle (Daily Briefing)** → Add companion agent metrics to daily brief (users, violations, costs, sentiment)
**Nexus (Command Center)** → Operations monitoring, per-user API costs, error rates
**Claude Code sessions** → Product development, bug fixes, new features, onboarding

---

## REVIEW CYCLE

**Daily:** Check constraint violation alerts, scan user messages for issues
**Weekly:** Transcript review, update next-actions per sector, cost check
**Monthly:** Full metrics review, user feedback synthesis, strategy adjustment

---

## REFERENCE DOCS
- Product strategy + revenue model: `agents/shared/strategy/health-companion-product.md`
- Technical architecture: `CLAUDE.md`
- Constraint checker: `core/constraint_checker.py`
