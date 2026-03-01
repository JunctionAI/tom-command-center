#!/usr/bin/env python3
"""
Order Intelligence Engine -- Per-order attribution + customer analysis.
Replaces Triple Whale by pulling raw data from Shopify, cross-referencing
with Klaviyo and Meta Ads, and building per-order attribution.

This is the core of the morning briefing's sales intelligence.
"""

import os
import json
import logging
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger(__name__)


def _shopify_headers():
    token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
    return {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}


def _shopify_url():
    return os.environ.get("SHOPIFY_STORE_URL", "")


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

    # --- Attribution hierarchy ---
    # Most specific signals first

    # 1. Email / Klaviyo
    if (utm_source in ("klaviyo", "email") or
        utm_medium == "email" or
        "klaviyo" in ref or
        "email" in ref):
        return {
            "channel": "Email",
            "source": "Klaviyo",
            "campaign": utm_campaign or "Unknown campaign",
            "confidence": "high",
            "evidence": f"UTM source={utm_source}, ref={ref[:50]}"
        }

    # 2. Meta Ads (Facebook / Instagram)
    if (utm_source in ("facebook", "fb", "instagram", "ig", "meta") or
        "facebook" in ref or "fb.com" in ref or
        "instagram" in ref or "l.instagram" in ref or
        "fbclid" in landing.lower()):
        campaign_name = utm_campaign or "Unknown campaign"
        return {
            "channel": "Meta Ads",
            "source": "Facebook" if "facebook" in ref or "fb" in utm_source else "Instagram",
            "campaign": campaign_name,
            "confidence": "high",
            "evidence": f"UTM source={utm_source}, ref={ref[:50]}"
        }

    # 3. Google (Ads or Organic)
    if (utm_source == "google" or "google" in ref):
        if utm_medium in ("cpc", "ppc", "paid"):
            return {
                "channel": "Google Ads",
                "source": "Google CPC",
                "campaign": utm_campaign or "Unknown",
                "confidence": "high",
                "evidence": f"UTM medium={utm_medium}"
            }
        elif "gclid" in landing.lower():
            return {
                "channel": "Google Ads",
                "source": "Google CPC (gclid)",
                "campaign": utm_campaign or "Auto-detected via gclid",
                "confidence": "high",
                "evidence": "gclid present in landing URL"
            }
        else:
            return {
                "channel": "Google Organic",
                "source": "Google Search",
                "campaign": "",
                "confidence": "medium",
                "evidence": f"Google referrer, no paid signals"
            }

    # 4. Other referral
    if ref and ref not in ("", "none"):
        return {
            "channel": "Referral",
            "source": ref[:60],
            "campaign": "",
            "confidence": "medium",
            "evidence": f"Referring site: {ref[:60]}"
        }

    # 5. Discount code hint
    if discount_codes:
        # Discount codes often encode the channel
        code = discount_codes[0]
        for keyword in ["email", "klaviyo", "newsletter"]:
            if keyword in code:
                return {
                    "channel": "Email",
                    "source": "Klaviyo (via discount code)",
                    "campaign": code,
                    "confidence": "medium",
                    "evidence": f"Discount code: {code}"
                }
        for keyword in ["fb", "meta", "ig", "instagram", "facebook"]:
            if keyword in code:
                return {
                    "channel": "Meta Ads",
                    "source": "Meta (via discount code)",
                    "campaign": code,
                    "confidence": "medium",
                    "evidence": f"Discount code: {code}"
                }
        return {
            "channel": "Promo",
            "source": f"Discount code: {code}",
            "campaign": code,
            "confidence": "low",
            "evidence": f"Discount code used but channel unclear"
        }

    # 6. Direct / Unknown
    return {
        "channel": "Direct",
        "source": "Direct / Typed URL / Bookmark",
        "campaign": "",
        "confidence": "low",
        "evidence": "No referrer, no UTMs, no discount code"
    }


def analyse_customer(order: dict) -> dict:
    """
    Build customer profile from order data.
    """
    customer = order.get("customer") or {}

    orders_count = customer.get("orders_count", 1)
    total_spent = float(customer.get("total_spent", "0") or "0")
    first_name = customer.get("first_name", "")
    created_at = customer.get("created_at", "")

    # Customer tenure
    tenure_days = 0
    if created_at:
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            tenure_days = (datetime.now(created.tzinfo) - created).days
        except Exception:
            pass

    # Determine customer type
    if orders_count <= 1:
        customer_type = "New"
    elif orders_count <= 3:
        customer_type = "Returning"
    elif orders_count <= 10:
        customer_type = "Loyal"
    else:
        customer_type = "VIP"

    # Location
    billing = order.get("billing_address") or {}
    city = billing.get("city", "")
    country = billing.get("country", "")
    location = f"{city}, {country}" if city else country

    return {
        "type": customer_type,
        "orders_count": orders_count,
        "ltv": total_spent,
        "first_name": first_name,
        "tenure_days": tenure_days,
        "location": location,
    }


# --- Main Intelligence Fetch ---

def fetch_order_intelligence(days: int = 1) -> str:
    """
    Fetch per-order attribution and customer intelligence.
    This is the Triple Whale replacement -- built from raw Shopify data.
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
            "fields": "id,name,created_at,total_price,subtotal_price,total_discounts,"
                      "referring_site,landing_site,source_name,discount_codes,"
                      "line_items,customer,billing_address,financial_status,"
                      "browser_ip,client_details,tags,note"
        }, timeout=15)
        orders = resp.json().get("orders", [])

        if not orders:
            return f"ORDER INTELLIGENCE -- No orders in last {days} day(s)"

        total_revenue = sum(float(o.get("total_price", 0)) for o in orders)

        # --- Per-order analysis ---
        order_analyses = []
        channel_totals = {}
        new_customers = 0
        returning_customers = 0

        for order in orders:
            attribution = classify_order_source(order)
            customer = analyse_customer(order)
            products = [item.get("title", "?") for item in order.get("line_items", [])]
            order_total = float(order.get("total_price", 0))
            discount = float(order.get("total_discounts", 0))

            # Track channel totals
            ch = attribution["channel"]
            if ch not in channel_totals:
                channel_totals[ch] = {"revenue": 0, "orders": 0}
            channel_totals[ch]["revenue"] += order_total
            channel_totals[ch]["orders"] += 1

            # Track customer types
            if customer["type"] == "New":
                new_customers += 1
            else:
                returning_customers += 1

            # Build order summary
            created = order.get("created_at", "")[:16].replace("T", " ")
            order_analyses.append({
                "name": order.get("name", "?"),
                "created": created,
                "total": order_total,
                "discount": discount,
                "products": products,
                "attribution": attribution,
                "customer": customer,
            })

        # --- Format output ---
        lines = [
            f"ORDER INTELLIGENCE -- Last {days} day(s)",
            f"  Total: {len(orders)} orders, ${total_revenue:,.2f} revenue",
            f"  Customers: {new_customers} new, {returning_customers} returning "
            f"({returning_customers / len(orders) * 100:.0f}% repeat rate)" if orders else "",
            "",
            "  CHANNEL ATTRIBUTION:",
        ]

        for ch, data in sorted(channel_totals.items(), key=lambda x: x[1]["revenue"], reverse=True):
            pct = (data["revenue"] / total_revenue * 100) if total_revenue > 0 else 0
            lines.append(f"    {ch}: ${data['revenue']:,.2f} ({pct:.0f}%) from {data['orders']} orders")

        lines.append("")
        lines.append("  PER-ORDER BREAKDOWN:")

        for oa in order_analyses:
            attr = oa["attribution"]
            cust = oa["customer"]
            products_str = " + ".join(oa["products"][:3])
            if len(oa["products"]) > 3:
                products_str += f" +{len(oa['products']) - 3} more"

            lines.append(f"")
            lines.append(f"  {oa['name']} | ${oa['total']:,.2f} | {oa['created']}")
            lines.append(f"    Products: {products_str}")
            lines.append(f"    Source: {attr['channel']} -- {attr['source']}")
            if attr["campaign"]:
                lines.append(f"    Campaign: {attr['campaign']}")
            lines.append(f"    Attribution confidence: {attr['confidence']}")
            lines.append(f"    Customer: {cust['type']} "
                         f"({cust['orders_count']} orders, LTV: ${cust['ltv']:,.2f})")
            if cust["location"]:
                lines.append(f"    Location: {cust['location']}")
            if oa["discount"] > 0:
                lines.append(f"    Discount: ${oa['discount']:,.2f}")

        # --- Pattern detection ---
        lines.append("")
        lines.append("  PATTERNS:")

        # AOV by channel
        for ch, data in sorted(channel_totals.items(), key=lambda x: x[1]["revenue"], reverse=True):
            aov = data["revenue"] / data["orders"] if data["orders"] > 0 else 0
            lines.append(f"    {ch} AOV: ${aov:,.2f}")

        # Returning vs new AOV
        new_rev = sum(oa["total"] for oa in order_analyses if oa["customer"]["type"] == "New")
        ret_rev = sum(oa["total"] for oa in order_analyses if oa["customer"]["type"] != "New")
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
            lines.append(f"    High-LTV customers ({len(vips)}): "
                         + ", ".join(f"{v['customer']['first_name'] or v['name']} "
                                    f"(${v['customer']['ltv']:,.0f})"
                                    for v in vips[:5]))

        # Low-confidence attributions
        low_conf = [oa for oa in order_analyses if oa["attribution"]["confidence"] == "low"]
        if low_conf:
            lines.append(f"    Unattributed orders: {len(low_conf)}/{len(orders)} "
                         f"-- consider post-purchase survey")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Order intelligence error: {e}")
        return f"[Order intelligence error: {str(e)}]"


# --- CLI ---

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    days = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    print(fetch_order_intelligence(days))
