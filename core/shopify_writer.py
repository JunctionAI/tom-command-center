#!/usr/bin/env python3
"""
Shopify Write-Back Client -- Autonomous write operations to Shopify Admin REST API.

Extends the existing read-only data_fetcher.py with write capabilities.
Uses Shopify Admin REST API 2025-01.

Rate Limits:
  - 40 requests per app per store per minute (leaky bucket: 2 req/s refill)
  - Shopify Plus: 400 requests per minute (20 req/s refill)
  - Response header X-Shopify-Shop-Api-Call-Limit shows usage
  - 429 response includes Retry-After header

Authentication:
  - X-Shopify-Access-Token header with private app token (shpat_...)
  - Token needs write scopes: write_customers, write_orders, write_products,
    write_inventory, write_draft_orders, write_price_rules

What can be done WITHOUT human approval:
  - Tag/untag customers (low risk, reversible)
  - Add order notes/tags (informational, reversible)
  - Update product metafields (data enrichment)
  - Adjust inventory levels (if tracking automation)
  - Read any data

What NEEDS human approval:
  - Create draft orders (involves money)
  - Create discount codes (involves money)
  - Trigger fulfillment updates (affects customer experience)
  - Price changes (business-critical)
  - Delete anything
"""

import os
import json
import time
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class ShopifyWriter:
    """
    Write-back client for Shopify Admin REST API 2025-01.

    Follows the same pattern as data_fetcher.py for authentication.
    All write operations include retry logic and rate limit handling.
    """

    API_VERSION = "2025-01"

    def __init__(self):
        self.store_url = os.environ.get("SHOPIFY_STORE_URL")  # e.g. "deepbluehealth.myshopify.com"
        self.token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
        self._last_call_limit = None

    @property
    def available(self) -> bool:
        return bool(self.store_url and self.token)

    @property
    def base_url(self) -> str:
        return f"https://{self.store_url}/admin/api/{self.API_VERSION}"

    @property
    def headers(self) -> dict:
        return {
            "X-Shopify-Access-Token": self.token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # --- Internal HTTP Methods with Retry Logic ---

    def _request(self, method: str, path: str, data: dict = None,
                 params: dict = None, max_retries: int = 3) -> dict:
        """
        Make an HTTP request with retry logic and rate limit handling.
        Returns parsed JSON response or raises exception.
        """
        import requests

        url = f"{self.base_url}/{path}"

        for attempt in range(max_retries):
            try:
                resp = requests.request(
                    method, url, headers=self.headers,
                    json=data, params=params, timeout=30
                )

                # Track rate limit usage
                limit_header = resp.headers.get("X-Shopify-Shop-Api-Call-Limit", "")
                if limit_header:
                    self._last_call_limit = limit_header
                    used, total = limit_header.split("/")
                    if int(used) > int(total) * 0.8:
                        logger.warning(f"Shopify rate limit approaching: {limit_header}")

                # Handle rate limiting
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", 2))
                    logger.warning(f"Shopify rate limited. Waiting {retry_after}s (attempt {attempt + 1})")
                    time.sleep(retry_after)
                    continue

                resp.raise_for_status()
                return resp.json() if resp.content else {}

            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"Shopify {method} {path} failed after {max_retries} attempts: {e}")
                    raise
                wait_time = 2 ** attempt
                logger.warning(f"Shopify request failed, retrying in {wait_time}s: {e}")
                time.sleep(wait_time)

        return {}

    def _get(self, path: str, params: dict = None) -> dict:
        return self._request("GET", path, params=params)

    def _post(self, path: str, data: dict) -> dict:
        return self._request("POST", path, data=data)

    def _put(self, path: str, data: dict) -> dict:
        return self._request("PUT", path, data=data)

    def _delete(self, path: str) -> dict:
        return self._request("DELETE", path)

    # ===================================================================
    # 1. CUSTOMER TAG MANAGEMENT
    #    Endpoint: PUT /admin/api/2025-01/customers/{customer_id}.json
    #    Scope: write_customers
    #    Autonomy: SAFE -- low risk, fully reversible
    # ===================================================================

    def get_customer(self, customer_id: str) -> dict:
        """Fetch a single customer by ID."""
        result = self._get(f"customers/{customer_id}.json")
        return result.get("customer", {})

    def get_customer_tags(self, customer_id: str) -> list:
        """Get current tags for a customer."""
        customer = self.get_customer(customer_id)
        tags_str = customer.get("tags", "")
        return [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []

    def add_customer_tags(self, customer_id: str, new_tags: list) -> dict:
        """
        Add tags to a customer (preserves existing tags).

        PUT /admin/api/2025-01/customers/{customer_id}.json
        Body: {"customer": {"id": customer_id, "tags": "tag1, tag2, tag3"}}

        Args:
            customer_id: Shopify customer ID
            new_tags: List of tag strings to add

        Returns:
            Updated customer object
        """
        existing = self.get_customer_tags(customer_id)
        combined = list(set(existing + new_tags))
        tags_str = ", ".join(combined)

        result = self._put(f"customers/{customer_id}.json", {
            "customer": {"id": int(customer_id), "tags": tags_str}
        })
        logger.info(f"Added tags {new_tags} to customer {customer_id}")
        return result.get("customer", {})

    def remove_customer_tags(self, customer_id: str, tags_to_remove: list) -> dict:
        """
        Remove specific tags from a customer.

        Args:
            customer_id: Shopify customer ID
            tags_to_remove: List of tag strings to remove

        Returns:
            Updated customer object
        """
        existing = self.get_customer_tags(customer_id)
        remaining = [t for t in existing if t not in tags_to_remove]
        tags_str = ", ".join(remaining)

        result = self._put(f"customers/{customer_id}.json", {
            "customer": {"id": int(customer_id), "tags": tags_str}
        })
        logger.info(f"Removed tags {tags_to_remove} from customer {customer_id}")
        return result.get("customer", {})

    def set_customer_tags(self, customer_id: str, tags: list) -> dict:
        """
        Replace all customer tags (overwrites existing).

        Args:
            customer_id: Shopify customer ID
            tags: Complete list of tags to set

        Returns:
            Updated customer object
        """
        tags_str = ", ".join(tags)
        result = self._put(f"customers/{customer_id}.json", {
            "customer": {"id": int(customer_id), "tags": tags_str}
        })
        logger.info(f"Set tags for customer {customer_id}: {tags}")
        return result.get("customer", {})

    # ===================================================================
    # 2. DRAFT ORDERS
    #    Endpoint: POST /admin/api/2025-01/draft_orders.json
    #    Scope: write_draft_orders
    #    Autonomy: NEEDS APPROVAL -- involves money
    # ===================================================================

    def create_draft_order(self, line_items: list, customer_id: str = None,
                           note: str = "", tags: str = "",
                           discount: dict = None,
                           shipping_address: dict = None) -> dict:
        """
        Create a draft order.

        POST /admin/api/2025-01/draft_orders.json

        Args:
            line_items: List of dicts with keys:
                - variant_id (int): Shopify variant ID
                - quantity (int): Number of units
                - OR title (str) + price (str): For custom line items
            customer_id: Optional Shopify customer ID to associate
            note: Optional order note
            tags: Optional comma-separated tags
            discount: Optional dict with keys:
                - description (str): e.g. "VIP Discount"
                - value_type (str): "percentage" or "fixed_amount"
                - value (str): e.g. "10.0"
                - amount (str): Fixed discount amount
            shipping_address: Optional dict with standard address fields

        Returns:
            Created draft order object

        Example:
            writer.create_draft_order(
                line_items=[{"variant_id": 12345, "quantity": 2}],
                customer_id="67890",
                note="Auto-created for VIP replenishment",
                discount={"description": "VIP 10%", "value_type": "percentage", "value": "10.0"}
            )
        """
        draft_order = {"line_items": line_items}

        if customer_id:
            draft_order["customer"] = {"id": int(customer_id)}
        if note:
            draft_order["note"] = note
        if tags:
            draft_order["tags"] = tags
        if discount:
            draft_order["applied_discount"] = discount
        if shipping_address:
            draft_order["shipping_address"] = shipping_address

        result = self._post("draft_orders.json", {"draft_order": draft_order})
        draft = result.get("draft_order", {})
        logger.info(f"Created draft order {draft.get('name', '?')} -- ${draft.get('total_price', 0)}")
        return draft

    def send_draft_order_invoice(self, draft_order_id: str,
                                  to: str = None, subject: str = None,
                                  custom_message: str = None) -> dict:
        """
        Send invoice for a draft order to the customer.

        POST /admin/api/2025-01/draft_orders/{draft_order_id}/send_invoice.json

        Args:
            draft_order_id: The draft order ID
            to: Optional email override (defaults to customer email)
            subject: Optional custom subject line
            custom_message: Optional message body

        Returns:
            Draft order invoice object
        """
        invoice = {}
        if to:
            invoice["to"] = to
        if subject:
            invoice["subject"] = subject
        if custom_message:
            invoice["custom_message"] = custom_message

        result = self._post(
            f"draft_orders/{draft_order_id}/send_invoice.json",
            {"draft_order_invoice": invoice}
        )
        logger.info(f"Sent invoice for draft order {draft_order_id}")
        return result.get("draft_order_invoice", {})

    def complete_draft_order(self, draft_order_id: str,
                              payment_pending: bool = False) -> dict:
        """
        Complete a draft order (convert to real order).

        PUT /admin/api/2025-01/draft_orders/{draft_order_id}/complete.json

        Args:
            draft_order_id: The draft order ID
            payment_pending: If True, marks as pending payment

        Returns:
            Completed draft order object
        """
        result = self._put(
            f"draft_orders/{draft_order_id}/complete.json",
            {"payment_pending": payment_pending}
        )
        logger.info(f"Completed draft order {draft_order_id}")
        return result.get("draft_order", {})

    # ===================================================================
    # 3. INVENTORY MANAGEMENT
    #    Endpoint: POST /admin/api/2025-01/inventory_levels/set.json
    #    Endpoint: POST /admin/api/2025-01/inventory_levels/adjust.json
    #    Scope: write_inventory
    #    Autonomy: SAFE for reads/adjustments, APPROVAL for absolute sets
    # ===================================================================

    def get_inventory_level(self, inventory_item_id: str,
                             location_id: str = None) -> dict:
        """
        Get inventory level for an item at a location.

        GET /admin/api/2025-01/inventory_levels.json

        Args:
            inventory_item_id: The inventory item ID
            location_id: Optional location ID (defaults to primary)

        Returns:
            Inventory level object
        """
        params = {"inventory_item_ids": inventory_item_id}
        if location_id:
            params["location_ids"] = location_id
        result = self._get("inventory_levels.json", params=params)
        levels = result.get("inventory_levels", [])
        return levels[0] if levels else {}

    def adjust_inventory(self, inventory_item_id: str, location_id: str,
                          adjustment: int, reason: str = "") -> dict:
        """
        Adjust inventory by a relative amount (+/-).

        POST /admin/api/2025-01/inventory_levels/adjust.json

        Args:
            inventory_item_id: The inventory item ID
            location_id: Location to adjust at
            adjustment: Positive to add, negative to subtract
            reason: Reason for adjustment (logged)

        Returns:
            Updated inventory level

        Example:
            writer.adjust_inventory("12345", "67890", -5, "Damaged stock removed")
        """
        result = self._post("inventory_levels/adjust.json", {
            "inventory_item_id": int(inventory_item_id),
            "location_id": int(location_id),
            "available_adjustment": adjustment,
        })
        logger.info(
            f"Adjusted inventory item {inventory_item_id} by {adjustment:+d} "
            f"at location {location_id}. Reason: {reason}"
        )
        return result.get("inventory_level", {})

    def set_inventory(self, inventory_item_id: str, location_id: str,
                       available: int) -> dict:
        """
        Set inventory to an absolute value.

        POST /admin/api/2025-01/inventory_levels/set.json

        CAUTION: This overwrites the current level. Prefer adjust_inventory
        for incremental changes.

        Args:
            inventory_item_id: The inventory item ID
            location_id: Location to set at
            available: Absolute quantity to set

        Returns:
            Updated inventory level
        """
        result = self._post("inventory_levels/set.json", {
            "inventory_item_id": int(inventory_item_id),
            "location_id": int(location_id),
            "available": available,
        })
        logger.info(f"Set inventory item {inventory_item_id} to {available} at location {location_id}")
        return result.get("inventory_level", {})

    def get_locations(self) -> list:
        """Get all inventory locations for the store."""
        result = self._get("locations.json")
        return result.get("locations", [])

    # ===================================================================
    # 4. ORDER NOTES & TAGS
    #    Endpoint: PUT /admin/api/2025-01/orders/{order_id}.json
    #    Scope: write_orders
    #    Autonomy: SAFE -- informational, reversible
    # ===================================================================

    def add_order_note(self, order_id: str, note: str) -> dict:
        """
        Add or update the note on an order.

        PUT /admin/api/2025-01/orders/{order_id}.json

        Args:
            order_id: Shopify order ID
            note: Note text to set (replaces existing note)

        Returns:
            Updated order object
        """
        result = self._put(f"orders/{order_id}.json", {
            "order": {"id": int(order_id), "note": note}
        })
        logger.info(f"Added note to order {order_id}")
        return result.get("order", {})

    def add_order_tags(self, order_id: str, new_tags: list) -> dict:
        """
        Add tags to an order (preserves existing tags).

        PUT /admin/api/2025-01/orders/{order_id}.json

        Args:
            order_id: Shopify order ID
            new_tags: List of tag strings to add

        Returns:
            Updated order object
        """
        # First get existing tags
        order = self._get(f"orders/{order_id}.json").get("order", {})
        existing_tags = order.get("tags", "")
        existing_list = [t.strip() for t in existing_tags.split(",") if t.strip()] if existing_tags else []
        combined = list(set(existing_list + new_tags))
        tags_str = ", ".join(combined)

        result = self._put(f"orders/{order_id}.json", {
            "order": {"id": int(order_id), "tags": tags_str}
        })
        logger.info(f"Added tags {new_tags} to order {order_id}")
        return result.get("order", {})

    # ===================================================================
    # 5. DISCOUNT CODES (via Price Rules)
    #    Endpoint: POST /admin/api/2025-01/price_rules.json
    #    Endpoint: POST /admin/api/2025-01/price_rules/{id}/discount_codes.json
    #    Scope: write_price_rules
    #    Autonomy: NEEDS APPROVAL -- involves money
    #    NOTE: Shopify recommends GraphQL for new discount logic, but REST
    #          still works for simple percentage/fixed discounts.
    # ===================================================================

    def create_price_rule(self, title: str, value_type: str, value: float,
                           target_type: str = "line_item",
                           target_selection: str = "all",
                           allocation_method: str = "across",
                           starts_at: str = None, ends_at: str = None,
                           usage_limit: int = None,
                           once_per_customer: bool = True,
                           prerequisite_subtotal_range: dict = None,
                           entitled_product_ids: list = None,
                           entitled_collection_ids: list = None) -> dict:
        """
        Create a price rule (the conditions for a discount).

        POST /admin/api/2025-01/price_rules.json

        Args:
            title: Internal name for the price rule (e.g. "VIP_SPRING_2026")
            value_type: "percentage" or "fixed_amount"
            value: Negative number. e.g. -10.0 for 10% off or -$10
            target_type: "line_item" or "shipping_line"
            target_selection: "all" or "entitled" (specific products/collections)
            allocation_method: "across" (spread) or "each" (per item)
            starts_at: ISO datetime string for start
            ends_at: ISO datetime string for expiry (None = no expiry)
            usage_limit: Max total uses (None = unlimited)
            once_per_customer: Limit to one use per customer
            prerequisite_subtotal_range: e.g. {"greater_than_or_equal_to": "50.00"}
            entitled_product_ids: Product IDs if target_selection = "entitled"
            entitled_collection_ids: Collection IDs if target_selection = "entitled"

        Returns:
            Created price rule object
        """
        rule = {
            "title": title,
            "value_type": value_type,
            "value": str(value),
            "target_type": target_type,
            "target_selection": target_selection,
            "allocation_method": allocation_method,
            "customer_selection": "all",
            "once_per_customer": once_per_customer,
            "starts_at": starts_at or datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        if ends_at:
            rule["ends_at"] = ends_at
        if usage_limit:
            rule["usage_limit"] = usage_limit
        if prerequisite_subtotal_range:
            rule["prerequisite_subtotal_range"] = prerequisite_subtotal_range
        if entitled_product_ids:
            rule["entitled_product_ids"] = entitled_product_ids
        if entitled_collection_ids:
            rule["entitled_collection_ids"] = entitled_collection_ids

        result = self._post("price_rules.json", {"price_rule": rule})
        pr = result.get("price_rule", {})
        logger.info(f"Created price rule '{title}' (ID: {pr.get('id')})")
        return pr

    def create_discount_code(self, price_rule_id: str, code: str) -> dict:
        """
        Create a discount code linked to a price rule.

        POST /admin/api/2025-01/price_rules/{price_rule_id}/discount_codes.json

        Args:
            price_rule_id: The price rule ID to attach to
            code: The discount code string customers will enter (e.g. "SPRING10")

        Returns:
            Created discount code object

        Example:
            # Create a 15% off discount code expiring end of month
            rule = writer.create_price_rule(
                title="MARCH_VIP_15",
                value_type="percentage",
                value=-15.0,
                ends_at="2026-03-31T23:59:59Z",
                usage_limit=100,
            )
            code = writer.create_discount_code(rule["id"], "VIPMAR15")
        """
        result = self._post(
            f"price_rules/{price_rule_id}/discount_codes.json",
            {"discount_code": {"code": code}}
        )
        dc = result.get("discount_code", {})
        logger.info(f"Created discount code '{code}' for price rule {price_rule_id}")
        return dc

    # ===================================================================
    # 6. PRODUCT METAFIELDS
    #    Endpoint: POST /admin/api/2025-01/products/{product_id}/metafields.json
    #    Endpoint: PUT /admin/api/2025-01/metafields/{metafield_id}.json
    #    Scope: write_products
    #    Autonomy: SAFE -- data enrichment, no customer impact
    # ===================================================================

    def set_product_metafield(self, product_id: str, namespace: str,
                                key: str, value: str,
                                value_type: str = "single_line_text_field") -> dict:
        """
        Create or update a metafield on a product.

        POST /admin/api/2025-01/products/{product_id}/metafields.json

        Args:
            product_id: Shopify product ID
            namespace: Metafield namespace (e.g. "custom", "intelligence")
            key: Metafield key (e.g. "replenishment_days", "best_paired_with")
            value: Metafield value
            value_type: One of: single_line_text_field, multi_line_text_field,
                        number_integer, number_decimal, boolean, json, date,
                        date_time, url, color, weight, dimension, volume

        Returns:
            Created/updated metafield object

        Example:
            writer.set_product_metafield(
                "12345", "intelligence", "avg_reorder_days", "45",
                value_type="number_integer"
            )
        """
        result = self._post(f"products/{product_id}/metafields.json", {
            "metafield": {
                "namespace": namespace,
                "key": key,
                "value": value,
                "type": value_type,
            }
        })
        mf = result.get("metafield", {})
        logger.info(f"Set metafield {namespace}.{key} on product {product_id}")
        return mf

    def get_product_metafields(self, product_id: str) -> list:
        """Get all metafields for a product."""
        result = self._get(f"products/{product_id}/metafields.json")
        return result.get("metafields", [])

    # ===================================================================
    # 7. FULFILLMENT STATUS UPDATES
    #    Endpoint: POST /admin/api/2025-01/orders/{order_id}/fulfillments.json
    #    Scope: write_fulfillments
    #    Autonomy: NEEDS APPROVAL -- affects customer experience
    # ===================================================================

    def create_fulfillment(self, order_id: str, location_id: str,
                            tracking_number: str = None,
                            tracking_company: str = None,
                            tracking_url: str = None,
                            line_items: list = None,
                            notify_customer: bool = True) -> dict:
        """
        Create a fulfillment for an order.

        POST /admin/api/2025-01/fulfillments.json (new fulfillment orders API)

        NOTE: Shopify has moved to Fulfillment Orders for newer API versions.
        This uses the legacy endpoint which still works in 2025-01.

        Args:
            order_id: Shopify order ID
            location_id: Fulfillment location ID
            tracking_number: Optional tracking number
            tracking_company: Optional carrier name
            tracking_url: Optional tracking URL
            line_items: Optional list of {"id": line_item_id, "quantity": n}
                       (None = fulfill all items)
            notify_customer: Whether to email the customer

        Returns:
            Created fulfillment object
        """
        fulfillment = {
            "location_id": int(location_id),
            "notify_customer": notify_customer,
        }

        tracking_info = {}
        if tracking_number:
            tracking_info["number"] = tracking_number
        if tracking_company:
            tracking_info["company"] = tracking_company
        if tracking_url:
            tracking_info["url"] = tracking_url
        if tracking_info:
            fulfillment["tracking_info"] = tracking_info

        if line_items:
            fulfillment["line_items"] = line_items

        result = self._post(f"orders/{order_id}/fulfillments.json", {
            "fulfillment": fulfillment
        })
        f_obj = result.get("fulfillment", {})
        logger.info(f"Created fulfillment for order {order_id} (status: {f_obj.get('status')})")
        return f_obj

    # ===================================================================
    # CONVENIENCE / BATCH METHODS
    # ===================================================================

    def tag_customers_by_segment(self, customer_ids: list, tag: str) -> dict:
        """
        Batch-tag multiple customers. Respects rate limits.

        Args:
            customer_ids: List of customer ID strings
            tag: Tag to add to all customers

        Returns:
            Dict with "success" and "failed" lists
        """
        results = {"success": [], "failed": []}
        for cid in customer_ids:
            try:
                self.add_customer_tags(cid, [tag])
                results["success"].append(cid)
                time.sleep(0.5)  # Stay well within rate limits
            except Exception as e:
                logger.error(f"Failed to tag customer {cid}: {e}")
                results["failed"].append({"id": cid, "error": str(e)})

        logger.info(
            f"Batch tag '{tag}': {len(results['success'])} success, "
            f"{len(results['failed'])} failed"
        )
        return results

    def create_vip_discount(self, code: str, percentage: float = 10.0,
                             ends_at: str = None, usage_limit: int = 1) -> dict:
        """
        Convenience method: create a VIP percentage discount code.

        Args:
            code: Discount code string (e.g. "VIP10MARCH")
            percentage: Discount percentage (e.g. 10.0 for 10% off)
            ends_at: Optional expiry datetime
            usage_limit: Max uses (default 1)

        Returns:
            Dict with "price_rule" and "discount_code"
        """
        rule = self.create_price_rule(
            title=f"Auto-VIP-{code}",
            value_type="percentage",
            value=-abs(percentage),
            usage_limit=usage_limit,
            once_per_customer=True,
            ends_at=ends_at,
        )

        dc = self.create_discount_code(str(rule["id"]), code)
        return {"price_rule": rule, "discount_code": dc}


# --- CLI ---

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    writer = ShopifyWriter()
    if not writer.available:
        print("SHOPIFY_STORE_URL and SHOPIFY_ACCESS_TOKEN required")
        sys.exit(1)

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python shopify_writer.py locations")
        print("  python shopify_writer.py tag-customer <customer_id> <tag1> <tag2>")
        print("  python shopify_writer.py add-order-note <order_id> 'note text'")
        print("  python shopify_writer.py get-inventory <inventory_item_id>")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "locations":
        for loc in writer.get_locations():
            print(f"  {loc['id']}: {loc['name']} ({loc.get('city', '')})")

    elif cmd == "tag-customer" and len(sys.argv) >= 4:
        cid = sys.argv[2]
        tags = sys.argv[3:]
        result = writer.add_customer_tags(cid, tags)
        print(f"Updated tags: {result.get('tags', '')}")

    elif cmd == "add-order-note" and len(sys.argv) >= 4:
        oid = sys.argv[2]
        note = " ".join(sys.argv[3:])
        result = writer.add_order_note(oid, note)
        print(f"Note set on order {result.get('name', oid)}")

    elif cmd == "get-inventory" and len(sys.argv) >= 3:
        iid = sys.argv[2]
        level = writer.get_inventory_level(iid)
        print(f"  Available: {level.get('available', 'N/A')}")
        print(f"  Location: {level.get('location_id', 'N/A')}")

    else:
        print(f"Unknown command: {cmd}")
