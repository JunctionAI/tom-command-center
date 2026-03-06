#!/usr/bin/env python3
"""
Meta Ads Write-Back Client -- Autonomous write operations to Meta Marketing API.

Extends the existing read-only data_fetcher.py with write capabilities.
Uses Meta Graph API v21.0 / Marketing API v21.0.

Rate Limits:
  - Score-based rolling 1-hour window per ad account
  - Read calls = 1 point, Write calls = 3 points
  - Heavy operations (insights with breakdowns) cost more points
  - 429 response when limit exceeded
  - Apply for elevated access via Ads Management Standard Access

Authentication:
  - System User Access Token (long-lived) or User Access Token
  - Token needs permissions: ads_management, ads_read, business_management
  - Pass as ?access_token= query param or Authorization header

What can be done WITHOUT human approval:
  - Pause ad sets/campaigns (protective action)
  - Read any performance data
  - Create/manage custom audiences from customer lists

What NEEDS human approval:
  - Resume paused campaigns (spending money)
  - Increase budgets (spending money)
  - Create new ad creatives (brand-facing content)
  - Update targeting (strategic decision)
  - Create automated rules above spend thresholds
  - Duplicate campaigns (creates new spend)

IMPORTANT NOTES:
  - Starting v21.0, new ad sets cannot use legacy campaign objectives
  - v22.0 requires customer list audience certification
  - Budget flexibility allows up to 75% overspend on high-performing days
"""

import os
import json
import time
import hashlib
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class MetaAdsWriter:
    """
    Write-back client for Meta Marketing API v21.0.

    Follows the same auth pattern as data_fetcher.py.
    All write operations include retry logic and rate limit handling.
    """

    API_VERSION = "v21.0"
    BASE_URL = f"https://graph.facebook.com/{API_VERSION}"

    def __init__(self):
        self.access_token = os.environ.get("META_ACCESS_TOKEN")
        self.ad_account_id = os.environ.get("META_AD_ACCOUNT_ID")

    @property
    def available(self) -> bool:
        return bool(self.access_token and self.ad_account_id)

    @property
    def account_path(self) -> str:
        """Returns the properly formatted ad account path."""
        account_id = self.ad_account_id
        if not account_id.startswith("act_"):
            account_id = f"act_{account_id}"
        return account_id

    # --- Internal HTTP Methods with Retry Logic ---

    def _request(self, method: str, path: str, data: dict = None,
                 params: dict = None, files: dict = None,
                 max_retries: int = 3) -> dict:
        """
        Make an HTTP request with retry logic and rate limit handling.
        Meta uses standard REST (not JSON:API).
        """
        import requests

        url = f"{self.BASE_URL}/{path}"

        # Always include access token in params
        if params is None:
            params = {}
        params["access_token"] = self.access_token

        for attempt in range(max_retries):
            try:
                if files:
                    # Multipart upload (for ad creatives)
                    resp = requests.request(
                        method, url, data=data, params=params,
                        files=files, timeout=60
                    )
                elif method.upper() in ("POST", "PUT", "PATCH") and data:
                    resp = requests.request(
                        method, url, params=params,
                        data=data, timeout=30
                    )
                else:
                    if data:
                        params.update(data)
                    resp = requests.request(
                        method, url, params=params, timeout=30
                    )

                # Check for rate limiting
                response_data = resp.json() if resp.content else {}

                if resp.status_code == 429 or (
                    response_data.get("error", {}).get("code") in (4, 17, 32)
                ):
                    # Error codes: 4 = API too many calls, 17 = User too many calls,
                    # 32 = Page-level throttle
                    wait_time = min(2 ** (attempt + 2), 300)
                    logger.warning(
                        f"Meta rate limited. Waiting {wait_time}s (attempt {attempt + 1})"
                    )
                    time.sleep(wait_time)
                    continue

                if "error" in response_data:
                    error = response_data["error"]
                    error_msg = f"Meta API error {error.get('code')}: {error.get('message', '')}"
                    logger.error(error_msg)
                    if attempt == max_retries - 1:
                        raise Exception(error_msg)
                    time.sleep(2 ** attempt)
                    continue

                return response_data

            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"Meta {method} {path} failed after {max_retries} attempts: {e}")
                    raise
                wait_time = 2 ** attempt
                logger.warning(f"Meta request failed, retrying in {wait_time}s: {e}")
                time.sleep(wait_time)

        return {}

    def _get(self, path: str, params: dict = None) -> dict:
        return self._request("GET", path, params=params)

    def _post(self, path: str, data: dict = None, files: dict = None) -> dict:
        return self._request("POST", path, data=data, files=files)

    # ===================================================================
    # 1. PAUSE / RESUME CAMPAIGNS AND AD SETS
    #    Endpoint: POST /{campaign_id} or POST /{adset_id}
    #    Params: status=PAUSED or status=ACTIVE
    #    Autonomy: PAUSE = SAFE (protective), RESUME = NEEDS APPROVAL
    # ===================================================================

    def get_campaigns(self, status_filter: str = None) -> list:
        """
        Get all campaigns in the ad account.

        GET /act_{ad_account_id}/campaigns

        Args:
            status_filter: Optional filter: "ACTIVE", "PAUSED", "ARCHIVED"

        Returns:
            List of campaign objects
        """
        params = {
            "fields": "id,name,status,objective,daily_budget,lifetime_budget,"
                       "budget_remaining,effective_status,created_time",
            "limit": 100,
        }
        if status_filter:
            params["effective_status"] = json.dumps([status_filter])

        result = self._get(f"{self.account_path}/campaigns", params=params)
        return result.get("data", [])

    def get_ad_sets(self, campaign_id: str = None,
                     status_filter: str = None) -> list:
        """
        Get ad sets, optionally filtered by campaign.

        Args:
            campaign_id: Optional campaign ID to filter by
            status_filter: Optional status filter

        Returns:
            List of ad set objects
        """
        path = f"{campaign_id}/adsets" if campaign_id else f"{self.account_path}/adsets"
        params = {
            "fields": "id,name,status,daily_budget,lifetime_budget,"
                       "targeting,optimization_goal,bid_strategy,"
                       "effective_status,campaign_id",
            "limit": 100,
        }
        if status_filter:
            params["effective_status"] = json.dumps([status_filter])

        result = self._get(path, params=params)
        return result.get("data", [])

    def pause_campaign(self, campaign_id: str, reason: str = "") -> dict:
        """
        Pause a campaign.

        POST /{campaign_id}?status=PAUSED

        Args:
            campaign_id: Meta campaign ID
            reason: Reason for pausing (logged internally)

        Returns:
            {"success": true} on success
        """
        result = self._post(campaign_id, data={"status": "PAUSED"})
        logger.info(f"Paused campaign {campaign_id}. Reason: {reason}")
        return result

    def resume_campaign(self, campaign_id: str, reason: str = "") -> dict:
        """
        Resume (unpause) a campaign. NEEDS HUMAN APPROVAL.

        POST /{campaign_id}?status=ACTIVE

        Args:
            campaign_id: Meta campaign ID
            reason: Reason for resuming

        Returns:
            {"success": true} on success
        """
        result = self._post(campaign_id, data={"status": "ACTIVE"})
        logger.info(f"Resumed campaign {campaign_id}. Reason: {reason}")
        return result

    def pause_ad_set(self, adset_id: str, reason: str = "") -> dict:
        """
        Pause an ad set.

        POST /{adset_id}?status=PAUSED

        Args:
            adset_id: Meta ad set ID
            reason: Reason for pausing

        Returns:
            {"success": true} on success
        """
        result = self._post(adset_id, data={"status": "PAUSED"})
        logger.info(f"Paused ad set {adset_id}. Reason: {reason}")
        return result

    def resume_ad_set(self, adset_id: str, reason: str = "") -> dict:
        """
        Resume an ad set. NEEDS HUMAN APPROVAL.

        POST /{adset_id}?status=ACTIVE
        """
        result = self._post(adset_id, data={"status": "ACTIVE"})
        logger.info(f"Resumed ad set {adset_id}. Reason: {reason}")
        return result

    # ===================================================================
    # 2. UPDATE CAMPAIGN / AD SET BUDGETS
    #    Endpoint: POST /{campaign_id} or POST /{adset_id}
    #    Autonomy: NEEDS APPROVAL -- involves money
    # ===================================================================

    def update_campaign_budget(self, campaign_id: str,
                                 daily_budget: float = None,
                                 lifetime_budget: float = None) -> dict:
        """
        Update campaign budget.

        POST /{campaign_id}

        NOTE: Budgets are in the account's currency in cents (for USD)
        or smallest unit. For NZD, $50 = "5000".

        Args:
            campaign_id: Campaign ID
            daily_budget: New daily budget in cents (e.g. 5000 = $50 NZD)
            lifetime_budget: New lifetime budget in cents

        Returns:
            {"success": true} on success
        """
        data = {}
        if daily_budget is not None:
            data["daily_budget"] = str(int(daily_budget))
        if lifetime_budget is not None:
            data["lifetime_budget"] = str(int(lifetime_budget))

        result = self._post(campaign_id, data=data)
        logger.info(f"Updated budget for campaign {campaign_id}: {data}")
        return result

    def update_adset_budget(self, adset_id: str,
                              daily_budget: float = None,
                              lifetime_budget: float = None) -> dict:
        """
        Update ad set budget.

        POST /{adset_id}

        Args:
            adset_id: Ad set ID
            daily_budget: New daily budget in cents
            lifetime_budget: New lifetime budget in cents
        """
        data = {}
        if daily_budget is not None:
            data["daily_budget"] = str(int(daily_budget))
        if lifetime_budget is not None:
            data["lifetime_budget"] = str(int(lifetime_budget))

        result = self._post(adset_id, data=data)
        logger.info(f"Updated budget for ad set {adset_id}: {data}")
        return result

    # ===================================================================
    # 3. CREATE AD CREATIVES
    #    Endpoint: POST /act_{ad_account_id}/adcreatives
    #    Autonomy: NEEDS APPROVAL -- brand-facing content
    # ===================================================================

    def create_ad_creative(self, name: str, page_id: str,
                             message: str = "",
                             link: str = "",
                             image_hash: str = None,
                             image_url: str = None,
                             call_to_action_type: str = "SHOP_NOW",
                             link_caption: str = "",
                             description: str = "") -> dict:
        """
        Create an ad creative (single image/link).

        POST /act_{ad_account_id}/adcreatives

        Args:
            name: Creative name (internal)
            page_id: Facebook Page ID to run ads from
            message: Ad copy text
            link: Destination URL
            image_hash: Hash of previously uploaded image
            image_url: URL of image (Meta will fetch it)
            call_to_action_type: CTA button type. Options:
                SHOP_NOW, LEARN_MORE, SIGN_UP, SUBSCRIBE, GET_OFFER,
                BOOK_TRAVEL, CONTACT_US, DOWNLOAD, ORDER_NOW
            link_caption: Optional link caption
            description: Optional link description

        Returns:
            Created creative object with ID
        """
        link_data = {
            "link": link,
            "call_to_action": {
                "type": call_to_action_type,
                "value": {"link": link}
            }
        }

        if image_hash:
            link_data["image_hash"] = image_hash
        elif image_url:
            link_data["picture"] = image_url

        if link_caption:
            link_data["caption"] = link_caption
        if description:
            link_data["description"] = description

        creative_data = {
            "name": name,
            "object_story_spec": json.dumps({
                "page_id": page_id,
                "link_data": {
                    **link_data,
                    "message": message,
                }
            }),
        }

        result = self._post(f"{self.account_path}/adcreatives", data=creative_data)
        logger.info(f"Created ad creative '{name}' (ID: {result.get('id', '?')})")
        return result

    def upload_ad_image(self, image_path: str) -> dict:
        """
        Upload an image for use in ad creatives.

        POST /act_{ad_account_id}/adimages

        Args:
            image_path: Local path to image file

        Returns:
            Dict with image hash and other metadata
        """
        with open(image_path, "rb") as f:
            result = self._post(
                f"{self.account_path}/adimages",
                files={"filename": f}
            )
        images = result.get("images", {})
        logger.info(f"Uploaded ad image: {image_path}")
        return images

    # ===================================================================
    # 4. UPDATE TARGETING
    #    Endpoint: POST /{adset_id}
    #    Autonomy: NEEDS APPROVAL -- strategic decision
    # ===================================================================

    def update_adset_targeting(self, adset_id: str,
                                 targeting: dict) -> dict:
        """
        Update targeting on an ad set.

        POST /{adset_id}

        Args:
            adset_id: Ad set ID
            targeting: Targeting spec dict. Example:
                {
                    "geo_locations": {
                        "countries": ["NZ", "AU"],
                        "location_types": ["home"]
                    },
                    "age_min": 35,
                    "age_max": 65,
                    "genders": [0],  # 0=all, 1=male, 2=female
                    "interests": [{"id": "123", "name": "Health supplements"}],
                    "custom_audiences": [{"id": "audience_id"}],
                    "excluded_custom_audiences": [{"id": "exclude_id"}],
                }

        Returns:
            {"success": true} on success
        """
        result = self._post(adset_id, data={
            "targeting": json.dumps(targeting)
        })
        logger.info(f"Updated targeting for ad set {adset_id}")
        return result

    # ===================================================================
    # 5. CUSTOM AUDIENCES
    #    Endpoint: POST /act_{ad_account_id}/customaudiences
    #    Endpoint: POST /{custom_audience_id}/users
    #    Autonomy: SAFE for creation from existing data
    # ===================================================================

    def create_custom_audience(self, name: str, description: str = "",
                                 subtype: str = "CUSTOM") -> dict:
        """
        Create a custom audience container.

        POST /act_{ad_account_id}/customaudiences

        Args:
            name: Audience name
            description: Audience description
            subtype: "CUSTOM" (customer list), "WEBSITE" (pixel),
                     "ENGAGEMENT" (interaction), "LOOKALIKE"

        Returns:
            Created audience object with ID
        """
        result = self._post(f"{self.account_path}/customaudiences", data={
            "name": name,
            "description": description,
            "subtype": subtype,
            "customer_file_source": "USER_PROVIDED_ONLY",
        })
        logger.info(f"Created custom audience '{name}' (ID: {result.get('id', '?')})")
        return result

    def add_users_to_custom_audience(self, audience_id: str,
                                       emails: list = None,
                                       phone_numbers: list = None) -> dict:
        """
        Add users to a custom audience from customer data.

        POST /{custom_audience_id}/users

        Data is hashed (SHA256) before sending to Meta.
        Meta matches against their user database.

        Args:
            audience_id: Custom audience ID
            emails: List of email addresses (will be hashed)
            phone_numbers: List of phone numbers (will be hashed)

        Returns:
            Audience user operation result
        """
        schema = []
        data_rows = []

        if emails:
            schema.append("EMAIL")
            for email in emails:
                hashed = hashlib.sha256(email.lower().strip().encode()).hexdigest()
                data_rows.append([hashed])

        if phone_numbers:
            if "EMAIL" not in schema:
                schema.append("PHONE")
            else:
                schema.append("PHONE")
            for i, phone in enumerate(phone_numbers):
                # Normalize: remove spaces, dashes
                normalized = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
                hashed = hashlib.sha256(normalized.encode()).hexdigest()
                if i < len(data_rows):
                    data_rows[i].append(hashed)
                else:
                    data_rows.append([""] * (len(schema) - 1) + [hashed])

        payload = {
            "payload": json.dumps({
                "schema": schema,
                "data": data_rows,
            })
        }

        result = self._post(f"{audience_id}/users", data=payload)
        count = len(emails or []) + len(phone_numbers or [])
        logger.info(f"Added {count} users to custom audience {audience_id}")
        return result

    def create_lookalike_audience(self, source_audience_id: str,
                                    name: str, country: str = "NZ",
                                    ratio: float = 0.01) -> dict:
        """
        Create a lookalike audience from an existing custom audience.

        POST /act_{ad_account_id}/customaudiences

        Args:
            source_audience_id: Source custom audience ID
            name: Name for the lookalike audience
            country: Target country code (e.g. "NZ", "AU")
            ratio: Audience size ratio (0.01 = top 1%, 0.10 = top 10%)

        Returns:
            Created lookalike audience object
        """
        result = self._post(f"{self.account_path}/customaudiences", data={
            "name": name,
            "subtype": "LOOKALIKE",
            "origin_audience_id": source_audience_id,
            "lookalike_spec": json.dumps({
                "type": "similarity",
                "country": country,
                "ratio": ratio,
            }),
        })
        logger.info(f"Created lookalike audience '{name}' from source {source_audience_id}")
        return result

    # ===================================================================
    # 6. DUPLICATE CAMPAIGNS / AD SETS
    #    Endpoint: POST /{campaign_id}/copies or POST /{adset_id}/copies
    #    Autonomy: NEEDS APPROVAL -- creates new ad spend
    # ===================================================================

    def duplicate_campaign(self, campaign_id: str,
                             new_name: str = None,
                             status: str = "PAUSED") -> dict:
        """
        Duplicate a campaign (creates copy in PAUSED state by default).

        POST /{campaign_id}/copies

        Args:
            campaign_id: Source campaign ID
            new_name: Name for the copy (default: "[Copy] Original Name")
            status: Status of the copy ("PAUSED" recommended)

        Returns:
            Object with copied_campaign_id
        """
        data = {"status_option": status}
        if new_name:
            data["rename_option"] = json.dumps({"rename_suffix": f" - {new_name}"})

        result = self._post(f"{campaign_id}/copies", data=data)
        logger.info(f"Duplicated campaign {campaign_id} (new status: {status})")
        return result

    def duplicate_adset(self, adset_id: str, campaign_id: str,
                          new_name: str = None,
                          status: str = "PAUSED") -> dict:
        """
        Duplicate an ad set into a campaign.

        POST /{adset_id}/copies

        Args:
            adset_id: Source ad set ID
            campaign_id: Destination campaign ID
            new_name: Optional new name suffix
            status: Status of the copy

        Returns:
            Object with copied_adset_id
        """
        data = {
            "campaign_id": campaign_id,
            "status_option": status,
        }
        if new_name:
            data["rename_option"] = json.dumps({"rename_suffix": f" - {new_name}"})

        result = self._post(f"{adset_id}/copies", data=data)
        logger.info(f"Duplicated ad set {adset_id} into campaign {campaign_id}")
        return result

    # ===================================================================
    # 7. AUTOMATED RULES (ROAS Floors, Spend Caps)
    #    Endpoint: POST /act_{ad_account_id}/adrules_library
    #    Autonomy: NEEDS APPROVAL for creation, then runs autonomously
    # ===================================================================

    def create_automated_rule(self, name: str, evaluation_spec: dict,
                                execution_spec: dict,
                                schedule_spec: dict = None,
                                entity_type: str = "ADSET") -> dict:
        """
        Create an automated rule for the ad account.

        POST /act_{ad_account_id}/adrules_library

        Args:
            name: Rule name
            evaluation_spec: Conditions to evaluate. Example:
                {
                    "evaluation_type": "TRIGGER",
                    "filters": [
                        {
                            "field": "purchase_roas",
                            "value": "2.0",
                            "operator": "LESS_THAN",
                        },
                        {
                            "field": "spent",
                            "value": "1000",  # cents
                            "operator": "GREATER_THAN",
                        }
                    ]
                }
            execution_spec: What to do when conditions met. Example:
                {
                    "execution_type": "PAUSE",
                }
                OR for budget changes:
                {
                    "execution_type": "CHANGE_BUDGET",
                    "execution_options": [{
                        "field": "daily_budget",
                        "value": "5000",
                        "operator": "DECREASE_BY",
                    }]
                }
            schedule_spec: When to evaluate. Example:
                {
                    "schedule_type": "SEMI_HOURLY"
                }
            entity_type: "CAMPAIGN", "ADSET", or "AD"

        Returns:
            Created rule object
        """
        data = {
            "name": name,
            "evaluation_spec": json.dumps(evaluation_spec),
            "execution_spec": json.dumps(execution_spec),
            "entity_type": entity_type,
        }
        if schedule_spec:
            data["schedule_spec"] = json.dumps(schedule_spec)

        result = self._post(f"{self.account_path}/adrules_library", data=data)
        logger.info(f"Created automated rule '{name}' (ID: {result.get('id', '?')})")
        return result

    def create_roas_floor_rule(self, min_roas: float = 2.0,
                                  min_spend_cents: int = 2000,
                                  lookback_hours: int = 24) -> dict:
        """
        Convenience: Create a ROAS floor rule that pauses underperforming ad sets.

        If ROAS < min_roas AND spend > min_spend, pause the ad set.

        Args:
            min_roas: Minimum acceptable ROAS (default 2.0x)
            min_spend_cents: Minimum spend before rule applies (default $20 NZD)
            lookback_hours: Hours to look back for metrics

        Returns:
            Created rule object
        """
        return self.create_automated_rule(
            name=f"Auto-pause: ROAS < {min_roas}x (min spend ${min_spend_cents / 100})",
            evaluation_spec={
                "evaluation_type": "TRIGGER",
                "filters": [
                    {
                        "field": "purchase_roas",
                        "value": str(min_roas),
                        "operator": "LESS_THAN",
                    },
                    {
                        "field": "spent",
                        "value": str(min_spend_cents),
                        "operator": "GREATER_THAN",
                    },
                ],
            },
            execution_spec={
                "execution_type": "PAUSE",
            },
            schedule_spec={
                "schedule_type": "SEMI_HOURLY",
            },
            entity_type="ADSET",
        )

    def create_spend_cap_rule(self, daily_spend_cap_cents: int = 10000) -> dict:
        """
        Convenience: Create a daily spend cap rule.

        Pauses ad sets when they exceed a daily spend threshold.

        Args:
            daily_spend_cap_cents: Max daily spend in cents (default $100 NZD)

        Returns:
            Created rule object
        """
        return self.create_automated_rule(
            name=f"Auto-pause: Daily spend > ${daily_spend_cap_cents / 100}",
            evaluation_spec={
                "evaluation_type": "TRIGGER",
                "filters": [
                    {
                        "field": "spent",
                        "value": str(daily_spend_cap_cents),
                        "operator": "GREATER_THAN",
                    },
                ],
            },
            execution_spec={
                "execution_type": "PAUSE",
            },
            schedule_spec={
                "schedule_type": "SEMI_HOURLY",
            },
            entity_type="ADSET",
        )

    # ===================================================================
    # CONVENIENCE: ROAS-BASED CAMPAIGN MANAGEMENT
    # ===================================================================

    def auto_pause_low_roas(self, min_roas: float = 2.0,
                              min_spend: float = 20.0,
                              days: int = 1) -> dict:
        """
        Check all active ad sets and pause those with ROAS below threshold.

        This is a manual check (not an automated rule). Call it from a
        scheduled task for regular monitoring.

        Args:
            min_roas: Minimum acceptable ROAS
            min_spend: Minimum spend (in dollars, not cents) before considering
            days: Days of data to evaluate

        Returns:
            Dict with "paused" and "kept" lists
        """
        import requests
        from datetime import timedelta

        since = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
        until = datetime.utcnow().strftime("%Y-%m-%d")

        # Get active ad sets with insights
        params = {
            "fields": "adset_name,adset_id,spend,purchase_roas,actions",
            "level": "adset",
            "time_range": json.dumps({"since": since, "until": until}),
            "filtering": json.dumps([{
                "field": "adset.effective_status",
                "operator": "IN",
                "value": ["ACTIVE"]
            }]),
            "limit": 100,
        }

        result = self._get(f"{self.account_path}/insights", params=params)
        adsets = result.get("data", [])

        paused = []
        kept = []

        for adset in adsets:
            spend = float(adset.get("spend", 0))
            roas_list = adset.get("purchase_roas", [])
            roas = float(roas_list[0].get("value", 0)) if roas_list else 0
            adset_id = adset.get("adset_id", "")
            adset_name = adset.get("adset_name", "Unknown")

            if spend >= min_spend and roas < min_roas and adset_id:
                try:
                    self.pause_ad_set(
                        adset_id,
                        reason=f"ROAS {roas:.2f}x < {min_roas}x floor (${spend:.2f} spend)"
                    )
                    paused.append({
                        "id": adset_id, "name": adset_name,
                        "spend": spend, "roas": roas
                    })
                except Exception as e:
                    logger.error(f"Failed to pause ad set {adset_id}: {e}")
            else:
                kept.append({
                    "id": adset_id, "name": adset_name,
                    "spend": spend, "roas": roas
                })

        if paused:
            names = ", ".join(a["name"] for a in paused)
            logger.info(f"Auto-paused {len(paused)} ad sets below ROAS floor: {names}")

        return {"paused": paused, "kept": kept}

    # ===================================================================
    # 8. CREATE CAMPAIGNS, AD SETS, AND ADS
    #    Endpoint: POST /act_{id}/campaigns, /act_{id}/adsets, /act_{id}/ads
    #    Autonomy: NEEDS APPROVAL -- creates new ad structure + spend
    # ===================================================================

    def create_campaign(self, name: str, objective: str = "OUTCOME_SALES",
                        daily_budget_cents: int = None,
                        status: str = "PAUSED",
                        special_ad_categories: list = None,
                        campaign_budget_optimization: bool = True) -> dict:
        """
        Create a new campaign.

        POST /act_{ad_account_id}/campaigns

        Args:
            name: Campaign name
            objective: Campaign objective. v21.0 options:
                OUTCOME_AWARENESS, OUTCOME_ENGAGEMENT, OUTCOME_LEADS,
                OUTCOME_SALES, OUTCOME_TRAFFIC, OUTCOME_APP_PROMOTION
            daily_budget_cents: Daily budget in cents (e.g. 5500 = $55 NZD).
                Required when campaign_budget_optimization=True.
            status: Initial status ("PAUSED" or "ACTIVE")
            special_ad_categories: List of special categories (e.g. ["HOUSING"])
                or empty list for none.
            campaign_budget_optimization: Enable Advantage Campaign Budget (CBO).

        Returns:
            Created campaign object with 'id' field
        """
        data = {
            "name": name,
            "objective": objective,
            "status": status,
            "buying_type": "AUCTION",
            "is_campaign_budget_optimization": "true" if campaign_budget_optimization else "false",
            "special_ad_categories": json.dumps(special_ad_categories or []),
        }
        if daily_budget_cents is not None:
            data["daily_budget"] = str(int(daily_budget_cents))

        result = self._post(f"{self.account_path}/campaigns", data=data)
        logger.info(f"Created campaign '{name}' (ID: {result.get('id', '?')}, "
                     f"objective: {objective}, budget: {daily_budget_cents}c, "
                     f"CBO: {campaign_budget_optimization})")
        return result

    def create_adset(self, name: str, campaign_id: str,
                     targeting: dict,
                     optimization_goal: str = "OFFSITE_CONVERSIONS",
                     billing_event: str = "IMPRESSIONS",
                     bid_strategy: str = "LOWEST_COST_WITHOUT_CAP",
                     promoted_object: dict = None,
                     status: str = "PAUSED",
                     daily_budget_cents: int = None,
                     attribution_spec: list = None,
                     targeting_optimization: str = "EXPANSION_ALL") -> dict:
        """
        Create a new ad set within a campaign.

        POST /act_{ad_account_id}/adsets

        Args:
            name: Ad set name
            campaign_id: Parent campaign ID
            targeting: Targeting spec dict. Example:
                {
                    "geo_locations": {"countries": ["NZ"]},
                    "age_min": 25,
                    "age_max": 65,
                }
            optimization_goal: "OFFSITE_CONVERSIONS", "LINK_CLICKS",
                "IMPRESSIONS", "REACH", "VALUE", etc.
            billing_event: "IMPRESSIONS" (standard) or "LINK_CLICKS"
            bid_strategy: "LOWEST_COST_WITHOUT_CAP" (default),
                "LOWEST_COST_WITH_BID_CAP", "COST_CAP"
            promoted_object: Conversion tracking. Example:
                {"pixel_id": "123", "custom_event_type": "Purchase"}
            status: Initial status
            daily_budget_cents: Ad set budget in cents (optional with CBO)
            attribution_spec: Attribution windows. Example:
                [{"event_type": "CLICK_THROUGH", "window_days": 7},
                 {"event_type": "VIEW_THROUGH", "window_days": 1}]
            targeting_optimization: "EXPANSION_ALL" for Advantage+ Audience,
                "NONE" for strict targeting.

        Returns:
            Created ad set object with 'id' field
        """
        data = {
            "name": name,
            "campaign_id": campaign_id,
            "optimization_goal": optimization_goal,
            "billing_event": billing_event,
            "bid_strategy": bid_strategy,
            "status": status,
            "targeting": json.dumps(targeting),
            "targeting_optimization": targeting_optimization,
        }

        if promoted_object:
            data["promoted_object"] = json.dumps(promoted_object)
        if daily_budget_cents is not None:
            data["daily_budget"] = str(int(daily_budget_cents))
        if attribution_spec:
            data["attribution_spec"] = json.dumps(attribution_spec)

        result = self._post(f"{self.account_path}/adsets", data=data)
        logger.info(f"Created ad set '{name}' in campaign {campaign_id} "
                     f"(ID: {result.get('id', '?')})")
        return result

    def create_ad(self, name: str, adset_id: str,
                  creative_id: str = None,
                  creative_spec: dict = None,
                  status: str = "PAUSED",
                  tracking_specs: list = None) -> dict:
        """
        Create a new ad within an ad set.

        POST /act_{ad_account_id}/ads

        Provide either creative_id (existing creative) or creative_spec
        (inline creative definition).

        Args:
            name: Ad name
            adset_id: Parent ad set ID
            creative_id: ID of an existing ad creative
            creative_spec: Inline creative spec. Built by the caller using
                create_ad_creative() first, or passed inline as:
                {"creative_id": "123"}
            status: Initial status
            tracking_specs: Tracking config for conversions. Example:
                [{"action.type": ["offsite_conversion"],
                  "fb_pixel": ["PIXEL_ID"]}]

        Returns:
            Created ad object with 'id' field
        """
        data = {
            "name": name,
            "adset_id": adset_id,
            "status": status,
        }

        if creative_id:
            data["creative"] = json.dumps({"creative_id": creative_id})
        elif creative_spec:
            data["creative"] = json.dumps(creative_spec)

        if tracking_specs:
            data["tracking_specs"] = json.dumps(tracking_specs)

        result = self._post(f"{self.account_path}/ads", data=data)
        logger.info(f"Created ad '{name}' in ad set {adset_id} "
                     f"(ID: {result.get('id', '?')})")
        return result


# --- CLI ---

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    writer = MetaAdsWriter()
    if not writer.available:
        print("META_ACCESS_TOKEN and META_AD_ACCOUNT_ID required")
        sys.exit(1)

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python meta_ads_writer.py campaigns")
        print("  python meta_ads_writer.py adsets [campaign_id]")
        print("  python meta_ads_writer.py pause-campaign <campaign_id>")
        print("  python meta_ads_writer.py pause-adset <adset_id>")
        print("  python meta_ads_writer.py check-roas [min_roas] [min_spend]")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "campaigns":
        for c in writer.get_campaigns():
            status = c.get("effective_status", c.get("status", "?"))
            budget = c.get("daily_budget", "N/A")
            print(f"  [{status}] {c.get('name', '?')} (ID: {c['id']}) budget: {budget}")

    elif cmd == "adsets":
        campaign_id = sys.argv[2] if len(sys.argv) > 2 else None
        for a in writer.get_ad_sets(campaign_id):
            status = a.get("effective_status", a.get("status", "?"))
            budget = a.get("daily_budget", "N/A")
            print(f"  [{status}] {a.get('name', '?')} (ID: {a['id']}) budget: {budget}")

    elif cmd == "pause-campaign" and len(sys.argv) > 2:
        result = writer.pause_campaign(sys.argv[2], "CLI manual pause")
        print(f"Paused: {result}")

    elif cmd == "pause-adset" and len(sys.argv) > 2:
        result = writer.pause_ad_set(sys.argv[2], "CLI manual pause")
        print(f"Paused: {result}")

    elif cmd == "check-roas":
        min_roas = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
        min_spend = float(sys.argv[3]) if len(sys.argv) > 3 else 20.0
        result = writer.auto_pause_low_roas(min_roas, min_spend)
        print(f"\nPaused {len(result['paused'])} ad sets:")
        for a in result["paused"]:
            print(f"  {a['name']}: ROAS {a['roas']:.2f}x, ${a['spend']:.2f} spend")
        print(f"\nKept {len(result['kept'])} ad sets:")
        for a in result["kept"]:
            print(f"  {a['name']}: ROAS {a['roas']:.2f}x, ${a['spend']:.2f} spend")

    else:
        print(f"Unknown command: {cmd}")
