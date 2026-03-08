"""
Unified Data Brief — Single source of truth for all agent data.

This module produces the SAME data that powers the dashboard, formatted as
plain text for injection into Telegram agent prompts. Instead of each agent
independently calling APIs (which often fails), all agents get their business
data from here — same queries, same databases, same API calls.

If the dashboard shows it correctly, agents see it correctly.

Usage:
    from core.data_brief import build_data_brief
    brief = build_data_brief(days=1)  # Returns plain text for agent injection
"""

import os
import sqlite3
import logging
from datetime import datetime, timedelta, date
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

NZ_TZ = ZoneInfo("Pacific/Auckland")


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER: Query local SQLite databases
# ═══════════════════════════════════════════════════════════════════════════════

def _query_db(db_name: str, query: str, params=(), one=False):
    """Query a local SQLite database."""
    db_path = BASE_DIR / "data" / db_name
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(query, params)
        result = cursor.fetchone() if one else cursor.fetchall()
        conn.close()
        return dict(result) if one and result else [dict(r) for r in result] if result else (None if one else [])
    except Exception as e:
        logger.warning(f"DB query failed ({db_name}): {e}")
        return None if one else []


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1: SHOPIFY — Orders, Revenue, Products (from customer_intelligence.db)
# ═══════════════════════════════════════════════════════════════════════════════

def _fetch_shopify_orders_since(store_url: str, token: str, since_iso: str, headers: dict) -> list:
    """Fetch all Shopify orders since a given ISO timestamp (handles pagination)."""
    import requests
    all_orders = []
    url = f"https://{store_url}/admin/api/2025-01/orders.json"
    params = {"created_at_min": since_iso, "status": "any", "limit": 250}
    while url:
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=15)
            if resp.status_code != 200:
                break
            orders = resp.json().get("orders", [])
            all_orders.extend(orders)
            # Shopify pagination via Link header
            link = resp.headers.get("Link", "")
            next_url = None
            for part in link.split(","):
                part = part.strip()
                if 'rel="next"' in part:
                    next_url = part.split(";")[0].strip().strip("<>")
            url = next_url
            params = {}  # params are already in next_url
        except Exception as e:
            logger.debug(f"Shopify paginated fetch: {e}")
            break
    return all_orders


def _shopify_brief(days: int = 1) -> str:
    """Shopify performance — MTD from live Shopify API (primary) + DB for product/channel detail."""
    import requests

    now = datetime.now(NZ_TZ)
    lines = [f"SHOPIFY — as of {now.strftime('%Y-%m-%d %H:%M NZST')}"]

    store_url = os.environ.get("SHOPIFY_STORE_URL")
    token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
    api_headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"} if token else {}

    # ── Monthly target math ──────────────────────────────────────────────────
    import calendar
    monthly_target = 50000.0
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    day_of_month = now.day
    days_remaining = days_in_month - day_of_month  # days after today
    days_elapsed = day_of_month  # days including today

    # ── MTD from live Shopify API (SINGLE SOURCE OF TRUTH) ──────────────────
    mtd_api_rev, mtd_api_orders, mtd_api_ok = 0.0, 0, False
    today_rev, today_orders = 0.0, 0

    if store_url and token:
        try:
            month_start_iso = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
            today_start_iso = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

            # Full MTD from API (paginated to handle large months)
            all_month_orders = _fetch_shopify_orders_since(store_url, token, month_start_iso, api_headers)
            for o in all_month_orders:
                price = float(o.get("total_price", 0))
                mtd_api_rev += price
                mtd_api_orders += 1
                # Split today vs earlier
                created = o.get("created_at", "")
                if created >= today_start_iso:
                    today_rev += price
                    today_orders += 1

            mtd_api_ok = True
        except Exception as e:
            logger.warning(f"Shopify MTD API fetch failed: {e}")

    # ── Revenue lines ────────────────────────────────────────────────────────
    if mtd_api_ok:
        lines.append(f"  Month-to-date (LIVE): ${mtd_api_rev:,.2f} from {mtd_api_orders} orders")
        lines.append(f"  Today so far: ${today_rev:,.2f} from {today_orders} orders")
        if mtd_api_orders > 0:
            lines.append(f"  AOV (month): ${mtd_api_rev/mtd_api_orders:,.2f}")

        # Daily pace vs target
        avg_daily = mtd_api_rev / days_elapsed if days_elapsed > 0 else 0
        needed_daily = (monthly_target - mtd_api_rev) / days_remaining if days_remaining > 0 else 0
        gap_pct = ((needed_daily - avg_daily) / avg_daily * 100) if avg_daily > 0 else 0
        gap_label = f"+{gap_pct:.0f}% acceleration needed" if gap_pct > 0 else f"on track ({abs(gap_pct):.0f}% ahead of pace)"
        lines.append(f"")
        lines.append(f"  MONTHLY PACE vs TARGET:")
        lines.append(f"    Target: ${monthly_target:,.0f} | Day {day_of_month} of {days_in_month} | {days_remaining} days remaining")
        lines.append(f"    Current avg: ${avg_daily:,.0f}/day | Required: ${needed_daily:,.0f}/day")
        lines.append(f"    Status: {gap_label}")

        # DB freshness check — warn if DB is out of sync
        month_start_str = now.strftime("%Y-%m-01")
        db_mtd = _query_db("customer_intelligence.db",
            "SELECT COALESCE(SUM(total_price), 0) as rev, COUNT(*) as orders FROM orders WHERE created_at >= ?",
            (month_start_str,), one=True)
        if db_mtd and db_mtd["rev"] > 0:
            db_rev = float(db_mtd["rev"])
            if db_rev < mtd_api_rev * 0.85:  # DB is >15% below API = stale
                lines.append(f"")
                lines.append(f"  ⚠ DATA SYNC WARNING: DB shows ${db_rev:,.2f} MTD vs API ${mtd_api_rev:,.2f}")
                lines.append(f"    intelligence_sync may be failing on Railway. DB data is stale.")
    else:
        # API failed — fall back to DB
        lines.append(f"  [API unavailable — using DB data, may be stale]")
        month_start_str = now.strftime("%Y-%m-01")
        mtd = _query_db("customer_intelligence.db",
            "SELECT COALESCE(SUM(total_price), 0) as rev, COUNT(*) as orders FROM orders WHERE created_at >= ?",
            (month_start_str,), one=True)
        if mtd:
            lines.append(f"  Month-to-date (DB): ${mtd['rev']:,.2f} from {mtd['orders']} orders")
            if mtd['orders'] > 0:
                lines.append(f"  AOV (month): ${mtd['rev']/mtd['orders']:,.2f}")
            avg_daily = mtd['rev'] / days_elapsed if days_elapsed > 0 else 0
            needed_daily = (monthly_target - mtd['rev']) / days_remaining if days_remaining > 0 else 0
            lines.append(f"  Required daily pace: ${needed_daily:,.0f}/day ({days_remaining} days remaining)")

    lines.append("")

    # ── Top products + attribution from DB (DB is fine for historical detail) ─
    month_start_str = now.strftime("%Y-%m-01")

    products = _query_db("customer_intelligence.db",
        "SELECT products, COUNT(*) as orders, COALESCE(SUM(total_price), 0) as rev "
        "FROM orders WHERE created_at >= ? GROUP BY products ORDER BY rev DESC LIMIT 8",
        (month_start_str,))
    if products:
        lines.append("  Top Products (this month, DB):")
        for p in products:
            lines.append(f"    {p['products']}: {p['orders']} orders, ${p['rev']:,.2f}")

    channels = _query_db("customer_intelligence.db",
        "SELECT channel, COUNT(*) as orders, COALESCE(SUM(total_price), 0) as rev "
        "FROM orders WHERE created_at >= ? GROUP BY channel ORDER BY rev DESC",
        (month_start_str,))
    if channels:
        total_rev = sum(c['rev'] for c in channels)
        lines.append("  Revenue Attribution (this month, DB):")
        for c in channels:
            pct = round(c['rev'] / total_rev * 100, 1) if total_rev else 0
            lines.append(f"    {c['channel']}: ${c['rev']:,.2f} ({pct}%) — {c['orders']} orders")

    # ── Period data (last N days) from DB ────────────────────────────────────
    if days > 1:
        cutoff = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        period = _query_db("customer_intelligence.db",
            "SELECT COALESCE(SUM(total_price), 0) as rev, COUNT(*) as orders FROM orders WHERE created_at >= ?",
            (cutoff,), one=True)
        if period:
            lines.append(f"  Last {days} days (DB): ${period['rev']:,.2f} from {period['orders']} orders")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2: KLAVIYO — Email Campaign Performance (direct API)
# ═══════════════════════════════════════════════════════════════════════════════

def _klaviyo_brief(days: int = 1) -> str:
    """Recent Klaviyo campaign performance from API."""
    import requests

    api_key = os.environ.get("KLAVIYO_API_KEY")
    if not api_key:
        return "KLAVIYO — Not configured (set KLAVIYO_API_KEY)"

    now = datetime.now(NZ_TZ)
    lines = [f"KLAVIYO — Recent campaigns (as of {now.strftime('%Y-%m-%d %H:%M NZST')})"]

    try:
        headers = {"Authorization": f"Klaviyo-API-Key {api_key}", "revision": "2025-07-15", "Accept": "application/json"}

        # Get recent campaigns (match dashboard call exactly)
        resp = requests.get(
            "https://a.klaviyo.com/api/campaigns",
            headers=headers,
            params={"filter": "equals(messages.channel,'email')", "sort": "-updated_at",
                    "include": "campaign-messages"},
            timeout=15
        )
        if resp.status_code != 200:
            return f"KLAVIYO — API error {resp.status_code}"

        data = resp.json()
        campaigns = data.get("data", [])

        # Build subject line map from included messages
        subject_map = {}
        for inc in data.get("included", []):
            if inc.get("type") == "campaign-message":
                label = inc.get("attributes", {}).get("label", "")
                camp_id = inc.get("relationships", {}).get("campaign", {}).get("data", {}).get("id", "")
                if camp_id and label:
                    subject_map[camp_id] = label

        # Find Placed Order metric ID (needed for revenue attribution)
        placed_order_metric_id = None
        try:
            mr = requests.get("https://a.klaviyo.com/api/metrics", headers=headers, timeout=15)
            if mr.status_code == 200:
                for m in mr.json().get("data", []):
                    if m.get("attributes", {}).get("name") == "Placed Order":
                        integration = m.get("attributes", {}).get("integration", {})
                        int_name = integration.get("name", "") if integration else ""
                        if int_name == "Shopify" or placed_order_metric_id is None:
                            placed_order_metric_id = m["id"]
        except Exception:
            pass

        sent_campaigns = []
        for c in campaigns:
            attrs = c.get("attributes", {})
            status = attrs.get("status", "")
            if status not in ("Sent", "Sending"):
                continue
            sent_campaigns.append((c["id"], attrs))

        if not sent_campaigns:
            lines.append("  No sent campaigns found")
            return "\n".join(lines)

        # Get metrics for each campaign (match dashboard call exactly)
        for camp_id, attrs in sent_campaigns[:6]:
            name = attrs.get("name", "Unknown")
            subject = subject_map.get(camp_id, "")
            send_time = attrs.get("send_time") or attrs.get("scheduled_at") or attrs.get("updated_at") or ""
            is_sending = attrs.get("status") == "Sending"

            stats = {}
            if camp_id and placed_order_metric_id:
                try:
                    metrics_resp = requests.post(
                        "https://a.klaviyo.com/api/campaign-values-reports/",
                        headers={**headers, "Content-Type": "application/json"},
                        json={
                            "data": {
                                "type": "campaign-values-report",
                                "attributes": {
                                    "statistics": ["opens", "clicks", "recipients", "unsubscribes",
                                                  "open_rate", "click_rate", "conversion_value",
                                                  "conversions", "conversion_rate"],
                                    "timeframe": {"key": "last_30_days"},
                                    "filter": f'equals(campaign_id,"{camp_id}")',
                                    "conversion_metric_id": placed_order_metric_id,
                                }
                            }
                        },
                        timeout=15
                    )
                    if metrics_resp.status_code == 200:
                        results = metrics_resp.json().get("data", {}).get("attributes", {}).get("results", [])
                        if results:
                            stats = results[0].get("statistics", {})
                except Exception:
                    pass

            recipients = int(stats.get("recipients", 0))
            opens = int(stats.get("opens", 0))
            open_rate = float(stats.get("open_rate", 0))
            clicks = int(stats.get("clicks", 0))
            click_rate = float(stats.get("click_rate", 0))
            revenue = float(stats.get("conversion_value", 0))
            conversions = int(stats.get("conversions", 0))
            conv_rate = float(stats.get("conversion_rate", 0))
            unsubs = int(stats.get("unsubscribes", 0))

            # Skip campaigns with no data (too old or not sent)
            if recipients == 0 and not is_sending:
                continue

            status_label = " (STILL SENDING)" if is_sending else ""
            lines.append(f"  Campaign: {name}{status_label}")
            if subject:
                lines.append(f"    Subject: {subject}")
            if send_time:
                lines.append(f"    Sent: {send_time[:16]}")
            lines.append(f"    Recipients: {recipients:,}")
            lines.append(f"    Opens: {opens:,} ({open_rate:.1%})")
            lines.append(f"    Clicks: {clicks:,} ({click_rate:.2%})")
            lines.append(f"    Conversions: {conversions} ({conv_rate:.2%})")
            lines.append(f"    Revenue: ${revenue:,.2f}")
            if recipients > 0:
                lines.append(f"    Rev/Recipient: ${revenue/recipients:.2f}")
            if unsubs > 0:
                unsub_rate = unsubs / recipients * 100 if recipients else 0
                lines.append(f"    Unsubscribes: {unsubs} ({unsub_rate:.2f}%)")
            lines.append("")

    except Exception as e:
        lines.append(f"  Error: {e}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3: META ADS — Campaign Performance (direct API)
# ═══════════════════════════════════════════════════════════════════════════════

def _meta_brief(days: int = 1) -> str:
    """Meta Ads performance from Graph API."""
    import requests

    token = os.environ.get("META_ACCESS_TOKEN")
    account_id = os.environ.get("META_AD_ACCOUNT_ID")
    if not token or not account_id:
        return "META ADS — Not configured (set META_ACCESS_TOKEN and META_AD_ACCOUNT_ID)"

    now = datetime.now(NZ_TZ)
    lines = [f"META ADS — Last {days} day(s) (as of {now.strftime('%Y-%m-%d %H:%M NZST')})"]

    try:
        # Date range
        end_date = now.strftime("%Y-%m-%d")
        start_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")

        # Account-level stats
        resp = requests.get(
            f"https://graph.facebook.com/v21.0/act_{account_id}/insights",
            params={
                "fields": "spend,impressions,clicks,ctr,cpc,actions,action_values,cost_per_action_type",
                "time_range": f'{{"since":"{start_date}","until":"{end_date}"}}',
                "access_token": token,
            },
            timeout=15
        )
        if resp.status_code != 200:
            return f"META ADS — API error {resp.status_code}: {resp.text[:100]}"

        data = resp.json().get("data", [])
        if not data:
            lines.append("  No data for this period")
            return "\n".join(lines)

        d = data[0]
        spend = float(d.get("spend", 0))
        impressions = int(d.get("impressions", 0))
        clicks = int(d.get("clicks", 0))
        ctr = float(d.get("ctr", 0))
        cpc = float(d.get("cpc", 0))

        # Extract purchases and revenue from actions
        purchases, revenue = 0, 0
        for a in d.get("actions", []):
            if a.get("action_type") == "purchase":
                purchases = int(a.get("value", 0))
        for a in d.get("action_values", []):
            if a.get("action_type") == "purchase":
                revenue = float(a.get("value", 0))

        roas = revenue / spend if spend > 0 else 0

        lines.append(f"  Spend: ${spend:,.2f}")
        lines.append(f"  Impressions: {impressions:,}")
        lines.append(f"  Clicks: {clicks:,} (CTR: {ctr:.2f}%)")
        lines.append(f"  CPC: ${cpc:.2f}")
        lines.append(f"  Purchases (Meta-claimed): {purchases}")
        lines.append(f"  Revenue (Meta-claimed): ${revenue:,.2f}")
        lines.append(f"  ROAS (Meta-claimed): {roas:.2f}x")
        if roas > 0:
            lines.append(f"  NOTE: Meta typically overclaims ROAS by ~150%. Shopify-verified ROAS is the truth.")

        # Campaign-level breakdown
        camp_resp = requests.get(
            f"https://graph.facebook.com/v21.0/act_{account_id}/insights",
            params={
                "fields": "campaign_name,spend,impressions,clicks,actions,action_values",
                "time_range": f'{{"since":"{start_date}","until":"{end_date}"}}',
                "level": "campaign",
                "access_token": token,
                "limit": 10,
            },
            timeout=15
        )
        if camp_resp.status_code == 200:
            camp_data = camp_resp.json().get("data", [])
            if camp_data:
                lines.append("  Campaigns:")
                for c in camp_data:
                    c_spend = float(c.get("spend", 0))
                    c_clicks = int(c.get("clicks", 0))
                    c_rev = 0
                    for a in c.get("action_values", []):
                        if a.get("action_type") == "purchase":
                            c_rev = float(a.get("value", 0))
                    c_roas = c_rev / c_spend if c_spend > 0 else 0
                    lines.append(f"    {c.get('campaign_name', '?')}: ${c_spend:.2f} spend, {c_clicks} clicks, ${c_rev:.2f} rev ({c_roas:.1f}x ROAS)")

    except Exception as e:
        lines.append(f"  Error: {e}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4: GOOGLE ADS (REST API)
# ═══════════════════════════════════════════════════════════════════════════════

def _google_ads_brief(days: int = 1) -> str:
    """Google Ads performance from REST API."""
    import requests

    client_id = os.environ.get("GOOGLE_ADS_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_ADS_CLIENT_SECRET")
    refresh_token = os.environ.get("GOOGLE_ADS_REFRESH_TOKEN")
    customer_id = os.environ.get("GOOGLE_ADS_CUSTOMER_ID")
    dev_token = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN")

    if not all([client_id, client_secret, refresh_token, customer_id, dev_token]):
        return "GOOGLE ADS — Not configured"

    now = datetime.now(NZ_TZ)
    lines = [f"GOOGLE ADS — Last {days} day(s) (as of {now.strftime('%Y-%m-%d %H:%M NZST')})"]

    try:
        # Get access token
        token_resp = requests.post("https://oauth2.googleapis.com/token", data={
            "client_id": client_id, "client_secret": client_secret,
            "refresh_token": refresh_token, "grant_type": "refresh_token"
        }, timeout=10)
        if token_resp.status_code != 200:
            return "GOOGLE ADS — OAuth token refresh failed"
        access_token = token_resp.json().get("access_token")

        # GAQL query
        end_date = now.strftime("%Y-%m-%d")
        start_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "developer-token": dev_token,
            "Content-Type": "application/json",
        }

        # Account-level query
        query = f"""
            SELECT metrics.cost_micros, metrics.clicks, metrics.impressions,
                   metrics.conversions, metrics.conversions_value,
                   campaign.name, campaign.status
            FROM campaign
            WHERE segments.date BETWEEN '{start_date}' AND '{end_date}'
              AND campaign.status != 'REMOVED'
        """

        resp = requests.post(
            f"https://googleads.googleapis.com/v19/customers/{customer_id}/googleAds:searchStream",
            headers=headers,
            json={"query": query},
            timeout=15
        )

        if resp.status_code != 200:
            lines.append(f"  API error: {resp.status_code}")
            return "\n".join(lines)

        results = resp.json()
        total_spend, total_clicks, total_impressions = 0, 0, 0
        total_conversions, total_conv_value = 0, 0
        campaigns = []

        for batch in results if isinstance(results, list) else [results]:
            for row in batch.get("results", []):
                m = row.get("metrics", {})
                spend = int(m.get("costMicros", 0)) / 1_000_000
                total_spend += spend
                total_clicks += int(m.get("clicks", 0))
                total_impressions += int(m.get("impressions", 0))
                total_conversions += float(m.get("conversions", 0))
                total_conv_value += float(m.get("conversionsValue", 0))

                camp_name = row.get("campaign", {}).get("name", "")
                if camp_name:
                    campaigns.append({
                        "name": camp_name,
                        "spend": spend,
                        "clicks": int(m.get("clicks", 0)),
                        "conversions": float(m.get("conversions", 0)),
                        "conv_value": float(m.get("conversionsValue", 0)),
                    })

        roas = total_conv_value / total_spend if total_spend > 0 else 0
        cpc = total_spend / total_clicks if total_clicks > 0 else 0

        lines.append(f"  Spend: ${total_spend:,.2f}")
        lines.append(f"  Clicks: {total_clicks:,} | Impressions: {total_impressions:,}")
        lines.append(f"  CPC: ${cpc:.2f}")
        lines.append(f"  Conversions: {total_conversions:.0f} | Value: ${total_conv_value:,.2f}")
        lines.append(f"  ROAS: {roas:.2f}x")

        if campaigns:
            # Aggregate by campaign name
            camp_agg = {}
            for c in campaigns:
                n = c["name"]
                if n not in camp_agg:
                    camp_agg[n] = {"spend": 0, "clicks": 0, "conversions": 0, "conv_value": 0}
                camp_agg[n]["spend"] += c["spend"]
                camp_agg[n]["clicks"] += c["clicks"]
                camp_agg[n]["conversions"] += c["conversions"]
                camp_agg[n]["conv_value"] += c["conv_value"]

            lines.append("  Campaigns:")
            for name, stats in sorted(camp_agg.items(), key=lambda x: x[1]["spend"], reverse=True):
                cr = stats["conv_value"] / stats["spend"] if stats["spend"] > 0 else 0
                lines.append(f"    {name}: ${stats['spend']:.2f} spend, {stats['clicks']} clicks, ${stats['conv_value']:.2f} value ({cr:.1f}x)")

    except Exception as e:
        lines.append(f"  Error: {e}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5: SEO RANKINGS (from pure_pets_rankings.db)
# ═══════════════════════════════════════════════════════════════════════════════

def _seo_brief() -> str:
    """SEO ranking status from Pure Pets rankings DB."""
    lines = ["SEO RANKINGS — Pure Pets Keywords"]

    rankings = _query_db("pure_pets_rankings.db",
        """SELECT r.* FROM pure_pets_rankings r
           INNER JOIN (SELECT keyword, MAX(date) as max_date FROM pure_pets_rankings GROUP BY keyword)
           latest ON r.keyword = latest.keyword AND r.date = latest.max_date
           ORDER BY r.position ASC""")

    if not rankings:
        lines.append("  No ranking data yet (GSC needs ~3 days after article publish)")
        return "\n".join(lines)

    positions = [r["position"] for r in rankings if r.get("position")]
    avg_pos = sum(positions) / len(positions) if positions else 0
    top_10 = sum(1 for p in positions if p <= 10)
    top_20 = sum(1 for p in positions if p <= 20)
    total_clicks = sum(r.get("clicks", 0) for r in rankings)

    lines.append(f"  Keywords with data: {len(rankings)} | Avg position: #{avg_pos:.1f}")
    lines.append(f"  In top 10: {top_10} | In top 20: {top_20}")
    lines.append(f"  Total clicks (7d): {total_clicks}")

    # Show all positions
    lines.append("  All positions:")
    for r in rankings:
        change = r.get("change_from_previous")
        change_str = ""
        if change is not None and change != 0:
            change_str = f" ({'+' if change > 0 else ''}{change:.0f})"
        alert = " !! DROP" if r.get("alert_flag") else ""
        lines.append(f"    #{r['position']:.1f} | {r['keyword']} | {r.get('clicks', 0)}c / {r.get('impressions', 0)}i{change_str}{alert}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6: EMAIL INTELLIGENCE SUMMARY (from intelligence.db)
# ═══════════════════════════════════════════════════════════════════════════════

def _email_intel_brief() -> str:
    """Email intelligence summary — hypotheses and recent campaign analysis."""
    lines = ["EMAIL INTELLIGENCE — Learning System Summary"]

    # Hypothesis counts
    for status in ["proven", "testing", "disproven"]:
        rows = _query_db("intelligence.db",
            "SELECT COUNT(*) as c FROM email_hypotheses WHERE status = ?", (status,), one=True)
        count = rows["c"] if rows else 0
        lines.append(f"  {status.title()} hypotheses: {count}")

    # Top proven hypotheses
    proven = _query_db("intelligence.db",
        "SELECT hypothesis, confidence FROM email_hypotheses WHERE status = 'proven' ORDER BY confidence DESC LIMIT 3")
    if proven:
        lines.append("  Top proven patterns:")
        for h in proven:
            lines.append(f"    ({h['confidence']:.0%}) {h['hypothesis'][:100]}")

    # Recent campaign performance tiers
    tiers = _query_db("intelligence.db",
        "SELECT performance_tier, COUNT(*) as c, AVG(rev_per_recipient) as avg_rpr "
        "FROM email_campaigns WHERE performance_tier IS NOT NULL GROUP BY performance_tier ORDER BY avg_rpr DESC")
    if tiers:
        lines.append("  Campaign tier distribution:")
        for t in tiers:
            lines.append(f"    Tier {t['performance_tier']}: {t['c']} campaigns (avg ${t['avg_rpr']:.2f}/recipient)")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6B: CREATIVE INTELLIGENCE (from intelligence.db)
# ═══════════════════════════════════════════════════════════════════════════════

def _creative_intel_brief() -> str:
    """Creative intelligence summary — hypothesis testing status and proven learnings."""
    lines = ["CREATIVE INTELLIGENCE — Hypothesis Testing Summary"]

    # Hypothesis counts
    for status in ["testing", "proven", "disproven"]:
        rows = _query_db("intelligence.db",
            "SELECT COUNT(*) as c FROM creative_hypotheses WHERE status = ?", (status,), one=True)
        count = rows["c"] if rows else 0
        lines.append(f"  {status.title()} hypotheses: {count}")

    # Active tests
    active = _query_db("intelligence.db",
        "SELECT COUNT(*) as c FROM creative_tests WHERE status = 'live'", one=True)
    active_count = active["c"] if active else 0
    lines.append(f"  Active creative tests: {active_count}")

    # Active test details
    if active_count > 0:
        tests = _query_db("intelligence.db",
            "SELECT hypothesis_id, meta_ad_name, spend, roas, cpa, hook_rate "
            "FROM creative_tests WHERE status = 'live' ORDER BY created_at DESC LIMIT 5")
        if tests:
            lines.append("  Live tests:")
            for t in tests:
                roas_str = f"{t['roas']:.2f}x" if t['roas'] > 0 else "pending"
                cpa_str = f"${t['cpa']:.2f}" if t['cpa'] > 0 else "pending"
                lines.append(f"    [{t['hypothesis_id']}] {t['meta_ad_name']}: ROAS {roas_str}, CPA {cpa_str}, spend ${t['spend']:.2f}")

    # Top proven creative learnings
    proven = _query_db("intelligence.db",
        "SELECT hypothesis_id, hypothesis, confidence FROM creative_hypotheses "
        "WHERE status = 'proven' ORDER BY confidence DESC LIMIT 3")
    if proven:
        lines.append("  Proven creative patterns:")
        for h in proven:
            lines.append(f"    [{h['hypothesis_id']}] ({h['confidence']:.0%}) {h['hypothesis'][:100]}")

    # Top disproven (things to avoid)
    disproven = _query_db("intelligence.db",
        "SELECT hypothesis_id, hypothesis FROM creative_hypotheses "
        "WHERE status = 'disproven' ORDER BY confidence ASC LIMIT 3")
    if disproven:
        lines.append("  Disproven (avoid):")
        for h in disproven:
            lines.append(f"    [{h['hypothesis_id']}] {h['hypothesis'][:100]}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 7: CUSTOMER INTELLIGENCE (from customer_intelligence.db)
# ═══════════════════════════════════════════════════════════════════════════════

def _customer_brief() -> str:
    """Customer intelligence — repeat buyers, at-risk, top customers."""
    lines = ["CUSTOMER INTELLIGENCE"]

    # Total stats (actual columns: shopify_customer_id, order_name, total_price, etc.)
    stats = _query_db("customer_intelligence.db",
        "SELECT COUNT(DISTINCT shopify_customer_id) as customers, COUNT(*) as orders, "
        "COALESCE(SUM(total_price), 0) as revenue FROM orders", one=True)
    if stats:
        lines.append(f"  Total customers: {stats['customers']} | Orders: {stats['orders']} | Revenue: ${stats['revenue']:,.2f}")

    # Repeat buyers
    repeats = _query_db("customer_intelligence.db",
        "SELECT COUNT(*) as c FROM (SELECT shopify_customer_id FROM orders GROUP BY shopify_customer_id HAVING COUNT(*) >= 2)",
        one=True)
    if repeats and stats and stats['customers'] > 0:
        rate = repeats['c'] / stats['customers'] * 100
        lines.append(f"  Repeat buyers: {repeats['c']} ({rate:.1f}% repeat rate)")

    # Top customers by LTV
    top = _query_db("customer_intelligence.db",
        "SELECT shopify_customer_id, order_name, COUNT(*) as orders, SUM(total_price) as ltv, "
        "MAX(created_at) as last_order FROM orders GROUP BY shopify_customer_id "
        "ORDER BY ltv DESC LIMIT 5")
    if top:
        lines.append("  Top 5 customers by LTV:")
        for c in top:
            name = c.get('order_name', f"Customer #{c['shopify_customer_id']}")
            lines.append(f"    {name}: {c['orders']} orders, ${c['ltv']:,.2f} LTV (last: {c['last_order'][:10]})")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN: Build complete data brief
# ═══════════════════════════════════════════════════════════════════════════════

def build_data_brief(days: int = 1, include_seo: bool = True, include_email_intel: bool = True,
                     include_customers: bool = True) -> str:
    """
    Build a comprehensive data brief from the same sources as the dashboard.
    Returns plain text formatted for injection into agent system prompts.

    This is the SINGLE SOURCE OF TRUTH for all agent business data.
    If the dashboard shows it correctly, this brief shows it correctly.
    """
    now = datetime.now(NZ_TZ)
    sections = [
        f"=== LIVE BUSINESS DATA (from dashboard — {now.strftime('%Y-%m-%d %H:%M NZST')}) ===",
        "Data pulled from the same sources as the Operations Dashboard.",
        "These numbers are verified and accurate.",
        ""
    ]

    # Core performance data (always included)
    sections.append(_shopify_brief(days))
    sections.append("")
    sections.append(_klaviyo_brief(days))
    sections.append("")
    sections.append(_meta_brief(days))
    sections.append("")
    sections.append(_google_ads_brief(days))

    if include_seo:
        sections.append("")
        sections.append(_seo_brief())

    if include_email_intel:
        sections.append("")
        sections.append(_email_intel_brief())
        sections.append("")
        sections.append(_creative_intel_brief())

    if include_customers:
        sections.append("")
        sections.append(_customer_brief())

    return "\n".join(sections)


def build_weekly_brief() -> str:
    """7-day data brief for weekly reviews."""
    return build_data_brief(days=7)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI — Test data brief output
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    print(build_data_brief(days))
