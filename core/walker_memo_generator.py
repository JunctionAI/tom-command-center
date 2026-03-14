"""
Walker Capital Management — Investment Memo Generator
Stage 7: Synthesises all pipeline data into a decision-ready one-page memo.
Uses Claude Opus 4.6. Delivers to Telegram (Tom + Trent simultaneously).
"""

import os
import json
import logging
from datetime import datetime
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent


def generate_investment_memo(company_profile: dict) -> str:
    """
    Take a full company profile from walker_pipeline_db.get_company_full_profile()
    and generate the one-page investment memo via Opus 4.6.
    Returns the formatted memo as a string.
    """
    company = company_profile
    val = company.get('valuation', {})
    risk = company.get('risk', {})
    sim = company.get('simulation', {})
    research = company.get('research', {})

    # Format sensitivity table
    sensitivity_raw = val.get('sensitivity_table', '{}')
    try:
        sensitivity = json.loads(sensitivity_raw) if isinstance(sensitivity_raw, str) else sensitivity_raw
    except Exception:
        sensitivity = {}

    # Format earnings flags
    flags_raw = risk.get('earnings_quality_flags', '[]')
    try:
        flags = json.loads(flags_raw) if isinstance(flags_raw, str) else flags_raw
    except Exception:
        flags = []

    # Format fisher breakdown
    fisher_strengths_raw = risk.get('fisher_strengths', '[]')
    fisher_concerns_raw = risk.get('fisher_concerns', '[]')
    try:
        fisher_strengths = json.loads(fisher_strengths_raw) if isinstance(fisher_strengths_raw, str) else fisher_strengths_raw
        fisher_concerns = json.loads(fisher_concerns_raw) if isinstance(fisher_concerns_raw, str) else fisher_concerns_raw
    except Exception:
        fisher_strengths = []
        fisher_concerns = []

    system_prompt = """You are Vesper, the investment analyst for Walker Capital Management.
Your job is to write a precise, decision-ready one-page investment memo.
Be clinical, factual, and specific. No filler. Every line must earn its place.
Format for Telegram delivery — use plain text with ━ dividers and clear sections.
Recommend BUY, WATCH, or AVOID based on all the evidence."""

    data_context = f"""
COMPANY: {company.get('name')} | {company.get('ticker')} | {company.get('exchange')}
SEGMENT: {'A (Mature)' if company.get('segment') == 'A' else 'B (Growth/Early-stage)'}
CATALYST ({company.get('catalyst_score', 0)}/3): {company.get('catalyst_description', 'Not recorded')}

VALUATION DATA:
- DCF Bull (25%): ${val.get('dcf_bull', 'N/A')} | Base (50%): ${val.get('dcf_base', 'N/A')} | Bear (25%): ${val.get('dcf_bear', 'N/A')}
- Weighted intrinsic value: ${val.get('weighted_intrinsic_value', 'N/A')}
- Current price: ${val.get('current_price', 'N/A')}
- Margin of safety: {val.get('margin_of_safety', 0) * 100:.1f}% (need ≥ 20%)
- Valuation confidence: {val.get('valuation_confidence', 'N/A')}
- WACC used: {val.get('dcf_wacc', 'N/A')}
- Comps EV/EBITDA: {val.get('comps_ev_ebitda', 'N/A')} | Fwd P/E: {val.get('comps_fwd_pe', 'N/A')} | EV/FCF: {val.get('comps_ev_fcf', 'N/A')}
- Comps implied value: ${val.get('comps_implied_value', 'N/A')}
- Morningstar fair value: ${val.get('ms_fair_value', 'N/A')} | Moat: {val.get('ms_moat', 'N/A')} | Stars: {val.get('ms_stars', 'N/A')}/5 | Stewardship: {val.get('ms_stewardship', 'N/A')}

RISK DATA:
- VaR 95% (1yr): {risk.get('var_95', 'N/A')}% | VaR 99% (1yr): {risk.get('var_99', 'N/A')}%
- CVaR 99%: {risk.get('cvar_99', 'N/A')}%
- Altman Z: {risk.get('altman_z', 'N/A')} [{risk.get('altman_zone', 'N/A')}]
- FCF Conversion: {risk.get('fcf_conversion', 'N/A')}
- Earnings quality flags ({len(flags)}): {'; '.join(flags) if flags else 'None'}

FISHER ANALYSIS:
- Total score: {risk.get('fisher_score', 'N/A')}/75
- Strengths: {'; '.join(fisher_strengths) if fisher_strengths else 'N/A'}
- Concerns: {'; '.join(fisher_concerns) if fisher_concerns else 'N/A'}

CONVICTION SCORE: {risk.get('conviction_score', 'N/A')}/10

MIROFISH SIMULATION:
- Market share 1yr: {sim.get('market_share_1yr', 'Not run')}
- Market share 3yr: {sim.get('market_share_3yr', 'Not run')}
- Market share 5yr: {sim.get('market_share_5yr', 'Not run')}
- TAM today: {sim.get('tam_current', 'N/A')} | 1yr: {sim.get('tam_1yr', 'N/A')} | 3yr: {sim.get('tam_3yr', 'N/A')} | 5yr: {sim.get('tam_5yr', 'N/A')}
- Key competitive risk: {sim.get('key_competitive_risk', 'Not run')}
- Bull scenario: {sim.get('bull_scenario', 'Not run')}
- Base scenario: {sim.get('base_scenario', 'Not run')}
- Bear scenario: {sim.get('bear_scenario', 'Not run')}

RESEARCH HIGHLIGHTS:
Bear case: {research.get('bear_case', 'N/A')[:300] if research.get('bear_case') else 'N/A'}
"""

    user_prompt = f"""Generate the Walker Capital investment memo for this company.

{data_context}

Format exactly as follows:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🏦 WALKER CAPITAL — INVESTMENT MEMO
{company.get('name', '')} | {company.get('ticker', '')} | {company.get('exchange', '')}
{datetime.now().strftime('%d %b %Y')} | Analyst: Vesper
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RECOMMENDATION: [BUY / WATCH / AVOID]
Entry: $X | Target: $X (XX% upside) | Stop: $X
Time horizon: XX months | Conviction: X/10

📌 CATALYST
[One precise sentence — what the step-change is and why now]

📊 SCENARIO-WEIGHTED DCF
Bull $X (25%) | Base $X (50%) | Bear $X (25%)
Weighted value: $X | Current: $X
Upside: XX% | Margin of safety: XX%
Confidence: [HIGH / MEDIUM / LOW — one line why]

🔍 COMPS CHECK
EV/EBITDA: X vs peers Y | Fwd P/E: X vs peers Y
Morningstar FV: $X | Moat: [Wide/Narrow/None] | ⭐[X]/5
Signal: [CHEAP / FAIR / RICH]

⚠️ RISK
VaR 99% (1yr): XX% | CVaR 99%: XX%
Altman Z: X.X [[SAFE/GREY/DISTRESS] — context note if Segment B]
FCF Conversion: XX% [[CLEAN/MONITOR/FLAG]]
EQ flags: X/10 [list if any]

🎯 FISHER ANALYSIS
Score: XX/75
Strengths: [Top 3, one line each]
Concerns: [Top 2, one line each]

🌊 MIROFISH SIMULATION
[Include only if simulation was run, otherwise omit this section]
Share trajectory: [1yr] → [3yr] → [5yr]
TAM: $X → $X (1yr) → $X (3yr) → $X (5yr)
Key risk: [One sentence]

✅ WHAT MUST REMAIN TRUE
1. [Exit trigger — be specific]
2. [Exit trigger — be specific]
3. [Exit trigger — be specific]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Reply: BUY | WATCH | AVOID — Trent Walker
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

    try:
        client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1500,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
        memo = response.content[0].text
        logger.info(f"Memo generated for {company.get('ticker')}: {len(memo)} chars")
        return memo
    except Exception as e:
        logger.error(f"Memo generation failed: {e}")
        return f"ERROR: Could not generate memo for {company.get('ticker')}: {e}"


def generate_daily_pipeline_brief(pipeline_summary: dict, recent_discoveries: list) -> str:
    """
    7am daily pipeline status brief for Tom and Trent.
    """
    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🏦 WALKER CAPITAL — DAILY BRIEF",
        f"{datetime.now().strftime('%A %d %b %Y, %H:%M')}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        "📊 PIPELINE STATUS",
    ]

    stage_labels = {
        "DISCOVERED": "Discovery",
        "SCREENED": "Screened",
        "RESEARCHED": "Deep Research",
        "VALUED": "Valued",
        "RISK_ASSESSED": "Risk Assessed",
        "SIMULATED": "MiroFish",
        "DECISION_READY": "Decision Ready",
        "APPROVED": "Approved (Portfolio)",
        "WATCHING": "Watchlist",
        "REJECTED": "Rejected",
    }

    for stage, label in stage_labels.items():
        count = pipeline_summary.get(stage, 0)
        if count > 0:
            lines.append(f"{label}: {count}")

    if recent_discoveries:
        lines.append("")
        lines.append("🔍 NEW DISCOVERIES TODAY")
        for d in recent_discoveries[:5]:
            lines.append(f"• {d.get('name', '')} ({d.get('ticker', '')}) — {d.get('discovery_thesis', '')[:80]}")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("Reply /pipeline for full details | /screen [ticker] to add a company")

    return "\n".join(lines)
