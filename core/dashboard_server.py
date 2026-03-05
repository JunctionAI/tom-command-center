"""
Tom's Command Center — Live Dashboard Server
Reads from all SQLite databases and orchestrator.log.
Serves the dashboard with real-time data.

Usage: python core/dashboard_server.py
Opens: http://localhost:8050
"""

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import json
import os
import re
import logging
from datetime import datetime, timedelta
from pathlib import Path
import uvicorn

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

NZ_TZ = ZoneInfo("Pacific/Auckland")
logger = logging.getLogger(__name__)

app = FastAPI(title="Tom's Command Center Dashboard")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Background order sync (keeps customer_intelligence.db fresh) ---
import asyncio
import threading

_sync_running = False
_last_sync = None

def _run_order_sync():
    """Sync orders from Shopify into customer_intelligence.db."""
    global _last_sync
    try:
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from core.order_intelligence import fetch_order_intelligence
        result = fetch_order_intelligence(days=2, yesterday_only=False)
        _last_sync = datetime.now()
        logger.info(f"Order sync complete: {result[:100] if result else 'done'}")
    except Exception as e:
        logger.error(f"Order sync failed: {e}")

async def _background_sync_loop():
    """Run order sync on startup, then every 30 minutes."""
    global _sync_running
    _sync_running = True
    # Initial sync on startup (in thread to not block)
    await asyncio.get_event_loop().run_in_executor(None, _run_order_sync)
    while _sync_running:
        await asyncio.sleep(1800)  # 30 minutes
        await asyncio.get_event_loop().run_in_executor(None, _run_order_sync)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(_background_sync_loop())

@app.get("/api/sync-status")
def get_sync_status():
    return {
        "last_sync": _last_sync.isoformat() if _last_sync else None,
        "sync_running": _sync_running,
        "next_sync_in": f"{max(0, 1800 - (datetime.now() - _last_sync).total_seconds()):.0f}s" if _last_sync else "starting",
    }

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
LOG_FILE = BASE_DIR / "orchestrator.log"
DASHBOARD_FILE = BASE_DIR / "SYSTEM-PIPELINE-DASHBOARD.html"


def get_db(name):
    db_path = DATA_DIR / name
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def query_db(db_name, sql, params=(), one=False):
    conn = get_db(db_name)
    if not conn:
        return None if one else []
    try:
        cur = conn.execute(sql, params)
        rows = [dict(row) for row in cur.fetchall()]
        return rows[0] if one and rows else (rows if not one else None)
    except Exception:
        return None if one else []
    finally:
        conn.close()


def parse_log(limit=200):
    if not LOG_FILE.exists():
        return []
    lines = []
    try:
        with open(LOG_FILE, "r") as f:
            all_lines = f.readlines()
            for line in all_lines[-limit:]:
                m = re.match(
                    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) \[(\w+)\] (.+)",
                    line.strip(),
                )
                if m:
                    lines.append(
                        {
                            "timestamp": m.group(1).replace(",", "."),
                            "level": m.group(2),
                            "message": m.group(3),
                        }
                    )
    except Exception:
        pass
    return lines


@app.get("/api/overview")
def get_overview():
    customers = query_db(
        "customer_intelligence.db",
        "SELECT COUNT(*) as count FROM customers",
        one=True,
    )
    customer_count = customers["count"] if customers else 0

    orders = query_db(
        "customer_intelligence.db",
        "SELECT COUNT(*) as count, COALESCE(SUM(total_price), 0) as revenue FROM orders",
        one=True,
    )
    order_count = orders["count"] if orders else 0
    total_revenue = orders["revenue"] if orders else 0

    today = datetime.now().strftime("%Y-%m-%d")
    snapshot = query_db(
        "customer_intelligence.db",
        "SELECT * FROM daily_snapshots WHERE date = ?",
        (today,),
        one=True,
    )

    events = query_db(
        "event_bus.db", "SELECT COUNT(*) as count FROM events", one=True
    )
    event_count = events["count"] if events else 0

    decisions = query_db(
        "decisions.db", "SELECT COUNT(*) as count FROM decisions", one=True
    )
    decision_count = decisions["count"] if decisions else 0

    briefs = query_db("briefs.db", "SELECT COUNT(*) as count FROM briefs", one=True)
    brief_count = briefs["count"] if briefs else 0

    notifs = query_db(
        "notification_queue.db",
        "SELECT COUNT(*) as count FROM pending_notifications WHERE sent_at IS NULL",
        one=True,
    )
    pending_notifs = notifs["count"] if notifs else 0

    interactions = query_db(
        "learning.db",
        "SELECT COUNT(*) as count FROM interactions WHERE DATE(created_at) = DATE('now')",
        one=True,
    )
    todays_runs = interactions["count"] if interactions else 0

    return {
        "customers": customer_count,
        "orders": order_count,
        "total_revenue": round(total_revenue, 2),
        "today": snapshot or {},
        "events": event_count,
        "decisions": decision_count,
        "briefs": brief_count,
        "pending_notifications": pending_notifs,
        "agent_runs_today": todays_runs,
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/feed")
def get_activity_feed(limit: int = 80):
    items = []

    events = query_db(
        "event_bus.db",
        "SELECT * FROM events ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    for e in events:
        payload = {}
        try:
            payload = json.loads(e["payload"]) if e["payload"] else {}
        except Exception:
            pass
        items.append(
            {
                "type": "event",
                "timestamp": e["created_at"],
                "agent": e["source_agent"],
                "severity": e["severity"],
                "title": e["event_type"],
                "detail": payload,
                "icon": "bolt",
            }
        )

    decisions = query_db(
        "decisions.db",
        "SELECT * FROM decisions ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    for d in decisions:
        items.append(
            {
                "type": "decision",
                "timestamp": d["created_at"],
                "agent": d["agent"],
                "severity": "NOTABLE",
                "title": d["title"],
                "detail": {
                    "reasoning": d["reasoning"],
                    "confidence": d["confidence"],
                    "status": d["status"],
                },
                "icon": "target",
            }
        )

    interactions = query_db(
        "learning.db",
        "SELECT * FROM interactions ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    for i in interactions:
        items.append(
            {
                "type": "agent_run",
                "timestamp": i["created_at"],
                "agent": i["agent"],
                "severity": "INFO",
                "title": f"{i['agent']}/{i['task']}",
                "detail": {
                    "trigger": i["trigger"],
                    "model": i.get("model_used", ""),
                    "tokens": i.get("tokens_used", 0),
                },
                "icon": "cpu",
            }
        )

    notifs = query_db(
        "notification_queue.db",
        "SELECT * FROM notification_log ORDER BY sent_at DESC LIMIT ?",
        (limit,),
    )
    for n in notifs:
        items.append(
            {
                "type": "notification",
                "timestamp": n["sent_at"],
                "agent": "",
                "severity": n["severity"],
                "title": "Notification sent",
                "detail": {
                    "message": n["message_preview"],
                    "batched": n["was_batched"],
                },
                "icon": "bell",
            }
        )

    insights = query_db(
        "intelligence.db",
        "SELECT * FROM insights ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    for ins in insights:
        items.append(
            {
                "type": "insight",
                "timestamp": ins["created_at"],
                "agent": ins["agent"],
                "severity": "NOTABLE",
                "title": ins["domain"],
                "detail": {
                    "insight": ins["insight"],
                    "confidence": ins["confidence"],
                    "score": ins["confidence_score"],
                },
                "icon": "lightbulb",
            }
        )

    log_entries = parse_log(200)
    for entry in log_entries:
        if entry["level"] in ("ERROR", "WARNING") or any(
            kw in entry["message"]
            for kw in ("EVENT", "Decision", "Completed:", "Running scheduled")
        ):
            items.append(
                {
                    "type": "log",
                    "timestamp": entry["timestamp"],
                    "agent": "",
                    "severity": "CRITICAL"
                    if entry["level"] == "ERROR"
                    else "WARNING"
                    if entry["level"] == "WARNING"
                    else "INFO",
                    "title": entry["level"],
                    "detail": {"message": entry["message"]},
                    "icon": "terminal",
                }
            )

    items.sort(key=lambda x: x["timestamp"] or "", reverse=True)
    return items[:limit]


@app.get("/api/pipeline")
def get_pipeline_status():
    nodes = {}

    recent_orders = query_db(
        "customer_intelligence.db",
        "SELECT COUNT(*) as count FROM orders WHERE DATE(created_at) >= DATE('now', '-7 days')",
        one=True,
    )
    nodes["shopify"] = {
        "status": "active"
        if recent_orders and recent_orders["count"] > 0
        else "partial",
        "detail": f"{recent_orders['count'] if recent_orders else 0} orders this week",
    }

    roas = query_db(
        "intelligence.db",
        "SELECT COUNT(*) as count FROM roas_daily",
        one=True,
    )
    nodes["meta"] = {
        "status": "blocked",
        "detail": "UTMs missing - 0 verified attribution",
    }

    recent_events = query_db(
        "event_bus.db",
        "SELECT COUNT(*) as count FROM events WHERE DATE(created_at) >= DATE('now', '-1 day')",
        one=True,
    )
    nodes["event_bus"] = {
        "status": "active"
        if recent_events and recent_events["count"] > 0
        else "partial",
        "detail": f"{recent_events['count'] if recent_events else 0} events today",
    }

    c = query_db(
        "customer_intelligence.db",
        "SELECT COUNT(*) as c FROM customers",
        one=True,
    )
    nodes["customer_intel"] = {
        "status": "active",
        "detail": f"{c['c'] if c else 0} customers tracked",
    }

    d = query_db(
        "decisions.db", "SELECT COUNT(*) as c FROM decisions", one=True
    )
    nodes["decisions"] = {
        "status": "active" if d and d["c"] > 0 else "partial",
        "detail": f"{d['c'] if d else 0} decisions logged",
    }

    b = query_db("briefs.db", "SELECT COUNT(*) as c FROM briefs", one=True)
    nodes["briefs"] = {
        "status": "active" if b and b["c"] > 0 else "partial",
        "detail": f"{b['c'] if b else 0} briefs generated",
    }

    return nodes


@app.get("/api/channel/{name}")
def get_channel_data(name: str):
    if name == "shopify":
        customers = query_db(
            "customer_intelligence.db",
            "SELECT segment, COUNT(*) as count, SUM(total_spent) as revenue, AVG(avg_order_value) as aov FROM customers GROUP BY segment",
        )
        recent_orders = query_db(
            "customer_intelligence.db",
            "SELECT * FROM orders ORDER BY created_at DESC LIMIT 20",
        )
        snapshots = query_db(
            "customer_intelligence.db",
            "SELECT * FROM daily_snapshots ORDER BY date DESC LIMIT 14",
        )
        return {
            "segments": customers,
            "recent_orders": recent_orders,
            "snapshots": snapshots,
        }

    elif name == "meta":
        roas_data = query_db(
            "intelligence.db",
            "SELECT * FROM roas_daily ORDER BY date DESC LIMIT 30",
        )
        alerts = query_db("intelligence.db", "SELECT * FROM roas_alerts")
        events = query_db(
            "event_bus.db",
            "SELECT * FROM events WHERE event_type LIKE 'campaign%' OR event_type LIKE 'meta%' ORDER BY created_at DESC LIMIT 20",
        )
        return {"roas_daily": roas_data, "alerts": alerts, "events": events}

    elif name == "email":
        snapshots = query_db(
            "customer_intelligence.db",
            "SELECT date, email_send_count, email_revenue FROM daily_snapshots ORDER BY date DESC LIMIT 30",
        )
        return {"snapshots": snapshots}

    elif name == "seo":
        briefs = query_db(
            "briefs.db",
            "SELECT * FROM briefs ORDER BY created_at DESC",
        )
        return {"articles": briefs}

    return {"error": "Unknown channel"}


@app.get("/api/agents")
def get_agents():
    interactions = query_db(
        "learning.db",
        "SELECT agent, task, trigger, model_used, tokens_used, created_at, output_summary FROM interactions ORDER BY created_at DESC",
    )
    agent_map = {}
    for i in interactions:
        if i["agent"] not in agent_map:
            agent_map[i["agent"]] = {
                "last_run": i["created_at"],
                "last_task": i["task"],
                "model": i.get("model_used"),
                "total_runs": 0,
                "total_tokens": 0,
                "last_output": (i.get("output_summary") or "")[:300],
            }
        agent_map[i["agent"]]["total_runs"] += 1
        agent_map[i["agent"]]["total_tokens"] += i.get("tokens_used") or 0

    return agent_map


@app.get("/api/customers")
def get_customers_summary():
    channels = query_db(
        "customer_intelligence.db",
        """SELECT
            CASE
                WHEN channels_used LIKE '%Meta%' OR channels_used LIKE '%facebook%' THEN 'Meta Ads'
                WHEN channels_used LIKE '%Google%' THEN 'Google'
                WHEN channels_used LIKE '%Email%' OR channels_used LIKE '%Klaviyo%' THEN 'Email'
                WHEN channels_used LIKE '%Direct%' THEN 'Direct'
                ELSE 'Other'
            END as channel_group,
            COUNT(*) as count,
            SUM(total_spent) as revenue,
            AVG(total_orders) as avg_orders
        FROM customers
        GROUP BY channel_group
        ORDER BY revenue DESC""",
    )
    top = query_db(
        "customer_intelligence.db",
        "SELECT first_name, last_name, total_spent, total_orders, segment, location FROM customers ORDER BY total_spent DESC LIMIT 10",
    )
    segments = query_db(
        "customer_intelligence.db",
        "SELECT segment, COUNT(*) as count, AVG(total_spent) as avg_ltv FROM customers GROUP BY segment",
    )
    total = query_db(
        "customer_intelligence.db",
        "SELECT COUNT(*) as c FROM customers",
        one=True,
    )

    return {
        "channel_distribution": channels,
        "top_customers": top,
        "segments": segments,
        "total_customers": total["c"] if total else 0,
    }


@app.get("/api/decisions")
def get_decisions():
    decisions = query_db(
        "decisions.db",
        "SELECT * FROM decisions ORDER BY created_at DESC LIMIT 20",
    )
    chains = query_db(
        "decisions.db",
        "SELECT dc.*, GROUP_CONCAT(cl.decision_id) as decision_ids FROM decision_chains dc LEFT JOIN chain_links cl ON dc.id = cl.chain_id GROUP BY dc.id",
    )
    return {"decisions": decisions, "chains": chains}


@app.get("/api/log")
def get_log(limit: int = 100):
    return parse_log(limit)


@app.get("/api/daily-ops")
def get_daily_ops():
    """
    Return today's task execution status for the Daily Ops timeline.
    Parses orchestrator.log for task runs, failures, and output snippets.
    Also computes chain health status.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    task_runs = []
    task_status_map = {}  # task_name -> {status, proof}

    # Parse orchestrator.log for today's task runs
    if LOG_FILE.exists():
        try:
            with open(LOG_FILE, "r") as f:
                for line in f:
                    if today not in line:
                        continue
                    # Successful task completion
                    if "Running scheduled task:" in line:
                        parts = line.split("Running scheduled task: ")
                        if len(parts) > 1:
                            agent_task = parts[1].strip()
                            task = agent_task.split("/")[-1] if "/" in agent_task else agent_task
                            task_status_map[task] = {"task": task, "status": "ran", "proof": f"Started at {line[:19]}"}
                    # Task crashed
                    if "TASK CRASHED:" in line:
                        parts = line.split("TASK CRASHED: ")
                        if len(parts) > 1:
                            agent_task = parts[1].split(":")[0].strip()
                            task = agent_task.split("/")[-1] if "/" in agent_task else agent_task
                            error = parts[1].split(":", 1)[-1].strip()[:150]
                            task_status_map[task] = {"task": task, "status": "failed", "proof": f"CRASHED: {error}"}
                    # Message sent (proof of completion)
                    if "Message sent to" in line:
                        parts = line.split("Message sent to ")
                        if len(parts) > 1:
                            info = parts[1].strip()
                            # Update most recent task's proof
                            for t in reversed(list(task_status_map.values())):
                                if t["status"] == "ran" and "chars" not in t.get("proof", ""):
                                    t["proof"] += f" | Output delivered ({info})"
                                    break
                    # API errors
                    if "API Error" in line:
                        # Find which task this belongs to
                        for t in reversed(list(task_status_map.values())):
                            if t["status"] == "ran":
                                t["status"] = "failed"
                                t["proof"] = "API Error — check credits or rate limits"
                                break
        except Exception:
            pass

    # Also check agent state files for staleness as proof
    agents_dir = BASE_DIR / "agents"
    if agents_dir.exists():
        for agent_dir in agents_dir.iterdir():
            if agent_dir.is_dir():
                ctx = agent_dir / "state" / "CONTEXT.md"
                if ctx.exists():
                    mtime = datetime.fromtimestamp(ctx.stat().st_mtime)
                    age_hours = (datetime.now() - mtime).total_seconds() / 3600
                    if age_hours < 24:
                        # Agent was active today — find its tasks
                        for task, info in task_status_map.items():
                            if info["status"] == "ran":
                                info["proof"] += f" | State updated {age_hours:.1f}h ago"

    task_runs = list(task_status_map.values())

    # Compute chain health
    chains = {
        "morning": [],    # Scout, Thought Leaders, Extract, Oracle, PREP, Meridian
        "night": [],      # Customer Sync, ROAS, Rule Engine, Auto-Opt, Snapshot
        "content": [],    # GSC, Beacon, Schema, Blog, Citation
        "financial": [],  # Wise, Xero, Odysseus, PREP, Tony
        "lifecycle": [],  # Shopify, Attribution, Replenishment, Klaviyo, LTV
    }

    def task_ran(name):
        return task_status_map.get(name, {}).get("status") == "ran"

    # Morning chain
    chains["morning"] = [
        "ok" if task_ran("daily_scan") else "off",
        "ok" if task_ran("thought_leader_scan") else "off",
        "ok" if task_ran("thought_leader_extract") else "off",
        "ok" if task_ran("morning_briefing") else "off",
        "ok" if task_ran("morning_briefing") else "off",  # PREP also morning_briefing
        "ok" if task_ran("morning_brief") else "off",
    ]

    # Night chain
    chains["night"] = [
        "ok" if task_ran("intelligence_sync") else "off",
        "ok" if task_ran("roas_check") else ("fail" if task_status_map.get("roas_check", {}).get("status") == "failed" else "off"),
        "ok" if task_ran("rule_check") else "off",
        "ok" if task_ran("auto_optimize") else "off",
        "ok" if task_ran("daily_snapshot") else "off",
    ]

    # Content chain
    chains["content"] = [
        "ok" if task_ran("gsc_feedback") else "off",
        "ok" if task_ran("content_generation") else "off",
        "ok" if task_ran("content_generation") else "off",  # schema follows beacon
        "ok" if task_ran("content_generation") else "off",  # blog follows schema
        "ok" if task_ran("citation_check") else "off",
    ]

    # Financial chain
    has_wise = bool(os.environ.get("WISE_API_TOKEN"))
    has_xero = bool(os.environ.get("XERO_CLIENT_ID"))
    chains["financial"] = [
        "ok" if has_wise else "off",
        "ok" if has_xero else "off",
        "ok" if task_ran("daily_briefing") else "off",
        "ok" if task_ran("morning_briefing") else "off",
        "ok" if task_ran("tony_report") else "off",
    ]

    # Lifecycle chain
    chains["lifecycle"] = [
        "ok",  # Shopify always pulling
        "ok" if task_ran("intelligence_sync") else "off",
        "ok" if task_ran("replenishment_scan") else "off",
        "ok" if task_ran("replenishment_scan") else "off",  # Klaviyo follows replenishment
        "ok" if task_ran("ltv_analysis") else "off",
    ]

    return {"task_runs": task_runs, "chains": chains}


# === DBH BUSINESS OPERATIONS ENDPOINTS ===

CAMPAIGNS_FILE = BASE_DIR / "config" / "dbh-campaigns.json"


def _load_campaigns_config():
    if CAMPAIGNS_FILE.exists():
        with open(CAMPAIGNS_FILE) as f:
            return json.load(f)
    return {}


@app.get("/api/dbh/targets")
def get_dbh_targets():
    """Revenue targets vs actuals — DB for monthly totals, live Shopify API for today."""
    import requests as http_requests

    config = _load_campaigns_config()
    targets = config.get("targets", {}).get("monthly", {})

    now = datetime.now()
    month_key = now.strftime("%Y-%m")
    month_start = now.strftime("%Y-%m-01")
    days_elapsed = now.day
    days_in_month = 31 if now.month in [1, 3, 5, 7, 8, 10, 12] else 30 if now.month != 2 else 28
    days_left = days_in_month - days_elapsed

    # DB for month-to-date (synced every 30 min by background task)
    today_str = now.strftime("%Y-%m-%d")
    yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    month_rev = query_db("customer_intelligence.db",
        "SELECT COALESCE(SUM(total_price), 0) as rev, COUNT(*) as orders FROM orders WHERE created_at >= ?",
        (month_start,), one=True)
    yesterday_rev = query_db("customer_intelligence.db",
        "SELECT COALESCE(SUM(total_price), 0) as rev, COUNT(*) as orders FROM orders WHERE DATE(created_at) = ?",
        (yesterday_str,), one=True)

    month_revenue = month_rev["rev"] if month_rev else 0
    month_orders = month_rev["orders"] if month_rev else 0

    # Live Shopify API for today's numbers (always fresh)
    today_revenue = 0
    today_orders = 0
    store_url = os.environ.get("SHOPIFY_STORE_URL")
    shopify_token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
    if store_url and shopify_token:
        try:
            now_nz = datetime.now(NZ_TZ)
            today_start = now_nz.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            headers = {"X-Shopify-Access-Token": shopify_token, "Content-Type": "application/json"}
            resp = http_requests.get(
                f"https://{store_url}/admin/api/2025-01/orders.json",
                headers=headers,
                params={"created_at_min": today_start, "status": "any", "limit": 250},
                timeout=10
            )
            if resp.status_code == 200:
                orders = resp.json().get("orders", [])
                today_orders = len(orders)
                today_revenue = sum(float(o.get("total_price", 0)) for o in orders)
        except Exception as e:
            logger.debug(f"Live Shopify today fetch: {e}")
            # Fall back to DB
            today_rev = query_db("customer_intelligence.db",
                "SELECT COALESCE(SUM(total_price), 0) as rev, COUNT(*) as orders FROM orders WHERE DATE(created_at) = ?",
                (today_str,), one=True)
            today_revenue = today_rev["rev"] if today_rev else 0
            today_orders = today_rev["orders"] if today_rev else 0

    target = targets.get(month_key, {})
    revenue_target = target.get("revenue", 50000)
    daily_run_rate = month_revenue / max(days_elapsed, 1)
    daily_needed = (revenue_target - month_revenue) / max(days_left, 1)
    pct_complete = round(month_revenue / revenue_target * 100, 1) if revenue_target else 0

    # Channel breakdown this month
    channels = query_db("customer_intelligence.db",
        "SELECT channel, COUNT(*) as orders, COALESCE(SUM(total_price), 0) as revenue, "
        "ROUND(AVG(total_price), 2) as aov FROM orders WHERE created_at >= ? GROUP BY channel ORDER BY revenue DESC",
        (month_start,))

    # 90-day goal: Mar-Jun cumulative trajectory
    ninety_day_targets = {
        "2026-03": 50000, "2026-04": 62500, "2026-05": 77500, "2026-06": 87500
    }
    ninety_day_total = sum(ninety_day_targets.values())  # $277,500
    ninety_day_start = "2026-03-01"

    # Days into the 90-day period (Mar 1 - Jun 30 = 122 days)
    period_start = datetime(2026, 3, 1)
    period_end = datetime(2026, 6, 30)
    total_period_days = (period_end - period_start).days  # 121
    days_into_period = (now - period_start).days
    days_remaining_period = max(total_period_days - days_into_period, 1)

    # Daily target north star: what we need per day to hit $277,500
    daily_target = round(ninety_day_total / total_period_days, 2) if total_period_days else 0

    # Total revenue since March 1 — use SAME source as monthly tracker
    # In March, cumulative = month revenue (they're the same period)
    # For future months, sum DB data for completed months + current month live
    current_month_key = now.strftime("%Y-%m")
    if current_month_key == "2026-03":
        # We're in month 1 — cumulative = monthly revenue (same data source)
        cumulative_rev = month_revenue
        cumulative_orders = month_orders
    else:
        # Future months: DB for completed months + live for current month
        cumulative_row = query_db("customer_intelligence.db",
            "SELECT COALESCE(SUM(total_price), 0) as rev, COUNT(*) as orders FROM orders WHERE created_at >= ?",
            (ninety_day_start,), one=True)
        cumulative_rev = cumulative_row["rev"] if cumulative_row else 0
        cumulative_orders = cumulative_row["orders"] if cumulative_row else 0
        # Add today's live orders not yet in DB
        cumulative_rev += today_revenue
        cumulative_orders += today_orders

    cumulative_pct = round(cumulative_rev / ninety_day_total * 100, 1) if ninety_day_total else 0

    # Expected cumulative by now (linear trajectory)
    expected_pct = round(days_into_period / total_period_days * 100, 1) if total_period_days else 0
    expected_rev = ninety_day_total * (days_into_period / total_period_days) if total_period_days else 0

    # Daily needed to still hit target from here
    remaining_target = ninety_day_total - cumulative_rev
    daily_needed_90 = round(remaining_target / days_remaining_period, 2) if days_remaining_period else 0

    # Monthly milestones with cumulative
    milestones = []
    cumul = 0
    for mk, mv in ninety_day_targets.items():
        cumul += mv
        milestones.append({"month": mk, "target": mv, "cumulative": cumul})

    return {
        "month": month_key,
        "revenue": round(month_revenue, 2),
        "revenue_target": revenue_target,
        "pct_complete": pct_complete,
        "orders": month_orders,
        "daily_run_rate": round(daily_run_rate, 2),
        "daily_needed": round(daily_needed, 2),
        "days_left": days_left,
        "today_revenue": round(today_revenue, 2),
        "today_orders": today_orders,
        "yesterday_revenue": round(yesterday_rev["rev"] if yesterday_rev else 0, 2),
        "channels": channels,
        "on_track": daily_run_rate >= (revenue_target / days_in_month),
        "last_db_sync": _last_sync.isoformat() if _last_sync else None,
        "ninety_day": {
            "total_target": ninety_day_total,
            "cumulative_revenue": round(cumulative_rev, 2),
            "cumulative_orders": cumulative_orders,
            "cumulative_pct": cumulative_pct,
            "days_into_period": days_into_period,
            "days_remaining": days_remaining_period,
            "expected_pct": expected_pct,
            "expected_revenue": round(expected_rev, 2),
            "daily_target": daily_target,
            "daily_needed": daily_needed_90,
            "today_revenue": round(today_revenue, 2),
            "today_orders": today_orders,
            "on_track": cumulative_pct >= expected_pct * 0.85,
            "milestones": milestones,
        },
    }


@app.get("/api/dbh/campaigns")
def get_dbh_campaigns():
    """Campaign calendar and deliverables pipeline."""
    config = _load_campaigns_config()
    return {
        "campaigns": config.get("campaigns", []),
        "deliverables": config.get("deliverables", []),
    }


@app.get("/api/dbh/unlocks")
def get_dbh_unlocks():
    """Revenue unlock signals: AI decisions + customer intelligence."""
    # Active decisions from decisions.db
    decisions = query_db("decisions.db",
        "SELECT * FROM decisions WHERE status = 'active' ORDER BY confidence DESC LIMIT 10")

    # Insights from intelligence.db
    insights = query_db("intelligence.db",
        "SELECT * FROM insights ORDER BY created_at DESC LIMIT 5")

    # Customers likely to reorder (JOIN orders->customers via shopify_customer_id for names+email)
    reorder_candidates = query_db("customer_intelligence.db",
        "SELECT c.email as customer_email, c.first_name, c.last_name, "
        "COUNT(*) as orders, SUM(o.total_price) as ltv, "
        "MAX(o.created_at) as last_order, "
        "CAST(julianday('now') - julianday(MAX(o.created_at)) AS INTEGER) as days_since "
        "FROM orders o JOIN customers c ON o.shopify_customer_id = c.shopify_id "
        "GROUP BY c.email HAVING orders >= 2 "
        "ORDER BY days_since DESC LIMIT 15")

    # High-value customers who haven't ordered recently
    at_risk = query_db("customer_intelligence.db",
        "SELECT c.email as customer_email, c.first_name, c.last_name, "
        "COUNT(*) as orders, SUM(o.total_price) as ltv, "
        "MAX(o.created_at) as last_order, "
        "CAST(julianday('now') - julianday(MAX(o.created_at)) AS INTEGER) as days_since "
        "FROM orders o JOIN customers c ON o.shopify_customer_id = c.shopify_id "
        "GROUP BY c.email HAVING ltv > 150 AND days_since > 14 "
        "ORDER BY ltv DESC LIMIT 10")

    # Names already included from JOIN
    def format_rows(rows):
        result = []
        for r in (rows or []):
            item = dict(r)
            item["name"] = f"{r.get('first_name', '')} {r.get('last_name', '')}".strip() or r.get("customer_email", "").split("@")[0]
            result.append(item)
        return result

    return {
        "decisions": decisions or [],
        "insights": insights or [],
        "reorder_candidates": format_rows(reorder_candidates),
        "at_risk_customers": format_rows(at_risk),
    }


@app.get("/api/dbh/channels")
def get_dbh_channels():
    """Channel-level status and tasks."""
    config = _load_campaigns_config()
    channel_systems = config.get("channel_systems", {})

    now = datetime.now()
    month_start = now.strftime("%Y-%m-01")

    # Real metrics per channel (column is 'channel' not 'channel_group', 'created_at' not 'order_date')
    email_rev = query_db("customer_intelligence.db",
        "SELECT COALESCE(SUM(total_price), 0) as rev, COUNT(*) as orders FROM orders "
        "WHERE channel = 'Email' AND created_at >= ?", (month_start,), one=True)
    meta_rev = query_db("customer_intelligence.db",
        "SELECT COALESCE(SUM(total_price), 0) as rev, COUNT(*) as orders FROM orders "
        "WHERE channel = 'Meta Ads' AND created_at >= ?", (month_start,), one=True)
    google_rev = query_db("customer_intelligence.db",
        "SELECT COALESCE(SUM(total_price), 0) as rev, COUNT(*) as orders FROM orders "
        "WHERE channel IN ('Google Organic', 'Google Ads') AND created_at >= ?", (month_start,), one=True)
    seo_rev = query_db("customer_intelligence.db",
        "SELECT COALESCE(SUM(total_price), 0) as rev, COUNT(*) as orders FROM orders "
        "WHERE channel = 'Google Organic' AND created_at >= ?", (month_start,), one=True)

    return {
        "email": {
            "metrics": {"revenue": round(email_rev["rev"], 2) if email_rev else 0, "orders": email_rev["orders"] if email_rev else 0},
            **channel_systems.get("email", {}),
        },
        "paid_ads": {
            "metrics": {"meta_revenue": round(meta_rev["rev"], 2) if meta_rev else 0, "meta_orders": meta_rev["orders"] if meta_rev else 0},
            **channel_systems.get("paid_ads", {}),
        },
        "seo": {
            "metrics": {"organic_revenue": round(seo_rev["rev"], 2) if seo_rev else 0, "organic_orders": seo_rev["orders"] if seo_rev else 0},
            **channel_systems.get("seo", {}),
        },
        "other": channel_systems.get("other", {}),
    }


@app.get("/api/dbh/customers-crm")
def get_dbh_customers_crm():
    """Mini CRM: top customers, segments, product affinity."""
    now = datetime.now()

    # Top customers by LTV (JOIN to get names directly)
    top = query_db("customer_intelligence.db",
        "SELECT c.email as customer_email, c.first_name, c.last_name, "
        "COUNT(*) as orders, SUM(o.total_price) as ltv, "
        "MAX(o.created_at) as last_order, o.customer_type "
        "FROM orders o JOIN customers c ON o.shopify_customer_id = c.shopify_id "
        "GROUP BY c.email ORDER BY ltv DESC LIMIT 20")

    # Customer type breakdown
    types = query_db("customer_intelligence.db",
        "SELECT customer_type, COUNT(DISTINCT shopify_customer_id) as customers, "
        "COALESCE(SUM(total_price), 0) as revenue "
        "FROM orders GROUP BY customer_type ORDER BY revenue DESC")

    # Top products this month
    month_start = now.strftime("%Y-%m-01")
    products = query_db("customer_intelligence.db",
        "SELECT products, COUNT(*) as orders, COALESCE(SUM(total_price), 0) as revenue "
        "FROM orders WHERE created_at >= ? GROUP BY products ORDER BY revenue DESC LIMIT 10",
        (month_start,))

    # Names already from JOIN
    enriched_top = []
    for r in (top or []):
        item = dict(r)
        item["name"] = f"{r.get('first_name', '')} {r.get('last_name', '')}".strip() or "Unknown"
        enriched_top.append(item)

    return {
        "top_customers": enriched_top,
        "customer_types": types or [],
        "top_products": products or [],
        "total_customers": len(top) if top else 0,
    }


@app.get("/api/dbh/intelligence")
def get_dbh_intelligence():
    """Live agent intelligence: latest briefings, cross-agent events, session insights."""
    agents_dir = BASE_DIR / "agents"
    now = datetime.now()

    # Key business agents and their latest state
    agent_briefs = []
    biz_agents = [
        ("dbh-marketing", "Meridian", "Marketing Operations", "blue"),
        ("beacon", "Beacon", "SEO & Content", "green"),
    ]
    for folder, name, role, color in biz_agents:
        ctx_file = agents_dir / folder / "state" / "CONTEXT.md"
        brief = {"agent": name, "role": role, "color": color, "summary": "", "updated": "", "key_points": []}

        if ctx_file.exists():
            mtime = datetime.fromtimestamp(ctx_file.stat().st_mtime)
            brief["updated"] = mtime.strftime("%b %d, %I:%M%p")
            age_hours = (now - mtime).total_seconds() / 3600
            brief["age_hours"] = round(age_hours, 1)

            try:
                content = ctx_file.read_text()
                lines = content.split("\n")
                # Extract key sections (skip headers, get substance)
                key_lines = []
                for line in lines:
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("---") or line.startswith("*Last"):
                        continue
                    if any(skip in line.lower() for skip in ["template", "placeholder", "tbd", "not yet"]):
                        continue
                    if len(line) > 20:
                        key_lines.append(line)
                # Take the most substantive lines as key points
                brief["key_points"] = key_lines[:6]
                brief["summary"] = key_lines[0] if key_lines else "No briefing data yet"
            except Exception:
                brief["summary"] = "Error reading state"

        # Check for latest session log
        state_dir = agents_dir / folder / "state"
        if state_dir.exists():
            session_logs = sorted(state_dir.glob("session-log-*.md"), reverse=True)
            if session_logs:
                try:
                    log_content = session_logs[0].read_text()
                    # Extract insights and events from session log
                    for line in log_content.split("\n"):
                        if "[INSIGHT]" in line or "[EVENT]" in line or "Extracted" in line:
                            brief["key_points"].append(line.strip()[:150])
                except Exception:
                    pass

        agent_briefs.append(brief)

    # Cross-agent events from event bus
    events = query_db("event_bus.db",
        "SELECT source_agent, event_type, severity, payload, created_at, status "
        "FROM events ORDER BY created_at DESC LIMIT 10")

    # Format event payloads
    formatted_events = []
    for e in (events or []):
        evt = dict(e)
        try:
            evt["payload"] = json.loads(evt["payload"]) if isinstance(evt["payload"], str) else evt["payload"]
        except Exception:
            pass
        formatted_events.append(evt)

    # Latest agent interactions from learning.db (what agents actually said)
    interactions = query_db("learning.db",
        "SELECT agent, task, output_summary, tokens_used, model_used, created_at "
        "FROM interactions WHERE output_summary IS NOT NULL AND output_summary != '' "
        "ORDER BY created_at DESC LIMIT 5")

    # Insights with full detail
    insights = query_db("intelligence.db",
        "SELECT agent, domain, insight, evidence, confidence, confidence_score, created_at "
        "FROM insights ORDER BY created_at DESC LIMIT 10")

    # Briefs generated
    briefs = query_db("briefs.db",
        "SELECT brief_id, title, campaign_type, product, status, assigned_to, deadline, created_at "
        "FROM briefs ORDER BY created_at DESC LIMIT 5")

    return {
        "agent_briefs": agent_briefs,
        "events": formatted_events,
        "interactions": interactions or [],
        "insights": insights or [],
        "briefs": briefs or [],
    }


@app.get("/api/dbh/live-performance")
async def get_live_performance():
    """Pull REAL-TIME data from Shopify, Klaviyo, Meta, Google APIs. Not cached DB snapshots."""
    import requests as http_requests

    now_nz = datetime.now(NZ_TZ)
    result = {"fetched_at": now_nz.isoformat(), "shopify": None, "klaviyo": None, "meta": None, "google": None}

    # --- SHOPIFY LIVE ---
    store_url = os.environ.get("SHOPIFY_STORE_URL")
    shopify_token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
    if store_url and shopify_token:
        try:
            headers = {"X-Shopify-Access-Token": shopify_token, "Content-Type": "application/json"}
            # Today's orders
            today_start = now_nz.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            resp = http_requests.get(
                f"https://{store_url}/admin/api/2025-01/orders.json",
                headers=headers,
                params={"created_at_min": today_start, "status": "any", "limit": 250},
                timeout=15
            )
            today_orders = resp.json().get("orders", [])
            today_revenue = sum(float(o.get("total_price", 0)) for o in today_orders)

            # 7-day orders for trend
            week_start = (now_nz - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            resp7 = http_requests.get(
                f"https://{store_url}/admin/api/2025-01/orders.json",
                headers=headers,
                params={"created_at_min": week_start, "status": "any", "limit": 250},
                timeout=15
            )
            week_orders = resp7.json().get("orders", [])
            week_revenue = sum(float(o.get("total_price", 0)) for o in week_orders)
            week_aov = week_revenue / len(week_orders) if week_orders else 0

            # Top products this week
            product_counts = {}
            product_revenue = {}
            for order in week_orders:
                for item in order.get("line_items", []):
                    name = item.get("title", "Unknown")
                    qty = item.get("quantity", 0)
                    price = float(item.get("price", 0)) * qty
                    product_counts[name] = product_counts.get(name, 0) + qty
                    product_revenue[name] = product_revenue.get(name, 0) + price
            top_products = sorted(product_revenue.items(), key=lambda x: x[1], reverse=True)[:8]

            # Attribution breakdown
            sources = {}
            for order in week_orders:
                ref = order.get("referring_site", "")
                source = order.get("source_name", "")
                if "klaviyo" in str(ref).lower() or "email" in str(source).lower():
                    key = "Email"
                elif "facebook" in str(ref).lower() or "fb" in str(ref).lower() or "instagram" in str(ref).lower():
                    key = "Meta Ads"
                elif "google" in str(ref).lower():
                    key = "Google"
                elif ref:
                    key = "Referral"
                else:
                    key = "Direct"
                if key not in sources:
                    sources[key] = {"orders": 0, "revenue": 0}
                sources[key]["orders"] += 1
                sources[key]["revenue"] += float(order.get("total_price", 0))

            result["shopify"] = {
                "today": {"orders": len(today_orders), "revenue": round(today_revenue, 2)},
                "week": {"orders": len(week_orders), "revenue": round(week_revenue, 2), "aov": round(week_aov, 2)},
                "top_products": [{"name": n, "revenue": round(r, 2), "units": product_counts.get(n, 0)} for n, r in top_products],
                "attribution": {k: {"orders": v["orders"], "revenue": round(v["revenue"], 2)} for k, v in sorted(sources.items(), key=lambda x: x[1]["revenue"], reverse=True)},
            }
        except Exception as e:
            logger.error(f"Shopify live fetch error: {e}")
            result["shopify"] = {"error": str(e)}

    # --- KLAVIYO LIVE ---
    klaviyo_key = os.environ.get("KLAVIYO_API_KEY")
    if klaviyo_key:
        try:
            kheaders = {"Authorization": f"Klaviyo-API-Key {klaviyo_key}", "Accept": "application/json", "revision": "2025-07-15"}

            # Get recent campaigns (sort by updated_at so most recently active comes first)
            resp = http_requests.get(
                "https://a.klaviyo.com/api/campaigns",
                headers=kheaders,
                params={"filter": "equals(messages.channel,'email')", "sort": "-updated_at", "include": "campaign-messages"},
                timeout=15
            )
            resp_json = resp.json() if resp.status_code == 200 else {}
            campaigns = resp_json.get("data", [])

            # Build message detail lookup (subject lines, from labels)
            message_details = {}
            for inc in resp_json.get("included", []):
                if inc.get("type") == "campaign-message":
                    content = inc.get("attributes", {}).get("definition", {}).get("content", {})
                    message_details[inc["id"]] = {
                        "subject": content.get("subject", ""),
                        "preview_text": content.get("preview_text", ""),
                        "from_label": content.get("from_label", ""),
                    }

            # Find Placed Order metric ID
            placed_order_metric_id = None
            try:
                mr = http_requests.get("https://a.klaviyo.com/api/metrics", headers=kheaders, timeout=15)
                if mr.status_code == 200:
                    for m in mr.json().get("data", []):
                        if m.get("attributes", {}).get("name") == "Placed Order":
                            integration = m.get("attributes", {}).get("integration", {})
                            int_name = integration.get("name", "") if integration else ""
                            if int_name == "Shopify" or placed_order_metric_id is None:
                                placed_order_metric_id = m["id"]
            except Exception:
                pass

            # Get metrics for recent sent campaigns
            campaign_results = []
            for c in campaigns[:10]:
                attrs = c.get("attributes", {})
                if attrs.get("status") not in ("Sent", "Sending"):
                    continue
                campaign_id = c.get("id", "")
                name = attrs.get("name", "Unknown")
                send_time = attrs.get("send_time", "")

                # Get subject line from included messages
                msg_ids = [r["id"] for r in c.get("relationships", {}).get("campaign-messages", {}).get("data", [])]
                msg_detail = message_details.get(msg_ids[0], {}) if msg_ids else {}

                camp_data = {
                    "name": name,
                    "send_time": send_time[:16].replace("T", " ") if send_time else "",
                    "subject": msg_detail.get("subject", ""),
                    "preview_text": msg_detail.get("preview_text", ""),
                    "from_label": msg_detail.get("from_label", ""),
                    "status": attrs.get("status", ""),
                }

                if campaign_id and placed_order_metric_id:
                    try:
                        metrics_payload = {
                            "data": {
                                "type": "campaign-values-report",
                                "attributes": {
                                    "statistics": ["opens", "clicks", "recipients", "unsubscribes", "open_rate", "click_rate", "conversion_value", "conversions", "conversion_rate"],
                                    "timeframe": {"key": "last_30_days"},
                                    "filter": f'equals(campaign_id,"{campaign_id}")',
                                    "conversion_metric_id": placed_order_metric_id,
                                },
                            }
                        }
                        mr = http_requests.post(
                            "https://a.klaviyo.com/api/campaign-values-reports/",
                            headers={**kheaders, "Content-Type": "application/json"},
                            json=metrics_payload, timeout=15
                        )
                        if mr.status_code == 200:
                            results = mr.json().get("data", {}).get("attributes", {}).get("results", [])
                            if results:
                                stats = results[0].get("statistics", {})
                                recipients = int(stats.get("recipients", 0))
                                conversions = int(stats.get("conversions", 0))
                                revenue = float(stats.get("conversion_value", 0))
                                unsubs = int(stats.get("unsubscribes", 0))
                                camp_data.update({
                                    "recipients": recipients,
                                    "opens": int(stats.get("opens", 0)),
                                    "open_rate": round(float(stats.get("open_rate", 0)) * 100, 1),
                                    "clicks": int(stats.get("clicks", 0)),
                                    "click_rate": round(float(stats.get("click_rate", 0)) * 100, 1),
                                    "conversions": conversions,
                                    "conversion_rate": round(float(stats.get("conversion_rate", 0)) * 100, 2),
                                    "revenue": round(revenue, 2),
                                    "unsubscribes": unsubs,
                                    "unsub_rate": round(unsubs / recipients * 100, 2) if recipients > 0 else 0,
                                    "rev_per_recipient": round(revenue / recipients, 2) if recipients > 0 else 0,
                                    "rev_per_click": round(revenue / int(stats.get("clicks", 0)), 2) if int(stats.get("clicks", 0)) > 0 else 0,
                                })
                    except Exception:
                        pass

                campaign_results.append(camp_data)
                if len(campaign_results) >= 5:
                    break

            # Aggregate email totals
            total_email_rev = sum(c.get("revenue", 0) for c in campaign_results)
            total_email_orders = sum(c.get("conversions", 0) for c in campaign_results)
            avg_open_rate = sum(c.get("open_rate", 0) for c in campaign_results if c.get("open_rate")) / max(len([c for c in campaign_results if c.get("open_rate")]), 1)
            avg_click_rate = sum(c.get("click_rate", 0) for c in campaign_results if c.get("click_rate")) / max(len([c for c in campaign_results if c.get("click_rate")]), 1)

            result["klaviyo"] = {
                "campaigns": campaign_results,
                "summary": {
                    "total_revenue": round(total_email_rev, 2),
                    "total_orders": total_email_orders,
                    "avg_open_rate": round(avg_open_rate, 1),
                    "avg_click_rate": round(avg_click_rate, 1),
                    "campaigns_analysed": len(campaign_results),
                },
            }
        except Exception as e:
            logger.error(f"Klaviyo live fetch error: {e}")
            result["klaviyo"] = {"error": str(e)}

    # --- META ADS LIVE ---
    meta_token = os.environ.get("META_ACCESS_TOKEN")
    meta_account = os.environ.get("META_AD_ACCOUNT_ID")
    if meta_token and meta_account:
        try:
            # 7-day window
            nz_start = (now_nz - timedelta(days=6)).replace(hour=0, minute=0, second=0, microsecond=0)
            nz_start_utc = nz_start.astimezone(ZoneInfo("UTC"))
            nz_end_utc = now_nz.astimezone(ZoneInfo("UTC"))
            since = nz_start_utc.strftime("%Y-%m-%d")
            until = nz_end_utc.strftime("%Y-%m-%d")

            # Also today only
            today_nz = now_nz.replace(hour=0, minute=0, second=0, microsecond=0)
            today_utc = today_nz.astimezone(ZoneInfo("UTC"))
            today_since = today_utc.strftime("%Y-%m-%d")

            def _meta_insights(since_d, until_d):
                url = f"https://graph.facebook.com/v21.0/act_{meta_account}/insights"
                resp = http_requests.get(url, params={
                    "access_token": meta_token,
                    "time_range": json.dumps({"since": since_d, "until": until_d}),
                    "fields": "spend,impressions,clicks,cpc,ctr,actions,action_values,purchase_roas",
                    "level": "account"
                }, timeout=15)
                if resp.status_code != 200:
                    return None
                data = resp.json().get("data", [])
                if not data:
                    return {"spend": 0, "impressions": 0, "clicks": 0, "ctr": 0, "cpc": 0, "purchases": 0, "revenue": 0, "roas": 0}
                d = data[0]
                purchases = 0
                purchase_value = 0
                for a in d.get("actions", []):
                    if a.get("action_type") == "purchase":
                        purchases = int(a.get("value", 0))
                for a in d.get("action_values", []):
                    if a.get("action_type") == "purchase":
                        purchase_value = float(a.get("value", 0))
                spend = float(d.get("spend", 0))
                return {
                    "spend": round(spend, 2),
                    "impressions": int(d.get("impressions", 0)),
                    "clicks": int(d.get("clicks", 0)),
                    "ctr": round(float(d.get("ctr", 0)), 2),
                    "cpc": round(float(d.get("cpc", 0)), 2),
                    "purchases": purchases,
                    "revenue": round(purchase_value, 2),
                    "roas": round(purchase_value / spend, 2) if spend > 0 else 0,
                }

            today_meta = _meta_insights(today_since, until)
            week_meta = _meta_insights(since, until)

            # Campaign-level breakdown
            camp_url = f"https://graph.facebook.com/v21.0/act_{meta_account}/insights"
            camp_resp = http_requests.get(camp_url, params={
                "access_token": meta_token,
                "time_range": json.dumps({"since": since, "until": until}),
                "fields": "campaign_name,spend,impressions,clicks,actions,action_values",
                "level": "campaign", "limit": 10
            }, timeout=15)
            campaign_breakdown = []
            if camp_resp.status_code == 200:
                for c in camp_resp.json().get("data", []):
                    c_spend = float(c.get("spend", 0))
                    c_purchases = 0
                    c_revenue = 0
                    for a in c.get("actions", []):
                        if a.get("action_type") == "purchase":
                            c_purchases = int(a.get("value", 0))
                    for a in c.get("action_values", []):
                        if a.get("action_type") == "purchase":
                            c_revenue = float(a.get("value", 0))
                    campaign_breakdown.append({
                        "name": c.get("campaign_name", "Unknown"),
                        "spend": round(c_spend, 2),
                        "clicks": int(c.get("clicks", 0)),
                        "purchases": c_purchases,
                        "revenue": round(c_revenue, 2),
                        "roas": round(c_revenue / c_spend, 2) if c_spend > 0 else 0,
                    })

            result["meta"] = {
                "today": today_meta,
                "week": week_meta,
                "campaigns": campaign_breakdown,
            }
        except Exception as e:
            logger.error(f"Meta live fetch error: {e}")
            result["meta"] = {"error": str(e)}

    # --- GOOGLE ADS LIVE ---
    g_dev_token = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN")
    g_client_id = os.environ.get("GOOGLE_ADS_CLIENT_ID")
    g_client_secret = os.environ.get("GOOGLE_ADS_CLIENT_SECRET")
    g_refresh = os.environ.get("GOOGLE_ADS_REFRESH_TOKEN")
    g_customer = os.environ.get("GOOGLE_ADS_CUSTOMER_ID")
    if g_dev_token and g_refresh and g_client_id and g_client_secret and g_customer:
        try:
            g_customer = g_customer.replace("-", "")
            # OAuth token exchange
            token_resp = http_requests.post("https://oauth2.googleapis.com/token", data={
                "client_id": g_client_id, "client_secret": g_client_secret,
                "refresh_token": g_refresh, "grant_type": "refresh_token",
            }, timeout=15)
            if token_resp.status_code == 200:
                access_token = token_resp.json().get("access_token")
                end_date = now_nz.strftime("%Y-%m-%d")
                start_date = (now_nz - timedelta(days=6)).strftime("%Y-%m-%d")
                query = (
                    "SELECT campaign.name, campaign.status, "
                    "metrics.cost_micros, metrics.clicks, metrics.impressions, "
                    "metrics.conversions, metrics.conversions_value "
                    f"FROM campaign WHERE segments.date BETWEEN '{start_date}' AND '{end_date}' "
                    "AND campaign.status != 'REMOVED' ORDER BY metrics.cost_micros DESC"
                )
                g_headers = {"Authorization": f"Bearer {access_token}", "developer-token": g_dev_token, "Content-Type": "application/json"}
                search_resp = http_requests.post(
                    f"https://googleads.googleapis.com/v19/customers/{g_customer}/googleAds:searchStream",
                    headers=g_headers, json={"query": query}, timeout=30
                )
                if search_resp.status_code == 200:
                    response_data = search_resp.json()
                    all_rows = []
                    if isinstance(response_data, list):
                        for batch in response_data:
                            all_rows.extend(batch.get("results", []))
                    elif isinstance(response_data, dict):
                        all_rows.extend(response_data.get("results", []))

                    total_spend = 0
                    total_clicks = 0
                    total_impressions = 0
                    total_conv = 0
                    total_conv_value = 0
                    g_campaigns = {}
                    for row in all_rows:
                        camp = row.get("campaign", {})
                        metrics = row.get("metrics", {})
                        name = camp.get("name", "Unknown")
                        spend = int(metrics.get("costMicros", 0)) / 1_000_000
                        clicks = int(metrics.get("clicks", 0))
                        impr = int(metrics.get("impressions", 0))
                        conv = float(metrics.get("conversions", 0))
                        cv = float(metrics.get("conversionsValue", 0))
                        total_spend += spend
                        total_clicks += clicks
                        total_impressions += impr
                        total_conv += conv
                        total_conv_value += cv
                        if name not in g_campaigns:
                            g_campaigns[name] = {"spend": 0, "clicks": 0, "conversions": 0, "conv_value": 0}
                        g_campaigns[name]["spend"] += spend
                        g_campaigns[name]["clicks"] += clicks
                        g_campaigns[name]["conversions"] += conv
                        g_campaigns[name]["conv_value"] += cv

                    result["google"] = {
                        "week": {
                            "spend": round(total_spend, 2),
                            "clicks": total_clicks,
                            "impressions": total_impressions,
                            "conversions": round(total_conv),
                            "conv_value": round(total_conv_value, 2),
                            "roas": round(total_conv_value / total_spend, 2) if total_spend > 0 else 0,
                            "cpc": round(total_spend / total_clicks, 2) if total_clicks > 0 else 0,
                        },
                        "campaigns": [
                            {"name": n, "spend": round(m["spend"], 2), "clicks": m["clicks"],
                             "conversions": round(m["conversions"]), "conv_value": round(m["conv_value"], 2),
                             "roas": round(m["conv_value"] / m["spend"], 2) if m["spend"] > 0 else 0}
                            for n, m in sorted(g_campaigns.items(), key=lambda x: x[1]["spend"], reverse=True)
                        ],
                    }
                else:
                    result["google"] = {"error": f"API {search_resp.status_code}"}
            else:
                result["google"] = {"error": f"OAuth {token_resp.status_code}"}
        except Exception as e:
            logger.error(f"Google Ads live fetch error: {e}")
            result["google"] = {"error": str(e)}

    return result


@app.get("/api/dbh/learnings")
def get_dbh_learnings():
    """Historical learnings: proven hypotheses, playbook insights, decision outcomes."""

    # Decisions with outcomes from decisions.db
    all_decisions = query_db("decisions.db",
        "SELECT * FROM decisions ORDER BY created_at DESC LIMIT 30")

    # Insights from intelligence.db (accumulated learnings)
    all_insights = query_db("intelligence.db",
        "SELECT agent, domain, insight, evidence, confidence, confidence_score, created_at "
        "FROM insights ORDER BY confidence_score DESC, created_at DESC LIMIT 30")

    # Learning interactions (what agents have learned)
    interactions = query_db("learning.db",
        "SELECT agent, task, output_summary, tokens_used, created_at "
        "FROM interactions WHERE output_summary IS NOT NULL AND output_summary != '' "
        "ORDER BY created_at DESC LIMIT 20")

    # Historical playbook data (read from files)
    playbook_learnings = []
    email_playbook = BASE_DIR.parent / "dbh-aios" / "playbooks" / "email-playbook.md"
    creative_playbook = BASE_DIR.parent / "dbh-aios" / "playbooks" / "creative-playbook.md"
    cpa_ltv = BASE_DIR.parent / "dbh-aios" / "analysis" / "CPA-LTV-ANALYSIS-MAR2026.md"

    for pf, label in [(email_playbook, "Email Playbook"), (creative_playbook, "Creative Playbook"), (cpa_ltv, "CPA:LTV Analysis")]:
        if pf.exists():
            try:
                content = pf.read_text()
                # Extract key learnings (lines with specific patterns)
                key_lines = []
                for line in content.split("\n"):
                    line = line.strip()
                    if any(kw in line.lower() for kw in ["proven", "winner", "disproven", "finding", "insight", "learning", "hypothesis", "result", "ltv", "cpa", "roas"]):
                        if len(line) > 20 and not line.startswith("#"):
                            key_lines.append(line.replace("**", "").replace("*", "").strip("- "))
                playbook_learnings.append({"source": label, "file": str(pf.name), "learnings": key_lines[:15]})
            except Exception:
                pass

    # Active hypotheses (from decisions that have test status)
    hypotheses = []
    for d in (all_decisions or []):
        if d.get("status") in ("active", "testing", "monitoring"):
            hypotheses.append({
                "title": d.get("title", ""),
                "reasoning": d.get("reasoning", ""),
                "confidence": d.get("confidence", 0),
                "status": d.get("status", ""),
                "created": d.get("created_at", ""),
                "agent": d.get("agent", ""),
            })

    return {
        "decisions": all_decisions or [],
        "insights": all_insights or [],
        "interactions": interactions or [],
        "playbook_learnings": playbook_learnings,
        "hypotheses": hypotheses,
    }


@app.post("/api/dbh/ask")
async def ask_agent(request: dict):
    """Send a question to a specific agent and get a response.
    Body: { "agent": "prep|meridian|oracle", "message": "your question" }
    """
    import httpx

    agent_name = request.get("agent", "prep").lower()
    message = request.get("message", "")
    if not message:
        return {"error": "No message provided"}

    # Map short names to agent folders (DBH business agents only)
    agent_map = {
        "meridian": "dbh-marketing",
        "beacon": "beacon",
    }
    folder = agent_map.get(agent_name, agent_name)
    agents_dir = BASE_DIR / "agents"

    # Load agent brain (AGENT.md + CONTEXT.md)
    system_parts = []
    agent_md = agents_dir / folder / "AGENT.md"
    ctx_md = agents_dir / folder / "state" / "CONTEXT.md"
    if agent_md.exists():
        system_parts.append(agent_md.read_text()[:4000])
    if ctx_md.exists():
        system_parts.append(ctx_md.read_text()[:4000])

    # Add live business data context
    month_start = datetime.now().strftime("%Y-%m-01")
    month_rev = query_db("customer_intelligence.db",
        "SELECT COALESCE(SUM(total_price), 0) as rev, COUNT(*) as orders FROM orders WHERE created_at >= ?",
        (month_start,), one=True)
    if month_rev:
        system_parts.append(
            f"\n[LIVE DATA] March revenue: ${month_rev['rev']:.0f} from {month_rev['orders']} orders. "
            f"Target: $50,000. Days left: {31 - datetime.now().day}."
        )

    system_prompt = "\n\n---\n\n".join(system_parts)

    # Call Claude API
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"error": "No API key configured"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 1024,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": message}],
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                text = data["content"][0]["text"] if data.get("content") else "No response"
                return {"agent": agent_name, "response": text}
            else:
                return {"error": f"API error: {resp.status_code}", "detail": resp.text[:200]}
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# SEO RANKINGS — Pure Pets keyword position tracking
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/dbh/seo-rankings")
def get_seo_rankings():
    """Latest keyword rankings + summary + alerts from Pure Pets tracker."""
    try:
        from core.pure_pets_ranking_tracker import (
            get_latest_rankings, get_alerts_since, TRACKED_KEYWORDS
        )
        rankings = get_latest_rankings()
        alerts_raw = get_alerts_since(7)

        # Compute summary
        positions = [r["position"] for r in rankings if r.get("position")]
        total_clicks = sum(r.get("clicks", 0) for r in rankings)
        total_impressions = sum(r.get("impressions", 0) for r in rankings)
        in_top_10 = sum(1 for p in positions if p <= 10)
        in_top_20 = sum(1 for p in positions if p <= 20)
        avg_pos = round(sum(positions) / len(positions), 1) if positions else 0

        # Compute trend from change_from_previous values
        changes = [r.get("change_from_previous", 0) or 0 for r in rankings]
        net_change = sum(changes)
        trend = "improving" if net_change > 2 else ("declining" if net_change < -2 else "stable")

        # Format rankings for frontend
        formatted = []
        for r in rankings:
            formatted.append({
                "keyword": r.get("keyword", ""),
                "position": round(r.get("position", 0), 1),
                "change": round(r.get("change_from_previous", 0) or 0, 1),
                "impressions": r.get("impressions", 0),
                "clicks": r.get("clicks", 0),
                "ctr": round((r.get("ctr", 0) or 0) * 100, 2),
                "article_url": r.get("article_url", ""),
                "date": r.get("date", ""),
                "alert_flag": bool(r.get("alert_flag", 0)),
            })

        # Format alerts
        alerts = []
        for a in alerts_raw:
            alerts.append({
                "keyword": a.get("keyword", ""),
                "old_position": round((a.get("position", 0) or 0) - (a.get("change_from_previous", 0) or 0), 1),
                "new_position": round(a.get("position", 0) or 0, 1),
                "change": round(a.get("change_from_previous", 0) or 0, 1),
                "severity": "CRITICAL" if abs(a.get("change_from_previous", 0) or 0) > 5 else "IMPORTANT",
                "date": a.get("date", ""),
                "article_url": a.get("article_url", ""),
            })

        return {
            "summary": {
                "total_tracked": len(TRACKED_KEYWORDS),
                "with_data": len(rankings),
                "in_top_10": in_top_10,
                "in_top_20": in_top_20,
                "avg_position": avg_pos,
                "total_clicks_7d": total_clicks,
                "total_impressions_7d": total_impressions,
                "trend": trend,
            },
            "rankings": formatted,
            "alerts": alerts,
        }
    except Exception as e:
        logger.error(f"SEO rankings endpoint error: {e}")
        return {"summary": {"total_tracked": 22, "with_data": 0}, "rankings": [], "alerts": [], "error": str(e)}


@app.get("/api/dbh/seo-rankings/history")
def get_seo_ranking_history(keyword: str = "", days: int = 30):
    """Position history for a single keyword (for sparkline charts)."""
    try:
        from core.pure_pets_ranking_tracker import get_ranking_history
        if not keyword:
            return {"error": "keyword parameter required"}
        history = get_ranking_history(keyword, days)
        return {
            "keyword": keyword,
            "days": days,
            "history": [
                {
                    "date": h.get("date", ""),
                    "position": round(h.get("position", 0), 1),
                    "impressions": h.get("impressions", 0),
                    "clicks": h.get("clicks", 0),
                    "ctr": round((h.get("ctr", 0) or 0) * 100, 2),
                }
                for h in history
            ],
        }
    except Exception as e:
        logger.error(f"SEO ranking history error: {e}")
        return {"keyword": keyword, "history": [], "error": str(e)}


# ═══════════════════════════════════════════════════════════════════════════════
# EMAIL INTELLIGENCE — Hypothesis-driven email learning system
# ═══════════════════════════════════════════════════════════════════════════════

INTEL_DB = BASE_DIR / "data" / "intelligence.db"

def _ensure_email_intel_tables():
    """Create email intelligence tables if they don't exist."""
    conn = sqlite3.connect(str(INTEL_DB))
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS email_hypotheses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hypothesis TEXT NOT NULL,
        category TEXT,
        status TEXT DEFAULT 'testing',
        confidence REAL DEFAULT 0.5,
        validations INTEGER DEFAULT 0,
        contradictions INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS hypothesis_evidence (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hypothesis_id INTEGER REFERENCES email_hypotheses(id),
        campaign_id TEXT,
        campaign_name TEXT,
        supports BOOLEAN,
        metric_name TEXT,
        metric_value REAL,
        comparison_value REAL,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS email_campaigns (
        id TEXT PRIMARY KEY,
        name TEXT,
        subject_line TEXT,
        formula_tag TEXT,
        segment TEXT,
        sent_at TIMESTAMP,
        recipients INTEGER,
        open_rate REAL,
        click_rate REAL,
        conversion_rate REAL,
        revenue REAL,
        rev_per_recipient REAL,
        unsub_rate REAL,
        performance_tier TEXT,
        first_principles_analysis TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    conn.commit()
    conn.close()


# Formula auto-classification keywords
_FORMULA_KEYWORDS = {
    "F1": ["learn", "guide", "educational", "how to", "what is", "benefits", "science", "understand"],
    "F2": ["results", "customer", "review", "testimonial", "success", "story", "feedback", "loved"],
    "F3": ["struggling", "problem", "relief", "solution", "tired of", "finally", "stop", "fix"],
    "F4": ["research", "study", "clinical", "proven", "expert", "doctor", "authority", "evidence"],
    "F5": ["limited", "last chance", "ending", "hurry", "urgent", "final", "exclusive", "flash"],
}

def _classify_formula(subject: str) -> str:
    """Auto-classify email formula from subject line."""
    if not subject:
        return "unknown"
    subj_lower = subject.lower()
    scores = {}
    for formula, keywords in _FORMULA_KEYWORDS.items():
        scores[formula] = sum(1 for kw in keywords if kw in subj_lower)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "unknown"

def _classify_tier(rev_per_recipient: float) -> str:
    """Classify performance tier from revenue per recipient."""
    if rev_per_recipient >= 2.0:
        return "S"
    elif rev_per_recipient >= 1.0:
        return "A"
    elif rev_per_recipient >= 0.50:
        return "B"
    elif rev_per_recipient >= 0.20:
        return "C"
    else:
        return "D"


def _seed_playbook_hypotheses():
    """Seed hypotheses from email-playbook.md on first load."""
    conn = sqlite3.connect(str(INTEL_DB))
    existing = conn.execute("SELECT COUNT(*) FROM email_hypotheses").fetchone()[0]
    if existing > 0:
        conn.close()
        return  # Already seeded

    # Proven hypotheses (from 7 proven winners)
    proven = [
        ("Exclusive access + countdown urgency + single CTA drives highest revenue per campaign for loyal customers", "formula", "proven", 0.95, 7, 0),
        ("Event announcements to broad audience at peak purchase intent (BFCM) are volume plays that work", "timing", "proven", 0.90, 5, 0),
        ("A/B tested variations with segment-specific design lift conversions 2-5x vs single variation", "segment", "proven", 0.92, 6, 1),
        ("Benefit-specific subject lines consistently outperform generic wellness positioning on open rates", "subject", "proven", 0.95, 8, 0),
        ("Testimonial + USP messaging delivers high engagement even on small lists", "formula", "proven", 0.88, 5, 0),
        ("Gift psychology (free gift with purchase) outperforms discount psychology (% off) on engagement and LTV", "offer", "proven", 0.93, 6, 0),
        ("Engaged lifecycle segments (90-day active) produce 2-3x better metrics than unsegmented sends", "segment", "proven", 0.95, 7, 0),
    ]

    # Testing hypotheses (4 emerging patterns)
    testing = [
        ("Post-purchase recommendations without discount drive repeat purchases from loyal buyers", "formula", "testing", 0.75, 3, 1),
        ("Quality assurance and trust-building content drives exceptional engagement and long-term loyalty", "formula", "testing", 0.70, 2, 0),
        ("New product launch with specific discount to broad list generates high CTR via self-selection", "formula", "testing", 0.75, 2, 0),
        ("Final deadline + loss aversion messaging captures profitable procrastinator segment", "timing", "testing", 0.80, 3, 0),
    ]

    # Disproven hypotheses
    disproven = [
        ("Discount-only subject lines work well for engaged segments", "subject", "disproven", 0.10, 0, 5),
        ("Batch-and-blast to full newsletter without segmentation is effective for revenue", "segment", "disproven", 0.08, 0, 6),
        ("Generic wellness positioning in subject lines performs adequately", "subject", "disproven", 0.12, 1, 5),
    ]

    all_hyps = proven + testing + disproven
    for hyp_text, category, status, confidence, validations, contradictions in all_hyps:
        conn.execute("""
            INSERT INTO email_hypotheses (hypothesis, category, status, confidence, validations, contradictions)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (hyp_text, category, status, confidence, validations, contradictions))

    conn.commit()
    logger.info(f"Seeded {len(all_hyps)} email hypotheses from playbook")

    # Also seed key campaign records from playbook data
    campaigns = [
        ("pb-early-access", "Early Access Reminder", "Early Access Reminder", "F3", "Loyal", "2025-11-20", 850, 31.8, 2.80, 0.80, 9259, 10.89, 0.3, "S"),
        ("pb-bfcm", "BLACK FRIDAY BEGINS!", "BLACK FRIDAY BEGINS!", "F4", "Broad", "2025-11-29", 5200, 21.9, 1.03, 0.35, 5875, 1.13, 0.4, "A"),
        ("pb-bf-announcement", "Black Friday Announcement", "Black Friday Announcement Campaign", "F4", "Multi-segment", "2025-11-25", 4800, 31.4, 1.92, 0.50, 4834, 1.01, 0.3, "A"),
        ("pb-joints", "Support Your Joints Naturally", "Support Your Joints Naturally", "F2", "All", "2025-10-15", 3200, 52.85, 2.20, 0.40, 1500, 0.47, 0.2, "C"),
        ("pb-discover", "Discover What Sets Us Apart", "Discover What Sets Us Apart", "F1", "All", "2025-09-20", 963, 48.53, 2.95, 0.60, 1067, 1.11, 0.1, "A"),
        ("pb-gift", "Spend $150, get free moisturiser", "Spend $150, get free moisturiser", "F3", "Loyal", "2025-10-01", 1200, 77.1, 4.15, 1.20, 2800, 2.33, 0.1, "S"),
        ("pb-seamax", "Discover SeaMAX: Get 20% OFF", "Discover SeaMAX: Get 20% OFF", "F4", "Broad", "2025-08-15", 5572, 28.0, 4.38, 0.45, 2444, 0.44, 0.5, "C"),
        ("pb-bfcm-last", "BFCM Last Chance — Final Hours", "BFCM Last Chance Email — Final Hours to Save", "F5", "Repeat+Loyal", "2025-12-01", 3800, 42.3, 3.11, 0.55, 4471, 1.18, 0.3, "A"),
        ("pb-expiry", "Products have 3 year expiry", "Products have 3 year expiry", "F2", "All", "2025-07-10", 2500, 84.4, 1.20, 0.10, 200, 0.08, 0.05, "D"),
        ("pb-purchaser", "DBH Campaign 1 — Purchaser w/o Discount", "DBH Campaign 1 — Purchaser w/o Discount", "F1", "Purchasers", "2025-09-01", 1800, 47.52, 3.72, 0.65, 1807, 1.00, 0.2, "B"),
    ]

    for c in campaigns:
        conn.execute("""
            INSERT OR IGNORE INTO email_campaigns
                (id, name, subject_line, formula_tag, segment, sent_at, recipients,
                 open_rate, click_rate, conversion_rate, revenue, rev_per_recipient,
                 unsub_rate, performance_tier)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, c)

    conn.commit()
    conn.close()
    logger.info(f"Seeded {len(campaigns)} email campaigns from playbook")


@app.get("/api/email-intel/seed")
def seed_email_intel():
    """Manually trigger playbook seeding (idempotent)."""
    _ensure_email_intel_tables()
    _seed_playbook_hypotheses()
    return {"status": "seeded"}


@app.get("/api/email-intel/hypotheses")
def get_email_hypotheses():
    """All hypotheses grouped by status."""
    _ensure_email_intel_tables()
    _seed_playbook_hypotheses()  # Idempotent — only seeds if empty
    conn = sqlite3.connect(str(INTEL_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT h.*, COUNT(e.id) as evidence_count
        FROM email_hypotheses h
        LEFT JOIN hypothesis_evidence e ON e.hypothesis_id = h.id
        GROUP BY h.id
        ORDER BY h.confidence DESC
    """).fetchall()
    conn.close()

    grouped = {"testing": [], "proven": [], "disproven": []}
    for r in rows:
        d = dict(r)
        status = d.get("status", "testing")
        if status not in grouped:
            grouped[status] = []
        grouped[status].append(d)
    return grouped


@app.get("/api/email-intel/campaigns")
def get_email_campaigns(formula: str = "", segment: str = "", tier: str = "", limit: int = 50):
    """Campaign history with optional filters."""
    _ensure_email_intel_tables()
    conn = sqlite3.connect(str(INTEL_DB))
    conn.row_factory = sqlite3.Row

    query = "SELECT * FROM email_campaigns WHERE 1=1"
    params = []
    if formula:
        query += " AND formula_tag = ?"
        params.append(formula)
    if segment:
        query += " AND segment LIKE ?"
        params.append(f"%{segment}%")
    if tier:
        query += " AND performance_tier = ?"
        params.append(tier)
    query += " ORDER BY sent_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return {"campaigns": [dict(r) for r in rows], "total": len(rows)}


@app.get("/api/email-intel/patterns")
def get_email_patterns():
    """Auto-generated pattern analysis from campaign data."""
    _ensure_email_intel_tables()
    conn = sqlite3.connect(str(INTEL_DB))
    conn.row_factory = sqlite3.Row

    patterns = []

    # Formula comparison
    formula_rows = conn.execute("""
        SELECT formula_tag, COUNT(*) as count, AVG(open_rate) as avg_open,
               AVG(click_rate) as avg_click, AVG(revenue) as avg_revenue,
               AVG(rev_per_recipient) as avg_rpr, AVG(conversion_rate) as avg_conv
        FROM email_campaigns
        WHERE formula_tag != 'unknown' AND formula_tag IS NOT NULL
        GROUP BY formula_tag HAVING count >= 2
        ORDER BY avg_rpr DESC
    """).fetchall()

    if formula_rows:
        formulas = [dict(r) for r in formula_rows]
        if len(formulas) >= 2:
            best = formulas[0]
            patterns.append({
                "type": "formula_comparison",
                "title": f"Formula {best['formula_tag']} leads with ${best['avg_rpr']:.2f}/recipient",
                "data": formulas,
                "confidence": min(0.9, 0.5 + len(formulas) * 0.1),
                "insight": f"{best['formula_tag']} ({best['count']} campaigns) averages ${best['avg_rpr']:.2f}/recipient vs next best at ${formulas[1]['avg_rpr']:.2f}/recipient"
            })

    # Performance tier distribution
    tier_rows = conn.execute("""
        SELECT performance_tier, COUNT(*) as count, AVG(revenue) as avg_revenue,
               AVG(rev_per_recipient) as avg_rpr
        FROM email_campaigns
        WHERE performance_tier IS NOT NULL
        GROUP BY performance_tier
        ORDER BY avg_rpr DESC
    """).fetchall()

    if tier_rows:
        tiers = [dict(r) for r in tier_rows]
        total = sum(t["count"] for t in tiers)
        s_count = next((t["count"] for t in tiers if t["performance_tier"] == "S"), 0)
        patterns.append({
            "type": "tier_distribution",
            "title": f"{s_count}/{total} campaigns are Tier S performers",
            "data": tiers,
            "confidence": 0.95 if total >= 10 else 0.6,
            "insight": f"Performance distribution across {total} campaigns: " +
                       ", ".join(f"Tier {t['performance_tier']}: {t['count']}" for t in tiers)
        })

    # Segment comparison
    seg_rows = conn.execute("""
        SELECT segment, COUNT(*) as count, AVG(open_rate) as avg_open,
               AVG(click_rate) as avg_click, AVG(revenue) as avg_revenue,
               AVG(rev_per_recipient) as avg_rpr
        FROM email_campaigns
        WHERE segment IS NOT NULL AND segment != ''
        GROUP BY segment HAVING count >= 2
        ORDER BY avg_rpr DESC
    """).fetchall()

    if seg_rows:
        segs = [dict(r) for r in seg_rows]
        if len(segs) >= 2:
            patterns.append({
                "type": "segment_comparison",
                "title": f"'{segs[0]['segment']}' segment drives highest revenue per recipient",
                "data": segs,
                "confidence": min(0.85, 0.4 + len(segs) * 0.1),
                "insight": f"Top segment: {segs[0]['segment']} (${segs[0]['avg_rpr']:.2f}/recipient across {segs[0]['count']} campaigns)"
            })

    conn.close()
    return {"patterns": patterns}


@app.get("/api/email-intel/playbook")
def get_email_playbook():
    """Parsed playbook data from email-playbook.md."""
    playbook_paths = [
        BASE_DIR.parent / "dbh-aios" / "playbooks" / "email-playbook.md",
        BASE_DIR / "agents" / "dbh-marketing" / "playbooks" / "email-playbook.md",
    ]

    content = ""
    for p in playbook_paths:
        if p.exists():
            content = p.read_text()
            break

    if not content:
        return {"formulas": [], "proven": [], "emerging": [], "disproven": [], "benchmarks": {}}

    # Parse sections from markdown
    sections = {}
    current_section = ""
    current_lines = []

    for line in content.split("\n"):
        if line.startswith("## ") or line.startswith("# "):
            if current_section:
                sections[current_section] = "\n".join(current_lines)
            current_section = line.lstrip("#").strip().lower()
            current_lines = []
        else:
            current_lines.append(line)
    if current_section:
        sections[current_section] = "\n".join(current_lines)

    # Extract structured data
    formulas = []
    for key in ["f1", "f2", "f3", "f4", "f5"]:
        for section_name, text in sections.items():
            if key in section_name.lower() or f"formula {key[-1]}" in section_name.lower():
                formulas.append({"id": key.upper(), "name": section_name, "description": text[:500]})

    return {
        "raw_sections": {k: v[:2000] for k, v in sections.items()},
        "formulas": formulas,
        "section_count": len(sections),
        "total_length": len(content),
    }


from fastapi import Request

@app.post("/api/email-intel/hypotheses")
async def create_hypothesis(request: Request):
    """Create a new hypothesis."""
    _ensure_email_intel_tables()
    body = await request.json()
    hypothesis = body.get("hypothesis", "")
    category = body.get("category", "")
    if not hypothesis:
        return {"error": "hypothesis text required"}

    conn = sqlite3.connect(str(INTEL_DB))
    cursor = conn.execute(
        "INSERT INTO email_hypotheses (hypothesis, category) VALUES (?, ?)",
        (hypothesis, category)
    )
    hyp_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return {"id": hyp_id, "status": "created"}


@app.post("/api/email-intel/evidence")
async def log_evidence(request: Request):
    """Log evidence for/against a hypothesis. Auto-updates confidence."""
    _ensure_email_intel_tables()
    body = await request.json()
    hyp_id = body.get("hypothesis_id")
    supports = body.get("supports", True)
    if not hyp_id:
        return {"error": "hypothesis_id required"}

    conn = sqlite3.connect(str(INTEL_DB))
    conn.row_factory = sqlite3.Row

    # Insert evidence
    conn.execute("""
        INSERT INTO hypothesis_evidence
            (hypothesis_id, campaign_id, campaign_name, supports, metric_name,
             metric_value, comparison_value, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        hyp_id, body.get("campaign_id", ""), body.get("campaign_name", ""),
        supports, body.get("metric_name", ""), body.get("metric_value"),
        body.get("comparison_value"), body.get("notes", "")
    ))

    # Update hypothesis confidence
    if supports:
        conn.execute("""
            UPDATE email_hypotheses SET
                validations = validations + 1,
                confidence = MIN(1.0, confidence + 0.10),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (hyp_id,))
    else:
        conn.execute("""
            UPDATE email_hypotheses SET
                contradictions = contradictions + 1,
                confidence = MAX(0.0, confidence - 0.20),
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """, (hyp_id,))

    # Auto-promote/demote
    hyp = conn.execute("SELECT * FROM email_hypotheses WHERE id = ?", (hyp_id,)).fetchone()
    if hyp:
        h = dict(hyp)
        new_status = h["status"]
        if h["validations"] >= 5 and h["confidence"] >= 0.85:
            new_status = "proven"
        elif h["contradictions"] > h["validations"] and h["confidence"] < 0.25:
            new_status = "disproven"

        if new_status != h["status"]:
            conn.execute("UPDATE email_hypotheses SET status = ? WHERE id = ?", (new_status, hyp_id))

    conn.commit()
    conn.close()
    return {"status": "logged", "hypothesis_id": hyp_id}


@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    if DASHBOARD_FILE.exists():
        with open(DASHBOARD_FILE, "r") as f:
            return f.read()
    return "<h1>Dashboard file not found</h1>"


if __name__ == "__main__":
    import webbrowser

    print("\n  Tom's Command Center Dashboard")
    print("  http://localhost:8050\n")
    webbrowser.open("http://localhost:8050")
    uvicorn.run(app, host="0.0.0.0", port=8050, log_level="warning")
