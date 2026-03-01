#!/usr/bin/env python3
"""
Scheduler — Reads schedules.json and registers cron jobs.
Uses APScheduler for cross-platform scheduling.

Install: pip install apscheduler anthropic requests
"""

import json
import logging
from pathlib import Path
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

# Import from orchestrator
import sys
sys.path.insert(0, str(Path(__file__).parent))
from orchestrator import load_config, run_scheduled_task

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"


def parse_cron(cron_str: str) -> dict:
    """Parse a standard 5-field cron string into APScheduler kwargs."""
    parts = cron_str.split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron: {cron_str}")
    return {
        "minute": parts[0],
        "hour": parts[1],
        "day": parts[2],
        "month": parts[3],
        "day_of_week": parts[4],
    }


def main():
    telegram_config, schedule_config = load_config()
    timezone = schedule_config.get("timezone", "Pacific/Auckland")
    
    scheduler = BlockingScheduler(timezone=timezone)
    
    for task in schedule_config["schedules"]:
        agent = task["agent"]
        task_name = task["task"]
        cron_str = task["cron"]
        description = task.get("description", f"{agent}/{task_name}")
        
        try:
            cron_kwargs = parse_cron(cron_str)
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
    
    logger.info(f"All tasks scheduled. Timezone: {timezone}")
    logger.info(f"Total scheduled tasks: {len(schedule_config['schedules'])}")
    
    # Print upcoming runs
    jobs = scheduler.get_jobs()
    logger.info("Next runs:")
    for job in sorted(jobs, key=lambda j: j.next_run_time):
        logger.info(f"  {job.name}: {job.next_run_time}")
    
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
