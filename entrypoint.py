#!/usr/bin/env python3
"""
Entrypoint for VPS/container deployment.
Runs both the Telegram poller and the APScheduler in parallel.
"""

import sys
import os
import threading
import logging

# Ensure project root is on Python path so 'from core.xxx import' works
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "orchestrator.log"), encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def _init_intelligence_db():
    """Create all required tables in intelligence.db at startup.
    Runs every boot — CREATE TABLE IF NOT EXISTS is idempotent.
    Fixes: email_hypotheses, email_campaigns, creative_hypotheses, creative_tests,
           and the new task_execution_log table for the health digest.
    """
    import sqlite3
    db_path = os.path.join(os.path.dirname(__file__), "data", "intelligence.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS email_hypotheses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hypothesis TEXT NOT NULL,
            category TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            confidence REAL DEFAULT 0.5,
            validations INTEGER DEFAULT 0,
            contradictions INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS email_campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            klaviyo_id TEXT UNIQUE,
            name TEXT,
            subject TEXT,
            formula TEXT DEFAULT '',
            segment TEXT DEFAULT '',
            tier TEXT DEFAULT '',
            send_date TEXT,
            open_rate REAL,
            click_rate REAL,
            revenue REAL,
            orders INTEGER,
            hypothesis_id INTEGER REFERENCES email_hypotheses(id),
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS creative_hypotheses (
            hypothesis_id TEXT PRIMARY KEY,
            hypothesis TEXT NOT NULL,
            category TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            confidence REAL DEFAULT 0.5,
            validations INTEGER DEFAULT 0,
            contradictions INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS creative_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hypothesis_id TEXT REFERENCES creative_hypotheses(hypothesis_id),
            test_name TEXT,
            variant TEXT,
            control TEXT,
            status TEXT DEFAULT 'running',
            result TEXT,
            confidence REAL,
            started_at TEXT DEFAULT (datetime('now')),
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS task_execution_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT NOT NULL,
            task TEXT NOT NULL,
            status TEXT NOT NULL,
            elapsed_secs REAL,
            output_chars INTEGER DEFAULT 0,
            error_msg TEXT DEFAULT '',
            ran_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()
    logger.info("intelligence.db: all tables verified/created")


def _log_task_execution(agent: str, task: str, status: str, elapsed: float, output_chars: int = 0, error_msg: str = ""):
    """Write one row to task_execution_log in intelligence.db."""
    import sqlite3
    db_path = os.path.join(os.path.dirname(__file__), "data", "intelligence.db")
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.execute(
            "INSERT INTO task_execution_log (agent, task, status, elapsed_secs, output_chars, error_msg) VALUES (?,?,?,?,?,?)",
            (agent, task, status, round(elapsed, 1), output_chars, error_msg[:200])
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"task_execution_log write failed (non-fatal): {e}")


def run_scheduler(telegram_config, schedule_config):
    """Run APScheduler in a background thread."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.executors.pool import ThreadPoolExecutor
    from core.orchestrator import run_scheduled_task

    def _tracked_task(agent, task_name, telegram_config):
        """Wrap run_scheduled_task with execution + delivery logging."""
        import time
        start = time.time()
        try:
            run_scheduled_task(agent, task_name, telegram_config)
            elapsed = round(time.time() - start, 1)
            _log_task_execution(agent, task_name, "success", elapsed)
            # Log delivery for monitoring
            try:
                from core.delivery_monitor import log_delivery, AGENT_RECIPIENTS
                recipient = AGENT_RECIPIENTS.get(agent, "Tom")
                log_delivery("command-center", recipient, agent, task_name,
                             "delivered", elapsed)
            except Exception:
                pass  # Non-fatal
        except Exception as e:
            elapsed = round(time.time() - start, 1)
            _log_task_execution(agent, task_name, "error", elapsed, error_msg=str(e))
            # Log failed delivery
            try:
                from core.delivery_monitor import log_delivery, AGENT_RECIPIENTS
                recipient = AGENT_RECIPIENTS.get(agent, "Tom")
                log_delivery("command-center", recipient, agent, task_name,
                             "failed", elapsed, error_msg=str(e))
            except Exception:
                pass  # Non-fatal
            raise

    timezone = schedule_config.get("timezone", "Pacific/Auckland")
    executors = {
        'default': ThreadPoolExecutor(10)  # Allow 10 concurrent tasks
    }
    job_defaults = {
        'coalesce': True,
        'max_instances': 1,
        'misfire_grace_time': 60,  # 60s grace — tasks that miss their window are skipped, not replayed
    }
    scheduler = BackgroundScheduler(
        timezone=timezone,
        executors=executors,
        job_defaults=job_defaults
    )

    for task in schedule_config["schedules"]:
        agent = task["agent"]
        task_name = task["task"]
        cron_str = task["cron"]
        description = task.get("description", f"{agent}/{task_name}")

        try:
            parts = cron_str.split()
            cron_kwargs = {
                "minute": parts[0],
                "hour": parts[1],
                "day": parts[2],
                "month": parts[3],
                "day_of_week": parts[4],
            }
            scheduler.add_job(
                _tracked_task,
                trigger=CronTrigger(**cron_kwargs, timezone=timezone),
                args=[agent, task_name, telegram_config],
                id=f"{agent}_{task_name}",
                name=description,
                replace_existing=True
            )
            logger.info(f"Scheduled: {description} ({cron_str})")
        except Exception as e:
            logger.error(f"Failed to schedule {description}: {e}")

    scheduler.start()
    logger.info(f"Scheduler running with {len(schedule_config['schedules'])} tasks (tz: {timezone})")

    return scheduler


def _run_missed_tasks(schedule_config, telegram_config, tracked_task_fn, timezone):
    """Check for tasks that should have run earlier today but were missed due to restart.
    Runs them now (staggered by 30s) so users still get their daily messages."""
    import sqlite3
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")
    hour_now = now.hour
    minute_now = now.minute
    day_of_week = now.weekday()  # 0=Monday ... 6=Sunday
    # APScheduler uses 0=Monday, cron uses 0=Sunday — convert
    cron_dow_map = {0: '1', 1: '2', 2: '3', 3: '4', 4: '5', 5: '6', 6: '0'}
    today_cron_dow = cron_dow_map[day_of_week]

    # Check task_execution_log for what already ran today
    db_path = os.path.join(os.path.dirname(__file__), "data", "intelligence.db")
    ran_today = set()
    try:
        conn = sqlite3.connect(db_path, check_same_thread=False)
        rows = conn.execute(
            "SELECT agent, task FROM task_execution_log WHERE ran_at >= ? AND status = 'success'",
            (today_str,)
        ).fetchall()
        conn.close()
        ran_today = {f"{r[0]}/{r[1]}" for r in rows}
    except Exception as e:
        logger.warning(f"Catch-up: couldn't read execution log: {e}")

    missed = []
    for task in schedule_config["schedules"]:
        agent = task["agent"]
        task_name = task["task"]
        cron_str = task["cron"]
        task_key = f"{agent}/{task_name}"

        if task_key in ran_today:
            continue  # Already ran today

        parts = cron_str.split()
        cron_minute, cron_hour, cron_day, cron_month, cron_dow = parts

        # Check if this task was scheduled for earlier today
        # Only catch up daily tasks (day=* and month=*)
        if cron_day != '*' or cron_month != '*':
            # Monthly/weekly-specific — check day-of-week
            if cron_dow != '*' and today_cron_dow not in cron_dow.split(',') and today_cron_dow not in _expand_cron_range(cron_dow):
                continue
            if cron_day != '*':
                if str(now.day) != cron_day:
                    continue

        # Check day-of-week constraint
        if cron_dow != '*':
            if today_cron_dow not in cron_dow.replace(' ', '').split(',') and today_cron_dow not in _expand_cron_range(cron_dow):
                continue

        # Check if the scheduled time was before now
        try:
            sched_hour = int(cron_hour)
            sched_minute = int(cron_minute)
        except ValueError:
            continue  # Skip complex cron expressions like */6

        sched_total = sched_hour * 60 + sched_minute
        now_total = hour_now * 60 + minute_now

        if sched_total < now_total:
            # Skip companion agent tasks that are more than 2 hours late
            # A Thursday midday check-in replayed Friday morning is confusing, not helpful
            # BUT: Tom's agent (apex) always catches up — morning briefs are useful even late
            from core.orchestrator import CHAT_USER_MAP
            minutes_late = now_total - sched_total
            if agent in CHAT_USER_MAP and agent != "apex" and minutes_late > 120:
                logger.info(f"Catch-up: SKIPPING {agent}/{task_name} — {minutes_late} min late (companion agent, >2hr threshold)")
                continue
            missed.append((agent, task_name, sched_hour, sched_minute, task.get("description", task_key)))

    if not missed:
        logger.info("Catch-up: no missed tasks found — all up to date")
        return

    logger.info(f"Catch-up: found {len(missed)} missed tasks, running now...")

    # Run missed tasks with 30-second stagger to avoid overwhelming the API
    import time
    for i, (agent, task_name, sh, sm, desc) in enumerate(missed):
        logger.info(f"Catch-up [{i+1}/{len(missed)}]: {agent}/{task_name} (was due {sh:02d}:{sm:02d})")
        try:
            threading.Thread(
                target=tracked_task_fn,
                args=(agent, task_name, telegram_config),
                name=f"catchup-{agent}-{task_name}",
                daemon=True
            ).start()
            if i < len(missed) - 1:
                time.sleep(30)  # Stagger to avoid API rate limits
        except Exception as e:
            logger.error(f"Catch-up failed for {agent}/{task_name}: {e}")


def _expand_cron_range(field):
    """Expand cron range like '1-5' into ['1','2','3','4','5']."""
    results = []
    for part in field.split(','):
        if '-' in part:
            try:
                start, end = part.split('-')
                results.extend(str(i) for i in range(int(start), int(end) + 1))
            except ValueError:
                results.append(part)
        else:
            results.append(part)
    return results


def main():
    # Validate environment
    required_vars = ["ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_OWNER_ID"]
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        logger.error("Set them in your .env file or deployment platform.")
        sys.exit(1)

    logger.info("=" * 50)
    logger.info("Tom's Command Center -- Starting")
    logger.info("=" * 50)

    # Log ALL integration env var status so we can see what's connected
    integrations = {
        "SHOPIFY_STORE_URL":       "Shopify (sales data)",
        "SHOPIFY_ACCESS_TOKEN":    "Shopify (auth)",
        "KLAVIYO_API_KEY":         "Klaviyo (email data)",
        "META_ACCESS_TOKEN":       "Meta Ads (auth)",
        "META_AD_ACCOUNT_ID":      "Meta Ads (account)",
        "GOOGLE_ADS_DEVELOPER_TOKEN": "Google Ads",
        "OPENAI_API_KEY":          "Voice transcription (Whisper)",
        "ASANA_ACCESS_TOKEN":      "Asana (tasks)",
        "ASANA_PROJECT_ID":        "Asana (project)",
        "SLACK_BOT_TOKEN":         "Slack monitoring",
        "WISE_API_TOKEN":          "Wise (multi-currency)",
        "XERO_CLIENT_ID":          "Xero (accounting)",
    }
    logger.info("--- Integration Status ---")
    connected = 0
    missing_list = []
    for var, label in integrations.items():
        is_set = bool(os.environ.get(var))
        status = "CONNECTED" if is_set else "NOT SET"
        logger.info(f"  [{status}] {label} ({var})")
        if is_set:
            connected += 1
        else:
            missing_list.append(label)
    logger.info(f"--- {connected}/{len(integrations)} integrations connected ---")
    if missing_list:
        logger.info(f"  Missing: {', '.join(missing_list)}")

    from core.orchestrator import load_config, start_polling, get_learning_db

    telegram_config, schedule_config = load_config()

    # Initialise all DB tables (idempotent — safe on every boot)
    _init_intelligence_db()

    # Initialise learning DB
    db = get_learning_db()
    if db:
        logger.info("Learning database: connected")
    else:
        logger.info("Learning database: unavailable (non-fatal)")

    # Start scheduler in background thread
    scheduler = run_scheduler(telegram_config, schedule_config)

    # Start dashboard API server in background thread (serves /api/system-health etc.)
    def _run_dashboard_api():
        try:
            import uvicorn
            from core.dashboard_server import app as dashboard_app
            port = int(os.environ.get("PORT", 8050))
            logger.info(f"Dashboard API starting on port {port}...")
            uvicorn.run(dashboard_app, host="0.0.0.0", port=port, log_level="warning")
        except Exception as e:
            logger.error(f"Dashboard API failed to start (non-fatal): {e}")

    api_thread = threading.Thread(target=_run_dashboard_api, name="dashboard-api", daemon=True)
    api_thread.start()

    # Start Telegram poller in main thread (blocking)
    logger.info("Starting Telegram polling...")
    try:
        start_polling(telegram_config)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        scheduler.shutdown()
        if db:
            db.close()


if __name__ == "__main__":
    main()
