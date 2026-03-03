#!/usr/bin/env python3
"""
ROAS Tracker — Shopify-verified Meta ROAS calculation engine.

Runs nightly after intelligence_sync to:
1. Match Shopify orders (channel=meta-ads) to Meta campaigns via UTM params
2. Pull Meta spend per campaign from data_fetcher
3. Calculate verified ROAS = shopify_revenue / meta_spend
4. Track 3-day rolling ROAS for auto-pause decisions
5. Generate weekly ROAS summary for Tony report

Tables (in intelligence.db):
  - roas_daily: date, campaign_id, campaign_name, shopify_revenue, meta_spend, verified_roas, meta_claimed_roas
  - roas_alerts: campaign_id, days_below_floor, last_alert_date, paused
"""

import os
import json
import sqlite3
import logging
from datetime import datetime, timedelta, date
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

NZ_TZ = ZoneInfo("Pacific/Auckland")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
INTELLIGENCE_DB = BASE_DIR / "data" / "intelligence.db"
CUSTOMER_DB = BASE_DIR / "data" / "customer_intelligence.db"

ROAS_FLOOR = 2.0
DAYS_BELOW_FLOOR_TO_PAUSE = 3


def _get_db() -> sqlite3.Connection:
    """Get intelligence.db connection with ROAS tables."""
    INTELLIGENCE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(INTELLIGENCE_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS roas_daily (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            campaign_id TEXT,
            campaign_name TEXT,
            shopify_revenue REAL DEFAULT 0,
            meta_spend REAL DEFAULT 0,
            verified_roas REAL DEFAULT 0,
            meta_claimed_roas REAL DEFAULT 0,
            orders_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS roas_alerts (
            campaign_id TEXT PRIMARY KEY,
            campaign_name TEXT,
            days_below_floor INTEGER DEFAULT 0,
            last_alert_date TEXT,
            paused INTEGER DEFAULT 0,
            paused_at TEXT,
            reason TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_roas_date ON roas_daily(date);
        CREATE INDEX IF NOT EXISTS idx_roas_campaign ON roas_daily(campaign_id);
    """)
    conn.commit()
    return conn


def _get_customer_db() -> sqlite3.Connection:
    """Get customer_intelligence.db connection."""
    conn = sqlite3.connect(str(CUSTOMER_DB))
    conn.row_factory = sqlite3.Row
    return conn


def run_nightly_roas_check() -> str:
    """
    Main nightly ROAS verification. Call after intelligence_sync.

    Returns a formatted string with results + severity indicator.
    """
    today = date.today().isoformat()
    results = []
    alerts = []

    # 1. Get Meta orders from customer_intelligence.db (last 24h)
    try:
        cdb = _get_customer_db()
        rows = cdb.execute("""
            SELECT campaign, SUM(total_price) as revenue, COUNT(*) as order_count
            FROM orders
            WHERE channel = 'meta-ads'
              AND DATE(created_at) = ?
            GROUP BY campaign
        """, (today,)).fetchall()
        cdb.close()
    except Exception as e:
        logger.error(f"ROAS check: customer DB query failed: {e}")
        return f"[PRIORITY: IMPORTANT] ROAS check failed: {e}"

    # 2. Get Meta spend per campaign
    try:
        from core.data_fetcher import fetch_meta_ads_data
        meta_raw = fetch_meta_ads_data(days=1)
        # Parse spend from the formatted string
        meta_spend_by_campaign = _parse_meta_spend(meta_raw)
    except Exception as e:
        logger.warning(f"ROAS check: Meta spend fetch failed: {e}")
        meta_spend_by_campaign = {}

    # 3. Calculate verified ROAS per campaign
    db = _get_db()

    campaign_results = []
    for row in rows:
        campaign = row["campaign"] or "unknown"
        revenue = row["revenue"] or 0
        orders = row["order_count"] or 0
        spend = meta_spend_by_campaign.get(campaign, 0)

        verified_roas = revenue / spend if spend > 0 else 0

        # Store in roas_daily
        db.execute("""
            INSERT INTO roas_daily (date, campaign_id, campaign_name, shopify_revenue,
                                     meta_spend, verified_roas, orders_count)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (today, campaign, campaign, revenue, spend, verified_roas, orders))

        campaign_results.append({
            "campaign": campaign,
            "revenue": revenue,
            "spend": spend,
            "roas": verified_roas,
            "orders": orders,
        })

    # Also record campaigns with spend but no Shopify orders
    for campaign, spend in meta_spend_by_campaign.items():
        if not any(r["campaign"] == campaign for r in campaign_results):
            db.execute("""
                INSERT INTO roas_daily (date, campaign_id, campaign_name, shopify_revenue,
                                         meta_spend, verified_roas, orders_count)
                VALUES (?, ?, ?, 0, ?, 0, 0)
            """, (today, campaign, campaign, spend))
            campaign_results.append({
                "campaign": campaign,
                "revenue": 0,
                "spend": spend,
                "roas": 0,
                "orders": 0,
            })

    db.commit()

    # 4. Check 3-day rolling ROAS for auto-pause alerts
    three_days_ago = (date.today() - timedelta(days=3)).isoformat()

    for cr in campaign_results:
        campaign_id = cr["campaign"]

        # Get 3-day average
        avg_row = db.execute("""
            SELECT AVG(verified_roas) as avg_roas, COUNT(*) as days
            FROM roas_daily
            WHERE campaign_id = ? AND date >= ?
        """, (campaign_id, three_days_ago)).fetchone()

        avg_roas = avg_row["avg_roas"] or 0
        days_tracked = avg_row["days"] or 0

        if days_tracked >= 3 and avg_roas < ROAS_FLOOR and cr["spend"] > 0:
            # Update or create alert
            existing = db.execute(
                "SELECT * FROM roas_alerts WHERE campaign_id = ?",
                (campaign_id,)
            ).fetchone()

            if existing and existing["paused"]:
                continue  # Already paused

            days_below = (existing["days_below_floor"] + 1) if existing else 1

            db.execute("""
                INSERT OR REPLACE INTO roas_alerts
                (campaign_id, campaign_name, days_below_floor, last_alert_date, paused, reason)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (campaign_id, campaign_id, days_below, today, 0,
                  f"3-day avg ROAS: {avg_roas:.2f}x (floor: {ROAS_FLOOR}x)"))

            if days_below >= DAYS_BELOW_FLOOR_TO_PAUSE:
                # Auto-pause via Meta Ads Writer
                try:
                    from core.meta_ads_writer import MetaAdsWriter
                    writer = MetaAdsWriter()
                    if writer.available:
                        writer.pause_campaign(campaign_id,
                                              reason=f"ROAS below {ROAS_FLOOR}x for {days_below} days")
                        db.execute("""
                            UPDATE roas_alerts SET paused = 1, paused_at = ?
                            WHERE campaign_id = ?
                        """, (today, campaign_id))
                        alerts.append(f"AUTO-PAUSED: {campaign_id} (3-day avg ROAS: {avg_roas:.2f}x)")
                except Exception as e:
                    alerts.append(f"PAUSE FAILED for {campaign_id}: {e}")
            else:
                alerts.append(f"WARNING: {campaign_id} below {ROAS_FLOOR}x ROAS for {days_below} day(s)")

        elif avg_roas > 4.0 and cr["spend"] > 0:
            alerts.append(f"SCALE OPPORTUNITY: {campaign_id} at {avg_roas:.2f}x verified ROAS")

    db.commit()
    db.close()

    # 5. Format output
    lines = ["*Meta ROAS Verification — Daily Check*\n"]

    total_revenue = sum(cr["revenue"] for cr in campaign_results)
    total_spend = sum(cr["spend"] for cr in campaign_results)
    overall_roas = total_revenue / total_spend if total_spend > 0 else 0

    lines.append(f"Date: {today}")
    lines.append(f"Total Shopify-verified revenue (Meta): ${total_revenue:,.2f}")
    lines.append(f"Total Meta spend: ${total_spend:,.2f}")
    lines.append(f"Overall verified ROAS: {overall_roas:.2f}x\n")

    for cr in campaign_results:
        roas_str = f"{cr['roas']:.2f}x" if cr["spend"] > 0 else "N/A (no spend data)"
        lines.append(f"- {cr['campaign']}: ${cr['revenue']:,.2f} rev / ${cr['spend']:,.2f} spend = {roas_str} ({cr['orders']} orders)")

    if alerts:
        severity = "CRITICAL" if any("AUTO-PAUSED" in a for a in alerts) else "IMPORTANT"
        lines.append(f"\n*Alerts:*")
        for alert in alerts:
            lines.append(f"  - {alert}")
        return f"[PRIORITY: {severity}]\n" + "\n".join(lines)

    return "[PRIORITY: INFO]\n" + "\n".join(lines)


def get_weekly_roas_summary() -> str:
    """
    Get 7-day ROAS summary for Tony report and Monday briefings.
    """
    db = _get_db()
    week_ago = (date.today() - timedelta(days=7)).isoformat()

    rows = db.execute("""
        SELECT campaign_name,
               SUM(shopify_revenue) as total_revenue,
               SUM(meta_spend) as total_spend,
               SUM(orders_count) as total_orders,
               AVG(verified_roas) as avg_roas,
               COUNT(*) as days_tracked
        FROM roas_daily
        WHERE date >= ?
        GROUP BY campaign_name
        ORDER BY total_revenue DESC
    """, (week_ago,)).fetchall()

    if not rows:
        db.close()
        return "No ROAS data available for the past 7 days."

    lines = ["*Weekly Meta ROAS Summary (Shopify-Verified)*\n"]

    total_rev = 0
    total_spend = 0
    total_orders = 0

    for row in rows:
        rev = row["total_revenue"] or 0
        spend = row["total_spend"] or 0
        orders = row["total_orders"] or 0
        roas = rev / spend if spend > 0 else 0

        total_rev += rev
        total_spend += spend
        total_orders += orders

        lines.append(f"- {row['campaign_name']}")
        lines.append(f"  Revenue: ${rev:,.2f} | Spend: ${spend:,.2f} | ROAS: {roas:.2f}x | Orders: {orders}")

    overall_roas = total_rev / total_spend if total_spend > 0 else 0
    lines.append(f"\nTotal: ${total_rev:,.2f} revenue / ${total_spend:,.2f} spend = {overall_roas:.2f}x ROAS ({total_orders} orders)")

    # Recommendations
    lines.append("\n*Recommendations:*")
    for row in rows:
        rev = row["total_revenue"] or 0
        spend = row["total_spend"] or 0
        roas = rev / spend if spend > 0 else 0
        if roas > 3.0:
            lines.append(f"  - SCALE: {row['campaign_name']} ({roas:.1f}x)")
        elif roas >= 2.0:
            lines.append(f"  - HOLD: {row['campaign_name']} ({roas:.1f}x)")
        elif spend > 0:
            lines.append(f"  - REVIEW/KILL: {row['campaign_name']} ({roas:.1f}x)")

    db.close()
    return "\n".join(lines)


def run_monthly_ltv_analysis() -> str:
    """
    Monthly CPA:LTV cohort analysis. Runs on 1st of each month.
    Groups customers by acquisition channel + cohort month.
    """
    try:
        cdb = _get_customer_db()

        lines = ["*Monthly CPA:LTV Cohort Analysis*\n"]

        # Get cohort data grouped by channel
        rows = cdb.execute("""
            SELECT
                COALESCE(
                    (SELECT channel FROM orders WHERE shopify_customer_id = c.shopify_id
                     ORDER BY created_at ASC LIMIT 1),
                    'unknown'
                ) as acquisition_channel,
                SUBSTR(c.first_order_date, 1, 7) as cohort_month,
                COUNT(*) as customers,
                AVG(c.total_spent) as avg_ltv,
                AVG(c.total_orders) as avg_orders,
                SUM(CASE WHEN c.total_orders > 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as repeat_rate
            FROM customers c
            WHERE c.first_order_date IS NOT NULL
            GROUP BY acquisition_channel, cohort_month
            ORDER BY cohort_month DESC, customers DESC
            LIMIT 50
        """).fetchall()

        if not rows:
            cdb.close()
            return "No cohort data available yet."

        current_channel = None
        for row in rows:
            channel = row["acquisition_channel"]
            if channel != current_channel:
                current_channel = channel
                lines.append(f"\n*Channel: {channel}*")

            lines.append(
                f"  {row['cohort_month']}: {row['customers']} customers | "
                f"Avg LTV: ${row['avg_ltv']:,.2f} | "
                f"Avg orders: {row['avg_orders']:.1f} | "
                f"Repeat rate: {row['repeat_rate']:.1f}%"
            )

        # Overall summary
        overall = cdb.execute("""
            SELECT
                COUNT(*) as total_customers,
                AVG(total_spent) as overall_avg_ltv,
                AVG(total_orders) as overall_avg_orders,
                SUM(CASE WHEN total_orders > 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as overall_repeat
            FROM customers
            WHERE total_orders > 0
        """).fetchone()

        if overall:
            lines.append(f"\n*Overall:*")
            lines.append(f"  Total customers: {overall['total_customers']}")
            lines.append(f"  Average LTV: ${overall['overall_avg_ltv']:,.2f}")
            lines.append(f"  Average orders: {overall['overall_avg_orders']:.1f}")
            lines.append(f"  Repeat rate: {overall['overall_repeat']:.1f}%")

        cdb.close()

        # Save report
        report_dir = Path.home() / "dbh-aios" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"ltv-cohort-{date.today().strftime('%Y-%m')}.md"
        report_path.write_text("\n".join(lines), encoding='utf-8')

        lines.append(f"\nReport saved: {report_path}")
        return "\n".join(lines)

    except Exception as e:
        logger.error(f"LTV analysis failed: {e}")
        return f"LTV analysis failed: {e}"


def _parse_meta_spend(meta_raw: str) -> dict:
    """
    Parse Meta spend per campaign from data_fetcher output.
    Returns dict of {campaign_name: spend_amount}.
    """
    spend = {}
    if not meta_raw or "unavailable" in meta_raw.lower():
        return spend

    # Try to extract spend data from the formatted string
    # Format varies but typically includes campaign name and spend
    current_campaign = None
    for line in meta_raw.split("\n"):
        line = line.strip()
        if "Campaign:" in line or "campaign:" in line:
            current_campaign = line.split(":", 1)[1].strip()
        elif current_campaign and ("Spend:" in line or "spend:" in line or "Cost:" in line):
            try:
                amount_str = line.split(":", 1)[1].strip()
                amount_str = amount_str.replace("$", "").replace(",", "").strip()
                spend[current_campaign] = float(amount_str)
            except (ValueError, IndexError):
                pass

    return spend


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(run_nightly_roas_check())
