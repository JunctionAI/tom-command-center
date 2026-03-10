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
        """Wrap run_scheduled_task with execution logging."""
        import time
        start = time.time()
        try:
            run_scheduled_task(agent, task_name, telegram_config)
            elapsed = round(time.time() - start, 1)
            _log_task_execution(agent, task_name, "success", elapsed)
        except Exception as e:
            elapsed = round(time.time() - start, 1)
            _log_task_execution(agent, task_name, "error", elapsed, error_msg=str(e))
            raise

    timezone = schedule_config.get("timezone", "Pacific/Auckland")
    executors = {
        'default': ThreadPoolExecutor(10)  # Allow 10 concurrent tasks
    }
    job_defaults = {
        'coalesce': True,
        'max_instances': 1,
        'misfire_grace_time': 3600,  # 1 hour grace — never silently skip
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
