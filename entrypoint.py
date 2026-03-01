#!/usr/bin/env python3
"""
Entrypoint for VPS/container deployment.
Runs both the Telegram poller and the APScheduler in parallel.
"""

import sys
import os
import threading
import logging

# Ensure we can import from core/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'core'))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


def run_scheduler(telegram_config, schedule_config):
    """Run APScheduler in a background thread."""
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    from orchestrator import run_scheduled_task

    timezone = schedule_config.get("timezone", "Pacific/Auckland")
    scheduler = BackgroundScheduler(timezone=timezone)

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

    from orchestrator import load_config, start_polling, get_learning_db

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
