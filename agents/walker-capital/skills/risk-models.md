# Skill: Quantitative Risk Models
## Vesper — Walker Capital Management

---

## VaR — VALUE AT RISK

**Method: Historical Simulation (primary)**
Use last 5 years of actual daily returns. No distribution assumption — captures real fat tails.

**Report at two levels:**
- VaR 95%, 1-year: loss not exceeded 95% of the time over 1 year
- VaR 99%, 1-year: loss not exceeded 99% of the time over 1 year

**CVaR (Expected Shortfall) — always report alongside VaR:**
CVaR = average of all losses beyond the VaR threshold.
Answers: "IF we have a catastrophic year, how bad is it?"
CVaR(99%) is typically 1.3–1.7x VaR(99%) for equity. If much higher, fat tail risk is significant.

**Calculation (Python):**
```python
import numpy as np

def calculate_var_cvar(daily_returns, confidence=0.99, horizon_days=252):
    # Scale daily returns to annual
    annual_returns = np.array(daily_returns) * np.sqrt(horizon_days)
    sorted_returns = np.sort(annual_returns)
    var_idx = int((1 - confidence) * len(sorted_returns))
    var = abs(sorted_returns[var_idx])
    cvar = abs(sorted_returns[:var_idx].mean())
    return var, cvar
```

---

## ALTMAN Z-SCORE

Z = 1.2×X1 + 1.4×X2 + 3.3×X3 + 0.6×X4 + 1.0×X5

Where:
- X1 = Working Capital / Total Assets
- X2 = Retained Earnings / Total Assets
- X3 = EBIT / Total Assets
- X4 = Market Cap / Book Value of Liabilities
- X5 = Revenue / Total Assets

**Interpretation:**
- Z > 2.99: Safe zone — low bankruptcy risk
- 1.81–2.99: Grey zone — monitor, investigate leverage trajectory
- Z < 1.81: Distress zone — flag prominently, does NOT mean automatic reject for growth companies

**CRITICAL CONTEXT RULE:**
For Segment B (growth/early-stage) companies, Altman Z will often be in grey or distress zone due to negative retained earnings and low/negative EBIT. This is expected. Do NOT penalise growth companies on this metric alone. Report the score, explain why it's low, assess whether the trajectory is improving as revenue scales. The score is a flag, not a verdict.

For Segment A (mature) companies: distress zone (< 1.81) is a serious flag requiring explicit justification to proceed.

---

## FCF CONVERSION

FCF Conversion = Operating Cash Flow / Net Income

**Benchmarks:**
- > 100%: Excellent — earnings understated vs cash reality (often due to non-cash charges)
- 80–100%: Good — healthy conversion
- 60–80%: Acceptable — investigate what's consuming cash (WC build, heavy capex cycle?)
- < 60%: Flag — earnings quality concern. Is revenue being recognised before cash received? Is WC ballooning?

**Common causes of poor FCF conversion to investigate:**
- Receivables growing faster than revenue → aggressive revenue recognition
- Inventory build → demand softness hidden in balance sheet
- Capitalising costs that should be expensed → overstating EBITDA
- Frequent "exceptional" items → if recurring, they're not exceptional

**Note for growth companies:** FCF conversion can legitimately be poor during heavy investment phases (Segment B). The question is whether it's improving toward 80%+ as the business scales. Model the trajectory.

---

## EARNINGS QUALITY FLAGS

Run all of these for every company at Stage 5. Flag any that apply.

1. Cash conversion < 80% (see above)
2. Receivables growing meaningfully faster than revenue (>150% of revenue growth rate)
3. Inventory growing faster than cost of goods sold
4. Gross margin declining while revenue grows (mix shift or pricing pressure signal)
5. D&A falling relative to asset base (potential underdepreciation)
6. Frequent "non-recurring" charges (if 3+ years running, they're recurring — normalise them out)
7. Auditor change or qualified opinion in last 3 years
8. Accelerating insider selling alongside bullish public commentary
9. Goodwill > 40% of total assets (acquisition-heavy; risk of impairment)
10. Revenue growth with margin compression AND rising leverage (triple negative)

**Output:** List of flags triggered with one-line explanation each. 0 flags = clean. 3+ flags = serious concern, requires explicit discussion in memo.

---

## CONVICTION SCORING (1–10)

Synthesises all analysis into a single number for position sizing guidance.

**Score 8–10 (High conviction):**
Strong catalyst, wide moat, DCF and comps agree, margin of safety > 30%, VaR manageable, 0–1 earnings quality flags, Morningstar moat = Wide or Narrow, Z-score safe.

**Score 6–7 (Moderate conviction):**
Good catalyst, narrow moat or competitive dynamics still playing out, DCF and comps within 20–30%, margin of safety 20–30%, some earnings quality flags but explainable, monitoring criteria clear.

**Score 4–5 (Low conviction):**
Catalyst unclear or weak, valuation tight (margin of safety 15–20%), multiple earnings quality flags, high VaR relative to upside, Z-score in grey zone without clear trajectory improvement.

**Score < 4:**
Do not recommend. Return company to watchlist with reason documented.

**Position sizing (conviction-weighted):**
Trent determines absolute position sizes, but the conviction score is the input:
- Score 8–10: Full position (Trent's discretion)
- Score 6–7: Half position, build on confirmation
- Score 4–5: Monitoring only, no position
