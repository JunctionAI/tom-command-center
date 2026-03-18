"""
Walker Capital Management — Stage 4: Valuation Engine
Pulls all financial data via Perplexity, builds 3-scenario DCF, runs comps + Morningstar cross-check.
Triggered from Telegram: "Value [TICKER]"
"""

import os
import json
import logging
import re
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

NZ_TZ = ZoneInfo("Pacific/Auckland")
logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent.parent

# Risk-free rates and ERPs by market (March 2026 approximations)
RISK_FREE_RATES = {"NZX": 0.047, "ASX": 0.044, "NYSE": 0.043, "NASDAQ": 0.043, "US": 0.043}
EQUITY_RISK_PREMIA = {"NZX": 0.065, "ASX": 0.060, "NYSE": 0.055, "NASDAQ": 0.055, "US": 0.055}


def _call_perplexity(prompt: str, max_tokens: int = 1800) -> str:
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
        logger.error(f"Perplexity error in stage4: {e}")
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


def get_financial_data(ticker: str, exchange: str, name: str, research_brief: str = "") -> dict:
    """
    Pull all financial inputs needed for DCF + comps + Morningstar via Perplexity.
    Returns structured dict. Uses null for unknown values — never guesses.
    """
    brief_ctx = f"\n\nContext from research brief:\n{research_brief[:800]}" if research_brief else ""

    prompt = f"""You are a financial analyst. Research {name} ({ticker} on {exchange}) right now and return ONLY a JSON object.

CRITICAL:
- Use null for ANY value you cannot find from a real, verifiable source. Do NOT estimate or infer.
- All monetary values in the company's native reporting currency, in millions.
- Current price in native per-share currency (not millions).

{{
  "current_price": null,
  "currency": null,
  "market_cap_m": null,
  "shares_outstanding_m": null,
  "net_debt_m": null,
  "fcf_yr1_m": null,
  "fcf_yr2_m": null,
  "fcf_yr3_m": null,
  "fcf_ntm_estimate_m": null,
  "revenue_last_m": null,
  "ebitda_last_m": null,
  "ebit_last_m": null,
  "fwd_eps": null,
  "revenue_growth_3yr_avg": null,
  "fcf_growth_3yr_avg": null,
  "gross_margin": null,
  "beta_5yr": null,
  "cost_of_debt_pct": null,
  "debt_to_total_capital": null,
  "tax_rate": null,
  "ms_fair_value": null,
  "ms_moat": null,
  "ms_stars": null,
  "ms_stewardship": null,
  "peer_ev_ebitda_median": null,
  "peer_fwd_pe_median": null,
  "peer_ev_fcf_median": null,
  "company_ev_ebitda": null,
  "company_fwd_pe": null,
  "company_ev_fcf": null
}}

Return ONLY the JSON object. No commentary.{brief_ctx}"""

    raw = _call_perplexity(prompt, max_tokens=1500)
    data = _parse_json(raw)
    data["_exchange"] = exchange
    return data


def _build_fcf_forecasts(start_fcf: float, near_growth: float, mid_growth: float, terminal: float) -> list:
    """Build 10-year FCF forecast fading from near-term to mid to terminal growth."""
    forecasts = []
    fcf = start_fcf
    for year in range(1, 11):
        if year <= 3:
            g = near_growth
        elif year <= 7:
            fade = (year - 3) / 4.0
            g = near_growth * (1 - fade) + mid_growth * fade
        else:
            fade = (year - 7) / 3.0
            g = mid_growth * (1 - fade) + terminal * fade
        fcf = fcf * (1 + g)
        forecasts.append(fcf)
    return forecasts


def build_dcf_scenarios(data: dict, segment: str) -> tuple:
    """
    Build bull/base/bear DCF scenario inputs from Perplexity financial data.
    Returns (bull_inputs, base_inputs, bear_inputs, base_wacc) tuple.
    """
    shares = data.get("shares_outstanding_m") or 100
    net_debt = data.get("net_debt_m") or 0

    # Base FCF starting point
    base_fcf = (
        data.get("fcf_ntm_estimate_m") or
        data.get("fcf_yr1_m") or
        (data.get("ebitda_last_m", 0) * 0.55 if data.get("ebitda_last_m") else None)
    )
    if base_fcf is None:
        raise ValueError(f"No FCF data available — cannot run DCF")

    hist_growth = data.get("fcf_growth_3yr_avg") or data.get("revenue_growth_3yr_avg") or 0.08

    if segment == "B":
        bull_near, base_near, bear_near = max(hist_growth * 1.3, 0.30), hist_growth, hist_growth * 0.5
        bull_mid, base_mid, bear_mid = 0.20, 0.12, 0.04
    else:
        bull_near = min(hist_growth * 1.2, 0.20)
        base_near = hist_growth
        bear_near = hist_growth * 0.6
        bull_mid, base_mid, bear_mid = 0.10, 0.06, 0.02

    # WACC
    exchange = data.get("_exchange", "NZX")
    rf = RISK_FREE_RATES.get(exchange, 0.045)
    erp = EQUITY_RISK_PREMIA.get(exchange, 0.060)
    beta = data.get("beta_5yr") or 1.0
    kd = data.get("cost_of_debt_pct") or 0.055
    dw = data.get("debt_to_total_capital") or 0.20
    ew = 1 - dw
    tax = data.get("tax_rate") or 0.28

    ke = rf + beta * erp
    kd_at = kd * (1 - tax)
    base_wacc = ew * ke + dw * kd_at
    bull_wacc = max(base_wacc - 0.010, 0.06)
    bear_wacc = min(base_wacc + 0.015, 0.15)

    common = {"net_debt": net_debt, "shares_outstanding": shares}

    return (
        {"fcf_forecasts": _build_fcf_forecasts(base_fcf * 1.10, bull_near, bull_mid, 0.030), "wacc": bull_wacc, "terminal_growth": 0.030, **common},
        {"fcf_forecasts": _build_fcf_forecasts(base_fcf, base_near, base_mid, 0.025),         "wacc": base_wacc, "terminal_growth": 0.025, **common},
        {"fcf_forecasts": _build_fcf_forecasts(base_fcf * 0.90, bear_near, bear_mid, 0.015), "wacc": bear_wacc, "terminal_growth": 0.015, **common},
        base_wacc,
    )


def run_stage4(ticker: str, exchange: str, name: str, company_id: int,
               segment: str, research_brief: str = "") -> dict:
    """
    Full Stage 4: pull financials → build scenarios → run DCF → comps → save → return results.
    """
    from core.walker_valuation import scenario_weighted_dcf, comps_implied_value
    from core.walker_pipeline_db import save_valuation, advance_stage

    logger.info(f"Walker Stage 4 starting for {ticker} ({exchange})")

    data = get_financial_data(ticker, exchange, name, research_brief)

    current_price = data.get("current_price")
    if not current_price:
        return {"success": False, "error": "Could not retrieve current share price from Perplexity"}

    # DCF
    try:
        bull_in, base_in, bear_in, base_wacc = build_dcf_scenarios(data, segment)
    except ValueError as e:
        return {"success": False, "error": str(e)}

    try:
        dcf = scenario_weighted_dcf(
            bull_inputs=bull_in,
            base_inputs=base_in,
            bear_inputs=bear_in,
            current_price=current_price,
        )
    except Exception as e:
        return {"success": False, "error": f"DCF calculation error: {e}"}

    weighted_value = dcf["weighted_intrinsic_value"]
    margin_of_safety = dcf["margin_of_safety"]

    # Comps
    comps_implied = None
    try:
        if all(data.get(k) is not None for k in [
            "ebitda_last_m", "fcf_yr1_m", "fwd_eps",
            "peer_ev_ebitda_median", "peer_fwd_pe_median", "peer_ev_fcf_median"
        ]):
            cr = comps_implied_value(
                company_ebitda=data["ebitda_last_m"],
                company_fcf=data["fcf_yr1_m"],
                company_fwd_eps=data["fwd_eps"],
                peer_median_ev_ebitda=data["peer_ev_ebitda_median"],
                peer_median_fwd_pe=data["peer_fwd_pe_median"],
                peer_median_ev_fcf=data["peer_ev_fcf_median"],
                net_debt=data.get("net_debt_m", 0) or 0,
                shares=data.get("shares_outstanding_m", 100) or 100,
            )
            comps_implied = cr.get("blended_comps_value")
    except Exception as e:
        logger.warning(f"Comps failed for {ticker}: {e}")

    # Confidence
    ms_fair = data.get("ms_fair_value")
    dcf_comps_diff = (
        abs(weighted_value - comps_implied) / weighted_value
        if comps_implied and weighted_value else None
    )
    if dcf_comps_diff is not None and dcf_comps_diff < 0.20:
        confidence = "HIGH"
    elif dcf_comps_diff is not None and dcf_comps_diff < 0.30:
        confidence = "MEDIUM"
    elif dcf_comps_diff is None:
        confidence = "LOW — insufficient comps data"
    else:
        confidence = "LOW — DCF and comps diverge >30%"

    # Save to DB
    save_valuation(company_id, {
        "dcf_bull": dcf["bull_per_share"],
        "dcf_base": dcf["base_per_share"],
        "dcf_bear": dcf["bear_per_share"],
        "dcf_weighted": weighted_value,
        "dcf_wacc": base_wacc,
        "dcf_terminal_growth": base_in["terminal_growth"],
        "comps_ev_ebitda": data.get("company_ev_ebitda"),
        "comps_fwd_pe": data.get("company_fwd_pe"),
        "comps_ev_fcf": data.get("company_ev_fcf"),
        "comps_implied_value": comps_implied,
        "ms_fair_value": ms_fair,
        "ms_moat": data.get("ms_moat"),
        "ms_stars": data.get("ms_stars"),
        "ms_stewardship": data.get("ms_stewardship"),
        "current_price": current_price,
        "weighted_intrinsic_value": weighted_value,
        "margin_of_safety": margin_of_safety,
        "valuation_confidence": confidence,
        "sensitivity_table": {},
    })

    if margin_of_safety >= 0.20:
        advance_stage(company_id, "VALUED")
        logger.info(f"{ticker} → VALUED (MoS={margin_of_safety:.1%})")
    else:
        advance_stage(company_id, "WATCHING", notes=f"MoS {margin_of_safety:.1%} < 20%")
        logger.info(f"{ticker} → WATCHING (MoS={margin_of_safety:.1%})")

    return {
        "success": True,
        "passes_threshold": margin_of_safety >= 0.20,
        "ticker": ticker,
        "current_price": current_price,
        "currency": data.get("currency", ""),
        "dcf_bull": dcf["bull_per_share"],
        "dcf_base": dcf["base_per_share"],
        "dcf_bear": dcf["bear_per_share"],
        "weighted_value": weighted_value,
        "margin_of_safety": margin_of_safety,
        "upside_pct": dcf["upside_pct"],
        "confidence": confidence,
        "ms_fair_value": ms_fair,
        "ms_moat": data.get("ms_moat"),
        "ms_stars": data.get("ms_stars"),
        "ms_stewardship": data.get("ms_stewardship"),
        "comps_implied": comps_implied,
        "base_wacc": base_wacc,
        "raw_data": data,
    }
