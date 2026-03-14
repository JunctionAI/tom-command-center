# Playbook: Walker Capital Investment Process
## End-to-End Pipeline — Stage by Stage

---

## STAGE 1: DISCOVERY (Automated, 7am daily)

**Trigger:** Scheduled cron job
**Tool:** Perplexity API (sonar-pro model)
**Output:** List of 3–10 candidate companies with one-line thesis each

**Perplexity scan prompts (rotate daily):**
- "What NZ and ASX listed companies have reported earnings surprises or analyst rating changes in the last 48 hours that may represent a valuation opportunity?"
- "What NZ, Australian, or US listed companies are experiencing structural tailwinds from regulatory changes, technology adoption, or sector consolidation in 2026?"
- "What growth companies in NZ, Australia, or US have recently achieved significant customer wins, partnerships, or market validation events that may signal a sentiment shift?"
- "What listed companies are trading at multi-year valuation lows due to temporary headwinds that may be reversing?"

**Pass criteria to Stage 2:**
- Listed on NZX, ASX, NYSE, NASDAQ
- Not a conglomerate
- Not in excluded sectors (tobacco, weapons, gambling)
- Preliminary catalyst identifiable (even vaguely)
- Not already in pipeline

**Output format to DB:**
```python
{
    'ticker': 'FPH.NZ',
    'name': 'Fisher & Paykel Healthcare',
    'exchange': 'NZX',
    'sector': 'Healthcare',
    'discovery_thesis': 'Aging population tailwind + respiratory care market expansion post-COVID',
    'source': 'Perplexity scan',
    'stage': 'DISCOVERED'
}
```

---

## STAGE 2: SCREENING (Automated, follows Stage 1)

**Trigger:** Automatic after discovery
**Tool:** Perplexity API for financial data pull
**Output:** Pass / Fail / Watchlist with scores

**Quantitative checks:**
Segment A (mature, FCF positive):
- ROIC > 12%
- Net Debt/EBITDA < 2.5x
- Revenue growth > 5% (last 3 years)
- FCF positive (last 2 years)

Segment B (growth/early-stage):
- Revenue growth > 20% YoY
- Gross margin > 40%
- Not burning more than 2x revenue per year (burn sustainability)

**Catalyst scoring (both segments — MANDATORY):**
3 = Strong: Specific, imminent, quantifiable. E.g. "FDA approval expected Q3 2026 for market-leading product" or "Regulatory change effective July 2026 removes key competitor."
2 = Moderate: Clear directional shift but timing or magnitude uncertain. E.g. "AI adoption in their sector accelerating, they are best positioned."
1 = Weak: Vague or already priced in. E.g. "General sector tailwinds."
0 = None identified: Automatic reject regardless of financials.

**Decision:**
- Quantitative pass + Catalyst ≥ 2 → Stage 3
- Quantitative pass + Catalyst = 1 → Watchlist (check back in 30 days)
- Quantitative fail → Reject (log reason)
- Catalyst = 0 → Reject

---

## STAGE 3: DEEP RESEARCH (Automated, Perplexity)

**Trigger:** Company enters Stage 3
**Tool:** Perplexity API (sonar-pro, deep research mode)
**Output:** Structured research brief (~1000 words, markdown)

**Research brief structure:**
1. Business model (how does it make money, who are customers, what are switching costs)
2. Competitive position (Porter's 5 Forces summary, moat sources)
3. Management quality (CEO background, tenure, track record, alignment)
4. Industry dynamics (growth rate, key trends, regulatory environment)
5. The catalyst (detailed — what exactly is it, timeline, probability, magnitude)
6. Bear case (what would make this wrong)
7. Key financial metrics (revenue, EBITDA, FCF, ROIC, leverage — last 3 years)
8. Comparable companies (list 5–10 direct peers)

**This brief becomes the input document for Stage 4 analysis AND MiroFish simulation.**

---

## STAGE 4: VALUATION (Interactive — Claude Code session)

**Trigger:** Research brief complete. Tom or Trent opens Claude Code, instructs Vesper to run valuation.
**Tools:** Morningstar MCP (fair value, moat, financials) + Vesper's DCF engine
**Output:** Valuation section of the memo

**Steps:**
1. Pull Morningstar data via MCP (fair value, moat, 5yr financials, stewardship)
2. Build scenario-weighted DCF (bull 25% / base 50% / bear 25%)
3. Build comps table (10–15 peers, EV/EBITDA, forward P/E, EV/FCF)
4. Synthesise: weighted intrinsic value, margin of safety, confidence level
5. If margin of safety < 20%: stop, log as "FAIR VALUE — monitoring"
6. If margin of safety ≥ 20%: proceed to Stage 5

---

## STAGE 5: RISK ASSESSMENT (Interactive — Claude Code session)

**Trigger:** Valuation passes 20% margin of safety threshold
**Tools:** Python risk engine + Claude synthesis
**Output:** Risk section of memo + conviction score (1–10)

**Steps:**
1. Run VaR (95% and 99%, 1-year, historical simulation)
2. Calculate Altman Z-Score (with segment-appropriate interpretation)
3. Calculate FCF conversion ratio
4. Check 10 earnings quality flags
5. Run Fisher Analysis (15 points, scored 1–5 each)
6. Synthesise conviction score (1–10)

**Gate:** Conviction score < 4 → return to watchlist with documented reason. Score ≥ 4 → proceed.

---

## STAGE 6: MIROFISH SIMULATION (Automated, high-conviction only)

**Trigger:** Conviction score ≥ 6 (Trent's threshold for MiroFish spend)
**Tool:** MiroFish API (localhost:5001)
**Output:** Competitive simulation report

**Process:**
1. Package research brief + competitor list as markdown document
2. POST to /api/graph/ontology/generate with simulation_requirement:
   "Simulate where market share will shift between [company] and its key competitors [list] over 1, 3, and 5 years. Also model the total addressable market size and growth rate at 1yr, 3yr, and 5yr timepoints. Identify the key competitive risks and the scenarios that would most benefit [company] vs those that would harm it."
3. POST to /api/graph/build — wait for graph_id
4. POST to /api/simulation/create + run
5. GET report when complete
6. Extract: market share trajectories, TAM projections, key scenarios, confidence level

---

## STAGE 7: DECISION MEMO (Automated generation)

**Trigger:** All previous stages complete
**Tool:** Claude Opus 4.6 synthesis + Telegram delivery
**Output:** One-page investment memo → Telegram to Tom + Trent simultaneously

**Memo template:**
```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
WALKER CAPITAL — INVESTMENT MEMO
[Company] | [Ticker] | [Exchange]
[Date] | Analyst: Vesper
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RECOMMENDATION: BUY / WATCH / AVOID
Entry: $X | Target: $X (XX% upside) | Stop: $X
Time horizon: XX months | Conviction: X/10

CATALYST
[One precise sentence — what the step-change is and why now]

SCENARIO-WEIGHTED DCF
Bull $X (25%) | Base $X (50%) | Bear $X (25%)
Weighted value: $X | Current price: $X
Upside: XX% | Margin of safety: XX%
Confidence: HIGH / MEDIUM / LOW

COMPS CHECK
EV/EBITDA: Xvs peers Yx | Forward P/E: X vs peers Y
Morningstar FV: $X | Moat: Wide/Narrow/None | Stars: X/5
Signal: CHEAP / FAIR / RICH

RISK
VaR 99% (1yr): XX% | CVaR 99%: XX%
Altman Z: X.X [SAFE/GREY/DISTRESS — context note]
FCF Conversion: XX% [CLEAN/FLAG]
Earnings quality flags: X/10

FISHER ANALYSIS
Score: XX/75
Strengths: [Top 3]
Concerns: [Top 2]

MIROFISH SIMULATION
Market share: [1yr] → [3yr] → [5yr]
TAM: $X today → $X (1yr) → $X (3yr) → $X (5yr)
Key competitive risk: [One sentence]

WHAT MUST REMAIN TRUE
1. [Exit trigger]
2. [Exit trigger]
3. [Exit trigger]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Reply BUY / WATCH / AVOID — Trent
```

**After Trent's decision:** Log to database. Update CONTEXT.md. If BUY: flag for portfolio tracking.
