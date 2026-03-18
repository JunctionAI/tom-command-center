"""
Walker Capital Management — Stage 5: Risk Assessment
VaR + CVaR via yfinance price history
Altman Z-Score + FCF Conversion + Earnings Quality via Perplexity
Fisher 15-Point Analysis via Claude Opus
Conviction Score synthesis
"""

import os
import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

NZ_TZ = ZoneInfo("Pacific/Auckland")
logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent

FISHER_SKILL = BASE_DIR / "agents" / "walker-capital" / "skills" / "fisher-analysis.md"


def _yf_ticker(ticker: str, exchange: str) -> str:
    ex = exchange.upper()
    t = ticker.upper()
    if ex == "NZX":
        return f"{t}.NZ"
    elif ex == "ASX":
        return f"{t}.AX"
    return t


def _call_perplexity(prompt: str, max_tokens: int = 1500) -> str:
    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=os.environ.get("PERPLEXITY_API_KEY", ""),
            base_url="https://api.perplexity.ai"
        )
        r = client.chat.completions.create(
            model="sonar-pro",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        return r.choices[0].message.content
    except Exception as e:
        logger.error(f"Perplexity error in stage5: {e}")
        return ""


def _parse_json(raw: str) -> dict:
    try:
        clean = re.sub(r'```(?:json)?\s*', '', raw).strip()
        match = re.search(r'\{.*\}', clean, re.DOTALL)
        if match:
            return json.loads(match.group())
    except Exception as e:
        logger.warning(f"JSON parse failed: {e}")
    return {}


def get_price_history(ticker: str, exchange: str) -> list:
    """Get 5yr daily returns via yfinance for VaR calculation."""
    try:
        import yfinance as yf
        yf_t = _yf_ticker(ticker, exchange)
        end = datetime.now()
        start = end - timedelta(days=5 * 365)
        hist = yf.download(yf_t, start=start, end=end, auto_adjust=True, progress=False)
        if hist.empty:
            logger.warning(f"No price history from yfinance for {yf_t}")
            return []
        closes = hist["Close"].squeeze().dropna()
        returns = closes.pct_change().dropna().tolist()
        logger.info(f"Got {len(returns)} daily returns for {yf_t}")
        return returns
    except Exception as e:
        logger.error(f"yfinance error for {ticker}: {e}")
        return []


def get_balance_sheet_data(ticker: str, exchange: str, name: str) -> dict:
    """Perplexity pull for Altman Z + earnings quality inputs."""
    prompt = f"""Research {name} ({ticker} on {exchange}). Return ONLY a JSON object with balance sheet and earnings quality data.
Use null for any value you cannot verify from a real source. All monetary values in millions (reporting currency).

{{
  "working_capital_m": null,
  "total_assets_m": null,
  "retained_earnings_m": null,
  "ebit_m": null,
  "total_liabilities_m": null,
  "revenue_m": null,
  "operating_cash_flow_m": null,
  "net_income_m": null,
  "receivables_growth": null,
  "revenue_growth": null,
  "inventory_growth": null,
  "cogs_growth": null,
  "gross_margin_current": null,
  "gross_margin_prior": null,
  "da_current_m": null,
  "da_prior_m": null,
  "goodwill_m": null,
  "net_debt_current_m": null,
  "net_debt_prior_m": null,
  "ebitda_growth": null,
  "exceptional_items_years": null
}}

Return ONLY the JSON."""
    raw = _call_perplexity(prompt, max_tokens=1200)
    return _parse_json(raw)


def score_fisher_analysis(ticker: str, name: str, research_brief: str, claude_client) -> dict:
    """
    Score all 15 Fisher points via Claude Opus using research brief + world knowledge.
    Returns dict with scores, total, strengths, concerns.
    """
    fisher_text = ""
    try:
        fisher_text = FISHER_SKILL.read_text()[:2500]
    except Exception:
        pass

    prompt = f"""You are Vesper, the investment analyst for Walker Capital Management.
Score all 15 Fisher points for {name} ({ticker}) based on the research brief below and your knowledge of this company.

{fisher_text}

RESEARCH BRIEF:
{research_brief[:2500] if research_brief else "Not available — use your general knowledge of this company."}

Return a JSON object with this exact structure:
{{
  "scores": {{
    "1_market_potential": {{"score": 3, "rationale": "one sentence"}},
    "2_new_product_development": {{"score": 3, "rationale": "one sentence"}},
    "3_rd_effectiveness": {{"score": 3, "rationale": "one sentence"}},
    "4_sales_organisation": {{"score": 3, "rationale": "one sentence"}},
    "5_profit_margins": {{"score": 3, "rationale": "one sentence"}},
    "6_margin_improvement": {{"score": 3, "rationale": "one sentence"}},
    "7_labour_relations": {{"score": 3, "rationale": "one sentence"}},
    "8_executive_relations": {{"score": 3, "rationale": "one sentence"}},
    "9_management_depth": {{"score": 3, "rationale": "one sentence"}},
    "10_cost_controls": {{"score": 3, "rationale": "one sentence"}},
    "11_industry_factors": {{"score": 3, "rationale": "one sentence"}},
    "12_long_term_outlook": {{"score": 3, "rationale": "one sentence"}},
    "13_dilution_risk": {{"score": 3, "rationale": "one sentence"}},
    "14_transparency": {{"score": 3, "rationale": "one sentence"}},
    "15_integrity": {{"score": 3, "rationale": "one sentence"}}
  }},
  "total_score": 45,
  "top_strengths": ["Point 1: ...", "Point 2: ...", "Point 3: ..."],
  "top_concerns": ["Point 1: ...", "Point 2: ..."]
}}

Be honest and specific. Score 1-5 per point. Return ONLY the JSON."""

    try:
        response = claude_client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text
        result = _parse_json(raw)
        if result:
            # Recalculate total from individual scores for accuracy
            scores = result.get("scores", {})
            total = sum(v.get("score", 0) for v in scores.values() if isinstance(v, dict))
            if total > 0:
                result["total_score"] = total
            return result
    except Exception as e:
        logger.error(f"Fisher analysis failed for {ticker}: {e}")

    return {"total_score": None, "top_strengths": [], "top_concerns": [], "scores": {}}


def run_stage5(ticker: str, exchange: str, name: str, company_id: int,
               segment: str, research_brief: str, valuation_data: dict) -> dict:
    """
    Full Stage 5: VaR + Altman Z + FCF conversion + earnings quality + Fisher + conviction.
    Saves to risk_assessments table. Returns structured result.
    """
    from core.walker_valuation import (
        calculate_var_cvar, altman_z_score, fcf_conversion,
        check_earnings_quality, calculate_conviction_score
    )
    from core.walker_pipeline_db import save_risk_assessment, advance_stage
    import anthropic

    logger.info(f"Walker Stage 5 starting for {ticker}")
    claude = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    # ── 1. VaR via yfinance ──────────────────────────────────────────────────
    daily_returns = get_price_history(ticker, exchange)
    var_data = {}
    if len(daily_returns) >= 100:
        try:
            var_data = calculate_var_cvar(daily_returns)
            logger.info(f"VaR99={var_data.get('var_99')}% for {ticker}")
        except Exception as e:
            logger.warning(f"VaR failed for {ticker}: {e}")
    else:
        logger.warning(f"Insufficient price history for VaR: {len(daily_returns)} days")

    # ── 2. Balance sheet data via Perplexity ─────────────────────────────────
    bs = get_balance_sheet_data(ticker, exchange, name)

    # ── 3. Altman Z-Score ────────────────────────────────────────────────────
    z_result = {}
    z_keys = ["working_capital_m", "total_assets_m", "retained_earnings_m",
              "ebit_m", "total_liabilities_m", "revenue_m"]
    if all(bs.get(k) is not None for k in z_keys):
        try:
            market_cap = valuation_data.get("raw_data", {}).get("market_cap_m") or 0
            z_result = altman_z_score(
                working_capital=bs["working_capital_m"],
                total_assets=bs["total_assets_m"],
                retained_earnings=bs["retained_earnings_m"],
                ebit=bs["ebit_m"],
                market_cap=market_cap,
                total_liabilities=bs["total_liabilities_m"],
                revenue=bs["revenue_m"],
            )
        except Exception as e:
            logger.warning(f"Altman Z failed for {ticker}: {e}")

    # ── 4. FCF Conversion ────────────────────────────────────────────────────
    fcf_result = {}
    ocf = bs.get("operating_cash_flow_m")
    ni = bs.get("net_income_m")
    if ocf is not None and ni is not None:
        try:
            fcf_result = fcf_conversion(ocf, ni)
        except Exception as e:
            logger.warning(f"FCF conversion failed for {ticker}: {e}")

    # ── 5. Earnings Quality ──────────────────────────────────────────────────
    eq_result = {"flags": [], "flag_count": 0, "quality_label": "INSUFFICIENT DATA"}
    eq_keys = ["receivables_growth", "revenue_growth", "gross_margin_current"]
    if all(bs.get(k) is not None for k in eq_keys):
        try:
            eq_result = check_earnings_quality(
                revenue_growth=bs.get("revenue_growth", 0),
                receivables_growth=bs.get("receivables_growth", 0),
                inventory_growth=bs.get("inventory_growth") or 0,
                cogs_growth=bs.get("cogs_growth") or 0,
                gross_margin_current=bs.get("gross_margin_current", 0),
                gross_margin_prior=bs.get("gross_margin_prior") or bs.get("gross_margin_current", 0),
                da_current=bs.get("da_current_m") or 0,
                da_prior=bs.get("da_prior_m") or 0,
                total_assets_current=bs.get("total_assets_m") or 1,
                total_assets_prior=bs.get("total_assets_m") or 1,
                exceptional_items_count=bs.get("exceptional_items_years") or 0,
                goodwill=bs.get("goodwill_m") or 0,
                total_assets=bs.get("total_assets_m") or 1,
                net_debt_current=bs.get("net_debt_current_m") or 0,
                net_debt_prior=bs.get("net_debt_prior_m") or 0,
                ebitda_growth=bs.get("ebitda_growth") or 0,
            )
        except Exception as e:
            logger.warning(f"Earnings quality check failed for {ticker}: {e}")

    # ── 6. Fisher Analysis via Claude Opus ───────────────────────────────────
    fisher = score_fisher_analysis(ticker, name, research_brief, claude)
    fisher_score = fisher.get("total_score") or 0

    # ── 7. Conviction Score ──────────────────────────────────────────────────
    margin_of_safety = valuation_data.get("margin_of_safety", 0)
    weighted_value = valuation_data.get("weighted_value") or 1
    comps_implied = valuation_data.get("comps_implied")
    dcf_comps_diff = (
        abs(weighted_value - comps_implied) / weighted_value
        if comps_implied else 0.25
    )

    # Pull catalyst score from pipeline DB
    catalyst_score = 2  # Default moderate
    try:
        from core.walker_pipeline_db import get_companies_at_stage
        for stage in ["VALUED", "RESEARCHED", "SCREENED", "DISCOVERED"]:
            for c in get_companies_at_stage(stage):
                if c["id"] == company_id:
                    catalyst_score = c.get("catalyst_score") or 2
                    break
    except Exception:
        pass

    conviction_result = {}
    try:
        conviction_result = calculate_conviction_score(
            margin_of_safety=margin_of_safety,
            dcf_comps_agreement=dcf_comps_diff,
            catalyst_score=catalyst_score,
            fisher_score=fisher_score,
            flag_count=eq_result.get("flag_count", 0),
            altman_zone=z_result.get("zone", "GREY"),
            segment=segment,
            var_99=var_data.get("var_99"),
            ms_moat=valuation_data.get("ms_moat"),
        )
    except Exception as e:
        logger.warning(f"Conviction score failed for {ticker}: {e}")
        conviction_result = {"conviction_score": 5.0, "label": "N/A", "proceed": True, "mirofish_eligible": False}

    conviction_score = conviction_result.get("conviction_score", 5.0)

    # ── Save to DB ───────────────────────────────────────────────────────────
    save_risk_assessment(company_id, {
        "var_95": var_data.get("var_95"),
        "var_99": var_data.get("var_99"),
        "cvar_99": var_data.get("cvar_99"),
        "altman_z": z_result.get("z_score"),
        "altman_zone": z_result.get("zone"),
        "fcf_conversion": fcf_result.get("ratio_pct"),
        "earnings_quality_flags": eq_result.get("flags", []),
        "fisher_score": fisher_score,
        "fisher_breakdown": fisher.get("scores", {}),
        "fisher_strengths": fisher.get("top_strengths", []),
        "fisher_concerns": fisher.get("top_concerns", []),
        "conviction_score": conviction_score,
    })
    advance_stage(company_id, "RISK_ASSESSED")
    logger.info(f"{ticker} → RISK_ASSESSED (conviction={conviction_score}/10)")

    return {
        "success": True,
        "ticker": ticker,
        "var_95": var_data.get("var_95"),
        "var_99": var_data.get("var_99"),
        "cvar_99": var_data.get("cvar_99"),
        "altman_z": z_result.get("z_score"),
        "altman_zone": z_result.get("zone", "N/A"),
        "fcf_conversion": fcf_result.get("ratio_pct"),
        "fcf_label": fcf_result.get("label", "N/A"),
        "earnings_flags": eq_result.get("flags", []),
        "flag_count": eq_result.get("flag_count", 0),
        "fisher_score": fisher_score,
        "fisher_strengths": fisher.get("top_strengths", []),
        "fisher_concerns": fisher.get("top_concerns", []),
        "conviction_score": conviction_score,
        "conviction_label": conviction_result.get("label", "N/A"),
        "mirofish_eligible": conviction_result.get("mirofish_eligible", False),
        "proceed": conviction_result.get("proceed", True),
    }
