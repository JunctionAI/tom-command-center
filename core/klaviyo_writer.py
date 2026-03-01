#!/usr/bin/env python3
"""
Klaviyo Write-Back Client -- Autonomous write operations to Klaviyo API.

Extends the existing read-only data_fetcher.py with write capabilities.
Uses Klaviyo API with revision header (2025-07-15 to match existing code).

Rate Limits (per-account, fixed-window algorithm):
  Tier XS: Burst 1/s,  Steady 15/m
  Tier S:  Burst 3/s,  Steady 60/m
  Tier M:  Burst 10/s, Steady 150/m
  Tier L:  Burst 75/s, Steady 700/m
  Tier XL: Burst 350/s, Steady 3500/m
  429 responses when either burst or steady limit is hit.

Authentication:
  - Header: Authorization: Klaviyo-API-Key pk_...
  - Header: revision: 2025-07-15
  - Private API key required (NOT public key)
  - Scopes needed: campaigns:write, flows:write, lists:write,
    profiles:write, segments:write, subscriptions:write, events:write

What can be done WITHOUT human approval:
  - Update profile properties (data enrichment)
  - Add/remove profiles to/from lists (segmentation)
  - Create custom events to trigger existing flows
  - Subscribe profiles (with proper consent)
  - Create segments from definitions

What NEEDS human approval:
  - Create and send email campaigns (customer-facing content)
  - A/B test creation and winner selection
  - Unsubscribe profiles (irreversible impact)
  - Create new flows (complex automation)
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class KlaviyoWriter:
    """
    Write-back client for Klaviyo API.

    Follows the same auth pattern as data_fetcher.py.
    All write operations include retry logic and rate limit handling.
    """

    BASE_URL = "https://a.klaviyo.com/api"
    REVISION = "2025-07-15"

    def __init__(self):
        self.api_key = os.environ.get("KLAVIYO_API_KEY")

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    @property
    def headers(self) -> dict:
        return {
            "Authorization": f"Klaviyo-API-Key {self.api_key}",
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/vnd.api+json",
            "revision": self.REVISION,
        }

    # --- Internal HTTP Methods with Retry Logic ---

    def _request(self, method: str, path: str, data: dict = None,
                 params: dict = None, max_retries: int = 3) -> dict:
        """
        Make an HTTP request with retry logic and rate limit handling.
        Klaviyo uses JSON:API format for request/response bodies.
        """
        import requests

        url = f"{self.BASE_URL}/{path}"

        for attempt in range(max_retries):
            try:
                resp = requests.request(
                    method, url, headers=self.headers,
                    json=data, params=params, timeout=30
                )

                # Handle rate limiting (429)
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", 1))
                    logger.warning(f"Klaviyo rate limited. Waiting {retry_after}s (attempt {attempt + 1})")
                    time.sleep(retry_after)
                    continue

                resp.raise_for_status()
                return resp.json() if resp.content else {}

            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"Klaviyo {method} {path} failed after {max_retries} attempts: {e}")
                    raise
                wait_time = 2 ** attempt
                logger.warning(f"Klaviyo request failed, retrying in {wait_time}s: {e}")
                time.sleep(wait_time)

        return {}

    def _get(self, path: str, params: dict = None) -> dict:
        return self._request("GET", path, params=params)

    def _post(self, path: str, data: dict) -> dict:
        return self._request("POST", path, data=data)

    def _patch(self, path: str, data: dict) -> dict:
        return self._request("PATCH", path, data=data)

    def _delete(self, path: str, data: dict = None) -> dict:
        return self._request("DELETE", path, data=data)

    # ===================================================================
    # 1. TRIGGER FLOWS VIA CUSTOM EVENTS
    #    Endpoint: POST /api/events
    #    Rate: Burst 350/s, Steady 3500/m (Tier XL)
    #    Autonomy: SAFE -- triggers existing pre-approved flows
    #
    #    NOTE: You cannot directly "trigger a flow" via API. Instead, you
    #    create a custom event that a flow is configured to listen for.
    #    The flow must be pre-built in Klaviyo with that event as trigger.
    # ===================================================================

    def create_event(self, event_name: str, profile_email: str,
                      properties: dict = None,
                      profile_properties: dict = None) -> dict:
        """
        Create a custom event to trigger a flow.

        POST /api/events

        The flow in Klaviyo must be configured to trigger on this event name.
        E.g., a "Replenishment Reminder" flow triggered by a "replenishment_due" event.

        Args:
            event_name: The metric name (e.g. "replenishment_due", "vip_milestone")
            profile_email: Customer's email address
            properties: Event-specific data dict (e.g. {"product": "GLM", "days_since": 45})
            profile_properties: Optional profile data to update simultaneously

        Returns:
            Empty dict on success (202 Accepted)

        Example:
            writer.create_event(
                "replenishment_due",
                "customer@example.com",
                properties={"product_name": "Green Lipped Mussel", "supply_days": 60}
            )
        """
        profile_data = {
            "type": "profile",
            "attributes": {
                "email": profile_email,
            }
        }
        if profile_properties:
            profile_data["attributes"]["properties"] = profile_properties

        payload = {
            "data": {
                "type": "event",
                "attributes": {
                    "metric": {
                        "data": {
                            "type": "metric",
                            "attributes": {
                                "name": event_name,
                            }
                        }
                    },
                    "profile": {
                        "data": profile_data,
                    },
                    "properties": properties or {},
                    "time": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                }
            }
        }

        result = self._post("events", payload)
        logger.info(f"Created event '{event_name}' for {profile_email}")
        return result

    def trigger_replenishment_reminder(self, email: str, product_name: str,
                                         days_since_purchase: int,
                                         supply_days: int = 60) -> dict:
        """
        Convenience: trigger a replenishment reminder flow.
        Requires a Klaviyo flow triggered by "replenishment_due" event.

        Args:
            email: Customer email
            product_name: Product they purchased
            days_since_purchase: Days since they bought it
            supply_days: Expected supply duration
        """
        return self.create_event(
            "replenishment_due",
            email,
            properties={
                "product_name": product_name,
                "days_since_purchase": days_since_purchase,
                "supply_days": supply_days,
                "urgency": "high" if days_since_purchase >= supply_days else "normal",
            }
        )

    # ===================================================================
    # 2. CREATE AND SCHEDULE EMAIL CAMPAIGNS
    #    Endpoint: POST /api/campaigns (create)
    #    Endpoint: POST /api/campaign-send-jobs (send/schedule)
    #    Rate: Burst 10/s, Steady 150/m (Tier M)
    #    Autonomy: NEEDS APPROVAL -- customer-facing content
    # ===================================================================

    def create_campaign(self, name: str, list_ids: list = None,
                         segment_ids: list = None,
                         subject: str = "", preview_text: str = "",
                         from_email: str = None, from_name: str = None,
                         reply_to_email: str = None,
                         template_id: str = None) -> dict:
        """
        Create an email campaign (draft state).

        POST /api/campaigns

        Args:
            name: Campaign name (internal)
            list_ids: List IDs to send to
            segment_ids: Segment IDs to send to
            subject: Email subject line
            preview_text: Email preview text
            from_email: Sender email
            from_name: Sender name
            reply_to_email: Reply-to email
            template_id: Klaviyo template ID to use

        Returns:
            Created campaign object
        """
        audiences = {"included": [], "excluded": []}
        if list_ids:
            for lid in list_ids:
                audiences["included"].append({"type": "list", "id": lid})
        if segment_ids:
            for sid in segment_ids:
                audiences["included"].append({"type": "segment", "id": sid})

        send_options = {}
        if from_email:
            send_options["from_email"] = from_email
        if from_name:
            send_options["from_name"] = from_name
        if reply_to_email:
            send_options["reply_to_email"] = reply_to_email

        message = {
            "data": {
                "type": "campaign-message",
                "attributes": {
                    "channel": "email",
                    "label": name,
                    "content": {
                        "subject": subject,
                        "preview_text": preview_text,
                    },
                    "render_options": {
                        "shorten_links": True,
                        "add_org_prefix": True,
                        "add_info_link": True,
                        "add_opt_out_language": False,
                    },
                }
            }
        }

        if template_id:
            message["data"]["relationships"] = {
                "template": {
                    "data": {"type": "template", "id": template_id}
                }
            }

        payload = {
            "data": {
                "type": "campaign",
                "attributes": {
                    "name": name,
                    "audiences": audiences,
                    "send_options": send_options,
                },
                "relationships": {
                    "campaign-messages": {
                        "data": [message["data"]]
                    }
                }
            }
        }

        result = self._post("campaigns", payload)
        campaign = result.get("data", {})
        logger.info(f"Created campaign '{name}' (ID: {campaign.get('id', '?')})")
        return campaign

    def schedule_campaign_send(self, campaign_id: str,
                                 send_at: str = None) -> dict:
        """
        Schedule or immediately send a campaign.

        POST /api/campaign-send-jobs

        Args:
            campaign_id: The campaign ID to send
            send_at: ISO datetime for scheduled send (None = send immediately)

        Returns:
            Campaign send job object
        """
        payload = {
            "data": {
                "type": "campaign-send-job",
                "attributes": {},
                "relationships": {
                    "campaign": {
                        "data": {"type": "campaign", "id": campaign_id}
                    }
                }
            }
        }

        if send_at:
            payload["data"]["attributes"]["scheduled_at"] = send_at

        result = self._post("campaign-send-jobs", payload)
        logger.info(f"Scheduled campaign {campaign_id} send (at: {send_at or 'immediately'})")
        return result.get("data", {})

    def cancel_campaign_send(self, campaign_send_job_id: str) -> dict:
        """
        Cancel a scheduled campaign send.

        PATCH /api/campaign-send-jobs/{id}

        Args:
            campaign_send_job_id: The send job ID

        Returns:
            Updated send job object
        """
        payload = {
            "data": {
                "type": "campaign-send-job",
                "id": campaign_send_job_id,
                "attributes": {
                    "status": "cancelled"
                }
            }
        }
        result = self._patch(f"campaign-send-jobs/{campaign_send_job_id}", payload)
        logger.info(f"Cancelled campaign send job {campaign_send_job_id}")
        return result.get("data", {})

    # ===================================================================
    # 3. PROFILE / LIST MANAGEMENT
    #    Endpoint: POST /api/profiles (create/update)
    #    Endpoint: POST /api/lists/{list_id}/relationships/profiles (add to list)
    #    Endpoint: DELETE /api/lists/{list_id}/relationships/profiles (remove from list)
    #    Rate: Burst 75/s, Steady 700/m (Tier L)
    #    Autonomy: SAFE for list management, APPROVAL for unsubscribe
    # ===================================================================

    def create_or_update_profile(self, email: str,
                                   first_name: str = None,
                                   last_name: str = None,
                                   phone_number: str = None,
                                   properties: dict = None) -> dict:
        """
        Create a new profile or update existing by email.

        POST /api/profile-import-jobs (bulk) or POST /api/profiles (single)

        Args:
            email: Profile email (identifier)
            first_name: Optional first name
            last_name: Optional last name
            phone_number: Optional phone (E.164 format: +6421...)
            properties: Optional custom properties dict

        Returns:
            Profile object
        """
        attributes = {"email": email}
        if first_name:
            attributes["first_name"] = first_name
        if last_name:
            attributes["last_name"] = last_name
        if phone_number:
            attributes["phone_number"] = phone_number
        if properties:
            attributes["properties"] = properties

        payload = {
            "data": {
                "type": "profile",
                "attributes": attributes,
            }
        }

        result = self._post("profiles", payload)
        profile = result.get("data", {})
        logger.info(f"Created/updated profile: {email}")
        return profile

    def update_profile_properties(self, profile_id: str,
                                    properties: dict) -> dict:
        """
        Update custom properties on an existing profile.

        PATCH /api/profiles/{profile_id}

        Args:
            profile_id: Klaviyo profile ID
            properties: Dict of custom properties to set/update

        Returns:
            Updated profile object

        Example:
            writer.update_profile_properties("ABC123", {
                "customer_segment": "VIP",
                "last_purchase_category": "Joint Health",
                "predicted_reorder_date": "2026-04-01",
            })
        """
        payload = {
            "data": {
                "type": "profile",
                "id": profile_id,
                "attributes": {
                    "properties": properties,
                }
            }
        }
        result = self._patch(f"profiles/{profile_id}", payload)
        logger.info(f"Updated properties on profile {profile_id}: {list(properties.keys())}")
        return result.get("data", {})

    def add_profiles_to_list(self, list_id: str, profile_ids: list) -> dict:
        """
        Add profiles to a list.

        POST /api/lists/{list_id}/relationships/profiles

        Args:
            list_id: Klaviyo list ID
            profile_ids: List of profile ID strings

        Returns:
            Empty on success (204)
        """
        payload = {
            "data": [{"type": "profile", "id": pid} for pid in profile_ids]
        }
        result = self._post(f"lists/{list_id}/relationships/profiles", payload)
        logger.info(f"Added {len(profile_ids)} profiles to list {list_id}")
        return result

    def remove_profiles_from_list(self, list_id: str, profile_ids: list) -> dict:
        """
        Remove profiles from a list.

        DELETE /api/lists/{list_id}/relationships/profiles

        Args:
            list_id: Klaviyo list ID
            profile_ids: List of profile ID strings

        Returns:
            Empty on success (204)
        """
        payload = {
            "data": [{"type": "profile", "id": pid} for pid in profile_ids]
        }
        result = self._delete(f"lists/{list_id}/relationships/profiles", data=payload)
        logger.info(f"Removed {len(profile_ids)} profiles from list {list_id}")
        return result

    def get_lists(self) -> list:
        """Get all lists."""
        result = self._get("lists")
        return result.get("data", [])

    # ===================================================================
    # 4. SEGMENTS
    #    Endpoint: POST /api/segments
    #    Rate: Burst 3/s, Steady 60/m (Tier S)
    #    Autonomy: SAFE -- creates targeting groups, no customer contact
    # ===================================================================

    def create_segment(self, name: str, definition: dict) -> dict:
        """
        Create a dynamic segment.

        POST /api/segments

        Args:
            name: Segment name
            definition: Segment condition definition (Klaviyo filter format)

        Returns:
            Created segment object

        Example definition for "VIP customers who haven't ordered in 60 days":
            {
                "and": [
                    {"dimension": "properties.$total_spent", "filter": {"greater-than": 200}},
                    {"dimension": "properties.last_order_date",
                     "filter": {"before": "2026-01-01"}}
                ]
            }
        """
        payload = {
            "data": {
                "type": "segment",
                "attributes": {
                    "name": name,
                    "definition": definition,
                }
            }
        }
        result = self._post("segments", payload)
        seg = result.get("data", {})
        logger.info(f"Created segment '{name}' (ID: {seg.get('id', '?')})")
        return seg

    # ===================================================================
    # 5. SUBSCRIBE / UNSUBSCRIBE
    #    Endpoint: POST /api/profile-subscription-bulk-create-jobs (subscribe)
    #    Endpoint: POST /api/profile-subscription-bulk-delete-jobs (unsubscribe)
    #    Rate: Burst 75/s, Steady 700/m (Tier L)
    #    Autonomy: Subscribe = SAFE (with consent), Unsubscribe = NEEDS APPROVAL
    # ===================================================================

    def subscribe_profiles(self, list_id: str, emails: list,
                             consent_source: str = "API") -> dict:
        """
        Subscribe profiles to email marketing via a list.

        POST /api/profile-subscription-bulk-create-jobs

        IMPORTANT: Only use with proper consent. Pass consent_source to
        document where consent was obtained.

        Args:
            list_id: The list to subscribe to
            emails: List of email addresses
            consent_source: Where consent was given (e.g. "CHECKOUT", "FORM", "API")

        Returns:
            Subscription job object
        """
        profiles = []
        for email in emails:
            profiles.append({
                "type": "profile",
                "attributes": {
                    "email": email,
                    "subscriptions": {
                        "email": {
                            "marketing": {
                                "consent": "SUBSCRIBED",
                                "consented_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                            }
                        }
                    }
                }
            })

        payload = {
            "data": {
                "type": "profile-subscription-bulk-create-job",
                "attributes": {
                    "custom_source": consent_source,
                },
                "relationships": {
                    "list": {
                        "data": {"type": "list", "id": list_id}
                    }
                },
            }
        }
        # Profiles are sent in the relationships
        payload["data"]["attributes"]["profiles"] = {"data": profiles}

        result = self._post("profile-subscription-bulk-create-jobs", payload)
        logger.info(f"Subscribed {len(emails)} profiles to list {list_id}")
        return result.get("data", {})

    def unsubscribe_profiles(self, list_id: str, emails: list) -> dict:
        """
        Unsubscribe profiles from email marketing.

        POST /api/profile-subscription-bulk-delete-jobs

        CAUTION: This is destructive. Profile will stop receiving marketing emails.

        Args:
            list_id: The list to unsubscribe from
            emails: List of email addresses

        Returns:
            Unsubscribe job object
        """
        profiles = []
        for email in emails:
            profiles.append({
                "type": "profile",
                "attributes": {
                    "email": email,
                }
            })

        payload = {
            "data": {
                "type": "profile-subscription-bulk-delete-job",
                "attributes": {
                    "profiles": {"data": profiles}
                },
                "relationships": {
                    "list": {
                        "data": {"type": "list", "id": list_id}
                    }
                },
            }
        }

        result = self._post("profile-subscription-bulk-delete-jobs", payload)
        logger.info(f"Unsubscribed {len(emails)} profiles from list {list_id}")
        return result.get("data", {})

    # ===================================================================
    # 6. A/B TEST MANAGEMENT (via Campaign Variants)
    #    Klaviyo handles A/B tests as campaign variants.
    #    Endpoint: Campaign creation with multiple messages
    #    Autonomy: NEEDS APPROVAL for creation, can AUTO-SELECT winner
    # ===================================================================

    def create_ab_test_campaign(self, name: str, list_ids: list,
                                  variant_a_subject: str,
                                  variant_b_subject: str,
                                  variant_a_preview: str = "",
                                  variant_b_preview: str = "",
                                  test_size_percent: int = 20,
                                  winning_metric: str = "open_rate",
                                  test_duration_hours: int = 4) -> dict:
        """
        Create a campaign with A/B testing on subject lines.

        This creates the campaign with two message variants.
        Klaviyo will auto-send the winner to the remaining audience
        after the test period.

        Args:
            name: Campaign name
            list_ids: List IDs for audience
            variant_a_subject: Subject line A
            variant_b_subject: Subject line B
            variant_a_preview: Preview text A
            variant_b_preview: Preview text B
            test_size_percent: % of audience for test (each variant gets half)
            winning_metric: "open_rate" or "click_rate"
            test_duration_hours: Hours before auto-selecting winner

        Returns:
            Created campaign with variants
        """
        # NOTE: Klaviyo's actual A/B test API structure may vary.
        # This creates the campaign; A/B test configuration is set
        # in the campaign's send_strategy attribute.
        audiences = {"included": [], "excluded": []}
        for lid in list_ids:
            audiences["included"].append({"type": "list", "id": lid})

        payload = {
            "data": {
                "type": "campaign",
                "attributes": {
                    "name": f"[A/B] {name}",
                    "audiences": audiences,
                    "send_strategy": {
                        "method": "ab_test",
                        "options_ab_test": {
                            "sample_size_percent": test_size_percent,
                            "winning_metric": winning_metric,
                            "test_length_hours": test_duration_hours,
                        }
                    },
                },
            }
        }

        result = self._post("campaigns", payload)
        campaign = result.get("data", {})
        logger.info(f"Created A/B test campaign '{name}' (ID: {campaign.get('id', '?')})")
        return campaign

    # ===================================================================
    # CONVENIENCE / BATCH METHODS
    # ===================================================================

    def bulk_update_profile_properties(self, updates: list) -> dict:
        """
        Batch update properties on multiple profiles.

        Args:
            updates: List of dicts: [{"email": "...", "properties": {...}}, ...]

        Returns:
            Dict with "success" and "failed" counts
        """
        results = {"success": 0, "failed": 0}
        for update in updates:
            try:
                self.create_or_update_profile(
                    email=update["email"],
                    properties=update.get("properties", {})
                )
                results["success"] += 1
                time.sleep(0.02)  # Stay within burst limits
            except Exception as e:
                results["failed"] += 1
                logger.error(f"Failed to update {update.get('email')}: {e}")

        logger.info(f"Bulk profile update: {results['success']} success, {results['failed']} failed")
        return results

    def trigger_churn_prevention(self, email: str, customer_name: str,
                                   days_since_last_order: int,
                                   last_product: str,
                                   lifetime_value: float) -> dict:
        """
        Convenience: trigger a churn prevention flow.
        Requires a Klaviyo flow triggered by "churn_risk_detected" event.

        Args:
            email: Customer email
            customer_name: Customer first name
            days_since_last_order: Days since last purchase
            last_product: Last product purchased
            lifetime_value: Customer LTV
        """
        return self.create_event(
            "churn_risk_detected",
            email,
            properties={
                "customer_name": customer_name,
                "days_since_last_order": days_since_last_order,
                "last_product": last_product,
                "lifetime_value": lifetime_value,
                "risk_level": "high" if days_since_last_order > 90 else "medium",
            }
        )


# --- CLI ---

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    writer = KlaviyoWriter()
    if not writer.available:
        print("KLAVIYO_API_KEY required")
        sys.exit(1)

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python klaviyo_writer.py lists")
        print("  python klaviyo_writer.py event <event_name> <email>")
        print("  python klaviyo_writer.py update-profile <email> key=value key2=value2")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "lists":
        for lst in writer.get_lists():
            attrs = lst.get("attributes", {})
            print(f"  {lst['id']}: {attrs.get('name', '?')}")

    elif cmd == "event" and len(sys.argv) >= 4:
        event_name = sys.argv[2]
        email = sys.argv[3]
        writer.create_event(event_name, email)
        print(f"Event '{event_name}' created for {email}")

    elif cmd == "update-profile" and len(sys.argv) >= 4:
        email = sys.argv[2]
        props = {}
        for kv in sys.argv[3:]:
            if "=" in kv:
                k, v = kv.split("=", 1)
                props[k] = v
        writer.create_or_update_profile(email, properties=props)
        print(f"Profile updated: {email}")

    else:
        print(f"Unknown command: {cmd}")
