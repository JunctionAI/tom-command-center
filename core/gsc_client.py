#!/usr/bin/env python3
"""
Google Search Console API Client -- OAuth 2.0 authenticated client
for search performance data, ranking queries, and page analytics.

Uses Google Search Console API v3 (searchAnalytics/query).

Authentication:
  - Reuses the SAME Google OAuth 2.0 credentials as Google Ads
  - Client ID / Client Secret / Refresh Token from env vars
  - Bearer token via refresh_token -> access_token exchange
  - GSC scope is included in the broad Google Ads OAuth grant

API Endpoints:
  - POST https://www.googleapis.com/webmasters/v3/sites/{siteUrl}/searchAnalytics/query
  - GET  https://www.googleapis.com/webmasters/v3/sites/{siteUrl}/sitemaps

Rate Limits:
  - 1,200 queries per minute (shared across all Google APIs)
  - Query responses may be sampled for high-traffic sites

Site URL Formats:
  - URL prefix property: "https://www.deepbluehealth.co.nz/"
  - Domain property: "sc-domain:deepbluehealth.co.nz"

What can be done WITHOUT human approval (SAFE -- read-only):
  - Get search analytics (queries, pages, countries, devices)
  - Get sitemaps status
  - Get top queries and page performance
  - Generate Beacon SEO feedback

What NEEDS human approval:
  - Nothing -- this client is read-only
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)


class GSCClient:
    """
    OAuth 2.0 authenticated client for Google Search Console API v3.

    Provides search performance data for the Beacon SEO agent,
    including ranking queries, page performance, and position tracking.
    """

    TOKEN_URL = "https://oauth2.googleapis.com/token"
    API_BASE = "https://www.googleapis.com/webmasters/v3"

    def __init__(self):
        self.client_id = os.environ.get("GOOGLE_ADS_CLIENT_ID")
        self.client_secret = os.environ.get("GOOGLE_ADS_CLIENT_SECRET")
        self.refresh_token = os.environ.get("GOOGLE_ADS_REFRESH_TOKEN")
        self.site_url = os.environ.get("GSC_SITE_URL", "https://www.deepbluehealth.co.nz/")
        self._access_token = None
        self._token_expires_at = 0

    @property
    def available(self) -> bool:
        """Check if GSC credentials are configured."""
        return bool(self.client_id and self.client_secret and self.refresh_token)

    # ===================================================================
    # TOKEN MANAGEMENT
    # ===================================================================

    def _get_access_token(self) -> str:
        """
        Exchange refresh token for a fresh access token.
        Same OAuth 2.0 flow as Google Ads -- the refresh token grant
        covers all Google API scopes the user originally authorized.

        Returns:
            Valid access token string

        Raises:
            Exception: If token exchange fails
        """
        import time
        import requests

        # Return cached token if still valid (with 60s buffer)
        if self._access_token and time.time() < self._token_expires_at - 60:
            return self._access_token

        if not self.client_id or not self.client_secret or not self.refresh_token:
            raise Exception(
                "GSC credentials not configured. "
                "Set GOOGLE_ADS_CLIENT_ID, GOOGLE_ADS_CLIENT_SECRET, GOOGLE_ADS_REFRESH_TOKEN"
            )

        try:
            resp = requests.post(
                self.TOKEN_URL,
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "refresh_token": self.refresh_token,
                    "grant_type": "refresh_token",
                },
                timeout=15,
            )

            if resp.status_code != 200:
                error_detail = resp.text[:200]
                raise Exception(f"OAuth token exchange failed ({resp.status_code}): {error_detail}")

            token_data = resp.json()
            self._access_token = token_data.get("access_token")
            expires_in = token_data.get("expires_in", 3600)
            self._token_expires_at = time.time() + expires_in

            if not self._access_token:
                raise Exception("No access_token in OAuth response")

            logger.info("GSC access token obtained successfully")
            return self._access_token

        except requests.RequestException as e:
            raise Exception(f"GSC token exchange network error: {e}")

    # ===================================================================
    # INTERNAL HTTP METHODS
    # ===================================================================

    def _request(self, method: str, path: str, data: dict = None,
                 params: dict = None) -> dict:
        """Make an authenticated API request to GSC."""
        import requests

        access_token = self._get_access_token()

        # URL-encode the site URL for the API path
        encoded_site = quote(self.site_url, safe="")
        url = f"{self.API_BASE}/sites/{encoded_site}/{path.lstrip('/')}"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.request(
                method, url, headers=headers,
                json=data, params=params, timeout=30
            )

            if resp.status_code == 401:
                # Token may have expired mid-request -- force refresh and retry
                self._access_token = None
                self._token_expires_at = 0
                access_token = self._get_access_token()
                headers["Authorization"] = f"Bearer {access_token}"
                resp = requests.request(
                    method, url, headers=headers,
                    json=data, params=params, timeout=30
                )

            if resp.status_code == 403:
                raise Exception(
                    f"GSC access forbidden -- ensure the OAuth account has access to {self.site_url}"
                )

            resp.raise_for_status()
            return resp.json() if resp.content else {}

        except requests.RequestException as e:
            logger.error(f"GSC {method} {path} failed: {e}")
            raise

    def _post(self, path: str, data: dict = None) -> dict:
        return self._request("POST", path, data=data)

    def _get(self, path: str, params: dict = None) -> dict:
        return self._request("GET", path, params=params)

    # ===================================================================
    # 1. SEARCH ANALYTICS
    #    POST /sites/{siteUrl}/searchAnalytics/query
    #    Autonomy: SAFE -- read-only
    # ===================================================================

    def get_search_analytics(self, days: int = 7, dimensions: list = None,
                             row_limit: int = 50,
                             dimension_filter: dict = None) -> list:
        """
        Query search analytics data from GSC.

        POST /sites/{siteUrl}/searchAnalytics/query

        Args:
            days: Number of days to look back (GSC data has ~3 day lag)
            dimensions: List of dimensions to group by.
                        Options: "query", "page", "country", "device", "date"
                        Default: ["query"]
            row_limit: Maximum rows to return (max 25000)
            dimension_filter: Optional filter dict, e.g.:
                {"dimension": "query", "operator": "contains", "expression": "mussel"}

        Returns:
            List of row dicts, each containing:
                - keys: list of dimension values
                - clicks: int
                - impressions: int
                - ctr: float (0-1)
                - position: float (average ranking position)
        """
        if dimensions is None:
            dimensions = ["query"]

        # GSC data has a ~3 day lag, so adjust date range
        end_date = (datetime.utcnow() - timedelta(days=3)).strftime("%Y-%m-%d")
        start_date = (datetime.utcnow() - timedelta(days=days + 3)).strftime("%Y-%m-%d")

        payload = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": dimensions,
            "rowLimit": min(row_limit, 25000),
            "dataState": "final",
        }

        if dimension_filter:
            payload["dimensionFilterGroups"] = [{
                "filters": [dimension_filter]
            }]

        try:
            result = self._post("searchAnalytics/query", data=payload)
            rows = result.get("rows", [])
            logger.info(
                f"GSC analytics: {len(rows)} rows for {start_date} to {end_date} "
                f"(dimensions: {dimensions})"
            )
            return rows

        except Exception as e:
            logger.error(f"GSC search analytics error: {e}")
            return []

    # ===================================================================
    # 2. TOP QUERIES
    #    Convenience method for Beacon SEO agent
    #    Autonomy: SAFE -- read-only
    # ===================================================================

    def get_top_queries(self, days: int = 7, limit: int = 20) -> str:
        """
        Get top search queries formatted for Beacon injection.

        Args:
            days: Lookback period in days
            limit: Number of queries to return

        Returns:
            Formatted string of top queries with metrics
        """
        try:
            rows = self.get_search_analytics(days=days, dimensions=["query"], row_limit=limit)

            if not rows:
                return f"[GSC: No query data for last {days} days]"

            lines = [f"GSC TOP QUERIES (last {days} days)"]

            for row in rows:
                query = row.get("keys", ["?"])[0]
                clicks = int(row.get("clicks", 0))
                impressions = int(row.get("impressions", 0))
                ctr = row.get("ctr", 0) * 100
                position = row.get("position", 0)

                lines.append(
                    f"  - \"{query}\" -- {clicks} clicks, {impressions} imp, "
                    f"CTR {ctr:.1f}%, pos {position:.1f}"
                )

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Top queries error: {e}")
            return f"[GSC top queries error: {str(e)}]"

    # ===================================================================
    # 3. PAGE PERFORMANCE
    #    Autonomy: SAFE -- read-only
    # ===================================================================

    def get_page_performance(self, days: int = 7, limit: int = 20) -> str:
        """
        Get top pages by clicks, formatted for briefing.

        Args:
            days: Lookback period in days
            limit: Number of pages to return

        Returns:
            Formatted string of top pages with metrics
        """
        try:
            rows = self.get_search_analytics(days=days, dimensions=["page"], row_limit=limit)

            if not rows:
                return f"[GSC: No page data for last {days} days]"

            lines = [f"GSC TOP PAGES (last {days} days)"]

            for row in rows:
                page = row.get("keys", ["?"])[0]
                # Strip domain for readability
                page_short = page.replace(self.site_url.rstrip("/"), "")
                if not page_short:
                    page_short = "/"
                clicks = int(row.get("clicks", 0))
                impressions = int(row.get("impressions", 0))
                ctr = row.get("ctr", 0) * 100
                position = row.get("position", 0)

                lines.append(
                    f"  - {page_short} -- {clicks} clicks, {impressions} imp, "
                    f"CTR {ctr:.1f}%, pos {position:.1f}"
                )

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Page performance error: {e}")
            return f"[GSC page performance error: {str(e)}]"

    # ===================================================================
    # 4. BEACON SEO FEEDBACK
    #    Combined intelligence output for Beacon agent
    #    Autonomy: SAFE -- read-only aggregation
    # ===================================================================

    def get_beacon_feedback(self) -> str:
        """
        Combined search intelligence for the Beacon SEO agent.

        Generates a comprehensive report including:
        - Top ranking queries
        - Pages gaining/losing position
        - New queries appearing
        - Recommended keywords to target next

        Returns:
            Formatted multi-section report string
        """
        sections = [
            "=== SEARCH CONSOLE INTELLIGENCE (Beacon SEO Feed) ===",
            "",
        ]

        # --- Top queries (28 days for better data) ---
        try:
            top_queries = self.get_search_analytics(
                days=28, dimensions=["query"], row_limit=30
            )
            if top_queries:
                sections.append("TOP RANKING QUERIES (28 days):")
                for row in top_queries[:15]:
                    query = row.get("keys", ["?"])[0]
                    clicks = int(row.get("clicks", 0))
                    position = row.get("position", 0)
                    ctr = row.get("ctr", 0) * 100
                    sections.append(
                        f"  - \"{query}\" -- pos {position:.1f}, {clicks} clicks, CTR {ctr:.1f}%"
                    )
                sections.append("")
        except Exception as e:
            sections.append(f"[Top queries unavailable: {e}]")
            sections.append("")

        # --- Position movers: compare last 7 days vs previous 7 days ---
        try:
            recent = self.get_search_analytics(days=7, dimensions=["query"], row_limit=100)
            previous = self._get_previous_period(days=7)

            if recent and previous:
                recent_dict = {
                    row["keys"][0]: row for row in recent
                }
                previous_dict = {
                    row["keys"][0]: row for row in previous
                }

                gainers = []
                losers = []
                new_queries = []

                for query, r_data in recent_dict.items():
                    if query in previous_dict:
                        p_data = previous_dict[query]
                        pos_change = p_data.get("position", 0) - r_data.get("position", 0)
                        if pos_change >= 2:
                            gainers.append((query, pos_change, r_data.get("position", 0)))
                        elif pos_change <= -2:
                            losers.append((query, pos_change, r_data.get("position", 0)))
                    else:
                        if int(r_data.get("impressions", 0)) >= 5:
                            new_queries.append((query, r_data.get("position", 0), int(r_data.get("clicks", 0))))

                if gainers:
                    gainers.sort(key=lambda x: x[1], reverse=True)
                    sections.append("POSITION GAINERS (improving):")
                    for query, change, pos in gainers[:10]:
                        sections.append(
                            f"  - \"{query}\" -- improved {change:.1f} positions (now pos {pos:.1f})"
                        )
                    sections.append("")

                if losers:
                    losers.sort(key=lambda x: x[1])
                    sections.append("POSITION LOSERS (declining):")
                    for query, change, pos in losers[:10]:
                        sections.append(
                            f"  - \"{query}\" -- dropped {abs(change):.1f} positions (now pos {pos:.1f})"
                        )
                    sections.append("")

                if new_queries:
                    new_queries.sort(key=lambda x: x[2], reverse=True)
                    sections.append("NEW QUERIES APPEARING:")
                    for query, pos, clicks in new_queries[:10]:
                        sections.append(
                            f"  - \"{query}\" -- pos {pos:.1f}, {clicks} clicks"
                        )
                    sections.append("")

        except Exception as e:
            sections.append(f"[Position tracking unavailable: {e}]")
            sections.append("")

        # --- Quick wins: high impressions, low CTR, position 5-20 ---
        try:
            if top_queries:
                quick_wins = [
                    row for row in top_queries
                    if (5 <= row.get("position", 0) <= 20
                        and int(row.get("impressions", 0)) >= 20
                        and row.get("ctr", 0) < 0.05)
                ]
                if quick_wins:
                    sections.append("QUICK WIN OPPORTUNITIES (high imp, low CTR, pos 5-20):")
                    for row in quick_wins[:10]:
                        query = row.get("keys", ["?"])[0]
                        position = row.get("position", 0)
                        impressions = int(row.get("impressions", 0))
                        ctr = row.get("ctr", 0) * 100
                        sections.append(
                            f"  - \"{query}\" -- pos {position:.1f}, {impressions} imp, "
                            f"CTR only {ctr:.1f}% (optimize title/meta)"
                        )
                    sections.append("")
        except Exception as e:
            sections.append(f"[Quick wins analysis unavailable: {e}]")
            sections.append("")

        # --- Top pages ---
        try:
            sections.append(self.get_page_performance(days=28, limit=10))
        except Exception as e:
            sections.append(f"[Page performance unavailable: {e}]")

        return "\n".join(sections)

    def _get_previous_period(self, days: int = 7) -> list:
        """
        Get search analytics for the period BEFORE the most recent period.
        Used for comparison / trend detection.

        Args:
            days: Period length in days

        Returns:
            List of analytics rows for the previous period
        """
        # Previous period: offset by (days + 3) to account for GSC data lag
        end_date = (datetime.utcnow() - timedelta(days=days + 3)).strftime("%Y-%m-%d")
        start_date = (datetime.utcnow() - timedelta(days=(days * 2) + 3)).strftime("%Y-%m-%d")

        payload = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": ["query"],
            "rowLimit": 100,
            "dataState": "final",
        }

        try:
            result = self._post("searchAnalytics/query", data=payload)
            return result.get("rows", [])
        except Exception as e:
            logger.warning(f"Could not fetch previous period data: {e}")
            return []

    # ===================================================================
    # 5. BRIEFING FORMAT
    #    Summary for Oracle/PREP morning briefings
    #    Autonomy: SAFE -- read-only
    # ===================================================================

    def format_for_briefing(self) -> str:
        """
        Concise search performance summary for Oracle/PREP morning briefings.
        Uses bullet points, no tables.

        Returns:
            Formatted text suitable for Telegram messages
        """
        try:
            if not self.available:
                return "GSC: Not configured"

            lines = ["Search Console (last 7 days):"]

            # Get aggregate totals
            rows = self.get_search_analytics(days=7, dimensions=["query"], row_limit=100)
            if not rows:
                return "GSC: No data available (check property access)"

            total_clicks = sum(int(r.get("clicks", 0)) for r in rows)
            total_impressions = sum(int(r.get("impressions", 0)) for r in rows)
            avg_ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0

            # Weighted average position
            weighted_pos = sum(
                r.get("position", 0) * int(r.get("impressions", 0)) for r in rows
            )
            avg_position = weighted_pos / total_impressions if total_impressions > 0 else 0

            lines.append(f"  - Total clicks: {total_clicks:,}")
            lines.append(f"  - Total impressions: {total_impressions:,}")
            lines.append(f"  - Average CTR: {avg_ctr:.1f}%")
            lines.append(f"  - Average position: {avg_position:.1f}")

            # Top 5 queries
            lines.append("  - Top queries:")
            for row in rows[:5]:
                query = row.get("keys", ["?"])[0]
                clicks = int(row.get("clicks", 0))
                position = row.get("position", 0)
                lines.append(f"    - \"{query}\" ({clicks} clicks, pos {position:.1f})")

            return "\n".join(lines)

        except Exception as e:
            return f"GSC: Unavailable ({str(e)})"


# ===================================================================
# CLI
# ===================================================================

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    client = GSCClient()

    if len(sys.argv) < 2:
        print("Google Search Console Client")
        print()
        print("Usage:")
        print("  python -m core.gsc_client queries [days] [limit]   Top search queries")
        print("  python -m core.gsc_client pages [days] [limit]     Top pages by clicks")
        print("  python -m core.gsc_client beacon                   Full Beacon SEO feedback")
        print("  python -m core.gsc_client briefing                 Morning briefing summary")
        print("  python -m core.gsc_client analytics [days]         Raw analytics data")
        print()
        print("Environment:")
        print(f"  GOOGLE_ADS_CLIENT_ID: {'set' if os.environ.get('GOOGLE_ADS_CLIENT_ID') else 'not set'}")
        print(f"  GOOGLE_ADS_CLIENT_SECRET: {'set' if os.environ.get('GOOGLE_ADS_CLIENT_SECRET') else 'not set'}")
        print(f"  GOOGLE_ADS_REFRESH_TOKEN: {'set' if os.environ.get('GOOGLE_ADS_REFRESH_TOKEN') else 'not set'}")
        print(f"  GSC_SITE_URL: {os.environ.get('GSC_SITE_URL', 'https://www.deepbluehealth.co.nz/ (default)')}")
        print(f"  Available: {client.available}")
        sys.exit(0)

    cmd = sys.argv[1]

    if not client.available:
        print("GSC credentials not configured.")
        print("Set GOOGLE_ADS_CLIENT_ID, GOOGLE_ADS_CLIENT_SECRET, GOOGLE_ADS_REFRESH_TOKEN")
        print("(Same credentials as Google Ads -- GSC uses the same OAuth grant)")
        sys.exit(1)

    if cmd == "queries":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        print(client.get_top_queries(days=days, limit=limit))

    elif cmd == "pages":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        print(client.get_page_performance(days=days, limit=limit))

    elif cmd == "beacon":
        print(client.get_beacon_feedback())

    elif cmd == "briefing":
        print(client.format_for_briefing())

    elif cmd == "analytics":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        rows = client.get_search_analytics(days=days, dimensions=["query"], row_limit=50)
        if not rows:
            print("No analytics data returned")
        else:
            print(f"Search Analytics ({len(rows)} rows, last {days} days):")
            for row in rows:
                query = row.get("keys", ["?"])[0]
                clicks = int(row.get("clicks", 0))
                impressions = int(row.get("impressions", 0))
                ctr = row.get("ctr", 0) * 100
                position = row.get("position", 0)
                print(
                    f"  - \"{query}\" -- {clicks} clicks, {impressions} imp, "
                    f"CTR {ctr:.1f}%, pos {position:.1f}"
                )

    else:
        print(f"Unknown command: {cmd}")
        print("Run without arguments to see usage")
        sys.exit(1)
