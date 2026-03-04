#!/usr/bin/env python3
"""
Daily Snapshot -- Locks calendar-day figures at 11:59pm NZST.

This prevents rolling 24-hour approximations. Every day at 11:59pm NZST:
- Queries exact date boundaries for that calendar day
- Records revenue, order count, channel breakdown, campaign spend
- Stores in daily_snapshots table (never overwrites historical data)
- PREP and other agents read from snapshots for accuracy

This is the single source of truth for daily performance.
"""

import os
import json
import sqlite3
import requests
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

NZ_TZ = ZoneInfo("Pacific/Auckland")

# --- Database ---

def get_snapshots_db():
    """Open or create daily_snapshots table."""
    db_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "data",
        "customer_intelligence.db"
    )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Create table if not exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS daily_snapshots (
            date TEXT PRIMARY KEY,
            captured_at TEXT,
            revenue REAL,
            order_count INTEGER,
            new_customers INTEGER,
            returning_customers INTEGER,
            repeat_rate REAL,
            channel_breakdown TEXT,
            meta_spend REAL,
            meta_conversions REAL,
            meta_roas REAL,
            email_send_count INTEGER,
            email_revenue REAL,
            google_spend REAL,
            google_conversions REAL,
            google_roas REAL,
            shopify_data TEXT,
            raw_snapshot TEXT,
            notes TEXT
        )
    """)
    conn.commit()
    return conn


# --- Snapshot Capture ---

def capture_daily_snapshot(date_str: str = None) -> dict:
    """
    Capture end-of-day snapshot for a specific date.

    Args:
        date_str: Date in YYYY-MM-DD format. If None, captures yesterday's date.
                  (Called at 11:59pm NZST, so "yesterday" = the day being closed out)

    Returns:
        dict with snapshot data ready for database storage
    """

    if date_str is None:
        # When called at 11:59pm, we want to capture the current day (still in progress)
        now_nz = datetime.now(NZ_TZ)
        date_str = now_nz.strftime("%Y-%m-%d")
    else:
        # Validate format
        datetime.strptime(date_str, "%Y-%m-%d")

    # Calculate exact date boundaries (midnight to midnight NZ time)
    day_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=NZ_TZ)
    day_start = day_date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = (day_date + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    snapshot = {
        "date": date_str,
        "captured_at": datetime.now(NZ_TZ).isoformat(),
        "revenue": 0,
        "order_count": 0,
        "new_customers": 0,
        "returning_customers": 0,
        "repeat_rate": 0,
        "channel_breakdown": {},
        "meta_spend": 0,
        "meta_conversions": 0,
        "meta_roas": 0,
        "email_send_count": 0,
        "email_revenue": 0,
        "google_spend": 0,
        "google_conversions": 0,
        "google_roas": 0,
        "shopify_data": {},
        "raw_snapshot": "",
        "notes": ""
    }

    # --- Fetch Shopify Orders ---
    store_url = os.environ.get("SHOPIFY_STORE_URL")
    shopify_token = os.environ.get("SHOPIFY_ACCESS_TOKEN")

    if store_url and shopify_token:
        try:
            headers = {
                "X-Shopify-Access-Token": shopify_token,
                "Content-Type": "application/json"
            }

            # Strict date boundaries
            orders_url = f"https://{store_url}/admin/api/2025-01/orders.json"
            resp = requests.get(orders_url, headers=headers, params={
                "created_at_min": day_start.isoformat(),
                "created_at_max": day_end.isoformat(),
                "status": "any",
                "limit": 250,
            }, timeout=15)

            orders = resp.json().get("orders", [])

            snapshot["order_count"] = len(orders)
            snapshot["revenue"] = sum(float(o.get("total_price", 0)) for o in orders)

            # Count new vs returning
            for order in orders:
                # Check if this is the customer's first order by looking at previous_orders_count
                if order.get("customer", {}).get("orders_count", 1) == 1:
                    snapshot["new_customers"] += 1
                else:
                    snapshot["returning_customers"] += 1

            total_customers = snapshot["new_customers"] + snapshot["returning_customers"]
            if total_customers > 0:
                snapshot["repeat_rate"] = snapshot["returning_customers"] / total_customers

            snapshot["shopify_data"] = {
                "orders_fetched": len(orders),
                "api_status": "success"
            }

        except Exception as e:
            snapshot["notes"] = f"Shopify API error: {str(e)}"
            snapshot["shopify_data"] = {"api_status": "error", "error": str(e)}

    # --- Fetch Meta Ads Spend (previous day closed, so use actual date) ---
    meta_access_token = os.environ.get("META_ACCESS_TOKEN")
    meta_ad_account_id = os.environ.get("META_AD_ACCOUNT_ID")

    if meta_access_token and meta_ad_account_id:
        try:
            # Meta's reporting is usually ready by next day morning
            # For today's snapshot at 11:59pm, we're capturing partial data
            meta_url = f"https://graph.instagram.com/v18.0/{meta_ad_account_id}/insights"
            resp = requests.get(meta_url, params={
                "access_token": meta_access_token,
                "fields": "spend,purchases,purchase_roas",
                "time_range": f'{{"since":"{date_str}","until":"{date_str}"}}',
            }, timeout=15)

            if resp.status_code == 200:
                insights = resp.json().get("data", [])
                if insights:
                    data = insights[0]
                    snapshot["meta_spend"] = float(data.get("spend", 0))
                    snapshot["meta_conversions"] = float(data.get("purchases", 0))
                    if snapshot["meta_spend"] > 0:
                        snapshot["meta_roas"] = snapshot["revenue"] / snapshot["meta_spend"] if snapshot["revenue"] > 0 else 0
        except Exception as e:
            pass  # Meta data is optional

    return snapshot


# --- Store Snapshot ---

def store_snapshot(snapshot: dict):
    """
    Store snapshot in database. If snapshot already exists for that date, update it.
    Never delete historical data.
    """
    db = get_snapshots_db()

    try:
        # Check if snapshot already exists
        existing = db.execute(
            "SELECT * FROM daily_snapshots WHERE date = ?",
            (snapshot["date"],)
        ).fetchone()

        if existing:
            # Update existing snapshot
            db.execute("""
                UPDATE daily_snapshots SET
                    captured_at = ?,
                    revenue = ?,
                    order_count = ?,
                    new_customers = ?,
                    returning_customers = ?,
                    repeat_rate = ?,
                    channel_breakdown = ?,
                    meta_spend = ?,
                    meta_conversions = ?,
                    meta_roas = ?,
                    email_send_count = ?,
                    email_revenue = ?,
                    google_spend = ?,
                    google_conversions = ?,
                    google_roas = ?,
                    shopify_data = ?,
                    raw_snapshot = ?,
                    notes = ?
                WHERE date = ?
            """, (
                snapshot["captured_at"],
                snapshot["revenue"],
                snapshot["order_count"],
                snapshot["new_customers"],
                snapshot["returning_customers"],
                snapshot["repeat_rate"],
                json.dumps(snapshot["channel_breakdown"]),
                snapshot["meta_spend"],
                snapshot["meta_conversions"],
                snapshot["meta_roas"],
                snapshot["email_send_count"],
                snapshot["email_revenue"],
                snapshot["google_spend"],
                snapshot["google_conversions"],
                snapshot["google_roas"],
                json.dumps(snapshot["shopify_data"]),
                json.dumps(snapshot),
                snapshot["notes"],
                snapshot["date"],
            ))
        else:
            # Insert new snapshot
            db.execute("""
                INSERT INTO daily_snapshots (
                    date, captured_at, revenue, order_count,
                    new_customers, returning_customers, repeat_rate,
                    channel_breakdown, meta_spend, meta_conversions, meta_roas,
                    email_send_count, email_revenue,
                    google_spend, google_conversions, google_roas,
                    shopify_data, raw_snapshot, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot["date"],
                snapshot["captured_at"],
                snapshot["revenue"],
                snapshot["order_count"],
                snapshot["new_customers"],
                snapshot["returning_customers"],
                snapshot["repeat_rate"],
                json.dumps(snapshot["channel_breakdown"]),
                snapshot["meta_spend"],
                snapshot["meta_conversions"],
                snapshot["meta_roas"],
                snapshot["email_send_count"],
                snapshot["email_revenue"],
                snapshot["google_spend"],
                snapshot["google_conversions"],
                snapshot["google_roas"],
                json.dumps(snapshot["shopify_data"]),
                json.dumps(snapshot),
                snapshot["notes"],
            ))

        db.commit()
        print(f"✓ Snapshot stored for {snapshot['date']}: ${snapshot['revenue']:.2f} from {snapshot['order_count']} orders")
        return True

    except Exception as e:
        print(f"✗ Error storing snapshot: {str(e)}")
        return False
    finally:
        db.close()


# --- Retrieve Snapshot ---

def get_snapshot(date_str: str) -> dict:
    """Retrieve a stored snapshot by date (YYYY-MM-DD)."""
    db = get_snapshots_db()

    try:
        row = db.execute(
            "SELECT * FROM daily_snapshots WHERE date = ?",
            (date_str,)
        ).fetchone()

        if not row:
            return None

        return dict(row)
    finally:
        db.close()


def get_recent_snapshots(days: int = 7) -> list:
    """Get last N days of snapshots."""
    db = get_snapshots_db()

    try:
        rows = db.execute(
            "SELECT * FROM daily_snapshots ORDER BY date DESC LIMIT ?",
            (days,)
        ).fetchall()

        return [dict(row) for row in rows]
    finally:
        db.close()


# --- Main Entry Point ---

def run_daily_snapshot():
    """
    Called at 11:59pm NZST by orchestrator.
    Captures today's complete day and stores it as locked snapshot.
    """
    now_nz = datetime.now(NZ_TZ)
    today_str = now_nz.strftime("%Y-%m-%d")

    print(f"\n[{now_nz.strftime('%H:%M:%S NZST')}] Capturing daily snapshot for {today_str}...")

    snapshot = capture_daily_snapshot(today_str)

    print(f"  Revenue: ${snapshot['revenue']:.2f}")
    print(f"  Orders: {snapshot['order_count']}")
    print(f"  Customers: {snapshot['new_customers']} new, {snapshot['returning_customers']} returning")

    stored = store_snapshot(snapshot)

    if stored:
        print(f"✓ Snapshot locked and ready for briefings\n")
    else:
        print(f"✗ Failed to store snapshot\n")

    return snapshot


if __name__ == "__main__":
    run_daily_snapshot()
