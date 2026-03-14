"""
Walker Capital Management — Valuation Engine
Scenario-weighted DCF, relative comps, Altman Z-Score, VaR, FCF conversion.
All maths runs here. Claude synthesises the output.
"""

import numpy as np
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# SCENARIO-WEIGHTED DCF
# ─────────────────────────────────────────────

def calculate_dcf(
    fcf_forecasts: list,        # List of FCF values, years 1-10
    wacc: float,                # e.g. 0.09 for 9%
    terminal_growth: float,     # e.g. 0.025 for 2.5%
    net_debt: float,            # Positive = net debt, negative = net cash
    shares_outstanding: float,  # Diluted shares
    non_core_assets: float = 0.0
) -> dict:
    """
    Calculate equity value per share via DCF.
    Returns: enterprise_value, equity_value, per_share_value, pv_fcfs, pv_terminal
    """
    if wacc <= terminal_growth:
        raise ValueError(f"WACC ({wacc:.1%}) must exceed terminal growth ({terminal_growth:.1%})")

    # PV of explicit forecast period
    pv_fcfs = []
    for i, fcf in enumerate(fcf_forecasts, start=1):
        pv = fcf / ((1 + wacc) ** i)
        pv_fcfs.append(pv)

    total_pv_fcf = sum(pv_fcfs)

    # Terminal value (Gordon Growth) discounted back
    terminal_fcf = fcf_forecasts[-1] * (1 + terminal_growth)
    terminal_value = terminal_fcf / (wacc - terminal_growth)
    pv_terminal = terminal_value / ((1 + wacc) ** len(fcf_forecasts))

    enterprise_value = total_pv_fcf + pv_terminal
    equity_value = enterprise_value - net_debt + non_core_assets
    per_share = equity_value / shares_outstanding if shares_outstanding > 0 else 0

    terminal_pct = (pv_terminal / enterprise_value * 100) if enterprise_value > 0 else 0

    return {
        'enterprise_value': enterprise_value,
        'equity_value': equity_value,
        'per_share_value': per_share,
        'pv_explicit_fcfs': total_pv_fcf,
        'pv_terminal_value': pv_terminal,
        'terminal_value_pct': terminal_pct,
        'wacc': wacc,
        'terminal_growth': terminal_growth,
    }


def scenario_weighted_dcf(
    bull_inputs: dict,    # {fcf_forecasts, wacc, terminal_growth, net_debt, shares, non_core}
    base_inputs: dict,
    bear_inputs: dict,
    current_price: float,
    bull_prob: float = 0.25,
    base_prob: float = 0.50,
    bear_prob: float = 0.25,
) -> dict:
    """
    Run DCF for all three scenarios and return weighted intrinsic value.
    """
    bull_result = calculate_dcf(**bull_inputs)
    base_result = calculate_dcf(**base_inputs)
    bear_result = calculate_dcf(**bear_inputs)

    weighted_value = (
        bull_result['per_share_value'] * bull_prob +
        base_result['per_share_value'] * base_prob +
        bear_result['per_share_value'] * bear_prob
    )

    margin_of_safety = (weighted_value - current_price) / weighted_value if weighted_value > 0 else -1
    upside_pct = (weighted_value - current_price) / current_price if current_price > 0 else 0

    return {
        'bull': bull_result,
        'base': base_result,
        'bear': bear_result,
        'bull_per_share': bull_result['per_share_value'],
        'base_per_share': base_result['per_share_value'],
        'bear_per_share': bear_result['per_share_value'],
        'weighted_intrinsic_value': weighted_value,
        'current_price': current_price,
        'margin_of_safety': margin_of_safety,
        'margin_of_safety_pct': margin_of_safety * 100,
        'upside_pct': upside_pct * 100,
        'passes_threshold': margin_of_safety >= 0.20,
    }


def sensitivity_table(
    base_fcf_forecasts: list,
    base_wacc: float,
    base_terminal_growth: float,
    net_debt: float,
    shares: float,
    wacc_range: list = [-0.01, 0.0, 0.01, 0.02],
    growth_range: list = [-0.01, 0.0, 0.01, 0.02],
) -> dict:
    """
    Generate sensitivity table: WACC × terminal growth → per-share value.
    Returns dict of dicts: table[growth_delta][wacc_delta] = per_share_value
    """
    table = {}
    for g_delta in growth_range:
        g_label = f"{g_delta:+.0%}"
        table[g_label] = {}
        for w_delta in wacc_range:
            w_label = f"{w_delta:+.0%}"
            try:
                result = calculate_dcf(
                    fcf_forecasts=base_fcf_forecasts,
                    wacc=base_wacc + w_delta,
                    terminal_growth=base_terminal_growth + g_delta,
                    net_debt=net_debt,
                    shares_outstanding=shares,
                )
                table[g_label][w_label] = round(result['per_share_value'], 2)
            except ValueError:
                table[g_label][w_label] = None
    return table


# ─────────────────────────────────────────────
# WACC CALCULATOR
# ─────────────────────────────────────────────

def calculate_wacc(
    risk_free_rate: float,      # e.g. 0.045 for 4.5%
    equity_risk_premium: float, # e.g. 0.065 for NZ
    beta: float,
    cost_of_debt: float,        # Pre-tax
    tax_rate: float,
    equity_weight: float,       # E/(E+D)
    debt_weight: float,         # D/(E+D)
) -> dict:
    cost_of_equity = risk_free_rate + beta * equity_risk_premium
    after_tax_cost_of_debt = cost_of_debt * (1 - tax_rate)
    wacc = equity_weight * cost_of_equity + debt_weight * after_tax_cost_of_debt
    return {
        'cost_of_equity': cost_of_equity,
        'after_tax_cost_of_debt': after_tax_cost_of_debt,
        'wacc': wacc,
        'equity_weight': equity_weight,
        'debt_weight': debt_weight,
    }


# ─────────────────────────────────────────────
# RELATIVE COMPS
# ─────────────────────────────────────────────

def comps_implied_value(
    company_ebitda: float,
    company_fcf: float,
    company_fwd_eps: float,
    peer_median_ev_ebitda: float,
    peer_median_fwd_pe: float,
    peer_median_ev_fcf: float,
    net_debt: float,
    shares: float,
) -> dict:
    """
    Calculate implied equity value from three comps multiples.
    Returns per-share implied value for each multiple and a blended estimate.
    """
    # EV/EBITDA implied
    ev_from_ebitda = company_ebitda * peer_median_ev_ebitda
    equity_from_ebitda = (ev_from_ebitda - net_debt) / shares if shares > 0 else 0

    # EV/FCF implied
    ev_from_fcf = company_fcf * peer_median_ev_fcf
    equity_from_fcf = (ev_from_fcf - net_debt) / shares if shares > 0 else 0

    # Forward P/E implied (already equity-level multiple)
    equity_from_pe = company_fwd_eps * peer_median_fwd_pe

    # Blended (equal weight across three methods)
    blended = (equity_from_ebitda + equity_from_fcf + equity_from_pe) / 3

    return {
        'implied_from_ev_ebitda': equity_from_ebitda,
        'implied_from_ev_fcf': equity_from_fcf,
        'implied_from_fwd_pe': equity_from_pe,
        'blended_comps_value': blended,
        'peer_median_ev_ebitda': peer_median_ev_ebitda,
        'peer_median_fwd_pe': peer_median_fwd_pe,
        'peer_median_ev_fcf': peer_median_ev_fcf,
    }


def comps_signal(company_multiple: float, peer_median: float, threshold_cheap: float = 0.85, threshold_rich: float = 1.15) -> str:
    """Returns CHEAP / FAIR / RICH relative to peer median."""
    if peer_median == 0:
        return "N/A"
    ratio = company_multiple / peer_median
    if ratio < threshold_cheap:
        return "CHEAP"
    elif ratio > threshold_rich:
        return "RICH"
    return "FAIR"


# ─────────────────────────────────────────────
# ALTMAN Z-SCORE
# ─────────────────────────────────────────────

def altman_z_score(
    working_capital: float,
    total_assets: float,
    retained_earnings: float,
    ebit: float,
    market_cap: float,
    total_liabilities: float,
    revenue: float,
) -> dict:
    """
    Calculate Altman Z-Score.
    Growth/early-stage companies often score low — interpret with segment context.
    """
    if total_assets == 0:
        return {'z_score': None, 'zone': 'INSUFFICIENT_DATA', 'interpretation': 'Cannot calculate'}

    x1 = working_capital / total_assets
    x2 = retained_earnings / total_assets
    x3 = ebit / total_assets
    x4 = market_cap / total_liabilities if total_liabilities > 0 else 0
    x5 = revenue / total_assets

    z = 1.2 * x1 + 1.4 * x2 + 3.3 * x3 + 0.6 * x4 + 1.0 * x5

    if z > 2.99:
        zone = 'SAFE'
        interpretation = 'Low bankruptcy risk'
    elif z >= 1.81:
        zone = 'GREY'
        interpretation = 'Monitor leverage trajectory closely'
    else:
        zone = 'DISTRESS'
        interpretation = 'Elevated risk — assess segment context (expected for Segment B growth companies)'

    return {
        'z_score': round(z, 2),
        'zone': zone,
        'interpretation': interpretation,
        'x1_working_capital_ratio': round(x1, 3),
        'x2_retained_earnings_ratio': round(x2, 3),
        'x3_ebit_ratio': round(x3, 3),
        'x4_market_to_liabilities': round(x4, 3),
        'x5_asset_turnover': round(x5, 3),
    }


# ─────────────────────────────────────────────
# FCF CONVERSION
# ─────────────────────────────────────────────

def fcf_conversion(operating_cash_flow: float, net_income: float) -> dict:
    """
    FCF Conversion = Operating Cash Flow / Net Income.
    Below 80% = flag. Negative net income = not applicable.
    """
    if net_income <= 0:
        return {
            'ratio': None,
            'ratio_pct': None,
            'flag': False,
            'interpretation': 'Net income negative — FCF conversion not applicable (Segment B typical)',
        }

    ratio = operating_cash_flow / net_income
    flag = ratio < 0.80

    if ratio >= 1.0:
        label = 'EXCELLENT'
    elif ratio >= 0.80:
        label = 'HEALTHY'
    elif ratio >= 0.60:
        label = 'MONITOR'
    else:
        label = 'FLAG — investigate earnings quality'

    return {
        'ratio': round(ratio, 3),
        'ratio_pct': round(ratio * 100, 1),
        'flag': flag,
        'label': label,
        'interpretation': label,
    }


# ─────────────────────────────────────────────
# VAR / CVAR (Historical Simulation)
# ─────────────────────────────────────────────

def calculate_var_cvar(
    daily_returns: list,
    confidence_levels: list = [0.95, 0.99],
    horizon_days: int = 252,
) -> dict:
    """
    Historical simulation VaR and CVaR.
    daily_returns: list of daily return floats (e.g. 0.012 for +1.2%)
    Returns VaR and CVaR at each confidence level, annualised.
    """
    returns = np.array(daily_returns)
    # Scale to annual using square root of time
    annual_returns = returns * np.sqrt(horizon_days)
    sorted_returns = np.sort(annual_returns)

    results = {}
    for conf in confidence_levels:
        cutoff_idx = int((1 - conf) * len(sorted_returns))
        var = abs(sorted_returns[cutoff_idx]) if cutoff_idx < len(sorted_returns) else None
        cvar = abs(sorted_returns[:max(cutoff_idx, 1)].mean()) if cutoff_idx > 0 else None
        results[f'var_{int(conf*100)}'] = round(var * 100, 2) if var is not None else None
        results[f'cvar_{int(conf*100)}'] = round(cvar * 100, 2) if cvar is not None else None

    # Expected return and volatility
    results['expected_annual_return_pct'] = round(float(np.mean(annual_returns) * 100), 2)
    results['annual_volatility_pct'] = round(float(np.std(annual_returns) * 100), 2)
    results['sharpe_ratio'] = round(
        float(np.mean(annual_returns) / np.std(annual_returns)) if np.std(annual_returns) > 0 else 0, 2
    )
    results['sample_size'] = len(daily_returns)

    return results


# ─────────────────────────────────────────────
# EARNINGS QUALITY FLAGS
# ─────────────────────────────────────────────

def check_earnings_quality(
    revenue_growth: float,
    receivables_growth: float,
    inventory_growth: float,
    cogs_growth: float,
    gross_margin_current: float,
    gross_margin_prior: float,
    da_current: float,
    da_prior: float,
    total_assets_current: float,
    total_assets_prior: float,
    exceptional_items_count: int,  # Number of years with "exceptional" charges
    goodwill: float,
    total_assets: float,
    net_debt_current: float,
    net_debt_prior: float,
    ebitda_growth: float,
) -> dict:
    """Check 10 earnings quality red flags. Returns list of triggered flags."""
    flags = []

    # 1. Receivables growing faster than revenue
    if receivables_growth > revenue_growth * 1.5 and receivables_growth > 0.05:
        flags.append(f"Receivables growing {receivables_growth:.0%} vs revenue {revenue_growth:.0%} — potential aggressive revenue recognition")

    # 2. Inventory building faster than COGS
    if inventory_growth > cogs_growth * 1.5 and inventory_growth > 0.05:
        flags.append(f"Inventory growing {inventory_growth:.0%} vs COGS {cogs_growth:.0%} — potential demand softness")

    # 3. Gross margin declining while revenue grows
    if gross_margin_current < gross_margin_prior - 0.02 and revenue_growth > 0.05:
        flags.append(f"Gross margin declining ({gross_margin_prior:.1%}→{gross_margin_current:.1%}) while revenue growing — mix shift or pricing pressure")

    # 4. D&A falling relative to asset base
    da_rate_current = da_current / total_assets_current if total_assets_current > 0 else 0
    da_rate_prior = da_prior / total_assets_prior if total_assets_prior > 0 else 0
    if da_rate_current < da_rate_prior * 0.85:
        flags.append(f"D&A falling relative to asset base — potential underdepreciation")

    # 5. Recurring "exceptional" items
    if exceptional_items_count >= 3:
        flags.append(f"Exceptional charges in {exceptional_items_count} consecutive years — these are recurring, not exceptional")

    # 6. Goodwill heavy
    goodwill_pct = goodwill / total_assets if total_assets > 0 else 0
    if goodwill_pct > 0.40:
        flags.append(f"Goodwill {goodwill_pct:.0%} of total assets — acquisition-heavy, impairment risk")

    # 7. Revenue growth + margin compression + rising leverage (triple negative)
    leverage_rising = net_debt_current > net_debt_prior * 1.15
    if revenue_growth > 0.05 and gross_margin_current < gross_margin_prior and leverage_rising:
        flags.append("Triple negative: revenue growth + margin compression + rising leverage simultaneously")

    flag_count = len(flags)
    if flag_count == 0:
        quality_label = "CLEAN"
    elif flag_count <= 2:
        quality_label = "MONITOR"
    else:
        quality_label = "CONCERN — investigate before proceeding"

    return {
        'flags': flags,
        'flag_count': flag_count,
        'quality_label': quality_label,
    }


# ─────────────────────────────────────────────
# CONVICTION SCORE CALCULATOR
# ─────────────────────────────────────────────

def calculate_conviction_score(
    margin_of_safety: float,
    dcf_comps_agreement: float,    # Absolute % difference between DCF and comps
    catalyst_score: int,           # 1-3
    fisher_score: int,             # 0-75
    flag_count: int,               # Earnings quality flags
    altman_zone: str,
    segment: str,                  # 'A' or 'B'
    var_99: Optional[float],       # Annual VaR 99% as percentage
    ms_moat: Optional[str] = None, # Wide / Narrow / None
) -> dict:
    """
    Synthesise a conviction score 1-10.
    """
    score = 5.0  # Start at neutral

    # Margin of safety (max +2 / min -3)
    if margin_of_safety >= 0.40:
        score += 2.0
    elif margin_of_safety >= 0.30:
        score += 1.5
    elif margin_of_safety >= 0.20:
        score += 1.0
    elif margin_of_safety >= 0.10:
        score -= 1.0
    else:
        score -= 3.0

    # DCF vs comps agreement (max +1 / min -1)
    if dcf_comps_agreement < 0.10:
        score += 1.0
    elif dcf_comps_agreement < 0.20:
        score += 0.5
    elif dcf_comps_agreement > 0.35:
        score -= 1.0

    # Catalyst strength (max +1.5 / min -1)
    if catalyst_score == 3:
        score += 1.5
    elif catalyst_score == 2:
        score += 0.5
    else:
        score -= 1.0

    # Fisher score (max +1 / min -1)
    if fisher_score >= 60:
        score += 1.0
    elif fisher_score >= 45:
        score += 0.5
    elif fisher_score < 30:
        score -= 1.0

    # Earnings quality flags (max 0 / min -2)
    if flag_count == 0:
        pass
    elif flag_count <= 2:
        score -= 0.5
    elif flag_count <= 4:
        score -= 1.5
    else:
        score -= 2.0

    # Altman Z-Score (context-adjusted for Segment B)
    if segment == 'A':
        if altman_zone == 'DISTRESS':
            score -= 1.5
        elif altman_zone == 'GREY':
            score -= 0.5
    # Segment B: distress/grey is expected, no penalty

    # Morningstar moat
    if ms_moat == 'Wide':
        score += 0.5
    elif ms_moat == 'None':
        score -= 0.5

    # VaR adjustment (max 0 / min -1)
    if var_99 is not None:
        if var_99 > 60:
            score -= 1.0
        elif var_99 > 40:
            score -= 0.5

    final_score = max(1.0, min(10.0, round(score, 1)))

    if final_score >= 8:
        label = "HIGH — full position"
    elif final_score >= 6:
        label = "MODERATE — half position, build on confirmation"
    elif final_score >= 4:
        label = "LOW — monitoring only"
    else:
        label = "INSUFFICIENT — return to watchlist"

    return {
        'conviction_score': final_score,
        'label': label,
        'proceed': final_score >= 4,
        'mirofish_eligible': final_score >= 6,
    }
