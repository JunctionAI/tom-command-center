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
        # Fetch recent campaigns (sort by -scheduled_at, not -send_time)
        resp = requests.get(
            "https://a.klaviyo.com/api/campaigns",
            headers=headers,
            params={"filter": "equals(messages.channel,'email')", "sort": "-scheduled_at"},
            timeout=15
        )

        if resp.status_code != 200:
            error_detail = resp.text[:200]
            logger.error(f"Klaviyo campaigns API error {resp.status_code}: {error_detail}")
            return f"[Klaviyo API error {resp.status_code}: {error_detail}]"

        campaigns = resp.json().get("data", [])

        # Filter to recent sent campaigns + a few for context
        cutoff = (datetime.now(NZ_TZ) - timedelta(days=max(days, 7))).isoformat()
        recent = []
        for c in campaigns:
            attrs = c.get("attributes", {})
            send_time = attrs.get("send_time", "")
            status = attrs.get("status", "")
            if status in ("Sent", "Sending") and send_time:
                if send_time >= cutoff or len(recent) < 5:
                    recent.append(c)
            if len(recent) >= 5:
                break

        lines = [
            f"KLAVIYO -- Recent campaigns (as of {datetime.now(NZ_TZ).strftime('%Y-%m-%d %H:%M NZST')})",
        ]

        if not recent:
            lines.append("  No recent sent campaigns found")
            return "\n".join(lines)

        # Fetch metrics for each campaign
        # Klaviyo requires conversion_metric_id -- use "Placed Order" (Shopify)
        # First find the metric ID for Placed Order
        placed_order_metric_id = None
        try:
            metrics_resp = requests.get(
                "https://a.klaviyo.com/api/metrics",
                headers=headers,
                timeout=15
            )
            if metrics_resp.status_code == 200:
                for m in metrics_resp.json().get("data", []):
                    if m.get("attributes", {}).get("name") == "Placed Order":
                        integration = m.get("attributes", {}).get("integration", {})
                        # Prefer Shopify Placed Order over API Placed Order
                        int_name = integration.get("name", "") if integration else ""
                        if int_name == "Shopify" or placed_order_metric_id is None:
                            placed_order_metric_id = m["id"]
        except Exception as me:
            logger.debug(f"Klaviyo metrics list failed: {me}")

        for c in recent:
            attrs = c.get("attributes", {})
            name = attrs.get("name", "Unknown")
            status = attrs.get("status", "unknown")
            send_time = attrs.get("send_time", "")
            campaign_id = c.get("id", "")

            lines.append(f"  Campaign: {name}")
            if send_time:
                lines.append(f"    Sent: {send_time[:16].replace('T', ' ')}")

            # Fetch campaign metrics
            if campaign_id and placed_order_metric_id:
                try:
                    metrics_payload = {
                        "data": {
                            "type": "campaign-values-report",
                            "attributes": {
                                "statistics": [
                                    "opens", "clicks", "recipients",
                                    "unsubscribes", "open_rate", "click_rate",
                                    "conversion_value", "conversions", "conversion_rate"
                                ],
                                "timeframe": {"key": "last_30_days"},
                                "filter": f"equals(campaign_id,\"{campaign_id}\")",
                                "conversion_metric_id": placed_order_metric_id
                            }
                        }
                    }
                    mr = requests.post(
                        "https://a.klaviyo.com/api/campaign-values-reports/",
                        headers={**headers, "Content-Type": "application/json"},
                        json=metrics_payload,
                        timeout=15
                    )
                    if mr.status_code == 200:
                        results = mr.json().get("data", {}).get("attributes", {}).get("results", [])
                        if results:
                            stats = results[0].get("statistics", {})
                            recipients = int(stats.get("recipients", 0))
                            opens = int(stats.get("opens", 0))
                            open_rate = stats.get("open_rate", 0)
                            clicks = int(stats.get("clicks", 0))
                            click_rate = stats.get("click_rate", 0)
                            revenue = stats.get("conversion_value", 0)
                            orders = int(stats.get("conversions", 0))
                            unsubs = int(stats.get("unsubscribes", 0))

                            lines.append(f"    Recipients: {recipients:,}")
                            lines.append(f"    Opens: {opens:,} ({open_rate:.1%})")
                            lines.append(f"    Clicks: {clicks:,} ({click_rate:.1%})")
                            if orders or revenue:
                                lines.append(f"    Orders: {orders} | Revenue: ${revenue:,.2f}")
                            if unsubs:
                                lines.append(f"    Unsubscribes: {unsubs}")
                    else:
                        logger.debug(f"Klaviyo metrics {mr.status_code} for {campaign_id}: {mr.text[:100]}")
                except Exception as me:
                    logger.debug(f"Klaviyo metrics fetch failed for {name}: {me}")

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


# --- Meta Ads Video Metrics ---

def fetch_meta_video_metrics(campaign_filter: str = None, days: int = 7,
                              since: str = None, until: str = None) -> dict:
    """Fetch ad-level video engagement metrics from Meta Ads API.

    Returns structured dict with per-ad video performance + formatted string.
    Supports either relative days or explicit date range (since/until as YYYY-MM-DD).
    """
    access_token = os.environ.get("META_ACCESS_TOKEN")
    ad_account_id = os.environ.get("META_AD_ACCOUNT_ID")

    if not access_token or not ad_account_id:
        return {"error": "Meta Ads not configured", "formatted": "[Meta Ads video data unavailable]", "ads": []}

    import requests

    # Date range
    if since and until:
        date_since = since
        date_until = until
    else:
        now_nz = datetime.now(NZ_TZ)
        nz_start = now_nz.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
        nz_start_utc = nz_start.astimezone(ZoneInfo("UTC"))
        nz_end_utc = now_nz.astimezone(ZoneInfo("UTC"))
        date_since = nz_start_utc.strftime("%Y-%m-%d")
        date_until = nz_end_utc.strftime("%Y-%m-%d")

    fields = ",".join([
        "ad_name", "campaign_name", "adset_name",
        "spend", "impressions", "reach", "clicks", "ctr", "cpc",
        "actions", "action_values", "cost_per_action_type",
        "video_play_actions",
        "video_thruplay_watched_actions",
        "video_p25_watched_actions",
        "video_p50_watched_actions",
        "video_p75_watched_actions",
        "video_p100_watched_actions",
        "video_avg_time_watched_actions",
    ])

    try:
        url = f"https://graph.facebook.com/v21.0/act_{ad_account_id}/insights"
        params = {
            "access_token": access_token,
            "time_range": json.dumps({"since": date_since, "until": date_until}),
            "fields": fields,
            "level": "ad",
            "limit": 50,
        }
        if campaign_filter:
            params["filtering"] = json.dumps([{
                "field": "campaign.name",
                "operator": "CONTAIN",
                "value": campaign_filter,
            }])

        resp = requests.get(url, params=params, timeout=30)

        if resp.status_code != 200:
            error_msg = resp.json().get("error", {}).get("message", resp.text[:200])
            logger.error(f"Meta video metrics API error {resp.status_code}: {error_msg}")
            return {"error": error_msg, "formatted": f"[Meta API error: {error_msg}]", "ads": []}

        raw_ads = resp.json().get("data", [])

        if not raw_ads:
            return {"error": None, "formatted": f"No video ad data for {date_since} to {date_until}", "ads": []}

        ads = []
        for ad in raw_ads:
            # Extract purchases + revenue from actions
            purchases = 0
            revenue = 0.0
            cpa = 0.0
            for a in ad.get("actions", []):
                if a.get("action_type") == "purchase":
                    purchases = int(a.get("value", 0))
            for a in ad.get("action_values", []):
                if a.get("action_type") == "purchase":
                    revenue = float(a.get("value", 0))
            for a in ad.get("cost_per_action_type", []):
                if a.get("action_type") == "purchase":
                    cpa = float(a.get("value", 0))

            spend = float(ad.get("spend", 0))
            impressions = int(ad.get("impressions", 0))

            # Video metrics — extract values from action arrays
            def _video_val(field_data):
                if not field_data:
                    return 0
                if isinstance(field_data, list):
                    return sum(int(v.get("value", 0)) for v in field_data)
                return int(field_data)

            video_plays = _video_val(ad.get("video_play_actions"))
            thruplay = _video_val(ad.get("video_thruplay_watched_actions"))
            p25 = _video_val(ad.get("video_p25_watched_actions"))
            p50 = _video_val(ad.get("video_p50_watched_actions"))
            p75 = _video_val(ad.get("video_p75_watched_actions"))
            p100 = _video_val(ad.get("video_p100_watched_actions"))

            avg_watch_raw = ad.get("video_avg_time_watched_actions")
            avg_watch = 0.0
            if avg_watch_raw and isinstance(avg_watch_raw, list):
                avg_watch = float(avg_watch_raw[0].get("value", 0)) if avg_watch_raw else 0.0
            elif avg_watch_raw:
                avg_watch = float(avg_watch_raw)

            # Derived metrics
            hook_rate = (p25 / impressions * 100) if impressions > 0 else 0  # ~3s for 13s video
            completion_rate = (p100 / video_plays * 100) if video_plays > 0 else 0
            thruplay_rate = (thruplay / impressions * 100) if impressions > 0 else 0
            roas = revenue / spend if spend > 0 else 0

            ad_record = {
                "ad_name": ad.get("ad_name", "Unknown"),
                "campaign_name": ad.get("campaign_name", "Unknown"),
                "adset_name": ad.get("adset_name", "Unknown"),
                "spend": spend,
                "impressions": impressions,
                "reach": int(ad.get("reach", 0)),
                "clicks": int(ad.get("clicks", 0)),
                "ctr": float(ad.get("ctr", 0)),
                "cpc": float(ad.get("cpc", 0)),
                "purchases": purchases,
                "revenue": revenue,
                "cpa": cpa,
                "roas": roas,
                "video_plays": video_plays,
                "thruplay": thruplay,
                "thruplay_rate": thruplay_rate,
                "p25": p25,
                "p50": p50,
                "p75": p75,
                "p100": p100,
                "avg_watch_time": avg_watch,
                "hook_rate": hook_rate,
                "completion_rate": completion_rate,
                "drop_off_25_50": ((p25 - p50) / p25 * 100) if p25 > 0 else 0,
                "drop_off_50_75": ((p50 - p75) / p50 * 100) if p50 > 0 else 0,
                "drop_off_75_100": ((p75 - p100) / p75 * 100) if p75 > 0 else 0,
            }
            ads.append(ad_record)

        # Sort by spend descending
        ads.sort(key=lambda x: x["spend"], reverse=True)

        # Format output
        lines = [
            f"META VIDEO METRICS — {date_since} to {date_until}",
            f"Filter: {campaign_filter or 'All campaigns'}",
            f"Ads found: {len(ads)}",
            "",
        ]

        for i, a in enumerate(ads, 1):
            lines.append(f"--- Ad {i}: {a['ad_name']} ---")
            lines.append(f"  Campaign: {a['campaign_name']}")
            lines.append(f"  Ad Set: {a['adset_name']}")
            lines.append(f"  Spend: ${a['spend']:,.2f}  |  Impressions: {a['impressions']:,}  |  Reach: {a['reach']:,}")
            lines.append(f"  Clicks: {a['clicks']:,}  |  CTR: {a['ctr']:.2f}%  |  CPC: ${a['cpc']:.2f}")
            lines.append(f"  Purchases: {a['purchases']}  |  Revenue: ${a['revenue']:,.2f}  |  CPA: ${a['cpa']:,.2f}  |  ROAS: {a['roas']:.2f}x")
            lines.append(f"  Video Plays: {a['video_plays']:,}  |  Avg Watch: {a['avg_watch_time']:.1f}s")
            lines.append(f"  Hook Rate (25%): {a['hook_rate']:.1f}%  |  ThruPlay Rate: {a['thruplay_rate']:.1f}%  |  Completion: {a['completion_rate']:.1f}%")
            lines.append(f"  Retention: 25%={a['p25']:,} → 50%={a['p50']:,} → 75%={a['p75']:,} → 100%={a['p100']:,}")
            lines.append(f"  Drop-off: 25→50: {a['drop_off_25_50']:.1f}%  |  50→75: {a['drop_off_50_75']:.1f}%  |  75→100: {a['drop_off_75_100']:.1f}%")
            lines.append("")

        # Comparative summary
        if len(ads) > 1:
            lines.append("=== COMPARATIVE SUMMARY ===")
            best_hook = max(ads, key=lambda x: x["hook_rate"])
            best_completion = max(ads, key=lambda x: x["completion_rate"])
            best_cpa = min((a for a in ads if a["purchases"] > 0), key=lambda x: x["cpa"], default=None)
            best_roas = max(ads, key=lambda x: x["roas"])

            lines.append(f"  Best Hook Rate: {best_hook['ad_name']} ({best_hook['hook_rate']:.1f}%)")
            lines.append(f"  Best Completion: {best_completion['ad_name']} ({best_completion['completion_rate']:.1f}%)")
            if best_cpa:
                lines.append(f"  Best CPA: {best_cpa['ad_name']} (${best_cpa['cpa']:,.2f})")
            lines.append(f"  Best ROAS: {best_roas['ad_name']} ({best_roas['roas']:.2f}x)")

        formatted = "\n".join(lines)
        return {"error": None, "formatted": formatted, "ads": ads}

    except Exception as e:
        logger.error(f"Meta video metrics error: {e}")
        return {"error": str(e), "formatted": f"[Meta video metrics error: {e}]", "ads": []}


# --- Google Ads ---

def fetch_google_ads_data(days: int = 1) -> str:
    """Fetch Google Ads campaign performance via REST API (no SDK needed)."""
    developer_token = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN")
    client_id = os.environ.get("GOOGLE_ADS_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_ADS_CLIENT_SECRET")
    refresh_token = os.environ.get("GOOGLE_ADS_REFRESH_TOKEN")
    customer_id = os.environ.get("GOOGLE_ADS_CUSTOMER_ID")

    if not developer_token or not refresh_token:
        return "[Google Ads data unavailable -- set GOOGLE_ADS_DEVELOPER_TOKEN and GOOGLE_ADS_REFRESH_TOKEN]"
    if not client_id or not client_secret:
        return "[Google Ads data unavailable -- set GOOGLE_ADS_CLIENT_ID and GOOGLE_ADS_CLIENT_SECRET]"
    if not customer_id:
        return "[Google Ads data unavailable -- set GOOGLE_ADS_CUSTOMER_ID]"

    import requests

    # Strip dashes from customer ID if present
    customer_id = customer_id.replace("-", "")

    try:
        # Step 1: Exchange refresh token for access token
        token_resp = requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=15,
        )
        if token_resp.status_code != 200:
            error_detail = token_resp.text[:200]
            logger.error(f"Google Ads OAuth error {token_resp.status_code}: {error_detail}")
            return f"[Google Ads OAuth error {token_resp.status_code}: {error_detail}]"

        access_token = token_resp.json().get("access_token")
        if not access_token:
            return "[Google Ads OAuth error: no access_token in response]"

        # Step 2: Build GAQL query with correct date filter
        now_nz = datetime.now(NZ_TZ)
        if days == 1:
            date_filter = f"segments.date = '{now_nz.strftime('%Y-%m-%d')}'"
        else:
            end_date = now_nz.strftime("%Y-%m-%d")
            start_date = (now_nz - timedelta(days=days - 1)).strftime("%Y-%m-%d")
            date_filter = f"segments.date BETWEEN '{start_date}' AND '{end_date}'"

        query = (
            "SELECT campaign.name, campaign.status, "
            "metrics.cost_micros, metrics.clicks, metrics.impressions, "
            "metrics.conversions, metrics.conversions_value, metrics.average_cpc "
            "FROM campaign "
            f"WHERE {date_filter} AND campaign.status != 'REMOVED' "
            "ORDER BY metrics.cost_micros DESC"
        )

        # Step 3: Call the Google Ads searchStream REST endpoint
        headers = {
            "Authorization": f"Bearer {access_token}",
            "developer-token": developer_token,
            "Content-Type": "application/json",
        }

        search_url = f"https://googleads.googleapis.com/v19/customers/{customer_id}/googleAds:searchStream"
        search_resp = requests.post(
            search_url,
            headers=headers,
            json={"query": query},
            timeout=30,
        )

        if search_resp.status_code != 200:
            error_detail = search_resp.text[:300]
            logger.error(f"Google Ads API error {search_resp.status_code}: {error_detail}")
            return f"[Google Ads API error {search_resp.status_code}: {error_detail}]"

        # Step 4: Parse the streaming response (list of result batches)
        response_data = search_resp.json()

        # searchStream returns a list of batches, each with "results"
        all_rows = []
        if isinstance(response_data, list):
            for batch in response_data:
                all_rows.extend(batch.get("results", []))
        elif isinstance(response_data, dict):
            all_rows.extend(response_data.get("results", []))

        if not all_rows:
            return f"GOOGLE ADS -- No campaign data for last {days} day(s) (as of {now_nz.strftime('%Y-%m-%d %H:%M NZST')})"

        # Step 5: Aggregate totals and per-campaign breakdown
        total_spend = 0.0
        total_clicks = 0
        total_impressions = 0
        total_conversions = 0.0
        total_conv_value = 0.0
        campaigns = {}

        for row in all_rows:
            campaign = row.get("campaign", {})
            metrics = row.get("metrics", {})
            name = campaign.get("name", "Unknown")

            cost_micros = int(metrics.get("costMicros", 0))
            spend = cost_micros / 1_000_000
            clicks = int(metrics.get("clicks", 0))
            impressions = int(metrics.get("impressions", 0))
            conversions = float(metrics.get("conversions", 0))
            conv_value = float(metrics.get("conversionsValue", 0))

            total_spend += spend
            total_clicks += clicks
            total_impressions += impressions
            total_conversions += conversions
            total_conv_value += conv_value

            # Aggregate per campaign (multiple rows if multi-day query)
            if name not in campaigns:
                campaigns[name] = {"spend": 0, "clicks": 0, "impressions": 0, "conversions": 0, "conv_value": 0}
            campaigns[name]["spend"] += spend
            campaigns[name]["clicks"] += clicks
            campaigns[name]["impressions"] += impressions
            campaigns[name]["conversions"] += conversions
            campaigns[name]["conv_value"] += conv_value

        total_cpc = total_spend / total_clicks if total_clicks > 0 else 0
        total_roas = total_conv_value / total_spend if total_spend > 0 else 0

        # Step 6: Format output
        lines = [
            f"GOOGLE ADS -- Last {days} day(s) (as of {now_nz.strftime('%Y-%m-%d %H:%M NZST')})",
            f"  Spend: ${total_spend:,.2f}",
            f"  Clicks: {total_clicks:,}  Impressions: {total_impressions:,}",
            f"  Conversions: {total_conversions:.0f}  Conv. Value: ${total_conv_value:,.2f}",
            f"  CPC: ${total_cpc:.2f}  ROAS: {total_roas:.2f}x",
        ]

        # Per-campaign breakdown sorted by spend descending
        sorted_campaigns = sorted(campaigns.items(), key=lambda x: x[1]["spend"], reverse=True)
        if sorted_campaigns:
            lines.append("")
            lines.append("  By Campaign:")
            for name, m in sorted_campaigns:
                c_roas = m["conv_value"] / m["spend"] if m["spend"] > 0 else 0
                lines.append(
                    f"    {name}: ${m['spend']:,.2f} spend, "
                    f"{m['clicks']:,} clicks, "
                    f"{m['conversions']:.0f} conversions, "
                    f"${m['conv_value']:,.2f} value, "
                    f"{c_roas:.2f}x ROAS"
                )

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Google Ads fetch error: {e}")
        return f"[Google Ads error: {str(e)}]"


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
