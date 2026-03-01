#!/usr/bin/env python3
"""
Order Intelligence Engine -- Per-order attribution, customer psychology,
cross-channel verification, and persistent learning.

Replaces Triple Whale by building attribution from raw Shopify data,
cross-referencing with Klaviyo sends and Meta Ads campaigns,
and maintaining a persistent customer intelligence database.

This is the core of the daily/weekly/monthly sales intelligence.
"""

import os
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "customer_intelligence.db"


def _shopify_headers():
    token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
    return {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}


def _shopify_url():
    return os.environ.get("SHOPIFY_STORE_URL", "")


# --- Customer Intelligence Database ---

def get_db() -> sqlite3.Connection:
    """Get or create the customer intelligence database."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
            shopify_id TEXT PRIMARY KEY,
            email TEXT,
            first_name TEXT,
            last_name TEXT,
            location TEXT,
            first_order_date TEXT,
            last_order_date TEXT,
            total_orders INTEGER DEFAULT 0,
            total_spent REAL DEFAULT 0,
            avg_order_value REAL DEFAULT 0,
            products_bought TEXT DEFAULT '[]',
            channels_used TEXT DEFAULT '[]',
            discount_codes_used TEXT DEFAULT '[]',
            segment TEXT DEFAULT 'unknown',
            notes TEXT DEFAULT '',
            updated_at TEXT
        );
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            shopify_customer_id TEXT,
            order_name TEXT,
            created_at TEXT,
            total_price REAL,
            products TEXT,
            channel TEXT,
            source TEXT,
            campaign TEXT,
            attribution_confidence TEXT,
            discount_code TEXT,
            discount_amount REAL DEFAULT 0,
            customer_type TEXT,
            location TEXT,
            klaviyo_email_match TEXT,
            meta_campaign_match TEXT,
            notes TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS insights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            period TEXT,
            insight_type TEXT,
            insight TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    return conn


def save_order_to_db(conn: sqlite3.Connection, order_data: dict):
    """Persist an order and update the customer record."""
    o = order_data
    # Upsert order
    conn.execute("""
        INSERT OR REPLACE INTO orders
        (order_id, shopify_customer_id, order_name, created_at, total_price,
         products, channel, source, campaign, attribution_confidence,
         discount_code, discount_amount, customer_type, location,
         klaviyo_email_match, meta_campaign_match)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        o.get("order_id"), o.get("customer_id"), o.get("name"), o.get("created"),
        o.get("total"), json.dumps(o.get("products", [])),
        o.get("channel"), o.get("source"), o.get("campaign"),
        o.get("confidence"), o.get("discount_code", ""),
        o.get("discount", 0), o.get("customer_type"), o.get("location"),
        o.get("klaviyo_match", ""), o.get("meta_match", "")
    ))

    # Upsert customer
    cust = o.get("customer_raw", {})
    customer_id = o.get("customer_id", "")
    if customer_id:
        existing = conn.execute(
            "SELECT products_bought, channels_used, discount_codes_used FROM customers WHERE shopify_id = ?",
            (customer_id,)
        ).fetchone()

        if existing:
            prev_products = json.loads(existing[0] or "[]")
            prev_channels = json.loads(existing[1] or "[]")
            prev_discounts = json.loads(existing[2] or "[]")
        else:
            prev_products = []
            prev_channels = []
            prev_discounts = []

        # Append new data
        for p in o.get("products", []):
            if p not in prev_products:
                prev_products.append(p)
        if o.get("channel") and o["channel"] not in prev_channels:
            prev_channels.append(o["channel"])
        dc = o.get("discount_code", "")
        if dc and dc not in prev_discounts:
            prev_discounts.append(dc)

        conn.execute("""
            INSERT OR REPLACE INTO customers
            (shopify_id, email, first_name, last_name, location,
             first_order_date, last_order_date, total_orders, total_spent,
             avg_order_value, products_bought, channels_used, discount_codes_used,
             segment, updated_at)
            VALUES (?, ?, ?, ?, ?,
                    COALESCE((SELECT first_order_date FROM customers WHERE shopify_id = ?), ?),
                    ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            customer_id,
            cust.get("email", ""),
            cust.get("first_name", ""),
            cust.get("last_name", ""),
            o.get("location", ""),
            customer_id, o.get("created", ""),
            o.get("created", ""),
            cust.get("orders_count", 1),
            float(cust.get("total_spent", 0) or 0),
            float(cust.get("total_spent", 0) or 0) / max(cust.get("orders_count", 1), 1),
            json.dumps(prev_products),
            json.dumps(prev_channels),
            json.dumps(prev_discounts),
            o.get("customer_type", "unknown"),
            datetime.utcnow().isoformat()
        ))

    conn.commit()


# --- Klaviyo Cross-Reference ---

def get_recent_klaviyo_sends(hours: int = 48) -> list:
    """
    Fetch recent Klaviyo campaign sends to cross-reference with orders.
    Returns list of {campaign_name, send_time, subject, status}.
    """
    api_key = os.environ.get("KLAVIYO_API_KEY")
    if not api_key:
        return []

    import requests
    headers = {
        "Authorization": f"Klaviyo-API-Key {api_key}",
        "Accept": "application/json",
        "revision": "2025-07-15"
    }

    try:
        resp = requests.get(
            "https://a.klaviyo.com/api/campaigns",
            headers=headers,
            params={"filter": "equals(messages.channel,'email')", "sort": "-send_time"},
            timeout=15
        )
        campaigns = resp.json().get("data", [])[:10]

        recent = []
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        for c in campaigns:
            attrs = c.get("attributes", {})
            send_time = attrs.get("send_time", "")
            if send_time:
                try:
                    sent = datetime.fromisoformat(send_time.replace("Z", "+00:00"))
                    if sent.replace(tzinfo=None) > cutoff:
                        recent.append({
                            "name": attrs.get("name", ""),
                            "send_time": send_time,
                            "status": attrs.get("status", ""),
                            "subject": attrs.get("subject", ""),
                        })
                except Exception:
                    pass
        return recent
    except Exception as e:
        logger.warning(f"Klaviyo cross-ref failed: {e}")
        return []


def get_active_meta_campaigns() -> list:
    """
    Fetch currently active Meta Ads campaigns for cross-referencing.
    """
    access_token = os.environ.get("META_ACCESS_TOKEN")
    ad_account_id = os.environ.get("META_AD_ACCOUNT_ID")
    if not access_token or not ad_account_id:
        return []

    import requests

    try:
        since = (datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%d")
        until = datetime.utcnow().strftime("%Y-%m-%d")
        url = f"https://graph.facebook.com/v21.0/act_{ad_account_id}/insights"
        resp = requests.get(url, params={
            "access_token": access_token,
            "time_range": json.dumps({"since": since, "until": until}),
            "fields": "campaign_name,spend,impressions,actions",
            "level": "campaign",
            "limit": 10
        }, timeout=15)
        return resp.json().get("data", [])
    except Exception as e:
        logger.warning(f"Meta cross-ref failed: {e}")
        return []


# --- Attribution Logic ---

def classify_order_source(order: dict) -> dict:
    """
    Determine the attribution source for a single order.
    Cross-references referring_site, landing_site UTMs, source_name,
    and discount codes to build a full attribution picture.
    """
    ref = (order.get("referring_site") or "").lower()
    landing = (order.get("landing_site") or "")
    source_name = (order.get("source_name") or "").lower()
    discount_codes = [d.get("code", "").lower() for d in order.get("discount_codes", [])]

    # Parse UTM params from landing URL
    utms = {}
    if landing:
        try:
            parsed = urlparse(landing)
            params = parse_qs(parsed.query)
            utms = {
                "source": params.get("utm_source", [""])[0],
                "medium": params.get("utm_medium", [""])[0],
                "campaign": params.get("utm_campaign", [""])[0],
                "content": params.get("utm_content", [""])[0],
            }
        except Exception:
            pass

    utm_source = utms.get("source", "").lower()
    utm_medium = utms.get("medium", "").lower()
    utm_campaign = utms.get("campaign", "")

    # 1. Email / Klaviyo
    if (utm_source in ("klaviyo", "email") or utm_medium == "email" or
        "klaviyo" in ref or "email" in ref):
        return {
            "channel": "Email", "source": "Klaviyo",
            "campaign": utm_campaign or "Unknown campaign",
            "confidence": "high",
            "evidence": f"UTM source={utm_source}, ref={ref[:50]}"
        }

    # 2. Meta Ads
    if (utm_source in ("facebook", "fb", "instagram", "ig", "meta") or
        "facebook" in ref or "fb.com" in ref or "instagram" in ref or
        "fbclid" in landing.lower()):
        return {
            "channel": "Meta Ads",
            "source": "Facebook" if "facebook" in ref or "fb" in utm_source else "Instagram",
            "campaign": utm_campaign or "Unknown campaign",
            "confidence": "high",
            "evidence": f"UTM source={utm_source}, ref={ref[:50]}"
        }

    # 3. Google
    if utm_source == "google" or "google" in ref:
        if utm_medium in ("cpc", "ppc", "paid") or "gclid" in landing.lower():
            return {
                "channel": "Google Ads", "source": "Google CPC",
                "campaign": utm_campaign or "Auto-detected",
                "confidence": "high",
                "evidence": f"UTM medium={utm_medium}"
            }
        return {
            "channel": "Google Organic", "source": "Google Search",
            "campaign": "", "confidence": "medium",
            "evidence": "Google referrer, no paid signals"
        }

    # 4. Other referral
    if ref and ref not in ("", "none"):
        return {
            "channel": "Referral", "source": ref[:60],
            "campaign": "", "confidence": "medium",
            "evidence": f"Referring site: {ref[:60]}"
        }

    # 5. Discount code hint
    if discount_codes:
        code = discount_codes[0]
        for kw, ch in [("email", "Email"), ("klaviyo", "Email"), ("newsletter", "Email"),
                       ("fb", "Meta Ads"), ("meta", "Meta Ads"), ("ig", "Meta Ads")]:
            if kw in code:
                return {
                    "channel": ch, "source": f"{ch} (via discount code)",
                    "campaign": code, "confidence": "medium",
                    "evidence": f"Discount code: {code}"
                }
        return {
            "channel": "Promo", "source": f"Discount code: {code}",
            "campaign": code, "confidence": "low",
            "evidence": "Discount code used but channel unclear"
        }

    # 6. Direct / Unknown
    return {
        "channel": "Direct", "source": "Direct / Typed URL / Bookmark",
        "campaign": "", "confidence": "low",
        "evidence": "No referrer, no UTMs, no discount code"
    }


def build_customer_profile(order: dict, db_conn: sqlite3.Connection = None) -> dict:
    """
    Build rich customer profile including history from the database,
    product psychology, and next-best-action recommendation data.
    """
    customer = order.get("customer") or {}
    customer_id = str(customer.get("id", ""))

    orders_count = customer.get("orders_count", 1)
    total_spent = float(customer.get("total_spent", "0") or "0")
    first_name = customer.get("first_name", "")
    last_name = customer.get("last_name", "")
    email = customer.get("email", "")
    created_at = customer.get("created_at", "")

    # Customer tenure
    tenure_days = 0
    if created_at:
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            tenure_days = (datetime.now(created.tzinfo) - created).days
        except Exception:
            pass

    # Customer segment
    if orders_count <= 1:
        segment = "New"
    elif orders_count <= 3:
        segment = "Returning"
    elif orders_count <= 10:
        segment = "Loyal"
    else:
        segment = "VIP"

    # Location
    billing = order.get("billing_address") or {}
    city = billing.get("city", "")
    province = billing.get("province", "")
    country = billing.get("country", "")
    location = ", ".join(filter(None, [city, province, country]))

    # Current order products with details
    products = []
    product_categories = set()
    for item in order.get("line_items", []):
        title = item.get("title", "Unknown")
        qty = item.get("quantity", 1)
        price = float(item.get("price", 0))
        products.append({"title": title, "quantity": qty, "price": price})
        # Infer category from product name
        title_lower = title.lower()
        for cat_keyword, cat_name in [
            ("joint", "Joint Health"), ("omega", "Heart/Brain Health"),
            ("collagen", "Anti-Aging/Beauty"), ("anti-aging", "Anti-Aging/Beauty"),
            ("immune", "Immune Support"), ("probiotic", "Gut Health"),
            ("sleep", "Sleep/Relaxation"), ("magnesium", "Sleep/Relaxation"),
            ("energy", "Energy/Vitality"), ("vitamin", "General Wellness"),
            ("calcium", "Bone Health"), ("eye", "Eye Health"),
            ("liver", "Detox/Liver"), ("green lipped", "Joint Health"),
            ("deer velvet", "Joint Health"), ("manuka", "Immune Support"),
        ]:
            if cat_keyword in title_lower:
                product_categories.add(cat_name)
                break

    # Pull historical data from DB if available
    purchase_history = []
    all_channels = []
    all_products_bought = []
    if db_conn and customer_id:
        try:
            row = db_conn.execute(
                "SELECT products_bought, channels_used, discount_codes_used FROM customers WHERE shopify_id = ?",
                (customer_id,)
            ).fetchone()
            if row:
                all_products_bought = json.loads(row[0] or "[]")
                all_channels = json.loads(row[1] or "[]")

            history = db_conn.execute(
                "SELECT order_name, created_at, total_price, products, channel FROM orders WHERE shopify_customer_id = ? ORDER BY created_at DESC LIMIT 5",
                (customer_id,)
            ).fetchall()
            for h in history:
                purchase_history.append({
                    "order": h[0], "date": h[1][:10] if h[1] else "",
                    "total": h[2], "products": json.loads(h[3] or "[]"),
                    "channel": h[4]
                })
        except Exception:
            pass

    # Build psychology profile data points
    profile = {
        "customer_id": customer_id,
        "segment": segment,
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "orders_count": orders_count,
        "ltv": total_spent,
        "aov": total_spent / max(orders_count, 1),
        "tenure_days": tenure_days,
        "location": location,
        "products_this_order": products,
        "product_categories": list(product_categories),
        "purchase_history": purchase_history,
        "all_products_ever": all_products_bought,
        "channels_used": all_channels,
        "tags": (order.get("tags") or "").split(", ") if order.get("tags") else [],
        "note": order.get("note", ""),
        "accepts_marketing": customer.get("accepts_marketing", False),
    }

    return profile


# --- Main Intelligence Fetch ---

def fetch_order_intelligence(days: int = 1) -> str:
    """
    Fetch per-order attribution, customer intelligence, and cross-channel verification.
    Persists to database for cumulative learning.
    """
    store_url = _shopify_url()
    token = os.environ.get("SHOPIFY_ACCESS_TOKEN")

    if not store_url or not token:
        return "[Order intelligence unavailable -- set SHOPIFY_STORE_URL and SHOPIFY_ACCESS_TOKEN]"

    import requests

    headers = _shopify_headers()
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")

    try:
        # Fetch orders with full details
        orders_url = f"https://{store_url}/admin/api/2025-01/orders.json"
        resp = requests.get(orders_url, headers=headers, params={
            "created_at_min": since,
            "status": "any",
            "limit": 250,
        }, timeout=15)
        orders = resp.json().get("orders", [])

        if not orders:
            return f"ORDER INTELLIGENCE -- No orders in last {days} day(s)"

        # Cross-reference data
        klaviyo_sends = get_recent_klaviyo_sends(hours=max(days * 24 + 24, 48))
        meta_campaigns = get_active_meta_campaigns()

        # Open customer intelligence DB
        try:
            db = get_db()
        except Exception:
            db = None

        total_revenue = sum(float(o.get("total_price", 0)) for o in orders)

        # --- Per-order analysis ---
        order_analyses = []
        channel_totals = {}
        new_customers = 0
        returning_customers = 0
        category_totals = {}

        for order in orders:
            attribution = classify_order_source(order)
            customer = build_customer_profile(order, db)
            order_total = float(order.get("total_price", 0))
            discount = float(order.get("total_discounts", 0))

            # Cross-reference with Klaviyo
            klaviyo_match = ""
            if attribution["channel"] == "Email" and klaviyo_sends:
                for ks in klaviyo_sends:
                    if ks["name"] and attribution.get("campaign", "").lower() in ks["name"].lower():
                        klaviyo_match = f"Verified: '{ks['name']}' sent {ks['send_time'][:10]}"
                        break
                if not klaviyo_match and klaviyo_sends:
                    klaviyo_match = f"Likely from recent send: '{klaviyo_sends[0]['name']}'"
            elif attribution["channel"] == "Direct" and klaviyo_sends:
                # Check if email was sent recently -- might be untracked email click
                klaviyo_match = f"Note: email '{klaviyo_sends[0]['name']}' was sent recently -- possible untracked email influence"

            # Cross-reference with Meta
            meta_match = ""
            if attribution["channel"] == "Meta Ads" and meta_campaigns:
                for mc in meta_campaigns:
                    if mc.get("campaign_name", "").lower() in attribution.get("campaign", "").lower():
                        spend = float(mc.get("spend", 0))
                        meta_match = f"Verified: '{mc['campaign_name']}' (${spend:.2f} spend)"
                        break
            elif attribution["channel"] == "Direct" and meta_campaigns:
                active = [mc.get("campaign_name", "") for mc in meta_campaigns[:3]]
                if active:
                    meta_match = f"Note: Meta campaigns running ({', '.join(active)}) -- possible untracked ad influence"

            # Track channel totals
            ch = attribution["channel"]
            if ch not in channel_totals:
                channel_totals[ch] = {"revenue": 0, "orders": 0}
            channel_totals[ch]["revenue"] += order_total
            channel_totals[ch]["orders"] += 1

            # Track categories
            for cat in customer.get("product_categories", []):
                if cat not in category_totals:
                    category_totals[cat] = {"revenue": 0, "orders": 0}
                category_totals[cat]["revenue"] += order_total
                category_totals[cat]["orders"] += 1

            if customer["segment"] == "New":
                new_customers += 1
            else:
                returning_customers += 1

            created = order.get("created_at", "")[:16].replace("T", " ")
            products_list = [p["title"] for p in customer["products_this_order"]]

            analysis = {
                "order_id": str(order.get("id", "")),
                "customer_id": customer["customer_id"],
                "name": order.get("name", "?"),
                "created": created,
                "total": order_total,
                "discount": discount,
                "discount_code": order.get("discount_codes", [{}])[0].get("code", "") if order.get("discount_codes") else "",
                "products": products_list,
                "attribution": attribution,
                "customer": customer,
                "customer_type": customer["segment"],
                "channel": attribution["channel"],
                "source": attribution["source"],
                "campaign": attribution.get("campaign", ""),
                "confidence": attribution["confidence"],
                "location": customer["location"],
                "klaviyo_match": klaviyo_match,
                "meta_match": meta_match,
                "customer_raw": order.get("customer", {}),
            }
            order_analyses.append(analysis)

            # Persist to DB
            if db:
                try:
                    save_order_to_db(db, analysis)
                except Exception as e:
                    logger.warning(f"DB save failed for order {analysis['name']}: {e}")

        # --- Format output ---
        lines = [
            f"ORDER INTELLIGENCE -- Last {days} day(s)",
            f"  Total: {len(orders)} orders, ${total_revenue:,.2f} revenue",
            f"  Customers: {new_customers} new, {returning_customers} returning "
            f"({returning_customers / len(orders) * 100:.0f}% repeat rate)" if orders else "",
            "",
        ]

        # Channel attribution summary
        lines.append("  CHANNEL ATTRIBUTION:")
        for ch, data in sorted(channel_totals.items(), key=lambda x: x[1]["revenue"], reverse=True):
            pct = (data["revenue"] / total_revenue * 100) if total_revenue > 0 else 0
            aov = data["revenue"] / data["orders"] if data["orders"] > 0 else 0
            lines.append(f"    {ch}: ${data['revenue']:,.2f} ({pct:.0f}%) | {data['orders']} orders | AOV ${aov:.2f}")

        # Category breakdown
        if category_totals:
            lines.append("")
            lines.append("  HEALTH CATEGORY BREAKDOWN:")
            for cat, data in sorted(category_totals.items(), key=lambda x: x[1]["revenue"], reverse=True):
                lines.append(f"    {cat}: ${data['revenue']:,.2f} from {data['orders']} orders")

        # Klaviyo cross-reference summary
        if klaviyo_sends:
            lines.append("")
            lines.append("  KLAVIYO SENDS (last 48hrs):")
            for ks in klaviyo_sends[:3]:
                lines.append(f"    '{ks['name']}' -- sent {ks['send_time'][:10]} ({ks['status']})")

        # Meta campaigns active
        if meta_campaigns:
            lines.append("")
            lines.append("  META CAMPAIGNS (active):")
            for mc in meta_campaigns[:5]:
                spend = float(mc.get("spend", 0))
                lines.append(f"    '{mc.get('campaign_name', '?')}' -- ${spend:.2f} spend")

        # Per-order breakdown with rich customer data
        lines.append("")
        lines.append("  === PER-ORDER CUSTOMER INTELLIGENCE ===")
        lines.append("  (Analyse each customer: why they bought, what to do next, psychology)")
        lines.append("")

        for oa in order_analyses:
            cust = oa["customer"]
            products_str = " + ".join(oa["products"][:3])
            if len(oa["products"]) > 3:
                products_str += f" +{len(oa['products']) - 3} more"

            lines.append(f"  --- {oa['name']} | ${oa['total']:,.2f} | {oa['created']} ---")
            lines.append(f"    Products: {products_str}")
            lines.append(f"    Categories: {', '.join(cust['product_categories']) or 'Uncategorised'}")
            lines.append(f"    Source: {oa['channel']} -- {oa['source']}")
            if oa["campaign"]:
                lines.append(f"    Campaign: {oa['campaign']}")
            if oa["klaviyo_match"]:
                lines.append(f"    Klaviyo: {oa['klaviyo_match']}")
            if oa["meta_match"]:
                lines.append(f"    Meta: {oa['meta_match']}")
            lines.append(f"    Attribution confidence: {oa['confidence']}")
            lines.append(f"    Customer: {cust['segment']} | {cust['orders_count']} orders | LTV: ${cust['ltv']:,.2f} | AOV: ${cust['aov']:,.2f}")
            lines.append(f"    Tenure: {cust['tenure_days']} days | Location: {cust['location'] or 'Unknown'}")
            if cust.get("purchase_history"):
                lines.append(f"    Previous orders: {len(cust['purchase_history'])}")
                for ph in cust["purchase_history"][:2]:
                    lines.append(f"      [{ph['date']}] ${ph['total']:.2f} via {ph['channel']} -- {', '.join(ph['products'][:2])}")
            if cust.get("all_products_ever"):
                lines.append(f"    Lifetime products: {', '.join(cust['all_products_ever'][:5])}")
            if oa["discount"] > 0:
                lines.append(f"    Discount: ${oa['discount']:,.2f} (code: {oa.get('discount_code', 'none')})")
            lines.append(f"    Accepts marketing: {'Yes' if cust.get('accepts_marketing') else 'No'}")
            lines.append("")

        # Pattern detection
        lines.append("  === PATTERNS & INSIGHTS ===")

        # New vs returning AOV
        new_rev = sum(oa["total"] for oa in order_analyses if oa["customer"]["segment"] == "New")
        ret_rev = sum(oa["total"] for oa in order_analyses if oa["customer"]["segment"] != "New")
        if new_customers > 0:
            lines.append(f"    New customer AOV: ${new_rev / new_customers:,.2f}")
        if returning_customers > 0:
            lines.append(f"    Returning customer AOV: ${ret_rev / returning_customers:,.2f}")

        # Top product
        product_counts = {}
        for oa in order_analyses:
            for p in oa["products"]:
                product_counts[p] = product_counts.get(p, 0) + 1
        if product_counts:
            top = max(product_counts.items(), key=lambda x: x[1])
            lines.append(f"    Top product: {top[0]} ({top[1]} units)")

        # VIP / high-LTV customers
        vips = [oa for oa in order_analyses if oa["customer"]["ltv"] > 200]
        if vips:
            lines.append(f"    High-LTV customers ({len(vips)}): " +
                         ", ".join(f"{v['customer']['first_name'] or v['name']} (${v['customer']['ltv']:,.0f})" for v in vips[:5]))

        # Low-confidence attributions
        low_conf = [oa for oa in order_analyses if oa["confidence"] == "low"]
        if low_conf:
            lines.append(f"    Unattributed orders: {len(low_conf)}/{len(orders)} -- add post-purchase survey to close this gap")

        # DB stats
        if db:
            try:
                total_customers = db.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
                total_orders_db = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
                lines.append(f"    Intelligence DB: {total_customers} customers, {total_orders_db} orders tracked")
                db.close()
            except Exception:
                pass

        # Instructions for Claude
        lines.append("")
        lines.append("  === ANALYSIS INSTRUCTIONS ===")
        lines.append("  For EACH customer above, provide:")
        lines.append("  1. PSYCHOLOGY: Why did they likely buy? What pain point or motivation?")
        lines.append("     Consider: product category, new vs returning, location, discount usage")
        lines.append("  2. JOURNEY STAGE: Where are they in their health journey?")
        lines.append("     New = exploring solutions. Returning = found something that works. VIP = committed.")
        lines.append("  3. NEXT ACTION: What should we do for this specific customer next?")
        lines.append("     Consider: cross-sell (what other products complement?), loyalty program,")
        lines.append("     personalised follow-up, review request, referral ask (for VIPs)")
        lines.append("  4. LOYALTY PROGRAM: How could Judge.me points enhance their experience?")
        lines.append("     Gamify their health journey -- points for reviews, referrals, repeat purchases.")
        lines.append("  5. CROSS-CHANNEL INSIGHT: What does their attribution tell us about")
        lines.append("     how to reach MORE people like them?")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Order intelligence error: {e}")
        return f"[Order intelligence error: {str(e)}]"


# --- Reporting ---

def get_customer_db_summary() -> str:
    """Get cumulative customer intelligence summary from the database."""
    try:
        db = get_db()
        total_customers = db.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        total_orders = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]

        if total_customers == 0:
            db.close()
            return "Customer Intelligence DB: Empty (will populate with next order fetch)"

        # Segment breakdown
        segments = db.execute(
            "SELECT segment, COUNT(*), SUM(total_spent), AVG(avg_order_value) FROM customers GROUP BY segment"
        ).fetchall()

        # Top channels
        channels = db.execute(
            "SELECT channel, COUNT(*), SUM(total_price) FROM orders GROUP BY channel ORDER BY SUM(total_price) DESC"
        ).fetchall()

        # Top products
        lines = [
            f"CUSTOMER INTELLIGENCE DATABASE",
            f"  Total customers tracked: {total_customers}",
            f"  Total orders tracked: {total_orders}",
            "",
            "  SEGMENTS:",
        ]
        for seg, count, spent, aov in segments:
            lines.append(f"    {seg}: {count} customers, ${spent or 0:,.2f} total, ${aov or 0:.2f} AOV")

        lines.append("")
        lines.append("  CHANNELS (all-time):")
        for ch, count, rev in channels:
            lines.append(f"    {ch}: {count} orders, ${rev or 0:,.2f} revenue")

        db.close()
        return "\n".join(lines)
    except Exception as e:
        return f"[Customer DB error: {e}]"


# --- CLI ---

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1 and sys.argv[1] == "db":
        print(get_customer_db_summary())
    else:
        days = int(sys.argv[1]) if len(sys.argv) > 1 else 1
        print(fetch_order_intelligence(days))
