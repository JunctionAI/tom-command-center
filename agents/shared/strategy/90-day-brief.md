# DBH 90-Day Execution Strategy
## Shared Context — All Strategic Agents
**Approved:** March 3, 2026 | **Last updated:** March 10, 2026 | **Owner:** Tom + Tony

---

## THE MODEL

Meta Ads fuels new customer acquisition. Retention (email, loyalty, flows) makes those customers profitable. SEO/AEO compounds organically. Distribution partnerships scale internationally. The AI system runs it all daily and reports to Tony weekly.

---

## CAMPAIGN LAUNCH ORDER (7 campaigns, fortnightly cadence)

1. Pure Pets Bi-Active (mid-March) — $20/day, pet-specific creative
2. Marine Collagen (late March) — $20/day, skin health testimonials
3. Colostrum (mid-April) — $20/day, trending ingredient + NZ provenance
4. Deer Velvet (late April) — $20/day, recovery + vitality
5. Pure Pets Round 2 (May) — refined from C1 learnings
6. Trending Bundle (May) — winter immunity bundle
7. Sea Cucumber (June) — biggest product, saved for when playbook is sharpest

Each launches at $15-20/day. Day 7 review: below 2x verified ROAS = kill. 2-3x = hold + test creative. Above 3x = scale 50% every 5 days. Campaigns that work STAY RUNNING (stacking model).

---

## BUDGET RAMP

- March: ~$50/day ($1,500/month) — existing campaigns under review + Pure Pets launch
- April: ~$150/day ($4,500/month) — scale Social Proof, add Colostrum + Deer Velvet
- May: ~$250/day ($7,500/month) — 6-8 campaigns stacked
- June: $300-400/day ($9,000-12,000/month) — full engine

---

## ROAS FLOOR

- Use Shopify-verified ROAS only, NEVER Meta's claimed numbers
- Meta over-reports by ~150% (6.16x claimed = ~2x verified)
- Floor: 2x verified ROAS. Below 2x for 3 days = auto-pause
- Target: 3x+ verified ROAS before scaling

---

## ATTRIBUTION RULES

- Every order classified by: UTM params > referrer > discount code > Klaviyo flow > direct
- New customers tagged in Shopify: `acquired:{channel}`, `acquired-date:YYYY-MM`, `cohort:YYYY-MM-{channel}`
- customer_intelligence.db is the source of truth (updated nightly at 11pm)

---

## RETENTION ENGINE (Combined: Email + Loyalty + Flows)

- 55.7% of customers buy once and never return — this is the #1 problem
- Autonomous email production: AI identifies segments, produces campaigns, Tom reviews
- Target: 2-3 email campaigns/week (up from ~1)
- Post-purchase journey: Day 1 → Day 3 → Day 14 → Day 30 → Day 45-60 → Day 90
- Replenishment tracker fires Klaviyo events at 70% product depletion (LIVE)
- Moving repeat rate from 29.4% to 35% = ~$163K/year additional revenue

---

## SEO/AEO — BEACON AGENT

- Target: 1 article per day, every day (Opus 4.6)
- Beacon runs at 10pm, saves Shopify blog draft, Tom reviews and publishes
- Weekly accountability: articles published (target 7), keywords ranking, AI citations detected
- Google Organic already drives 36% of revenue at $0 cost
- ChatGPT already sending customers ($1,549 from 14 orders)

---

## WEEKLY TONY REPORT (Monday 7am)

Generated automatically, saved to ~/dbh-aios/reports/tony-reports/. Tom reviews, edits, emails to Tony.

Sections: Revenue → Meta Ads (verified ROAS) → Retention + Email → CPA:LTV Tracker → SEO Progress → What's Coming

---

## REVENUE TRAJECTORY

- March: $50K minimum
- April: $60-65K
- May: $75-80K
- June: $85-90K

---

## THREE PROVEN CREATIVE FORMULAS

1. TRUST + SOCIAL PROOF = 7.78x ROAS (Meta), 48.53% open rate (Email)
2. EXCLUSIVITY + SCARCITY = 8.45x ROAS (Meta), $9,259 revenue (Email) — max 4-6x/year
3. GIFT PSYCHOLOGY = 77.1% open rate, 4.15% click rate (Email)

---

## TARGETING

- NZ and AU only (no international until distribution partners are set up)
- Broad targeting with strong creative outperforms interest targeting (PROVEN)

---

## MARCH 10 UPDATE — AGREED WITH TONY

**Retention reality check:** Verified repeat purchase rate = 31.7% (mature cohort, 11,898 customers, 90+ days). Previous figure of 29.4% was underestimate. 2,035 customers have ordered 3+ times. Median reorder time = 75 days. The retention story is STRONG — the focus is acquisition, not fixing churn.

**Google Ads — going in-house:** Previous agency (Josh) being terminated. Tom managing Google Ads directly. Developer token Standard Access applied March 10 — awaiting Google approval. Until live: Google Ads intelligence derived from Shopify first-click attribution. Google Ads is acquisition-only (not retention). Goal: outperform Josh's results with better POAS targeting, proper NZ/AU segmentation, and PMax + Standard Shopping hybrid (NOT PMax alone).

**Pure Pets Meta — video test running:** Pure Pets Bi-Active had unverified ROAS. Video creative added March 10. DO NOT recommend killing Pure Pets Meta until video has run 5-7 days and results assessed. The bottleneck was creative format (video vs static), not the channel or audience.

**First-click attribution LIVE:** Pixel installed March 9. Replacing Triple Whale (~$300 USD/month saved). Coverage growing daily. Customer_intelligence.db updated nightly. Source of truth for all channel attribution.

**Email cadence ON TRACK:** 4 emails sent week of March 2-8. Design bottleneck removed March 9 — text-first sends now unblocked. Target 3/week. Email remains the highest-leverage retention channel.

**Sea Cucumber = dominant product:** 11 orders, $1,514 MTD (March 1-9). Strong repurchase signal. Campaign brief ready — launch after Pure Pets video test concludes and ROAS confirmed.

---

## THIS WEEK EXECUTION FILE

Every Monday review writes to: `agents/shared/strategy/THIS-WEEK.md`
All agents read THIS-WEEK.md at session start.
If THIS-WEEK.md exists and is current (written this week), it overrides general recommendations.
Work is produced in this order: Strategy (PREP/Monday review) → Copy production (Meridian) → Asana tasks (auto) → Tom approves → Execution.

---

## WHAT NEVER CHANGES

- Health claims: "supports" and "helps maintain" — NEVER "cures" or "treats" (TAPS/ASA)
- Brand tone: warm, trustworthy, science-backed but accessible
- Attribution truth: always use Shopify-verified numbers, not platform-claimed
- Playbooks > Skills > General knowledge (knowledge hierarchy)

---

*This brief is loaded into every strategic agent at session start. Update this ONE file to update all agents.*
