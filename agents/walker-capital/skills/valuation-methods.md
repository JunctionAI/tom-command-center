# Skill: Investment Valuation Methods
## Vesper — Walker Capital Management

---

## PRIMARY: SCENARIO-WEIGHTED DCF

Three scenarios, every company, no exceptions:

**BULL CASE (25% probability)**
Catalyst fully materialises. Above-consensus execution. Best-case FCF growth, lowest reasonable WACC, highest defensible terminal multiple.

**BASE CASE (50% probability)**
Catalyst partially materialises. In-line execution. Mid-range FCF growth, WACC at calculated rate, sector-median terminal multiple.

**BEAR CASE (25% probability)**
Catalyst delayed or fails. Headwinds materialise. Conservative FCF (flat or declining near-term), WACC + 100bps, discount to sector terminal multiple.

**Weighted Intrinsic Value = (Bull × 0.25) + (Base × 0.50) + (Bear × 0.25)**
Margin of safety = (Weighted Value − Market Price) / Weighted Value. Must be ≥ 20%.

---

### DCF CONSTRUCTION

**Step 1: Normalise earnings**
Strip one-offs (restructuring, asset sales, impairments). Adjust for WC swings. Separate growth capex from maintenance capex. Owner Earnings = Net Income + D&A − Maintenance Capex − ΔWC.

**Step 2: Segment A (Mature businesses) — FCF model**
FCFF = EBIT(1−t) + D&A − ΔWC − Total Capex
FCFE = FCFF − Net Interest(1−t) + Net Borrowing
Forecast 5–10 years bottom-up: revenue × margin progression × capex intensity.

**Step 3: Segment B (Growth/early-stage) — handle negative near-term FCF explicitly**
Model negative FCF years 1–3 without smoothing. Value resides in years 4–10 and terminal.
Key variable for sensitivity: time-to-profitability (shift by ±1 year in each scenario).
Use EV/Revenue or EV/Gross Profit as a comps cross-check since EBITDA may be negative.

**Step 4: WACC**
- Risk-free rate: Current 10yr NZ Govt Bond (NZ stocks) or US 10yr (US stocks)
- Equity Risk Premium: NZ ~6.5%, AU ~6.0%, US ~5.5% (Damodaran estimates)
- Beta: 5-year weekly regression vs NZX50/ASX200/S&P500; use industry beta if illiquid
- Cost of equity = Rf + β × ERP
- Cost of debt = pre-tax yield on existing debt × (1 − effective tax rate)
- WACC = (E/V) × Ke + (D/V) × Kd
- NZ equity typical range: 8–11%. US large cap: 7–10%.

**Step 5: Terminal value**
Gordon Growth: TV = FCF(n+1) / (WACC − g), where g = 2–3% long-term GDP growth.
Exit multiple cross-check: TV = EBITDA(n) × sector EV/EBITDA exit multiple.
Terminal value is typically 60–70% of total DCF — be conservative here.

**Step 6: Sensitivity table (always produce for base case)**
```
          WACC:  -1%    Base    +1%    +2%
Growth:
  -1%           $X     $X      $X     $X
 Base           $X     $X      $X     $X
  +1%           $X     $X      $X     $X
  +2%           $X     $X      $X     $X
```

---

## SECONDARY: RELATIVE COMPS

**Peer group:** 10–15 companies, same sector and sub-sector, similar size (±50% market cap), similar growth profile. No conglomerates.

**Multiples by relevance:**
1. EV/EBITDA — capital structure-neutral (primary for mature)
2. Forward P/E — NTM consensus estimates
3. EV/FCF — best cash discipline measure
4. EV/EBIT — better than EBITDA for capital-light
5. EV/Revenue or EV/Gross Profit — for pre-profit growth companies (Segment B)
6. PEG — P/E ÷ 3yr EPS growth rate; PEG < 1.0 = attractive

**Compare vs:**
- Peer median (not mean — outliers distort)
- Own 5-year and 10-year historical average multiple
- Premium/discount must be justified: if trading at premium, what earns it?

**Implied range:** Low = 25th percentile peers, Mid = median, High = 75th percentile.

---

## MORNINGSTAR CROSS-CHECK (via MCP in Claude Code sessions)

Pull for every company at Stage 4:
- Morningstar Fair Value estimate → compare to our DCF
- Economic Moat rating (Wide / Narrow / None) → feeds Fisher analysis and quality score
- Star rating (1–5) → their margin of safety signal
- Stewardship rating (Exemplary / Standard / Poor) → management quality input
- 5-year normalised financials → validate our FCF model inputs

If our DCF and Morningstar fair value diverge by >30%: investigate before proceeding. Usually means different growth assumptions — reconcile explicitly.

---

## VALUATION SYNTHESIS

**Agreement check:**
- DCF and comps agree within 20%: HIGH conviction on valuation
- DCF and comps agree within 30%: MEDIUM conviction
- Diverge >30%: investigate — probably structural difference in business model or growth assumption

**Weighting:**
- Scenario-weighted DCF: 60% weight
- Relative comps: 30% weight
- Morningstar fair value: 10% weight (independent cross-check)

**Output (always):**
- Intrinsic value: low / base / high (the three scenario outputs)
- Probability-weighted value
- Current price and upside %
- Margin of safety %
- Confidence: HIGH / MEDIUM / LOW with one-line rationale
- Key upside assumption: "If [X] materialises, upside increases to [Y]"
- Key downside risk: "If [Z] materialises, downside is [W]"
