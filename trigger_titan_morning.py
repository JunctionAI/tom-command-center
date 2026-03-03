#!/usr/bin/env python3
"""
Quick trigger to run TITAN morning protocol NOW.
Usage: python trigger_titan_morning.py
"""

import sys
import os
from pathlib import Path

# Add project to path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# Load configuration
from core.orchestrator import load_config, run_scheduled_task

def main():
    print("🏋️ Triggering TITAN morning protocol NOW...")

    try:
        telegram_config, schedule_config = load_config()

        # Run TITAN's morning protocol task
        run_scheduled_task("health-fitness", "morning_protocol", telegram_config)

        print("✅ TITAN morning protocol sent to Telegram")

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
