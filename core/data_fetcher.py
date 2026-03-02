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

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

NZ_TZ = ZoneInfo("Pacific/Auckland")

logger = logging.getLogger(__name__)


def _nz_day_start(days_ago: int = 0) -> str:
    """Return ISO timestamp for midnight NZST, `days_ago` days back.
    Shopify API accepts ISO timestamps and interprets them correctly."""
    now_nz = datetime.now(NZ_TZ)
    day_start = now_nz.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days_ago)
    return day_start.isoformat()


# --- Shopify ---

def fetch_shopify_data(days: int = 1) -> str:
    """Fetch recent Shopify orders, revenue, and product performance."""
    store_url = os.environ.get("SHOPIFY_STORE_URL")  # e.g. "deepbluehealth.myshopify.com"
    token = os.environ.get("SHOPIFY_ACCESS_TOKEN")

    if not store_url or not token:
        return "[Shopify data unavailable -- set SHOPIFY_STORE_URL and SHOPIFY_ACCESS_TOKEN]"

    import requests

    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}
    since = _nz_day_start(days_ago=days - 1)  # days=1 means "today" = midnight NZST today

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
            f"SHOPIFY -- Last {days} day(s) (as of {datetime.now(NZ_TZ).strftime('%Y-%m-%d %H:%M NZST')})",
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
    """Fetch recent Klaviyo email campaign performance with metrics."""
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

        if resp.status_code != 200:
            error_detail = resp.text[:200]
            logger.error(f"Klaviyo campaigns API error {resp.status_code}: {error_detail}")
            return f"[Klaviyo API error {resp.status_code}: {error_detail}]"

        campaigns = resp.json().get("data", [])[:10]

        # Filter to campaigns sent within our date range
        cutoff = (datetime.now(NZ_TZ) - timedelta(days=days)).isoformat()
        recent = []
        for c in campaigns:
            attrs = c.get("attributes", {})
            send_time = attrs.get("send_time", "")
            status = attrs.get("status", "")
            # Include sent campaigns within the date range
            if status == "Sent" and send_time and send_time >= cutoff:
                recent.append(c)
            # Also include first few regardless for context
            elif len(recent) < 3:
                recent.append(c)

        lines = [
            f"KLAVIYO -- Last {days} day(s) (as of {datetime.now(NZ_TZ).strftime('%Y-%m-%d %H:%M NZST')})",
        ]

        if not recent:
            lines.append("  No recent campaigns found")
            return "\n".join(lines)

        for c in recent:
            attrs = c.get("attributes", {})
            name = attrs.get("name", "Unknown")
            status = attrs.get("status", "unknown")
            send_time = attrs.get("send_time", "")
            campaign_id = c.get("id", "")

            lines.append(f"  Campaign: {name}")
            lines.append(f"    Status: {status}")
            if send_time:
                lines.append(f"    Sent: {send_time[:16].replace('T', ' ')}")

            # Fetch campaign metrics via campaign values endpoint
            if campaign_id and status == "Sent":
                try:
                    # Use the query endpoint for campaign metrics
                    metrics_payload = {
                        "data": {
                            "type": "campaign-values-report",
                            "attributes": {
                                "statistics": [
                                    "opens", "unique_opens", "open_rate",
                                    "clicks", "unique_clicks", "click_rate",
                                    "revenue", "unsubscribes", "recipients"
                                ],
                                "timeframe": {"key": "last_30_days"},
                                "filter": f"equals(campaign_id,\"{campaign_id}\")"
                            }
                        }
                    }
                    metrics_resp = requests.post(
                        "https://a.klaviyo.com/api/campaign-values-reports/",
                        headers={**headers, "Content-Type": "application/json"},
                        json=metrics_payload,
                        timeout=15
                    )
                    if metrics_resp.status_code == 200:
                        metrics_data = metrics_resp.json()
                        results = metrics_data.get("data", {}).get("attributes", {}).get("results", [])
                        if results:
                            r = results[0]
                            stats = r.get("statistics", {})
                            recipients = stats.get("recipients", 0)
                            opens = stats.get("unique_opens", 0)
                            open_rate = stats.get("open_rate", 0)
                            clicks = stats.get("unique_clicks", 0)
                            click_rate = stats.get("click_rate", 0)
                            revenue = stats.get("revenue", 0)
                            unsubs = stats.get("unsubscribes", 0)

                            lines.append(f"    Recipients: {recipients:,}")
                            lines.append(f"    Opens: {opens:,} ({open_rate:.1%})")
                            lines.append(f"    Clicks: {clicks:,} ({click_rate:.1%})")
                            if revenue:
                                lines.append(f"    Revenue: ${revenue:,.2f}")
                            if unsubs:
                                lines.append(f"    Unsubscribes: {unsubs}")
                    else:
                        logger.debug(f"Klaviyo metrics {metrics_resp.status_code} for {campaign_id}")
                except Exception as me:
                    logger.debug(f"Klaviyo metrics fetch failed for {name}: {me}")

        # Flow summary
        lines.append("")
        lines.append("  Active Flows: see Klaviyo dashboard for flow-level revenue")

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

    # Meta Graph API interprets time_range dates as UTC.
    # To get a full NZ day, we convert NZ midnight to UTC dates.
    now_nz = datetime.now(NZ_TZ)
    nz_start = now_nz.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
    # NZ midnight in UTC is the previous day (NZDT = UTC+13)
    nz_start_utc = nz_start.astimezone(ZoneInfo("UTC"))
    nz_end_utc = now_nz.astimezone(ZoneInfo("UTC"))
    since = nz_start_utc.strftime("%Y-%m-%d")
    until = nz_end_utc.strftime("%Y-%m-%d")

    try:
        # Account-level insights
        url = f"https://graph.facebook.com/v21.0/act_{ad_account_id}/insights"
        resp = requests.get(url, params={
            "access_token": access_token,
            "time_range": json.dumps({"since": since, "until": until}),
            "fields": "spend,impressions,clicks,cpc,cpm,ctr,actions,action_values,cost_per_action_type,purchase_roas",
            "level": "account"
        }, timeout=15)

        if resp.status_code != 200:
            error_msg = resp.json().get("error", {}).get("message", resp.text[:200])
            logger.error(f"Meta Ads API error {resp.status_code}: {error_msg}")
            return f"[Meta Ads API error {resp.status_code}: {error_msg}]"

        data = resp.json().get("data", [])

        if not data:
            return f"META ADS -- No data for {since} to {until} (NZ day: {nz_start.strftime('%Y-%m-%d')})"

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
            "fields": "campaign_name,spend,impressions,clicks,actions,action_values",
            "level": "campaign",
            "limit": 10
        }, timeout=15)

        if camp_resp.status_code == 200:
            camp_data = camp_resp.json().get("data", [])
            if camp_data:
                lines.append("")
                lines.append("  By Campaign:")
                for c in camp_data:
                    name = c.get("campaign_name", "Unknown")
                    c_spend = float(c.get("spend", 0))
                    c_clicks = int(c.get("clicks", 0))
                    # Extract campaign purchases + revenue
                    c_purchases = 0
                    c_revenue = 0
                    for a in c.get("actions", []):
                        if a.get("action_type") == "purchase":
                            c_purchases = int(a.get("value", 0))
                    for a in c.get("action_values", []):
                        if a.get("action_type") == "purchase":
                            c_revenue = float(a.get("value", 0))
                    c_roas = c_revenue / c_spend if c_spend > 0 else 0
                    lines.append(f"    {name}: ${c_spend:,.2f} spend, {c_clicks} clicks, {c_purchases} purchases, ${c_revenue:,.2f} rev, {c_roas:.2f}x ROAS")

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
        f"=== LIVE PERFORMANCE DATA (fetched {datetime.now(NZ_TZ).strftime('%Y-%m-%d %H:%M NZST')}) ===",
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
