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


def run_scheduler(telegram_config, schedule_config):
    """Run APScheduler in a background thread."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.executors.pool import ThreadPoolExecutor
    from core.orchestrator import run_scheduled_task

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
                run_scheduled_task,
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
