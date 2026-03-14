"""
Walker Capital Management — MiroFish Swarm Intelligence Client
Stage 6: Upload research brief, run competitive simulation, extract predictions.
Only runs on high-conviction companies (conviction score >= 6).
MiroFish runs locally at http://localhost:5001
"""

import os
import time
import json
import logging
import requests
from pathlib import Path

logger = logging.getLogger(__name__)

MIROFISH_BASE = os.environ.get("MIROFISH_URL", "http://localhost:5001")
TIMEOUT = 30  # seconds for API calls
SIMULATION_POLL_INTERVAL = 10  # seconds between status checks
SIMULATION_MAX_WAIT = 600  # 10 minutes max


def _post(endpoint: str, data: dict = None, files: dict = None) -> dict:
    """POST to MiroFish API. Returns response dict."""
    url = f"{MIROFISH_BASE}/api{endpoint}"
    try:
        if files:
            resp = requests.post(url, data=data, files=files, timeout=TIMEOUT)
        else:
            resp = requests.post(url, json=data, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        logger.error(f"MiroFish not reachable at {MIROFISH_BASE}. Is it running? (npm run dev in ~/MiroFish)")
        return {"success": False, "error": "MiroFish not running"}
    except Exception as e:
        logger.error(f"MiroFish API error on {endpoint}: {e}")
        return {"success": False, "error": str(e)}


def _get(endpoint: str, params: dict = None) -> dict:
    url = f"{MIROFISH_BASE}/api{endpoint}"
    try:
        resp = requests.get(url, params=params, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.error(f"MiroFish GET error on {endpoint}: {e}")
        return {"success": False, "error": str(e)}


def run_competitive_simulation(
    company_name: str,
    ticker: str,
    brief_file_path: str,
    competitors: list,
    sector: str,
) -> dict:
    """
    Full MiroFish pipeline for a company:
    1. Upload research brief → generate ontology (project_id)
    2. Build knowledge graph
    3. Create + run simulation
    4. Extract and return results

    Returns structured simulation results dict.
    """
    logger.info(f"Starting MiroFish simulation for {ticker}")

    brief_path = Path(brief_file_path)
    if not brief_path.exists():
        return {"success": False, "error": f"Brief file not found: {brief_file_path}"}

    competitors_str = ", ".join(competitors[:6]) if competitors else "key industry competitors"

    simulation_requirement = (
        f"Simulate the competitive dynamics between {company_name} ({ticker}) and its key competitors "
        f"({competitors_str}) in the {sector} market. "
        f"Predict: (1) Where will market share shift between these companies over 1 year, 3 years, and 5 years? "
        f"(2) What is the total addressable market today and what will it be at 1 year, 3 years, and 5 years? "
        f"(3) What are the key competitive risks that could harm {company_name}? "
        f"(4) What scenarios most benefit {company_name} vs those that harm it? "
        f"Run bull, base, and bear scenarios for the competitive outlook."
    )

    # Step 1: Upload brief and generate ontology
    logger.info(f"Step 1: Uploading brief to MiroFish for {ticker}")
    with open(brief_path, 'rb') as f:
        ontology_response = _post(
            "/graph/ontology/generate",
            data={
                "simulation_requirement": simulation_requirement,
                "project_name": f"Walker Capital — {company_name} ({ticker})",
                "additional_context": f"Investment research for Walker Capital Management. Sector: {sector}. Focus on competitive dynamics and market share evolution.",
            },
            files={"files": (brief_path.name, f, "text/markdown")}
        )

    if not ontology_response.get("success"):
        return {"success": False, "error": f"Ontology generation failed: {ontology_response.get('error')}"}

    project_id = ontology_response["data"]["project_id"]
    logger.info(f"MiroFish project created: {project_id}")

    # Step 2: Build knowledge graph
    logger.info(f"Step 2: Building knowledge graph for {project_id}")
    build_response = _post("/graph/build", {"project_id": project_id})

    if not build_response.get("success"):
        return {"success": False, "error": f"Graph build failed: {build_response.get('error')}"}

    # Wait for graph build to complete
    graph_id = None
    wait_time = 0
    while wait_time < SIMULATION_MAX_WAIT:
        project_status = _get(f"/graph/project/{project_id}")
        if project_status.get("success"):
            project_data = project_status["data"]
            status = project_data.get("status", "")
            if "GRAPH" in status.upper() and project_data.get("graph_id"):
                graph_id = project_data["graph_id"]
                logger.info(f"Graph built: {graph_id}")
                break
            elif "ERROR" in status.upper() or "FAILED" in status.upper():
                return {"success": False, "error": f"Graph build failed with status: {status}"}
        time.sleep(SIMULATION_POLL_INTERVAL)
        wait_time += SIMULATION_POLL_INTERVAL

    if not graph_id:
        return {"success": False, "error": "Graph build timed out"}

    # Step 3: Create simulation
    logger.info(f"Step 3: Creating simulation for {project_id}")
    sim_create_response = _post("/simulation/create", {
        "project_id": project_id,
        "graph_id": graph_id,
        "enable_twitter": True,
        "enable_reddit": True,
    })

    if not sim_create_response.get("success"):
        return {"success": False, "error": f"Simulation create failed: {sim_create_response.get('error')}"}

    simulation_id = sim_create_response["data"]["simulation_id"]
    logger.info(f"Simulation created: {simulation_id}")

    # Step 4: Run simulation
    logger.info(f"Step 4: Running simulation {simulation_id}")
    run_response = _post("/simulation/run", {"simulation_id": simulation_id})

    if not run_response.get("success"):
        return {"success": False, "error": f"Simulation run failed: {run_response.get('error')}"}

    # Poll for completion
    wait_time = 0
    while wait_time < SIMULATION_MAX_WAIT:
        status_response = _get(f"/simulation/status/{simulation_id}")
        if status_response.get("success"):
            sim_status = status_response["data"].get("status", "")
            logger.info(f"Simulation status: {sim_status} (waited {wait_time}s)")
            if sim_status in ("COMPLETED", "FINISHED", "DONE"):
                break
            elif sim_status in ("FAILED", "ERROR"):
                return {"success": False, "error": f"Simulation failed: {sim_status}"}
        time.sleep(SIMULATION_POLL_INTERVAL)
        wait_time += SIMULATION_POLL_INTERVAL

    if wait_time >= SIMULATION_MAX_WAIT:
        return {"success": False, "error": "Simulation timed out"}

    # Step 5: Get report
    logger.info(f"Step 5: Fetching report for {simulation_id}")
    report_response = _get(f"/report/{simulation_id}")

    if not report_response.get("success"):
        return {"success": False, "error": f"Report fetch failed: {report_response.get('error')}"}

    full_report = report_response.get("data", {})
    report_text = full_report.get("report_text", json.dumps(full_report, indent=2))

    # Extract key metrics from report using basic parsing
    extracted = _extract_simulation_insights(report_text, company_name)

    return {
        "success": True,
        "project_id": project_id,
        "simulation_id": simulation_id,
        "full_report": report_text,
        **extracted,
    }


def _extract_simulation_insights(report_text: str, company_name: str) -> dict:
    """
    Extract structured insights from MiroFish report text.
    Returns dict with market share, TAM, scenarios.
    """
    # These are populated from Claude synthesis in the memo generation step
    # MiroFish report text is passed to Opus 4.6 for extraction
    return {
        "market_share_1yr": "See full report",
        "market_share_3yr": "See full report",
        "market_share_5yr": "See full report",
        "tam_current": None,
        "tam_1yr": None,
        "tam_3yr": None,
        "tam_5yr": None,
        "key_competitive_risk": "See full report",
        "bull_scenario": "See full report",
        "base_scenario": "See full report",
        "bear_scenario": "See full report",
        "simulation_confidence": "See full report",
        "raw_report_for_synthesis": report_text,
    }


def check_mirofish_health() -> bool:
    """Quick health check — is MiroFish running?"""
    try:
        resp = requests.get(f"{MIROFISH_BASE}", timeout=5)
        return resp.status_code < 500
    except Exception:
        return False
