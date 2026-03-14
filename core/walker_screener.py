"""
Walker Capital Management — Company Screener
Stage 1 (Discovery) + Stage 2 (Screening) + Stage 3 (Deep Research)
Powered by Perplexity API via Claude Opus 4.6 context.
"""

import os
import json
import logging
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent


def get_perplexity_key():
    return os.environ.get("PERPLEXITY_API_KEY", "")


def call_perplexity(prompt: str, model: str = "sonar-pro", max_tokens: int = 2000) -> str:
    """
    Call Perplexity API. Returns text response.
    Uses openai-compatible SDK format.
    """
    try:
        from openai import OpenAI
        client = OpenAI(
            api_key=get_perplexity_key(),
            base_url="https://api.perplexity.ai"
        )
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Perplexity API error: {e}")
        return ""


# ─────────────────────────────────────────────
# STAGE 1: DISCOVERY
# ─────────────────────────────────────────────

DISCOVERY_PROMPTS = [
    """List 5 NZ (NZX), Australian (ASX), or US listed companies that have reported significant earnings surprises, major analyst rating changes, or entered a new growth phase in the last 48-72 hours. For each company provide: ticker, exchange, company name, sector, and a one-sentence reason why this represents a potential investment opportunity. Focus on companies with genuine catalysts, not just momentum. Format as JSON array.""",

    """List 5 listed companies (NZX, ASX, or US markets) currently experiencing a structural tailwind that the market may not have fully priced in. This could be regulatory change, technology adoption, demographic shift, or sector consolidation. For each: ticker, exchange, name, sector, and one-sentence catalyst description. Format as JSON array.""",

    """List 5 listed companies (NZX, ASX, or US markets) that have recently achieved major milestones — significant new contracts, strategic partnerships, regulatory approvals, or institutional recognition — that could signal a sentiment shift for growth companies. For each: ticker, exchange, name, sector, one-sentence thesis. Format as JSON array.""",

    """List 5 quality listed companies (NZX, ASX, or US) currently trading at multi-year valuation lows due to temporary or cyclical headwinds that appear to be reversing. Exclude structurally impaired businesses. For each: ticker, exchange, name, sector, why it's cheap and why that may be temporary. Format as JSON array.""",
]

_discovery_prompt_index = 0


def run_discovery_scan() -> list:
    """
    Stage 1: Scan for new investment candidates.
    Returns list of dicts: {ticker, exchange, name, sector, discovery_thesis}
    """
    global _discovery_prompt_index
    prompt = DISCOVERY_PROMPTS[_discovery_prompt_index % len(DISCOVERY_PROMPTS)]
    _discovery_prompt_index += 1

    logger.info(f"Running discovery scan (prompt {_discovery_prompt_index})")
    raw = call_perplexity(prompt, max_tokens=1500)

    if not raw:
        return []

    # Extract JSON from response — strip markdown code fences first
    candidates = []
    try:
        # Strip ```json ... ``` fences
        clean = re.sub(r'```(?:json)?\s*', '', raw).strip()
        json_match = re.search(r'\[.*?\](?=\s*$|\s*\n\s*[^[\]{}])', clean, re.DOTALL)
        if not json_match:
            json_match = re.search(r'\[.*\]', clean, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            for item in data:
                candidates.append({
                    'ticker': item.get('ticker', ''),
                    'exchange': item.get('exchange', ''),
                    'name': item.get('name', item.get('company_name', '')),
                    'sector': item.get('sector', ''),
                    'discovery_thesis': item.get('thesis', item.get('reason', item.get('catalyst', item.get('discovery_thesis', '')))),
                })
    except Exception as e:
        logger.warning(f"Could not parse discovery JSON: {e}. Raw: {raw[:200]}")

    logger.info(f"Discovery scan found {len(candidates)} candidates")
    return candidates


# ─────────────────────────────────────────────
# STAGE 2: SCREENING
# ─────────────────────────────────────────────

def run_quantitative_screen(ticker: str, exchange: str, name: str) -> dict:
    """
    Stage 2: Pull key financial metrics and catalyst score via Perplexity.
    Returns structured screening result.
    """
    prompt = f"""Research {name} ({ticker} on {exchange}) and return ONLY a JSON object with these fields.
CRITICAL: Use null (not 0) for any metric you cannot find real data for. Never guess or infer — null means unknown.

{{
  "revenue_growth_3yr_avg": null,       // 3-year average annual revenue growth rate as decimal (e.g. 0.15 = 15%). null if unavailable.
  "roic_latest": null,                  // Return on invested capital, most recent fiscal year, as decimal. null if unavailable.
  "gross_margin_latest": null,          // Gross profit margin, most recent fiscal year, as decimal. null if unavailable.
  "fcf_positive": null,                 // true if free cash flow was positive in BOTH of the last 2 fiscal years, false if negative, null if unknown.
  "net_debt_ebitda": null,              // Net debt divided by EBITDA (negative = net cash position). null if unavailable.
  "segment": "A",                       // "A" = mature, profitable, established revenue. "B" = early-stage, growth, pre-profit or rapid expansion.
  "catalyst_description": "",           // What is the specific catalyst for {name} RIGHT NOW in March 2026? Be concrete.
  "catalyst_score": 0,                  // 3=Strong imminent specific catalyst. 2=Moderate directional tailwind. 1=Weak or vague. 0=No catalyst.
  "catalyst_score_rationale": "",       // One sentence: why this score?
  "comparable_companies": []            // 5-8 direct peer tickers (same exchange preferred)
}}

Return ONLY the JSON object. No commentary."""

    raw = call_perplexity(prompt, max_tokens=1200)

    result = {
        'ticker': ticker,
        'exchange': exchange,
        'name': name,
        'screen_passed': False,
        'screen_reason': '',
        'segment': None,
        'catalyst_score': 0,
        'catalyst_description': '',
        'raw_data': {},
    }

    try:
        clean = re.sub(r'```(?:json)?\s*', '', raw).strip()
        json_match = re.search(r'\{.*\}', clean, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            result['raw_data'] = data

            segment = data.get('segment', 'A')
            catalyst_score = data.get('catalyst_score', 0) or 0
            result['segment'] = segment
            result['catalyst_score'] = catalyst_score
            result['catalyst_description'] = data.get('catalyst_description', '')
            result['comparable_companies'] = data.get('comparable_companies', [])

            # Catalyst gate — applies to BOTH segments
            if catalyst_score < 2:
                result['screen_reason'] = f"Catalyst too weak (score={catalyst_score}/3): {data.get('catalyst_score_rationale', 'No strong catalyst identified')}"
                result['screen_passed'] = False
                result['watchlist'] = catalyst_score == 1
                return result

            # Segment A quantitative checks
            if segment == 'A':
                roic = data.get('roic_latest')
                net_debt_ebitda = data.get('net_debt_ebitda')
                revenue_growth = data.get('revenue_growth_3yr_avg')
                fcf_positive = data.get('fcf_positive')

                fails = []
                data_gaps = []

                if roic is None:
                    data_gaps.append("ROIC unknown")
                elif roic < 0.12:
                    fails.append(f"ROIC {roic:.1%} < 12%")

                if net_debt_ebitda is not None and net_debt_ebitda > 2.5:
                    fails.append(f"Net Debt/EBITDA {net_debt_ebitda:.1f}x > 2.5x")

                if revenue_growth is None:
                    data_gaps.append("revenue growth unknown")
                elif revenue_growth < 0.05:
                    fails.append(f"Revenue growth {revenue_growth:.1%} < 5%")

                if fcf_positive is None:
                    data_gaps.append("FCF status unknown")
                elif not fcf_positive:
                    fails.append("FCF not positive in last 2 years")

                if fails:
                    result['screen_reason'] = "Segment A fails: " + "; ".join(fails)
                    result['screen_passed'] = False
                elif data_gaps:
                    # Has catalyst, no hard fails, but data incomplete — pass with caveat
                    result['screen_passed'] = True
                    result['screen_reason'] = f"Segment A provisional pass (data gaps: {', '.join(data_gaps)}). Catalyst: {catalyst_score}/3"
                    result['data_gaps'] = data_gaps
                else:
                    result['screen_passed'] = True
                    result['screen_reason'] = f"Segment A pass. Catalyst: {catalyst_score}/3"

            # Segment B quantitative checks
            elif segment == 'B':
                revenue_growth = data.get('revenue_growth_3yr_avg')
                gross_margin = data.get('gross_margin_latest')

                fails = []
                data_gaps = []

                if revenue_growth is None:
                    data_gaps.append("revenue growth unknown")
                elif revenue_growth < 0.20:
                    fails.append(f"Revenue growth {revenue_growth:.1%} < 20%")

                if gross_margin is None:
                    data_gaps.append("gross margin unknown")
                elif gross_margin < 0.40:
                    fails.append(f"Gross margin {gross_margin:.1%} < 40%")

                if fails:
                    result['screen_reason'] = "Segment B fails: " + "; ".join(fails)
                    result['screen_passed'] = False
                elif data_gaps:
                    result['screen_passed'] = True
                    result['screen_reason'] = f"Segment B provisional pass (data gaps: {', '.join(data_gaps)}). Catalyst: {catalyst_score}/3"
                    result['data_gaps'] = data_gaps
                else:
                    result['screen_passed'] = True
                    result['screen_reason'] = f"Segment B pass. Catalyst: {catalyst_score}/3"

    except Exception as e:
        logger.warning(f"Could not parse screen JSON for {ticker}: {e}")
        result['screen_reason'] = f"Parse error: {e}"

    return result


# ─────────────────────────────────────────────
# STAGE 3: DEEP RESEARCH BRIEF
# ─────────────────────────────────────────────

def generate_research_brief(ticker: str, exchange: str, name: str, sector: str,
                             catalyst_description: str, comparable_companies: list) -> dict:
    """
    Stage 3: Generate a full research brief for a company that passed screening.
    Returns structured dict with all sections.
    """
    peers_str = ", ".join(comparable_companies[:8]) if comparable_companies else "key industry peers"

    prompt = f"""Write a comprehensive investment research brief for {name} ({ticker} on {exchange}).

Structure your response EXACTLY as follows (use these exact headers):

## BUSINESS MODEL
How does {name} make money? Who are the customers? What are the switching costs? Revenue streams.

## COMPETITIVE POSITION (Porter's Five Forces)
Threat of new entrants, supplier power, buyer power, threat of substitutes, competitive rivalry. Identify the specific sources of competitive advantage or disadvantage.

## MANAGEMENT QUALITY
CEO background, tenure, track record, capital allocation history, insider ownership, recent strategic decisions.

## INDUSTRY DYNAMICS
Market growth rate, key trends driving the industry, regulatory environment, technology forces, demographic tailwinds or headwinds.

## THE CATALYST
Detailed analysis of: {catalyst_description}
Specifically: What is it, what is the timeline, what is the probability of materialising, what is the magnitude of impact on earnings/valuation?

## BEAR CASE
What are the 3 most credible reasons this investment could go wrong? Be specific — not generic market risk.

## KEY FINANCIAL METRICS (last 3 years where available)
Revenue, gross margin, EBITDA margin, FCF, ROIC, net debt/EBITDA, EPS growth.

## COMPETITIVE EDGE
Why is {name} ahead of its competitors RIGHT NOW? Be specific — not generic. Cover:
- What does it do better than {peers_str}?
- What structural advantages does it hold (IP, scale, switching costs, network effects, brand, cost position)?
- What would it take for a competitor to close the gap?
- Is this advantage widening or narrowing?

## COMPARABLE COMPANIES
Compared to {peers_str}: how does {name} differ in business model, growth profile, and competitive positioning?

Be factual, specific, and investment-grade in quality. No filler."""

    logger.info(f"Generating research brief for {ticker}")
    raw = call_perplexity(prompt, max_tokens=3000)

    if not raw:
        return {'brief_text': '', 'error': 'Perplexity returned empty response'}

    # Parse sections
    sections = {}
    section_map = {
        'business_model': 'BUSINESS MODEL',
        'competitive_position': 'COMPETITIVE POSITION',
        'management_quality': 'MANAGEMENT QUALITY',
        'industry_dynamics': 'INDUSTRY DYNAMICS',
        'catalyst_detail': 'THE CATALYST',
        'bear_case': 'BEAR CASE',
        'key_metrics': 'KEY FINANCIAL METRICS',
        'competitive_edge': 'COMPETITIVE EDGE',
        'comparable_companies_analysis': 'COMPARABLE COMPANIES',
    }

    for key, header in section_map.items():
        pattern = rf'## {re.escape(header)}(.*?)(?=## [A-Z]|\Z)'
        match = re.search(pattern, raw, re.DOTALL | re.IGNORECASE)
        sections[key] = match.group(1).strip() if match else ''

    # Save brief to file for MiroFish upload
    brief_path = BASE_DIR / "agents" / "walker-capital" / "pipeline" / f"{ticker}_{exchange}_brief.md"
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(raw, encoding='utf-8')
    logger.info(f"Research brief saved to {brief_path}")

    return {
        'brief_text': raw,
        'brief_file_path': str(brief_path),
        **sections,
        'ticker': ticker,
        'exchange': exchange,
        'name': name,
        'generated_at': datetime.now().isoformat(),
    }
