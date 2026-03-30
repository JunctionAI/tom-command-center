#!/usr/bin/env python3
"""
Scheduler — Reads schedules.json and registers cron jobs.
Uses APScheduler for cross-platform scheduling.

Install: pip install apscheduler anthropic requests
"""

import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
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
DATA_DIR = BASE_DIR / "data"

# How long (seconds) to lock a task after it fires — prevents duplicate execution
# when Railway restarts and misfire jobs fire immediately after the restart.
TASK_LOCK_SECONDS = 1800  # 30 minutes


def _get_lock_db() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / "scheduler_locks.db"


def _init_lock_db():
    db_path = _get_lock_db()
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_locks (
                task_id TEXT PRIMARY KEY,
                fired_at INTEGER NOT NULL
            )
        """)
        conn.commit()


def _try_acquire_lock(task_id: str) -> bool:
    """
    Try to acquire a lock for this task. Returns True if we should run, False if duplicate.
    A task is locked for TASK_LOCK_SECONDS after its last fire.
    """
    db_path = _get_lock_db()
    now = int(time.time())
    cutoff = now - TASK_LOCK_SECONDS

    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute(
            "SELECT fired_at FROM task_locks WHERE task_id = ?", (task_id,)
        ).fetchone()

        if row and row[0] > cutoff:
            fired_ago = now - row[0]
            logger.warning(
                f"DUPLICATE SUPPRESSED: {task_id} already fired {fired_ago}s ago "
                f"(lock window: {TASK_LOCK_SECONDS}s). Skipping."
            )
            return False

        # Upsert the lock
        conn.execute(
            "INSERT OR REPLACE INTO task_locks (task_id, fired_at) VALUES (?, ?)",
            (task_id, now)
        )
        conn.commit()

    return True


def _safe_run_task(agent: str, task_name: str, telegram_config: dict):
    """Wrapper around run_scheduled_task that acquires a dedup lock first."""
    task_id = f"{agent}_{task_name}"
    if not _try_acquire_lock(task_id):
        return
    run_scheduled_task(agent, task_name, telegram_config)


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
    _init_lock_db()

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
                _safe_run_task,
                trigger=CronTrigger(**cron_kwargs, timezone=timezone),
                args=[agent, task_name, telegram_config],
                id=f"{agent}_{task_name}",
                name=description,
                replace_existing=True,
                # misfire_grace_time: if Railway restarts and the job missed its window
                # by more than this many seconds, skip it (don't fire late).
                # Set to 300s (5 min) — if we missed by more than 5 min, skip.
                misfire_grace_time=300,
                # max_instances: never run more than 1 copy of the same job simultaneously.
                max_instances=1,
                coalesce=True,  # if multiple misfires stacked up, fire only once
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
