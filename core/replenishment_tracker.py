#!/usr/bin/env python3
"""
Replenishment Tracker -- Identifies customers due for reorder and triggers
Klaviyo replenishment reminder flows via custom events.

Runs daily as a scheduled task. Scans order history, calculates when
each customer's supply runs out, and fires 'replenishment_due' events
to Klaviyo for customers approaching reorder time.

Requires:
- SHOPIFY_STORE_URL + SHOPIFY_ACCESS_TOKEN (order history)
- KLAVIYO_API_KEY (event triggers)
- customer_intelligence.db (order history, built by order_intelligence.py)
"""

import os
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "customer_intelligence.db"

# --- Product Consumption Rates ---
# Maps product name keywords to supply duration and optimal reminder day.
# These are based on standard dosage recommendations per product.

PRODUCT_CONSUMPTION = {
    # DBH Products
    "green lipped mussel 18000": {"days_supply": 60, "reminder_day": 50, "category": "Joint Health"},
    "green lipped mussel 9000": {"days_supply": 30, "reminder_day": 25, "category": "Joint Health"},
    "green lipped mussel": {"days_supply": 30, "reminder_day": 25, "category": "Joint Health"},
    "deer velvet": {"days_supply": 30, "reminder_day": 25, "category": "Joint Health"},
    "omega 3": {"days_supply": 30, "reminder_day": 25, "category": "Heart/Brain Health"},
    "fish oil": {"days_supply": 30, "reminder_day": 25, "category": "Heart/Brain Health"},
    "vitamin d": {"days_supply": 60, "reminder_day": 50, "category": "General Wellness"},
    "collagen": {"days_supply": 30, "reminder_day": 25, "category": "Anti-Aging/Beauty"},
    "joint support": {"days_supply": 30, "reminder_day": 25, "category": "Joint Health"},
    "immune": {"days_supply": 30, "reminder_day": 25, "category": "Immune Support"},
    "probiotic": {"days_supply": 30, "reminder_day": 25, "category": "Gut Health"},
    "manuka": {"days_supply": 30, "reminder_day": 25, "category": "Immune Support"},
    "calcium": {"days_supply": 60, "reminder_day": 50, "category": "Bone Health"},
    "magnesium": {"days_supply": 30, "reminder_day": 25, "category": "Sleep/Relaxation"},
    "sleep": {"days_supply": 30, "reminder_day": 25, "category": "Sleep/Relaxation"},
    "eye": {"days_supply": 30, "reminder_day": 25, "category": "Eye Health"},
    "liver": {"days_supply": 30, "reminder_day": 25, "category": "Detox/Liver"},
    "anti-aging": {"days_supply": 30, "reminder_day": 25, "category": "Anti-Aging/Beauty"},
    "energy": {"days_supply": 30, "reminder_day": 25, "category": "Energy/Vitality"},
    # Pure Pets Products
    "pure pets": {"days_supply": 30, "reminder_day": 22, "category": "Pet Health"},
    "pet joint": {"days_supply": 30, "reminder_day": 22, "category": "Pet Health"},
    "pet senior": {"days_supply": 30, "reminder_day": 22, "category": "Pet Health"},
}

# Default for unrecognised products
DEFAULT_CONSUMPTION = {"days_supply": 30, "reminder_day": 25, "category": "General"}


def match_product_consumption(product_name: str) -> dict:
    """Match a product name to its consumption rate."""
    name_lower = product_name.lower()
    for keyword, data in PRODUCT_CONSUMPTION.items():
        if keyword in name_lower:
            return data
    return DEFAULT_CONSUMPTION


def get_replenishment_candidates(lookback_days: int = 60) -> list:
    """
    Find customers who are approaching reorder time based on their
    last purchase date and product consumption rates.

    Returns list of dicts with customer info and recommended action.
    """
    if not DB_PATH.exists():
        logger.warning("Customer intelligence DB not found. Run order intelligence first.")
        return []

    conn = sqlite3.connect(str(DB_PATH))

    try:
        # Get orders from the lookback period with customer details
        orders = conn.execute("""
            SELECT
                o.shopify_customer_id,
                o.created_at,
                o.products,
                o.total_price,
                c.email,
                c.first_name,
                c.last_name,
                c.total_orders,
                c.total_spent,
                c.segment
            FROM orders o
            JOIN customers c ON o.shopify_customer_id = c.shopify_id
            WHERE o.created_at >= ?
            AND c.email IS NOT NULL
            AND c.email != ''
            ORDER BY o.created_at DESC
        """, ((datetime.utcnow() - timedelta(days=lookback_days)).isoformat(),)).fetchall()

        if not orders:
            return []

        # Group by customer, find their most recent order per product
        customer_products = {}  # {email: [{product, order_date, days_since, consumption}]}

        for row in orders:
            customer_id, created_at, products_json, total, email, first_name, last_name, total_orders, total_spent, segment = row

            if not email:
                continue

            try:
                products = json.loads(products_json) if products_json else []
            except (json.JSONDecodeError, TypeError):
                products = [products_json] if products_json else []

            try:
                order_date = datetime.fromisoformat(created_at.replace("Z", "+00:00")).replace(tzinfo=None)
            except (ValueError, AttributeError):
                continue

            days_since = (datetime.utcnow() - order_date).days

            if email not in customer_products:
                customer_products[email] = {
                    "email": email,
                    "first_name": first_name or "",
                    "last_name": last_name or "",
                    "customer_id": customer_id,
                    "total_orders": total_orders or 1,
                    "total_spent": total_spent or 0,
                    "segment": segment or "unknown",
                    "products": [],
                }

            for product in products:
                product_name = product if isinstance(product, str) else str(product)
                consumption = match_product_consumption(product_name)

                # Only track if we haven't already seen this product for this customer
                # (we want the most recent order per product)
                existing = [p for p in customer_products[email]["products"] if p["product"] == product_name]
                if not existing:
                    customer_products[email]["products"].append({
                        "product": product_name,
                        "order_date": created_at[:10],
                        "days_since": days_since,
                        "days_supply": consumption["days_supply"],
                        "reminder_day": consumption["reminder_day"],
                        "category": consumption["category"],
                        "days_remaining": max(0, consumption["days_supply"] - days_since),
                        "status": _get_status(days_since, consumption),
                    })

        conn.close()

        # Filter to candidates who are in the reminder window
        candidates = []
        for email, data in customer_products.items():
            for product_info in data["products"]:
                if product_info["status"] in ("reminder", "urgent", "overdue"):
                    candidates.append({
                        **data,
                        "trigger_product": product_info["product"],
                        "trigger_status": product_info["status"],
                        "days_since_purchase": product_info["days_since"],
                        "days_supply": product_info["days_supply"],
                        "days_remaining": product_info["days_remaining"],
                        "category": product_info["category"],
                    })

        # Sort by urgency
        status_priority = {"overdue": 0, "urgent": 1, "reminder": 2}
        candidates.sort(key=lambda x: status_priority.get(x["trigger_status"], 3))

        return candidates

    except Exception as e:
        logger.error(f"Replenishment scan error: {e}")
        conn.close()
        return []


def _get_status(days_since: int, consumption: dict) -> str:
    """Determine replenishment status."""
    reminder_day = consumption["reminder_day"]
    supply_day = consumption["days_supply"]

    if days_since >= supply_day + 7:
        return "overdue"  # Well past supply end
    elif days_since >= supply_day:
        return "urgent"  # Supply should be out
    elif days_since >= reminder_day:
        return "reminder"  # In the reminder window
    else:
        return "active"  # Still has supply


def run_replenishment_scan() -> str:
    """
    Run the daily replenishment scan and trigger Klaviyo events
    for customers approaching reorder time.

    Returns a summary string for logging/Telegram.
    """
    candidates = get_replenishment_candidates()

    if not candidates:
        return "Replenishment scan: No candidates found (either no orders in DB or all customers still have supply)"

    # Check if Klaviyo is available
    try:
        from core.klaviyo_writer import KlaviyoWriter
        klaviyo = KlaviyoWriter()
        klaviyo_available = klaviyo.available
    except Exception:
        klaviyo_available = False

    triggered = 0
    skipped = 0
    errors = 0

    lines = [
        f"REPLENISHMENT SCAN -- {len(candidates)} customers approaching reorder",
        "",
    ]

    for candidate in candidates:
        email = candidate["email"]
        product = candidate["trigger_product"]
        status = candidate["trigger_status"]
        days = candidate["days_since_purchase"]
        supply = candidate["days_supply"]

        if klaviyo_available:
            try:
                klaviyo.trigger_replenishment_reminder(
                    email=email,
                    product_name=product,
                    days_since_purchase=days,
                    supply_days=supply,
                )
                triggered += 1
                lines.append(
                    f"  [{status.upper()}] {candidate['first_name']} {candidate['last_name'][:1]}. "
                    f"-- {product} (day {days}/{supply}) -- event fired"
                )
            except Exception as e:
                errors += 1
                logger.error(f"Failed to trigger replenishment for {email}: {e}")
                lines.append(f"  [ERROR] {email} -- {product}: {e}")
        else:
            skipped += 1
            lines.append(
                f"  [{status.upper()}] {candidate['first_name']} {candidate['last_name'][:1]}. "
                f"-- {product} (day {days}/{supply}) -- SKIPPED (no Klaviyo key)"
            )

    lines.append("")
    lines.append(f"Summary: {triggered} triggered, {skipped} skipped, {errors} errors")

    if not klaviyo_available:
        lines.append("NOTE: Set KLAVIYO_API_KEY to enable automatic triggers")
        lines.append("NOTE: Create Klaviyo flow triggered by 'replenishment_due' event")

    return "\n".join(lines)


def format_replenishment_brief() -> str:
    """
    Format a brief summary for agent injection (Meridian morning brief).
    Shows customers approaching reorder without triggering events.
    """
    candidates = get_replenishment_candidates()

    if not candidates:
        return ""

    lines = [
        f"REORDER CANDIDATES: {len(candidates)} customers approaching replenishment",
    ]

    # Group by status
    by_status = {}
    for c in candidates:
        status = c["trigger_status"]
        if status not in by_status:
            by_status[status] = []
        by_status[status].append(c)

    for status in ("overdue", "urgent", "reminder"):
        group = by_status.get(status, [])
        if group:
            lines.append(f"  {status.upper()} ({len(group)}):")
            for c in group[:5]:
                lines.append(
                    f"    {c['first_name']} {c.get('last_name', '')[:1]}. "
                    f"-- {c['trigger_product']} (day {c['days_since_purchase']}/{c['days_supply']}) "
                    f"[{c['segment']}, LTV ${c['total_spent']:,.0f}]"
                )
            if len(group) > 5:
                lines.append(f"    ... and {len(group) - 5} more")

    return "\n".join(lines)


# --- CLI ---

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1 and sys.argv[1] == "scan":
        print(run_replenishment_scan())
    elif len(sys.argv) > 1 and sys.argv[1] == "brief":
        print(format_replenishment_brief())
    else:
        candidates = get_replenishment_candidates()
        print(f"Found {len(candidates)} replenishment candidates")
        for c in candidates[:10]:
            print(f"  [{c['trigger_status']}] {c['email']} -- {c['trigger_product']} "
                  f"(day {c['days_since_purchase']}/{c['days_supply']})")
