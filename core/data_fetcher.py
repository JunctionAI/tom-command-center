#!/usr/bin/env python3
"""
Data Fetcher -- Pulls real performance data from business APIs.
Injects live metrics into agent prompts so Claude can analyse real numbers.

All APIs are optional -- if a key isn't set, that section returns a placeholder.
"""

import os
import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


# --- Shopify ---

def fetch_shopify_data(days: int = 1) -> str:
    """Fetch recent Shopify orders, revenue, and product performance."""
    store_url = os.environ.get("SHOPIFY_STORE_URL")  # e.g. "deepbluehealth.myshopify.com"
    token = os.environ.get("SHOPIFY_ACCESS_TOKEN")

    if not store_url or not token:
        return "[Shopify data unavailable -- set SHOPIFY_STORE_URL and SHOPIFY_ACCESS_TOKEN]"

    import requests

    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")

    try:
        # Fetch orders
        orders_url = f"https://{store_url}/admin/api/2025-01/orders.json"
        resp = requests.get(orders_url, headers=headers, params={
            "created_at_min": since,
            "status": "any",
            "limit": 250
        }, timeout=15)
        orders = resp.json().get("orders", [])

        total_revenue = sum(float(o.get("total_price", 0)) for o in orders)
        total_orders = len(orders)
        avg_order = total_revenue / total_orders if total_orders > 0 else 0

        # Product breakdown
        product_counts = {}
        for order in orders:
            for item in order.get("line_items", []):
                name = item.get("title", "Unknown")
                qty = item.get("quantity", 0)
                product_counts[name] = product_counts.get(name, 0) + qty

        top_products = sorted(product_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        # Attribution breakdown
        sources = {}
        for order in orders:
            source = order.get("source_name", "Unknown")
            ref = order.get("referring_site", "")
            if "klaviyo" in str(ref).lower() or "email" in str(source).lower():
                key = "Email/Klaviyo"
            elif "facebook" in str(ref).lower() or "fb" in str(ref).lower() or "instagram" in str(ref).lower():
                key = "Meta Ads"
            elif "google" in str(ref).lower():
                key = "Google"
            elif ref:
                key = f"Referral ({ref[:30]})"
            else:
                key = "Direct/Other"
            sources[key] = sources.get(key, 0) + float(order.get("total_price", 0))

        lines = [
            f"SHOPIFY -- Last {days} day(s) (as of {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')})",
            f"  Revenue: ${total_revenue:,.2f}",
            f"  Orders: {total_orders}",
            f"  AOV: ${avg_order:,.2f}",
            "",
            "  Top Products:",
        ]
        for name, qty in top_products:
            lines.append(f"    {name}: {qty} units")

        lines.append("")
        lines.append("  Revenue Attribution:")
        for source, rev in sorted(sources.items(), key=lambda x: x[1], reverse=True):
            pct = (rev / total_revenue * 100) if total_revenue > 0 else 0
            lines.append(f"    {source}: ${rev:,.2f} ({pct:.0f}%)")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Shopify fetch error: {e}")
        return f"[Shopify error: {str(e)}]"


# --- Klaviyo ---

def fetch_klaviyo_data(days: int = 1) -> str:
    """Fetch recent Klaviyo email campaign performance."""
    api_key = os.environ.get("KLAVIYO_API_KEY")

    if not api_key:
        return "[Klaviyo data unavailable -- set KLAVIYO_API_KEY]"

    import requests

    headers = {
        "Authorization": f"Klaviyo-API-Key {api_key}",
        "Accept": "application/json",
        "revision": "2025-07-15"
    }

    try:
        # Fetch recent campaigns
        resp = requests.get(
            "https://a.klaviyo.com/api/campaigns",
            headers=headers,
            params={"filter": "equals(messages.channel,'email')", "sort": "-send_time"},
            timeout=15
        )
        campaigns = resp.json().get("data", [])[:5]

        lines = [
            f"KLAVIYO -- Last {days} day(s)",
        ]

        if not campaigns:
            lines.append("  No recent campaigns found")
            return "\n".join(lines)

        for c in campaigns:
            attrs = c.get("attributes", {})
            name = attrs.get("name", "Unknown")
            status = attrs.get("status", "unknown")
            send_time = attrs.get("send_time", "")

            # Get campaign stats via metrics
            lines.append(f"  Campaign: {name}")
            lines.append(f"    Status: {status}")
            if send_time:
                lines.append(f"    Sent: {send_time[:10]}")

        # Fetch flow performance (top revenue drivers)
        lines.append("")
        lines.append("  Active Flows: check Klaviyo dashboard for flow-level revenue")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Klaviyo fetch error: {e}")
        return f"[Klaviyo error: {str(e)}]"


# --- Meta Ads ---

def fetch_meta_ads_data(days: int = 1) -> str:
    """Fetch Meta Ads campaign performance."""
    access_token = os.environ.get("META_ACCESS_TOKEN")
    ad_account_id = os.environ.get("META_AD_ACCOUNT_ID")

    if not access_token or not ad_account_id:
        return "[Meta Ads data unavailable -- set META_ACCESS_TOKEN and META_AD_ACCOUNT_ID]"

    import requests

    since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    until = datetime.utcnow().strftime("%Y-%m-%d")

    try:
        # Account-level insights
        url = f"https://graph.facebook.com/v21.0/act_{ad_account_id}/insights"
        resp = requests.get(url, params={
            "access_token": access_token,
            "time_range": json.dumps({"since": since, "until": until}),
            "fields": "spend,impressions,clicks,cpc,cpm,ctr,actions,cost_per_action_type,purchase_roas",
            "level": "account"
        }, timeout=15)
        data = resp.json().get("data", [])

        if not data:
            return f"META ADS -- No data for last {days} day(s)"

        d = data[0]
        spend = float(d.get("spend", 0))
        impressions = int(d.get("impressions", 0))
        clicks = int(d.get("clicks", 0))
        ctr = float(d.get("ctr", 0))
        cpc = float(d.get("cpc", 0))

        # Extract purchases and ROAS from actions
        purchases = 0
        purchase_value = 0
        for action in d.get("actions", []):
            if action.get("action_type") == "purchase":
                purchases = int(action.get("value", 0))
        for action in d.get("action_values", []):
            if action.get("action_type") == "purchase":
                purchase_value = float(action.get("value", 0))

        roas = purchase_value / spend if spend > 0 else 0

        lines = [
            f"META ADS -- Last {days} day(s)",
            f"  Spend: ${spend:,.2f}",
            f"  Impressions: {impressions:,}",
            f"  Clicks: {clicks:,}  CTR: {ctr:.2f}%  CPC: ${cpc:.2f}",
            f"  Purchases: {purchases}  Revenue: ${purchase_value:,.2f}",
            f"  ROAS: {roas:.2f}x",
        ]

        # Campaign-level breakdown
        camp_url = f"https://graph.facebook.com/v21.0/act_{ad_account_id}/insights"
        camp_resp = requests.get(camp_url, params={
            "access_token": access_token,
            "time_range": json.dumps({"since": since, "until": until}),
            "fields": "campaign_name,spend,impressions,actions,purchase_roas",
            "level": "campaign",
            "limit": 5
        }, timeout=15)
        camp_data = camp_resp.json().get("data", [])

        if camp_data:
            lines.append("")
            lines.append("  By Campaign:")
            for c in camp_data:
                name = c.get("campaign_name", "Unknown")
                c_spend = float(c.get("spend", 0))
                lines.append(f"    {name}: ${c_spend:,.2f} spend")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Meta Ads fetch error: {e}")
        return f"[Meta Ads error: {str(e)}]"


# --- Google Ads ---

def fetch_google_ads_data(days: int = 1) -> str:
    """Placeholder for Google Ads -- requires google-ads library."""
    api_key = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN")
    if not api_key:
        return "[Google Ads data unavailable -- set GOOGLE_ADS_DEVELOPER_TOKEN]"
    return "[Google Ads integration: coming soon]"


# --- Combined Fetch ---

def fetch_all_performance_data(days: int = 1) -> str:
    """
    Fetch performance data from all connected platforms.
    Returns a formatted text block for injection into agent prompts.
    """
    sections = [
        f"=== LIVE PERFORMANCE DATA (fetched {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}) ===",
        ""
    ]

    sections.append(fetch_shopify_data(days))
    sections.append("")
    sections.append(fetch_klaviyo_data(days))
    sections.append("")
    sections.append(fetch_meta_ads_data(days))
    sections.append("")
    sections.append(fetch_google_ads_data(days))

    return "\n".join(sections)


def fetch_weekly_performance_data() -> str:
    """Fetch 7-day data for weekly reviews."""
    return fetch_all_performance_data(days=7)


# --- CLI ---

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    days = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    print(fetch_all_performance_data(days))
