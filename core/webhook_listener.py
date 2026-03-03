#!/usr/bin/env python3
"""
Webhook Listener — Real-time event processing for Tom's Command Center.

FastAPI server that handles incoming Shopify and Klaviyo webhooks,
replacing the nightly cron with instant attribution, churn alerts,
and cross-channel verification.

Endpoints:
    POST /webhook/shopify/order-created  — Instant order attribution + customer tagging
    POST /webhook/shopify/refund         — Churn risk alert with LTV context
    POST /webhook/klaviyo/event          — Klaviyo event logging + attribution verification
    GET  /health                         — Railway health check

Runs alongside the Telegram polling bot on a separate port (default 8080).
Designed to be importable as a module (use `app` object) or run standalone.

Security:
    Shopify webhooks are verified via HMAC-SHA256 using SHOPIFY_WEBHOOK_SECRET.
    If the secret is not set, webhooks are processed with a logged warning (for testing).

Usage:
    # Standalone
    python -m core.webhook_listener

    # Or import the FastAPI app for uvicorn
    from core.webhook_listener import app
"""

import os
import json
import logging
import hashlib
import hmac
import base64
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# --- Configuration ---

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
INTELLIGENCE_DB = DATA_DIR / "intelligence.db"
CUSTOMER_DB = DATA_DIR / "customer_intelligence.db"
CONFIG_DIR = BASE_DIR / "config"

PORT = int(os.environ.get("PORT", 8080))
SHOPIFY_WEBHOOK_SECRET = os.environ.get("SHOPIFY_WEBHOOK_SECRET", "")

# High-value order threshold (NZD)
HIGH_VALUE_THRESHOLD = 200.0

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "orchestrator.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)


# --- FastAPI App ---

app = FastAPI(
    title="Tom's Command Center — Webhook Listener",
    description="Real-time Shopify and Klaviyo webhook processing.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Shopify HMAC Verification ---

def verify_shopify_hmac(body: bytes, hmac_header: str) -> bool:
    """
    Verify a Shopify webhook's HMAC-SHA256 signature.

    Shopify signs the raw request body with the webhook secret and sends
    the base64-encoded digest in X-Shopify-Hmac-SHA256. We recompute
    and compare.

    Returns True if the signature is valid. Returns True with a warning
    if SHOPIFY_WEBHOOK_SECRET is not configured (allows testing).
    """
    if not SHOPIFY_WEBHOOK_SECRET:
        logger.warning("SHOPIFY_WEBHOOK_SECRET not set — skipping HMAC verification (testing mode)")
        return True

    if not hmac_header:
        logger.warning("No X-Shopify-Hmac-SHA256 header present on request")
        return False

    computed = base64.b64encode(
        hmac.new(
            SHOPIFY_WEBHOOK_SECRET.encode("utf-8"),
            body,
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")

    return hmac.compare_digest(computed, hmac_header)


# --- Database Helpers ---

def _get_intelligence_db() -> sqlite3.Connection:
    """Get intelligence.db connection for webhook event logging."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(INTELLIGENCE_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS webhook_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT,
            processed_at TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
    """)
    return conn


def _get_customer_db() -> sqlite3.Connection:
    """Get customer_intelligence.db connection."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CUSTOMER_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _log_webhook_event(source: str, event_type: str, payload: dict):
    """Persist a webhook event to intelligence.db for audit trail."""
    try:
        conn = _get_intelligence_db()
        conn.execute(
            "INSERT INTO webhook_events (source, event_type, payload, processed_at) VALUES (?, ?, ?, ?)",
            (source, event_type, json.dumps(payload, default=str), datetime.utcnow().isoformat()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"Failed to log webhook event: {e}")


def _get_customer_ltv(customer_id: str) -> Optional[dict]:
    """
    Look up a customer's lifetime value context from customer_intelligence.db.
    Returns dict with total_orders, total_spent, segment, or None.
    """
    try:
        conn = _get_customer_db()
        row = conn.execute(
            "SELECT total_orders, total_spent, avg_order_value, segment, first_order_date "
            "FROM customers WHERE shopify_id = ?",
            (str(customer_id),),
        ).fetchone()
        conn.close()
        if row:
            return {
                "total_orders": row["total_orders"],
                "total_spent": row["total_spent"],
                "avg_order_value": row["avg_order_value"],
                "segment": row["segment"],
                "first_order_date": row["first_order_date"],
            }
    except Exception as e:
        logger.debug(f"Customer LTV lookup failed for {customer_id}: {e}")
    return None


# --- Notification + Attribution Helpers ---

def _send_notification(message: str, severity: str = "INFO", channel: str = "dbh-marketing"):
    """
    Send a notification to a Telegram channel via NotificationRouter.

    Falls back to logging if the router is not available (e.g. running standalone
    without the full orchestrator environment).
    """
    try:
        from core.notification_router import NotificationRouter
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        telegram_config_path = CONFIG_DIR / "telegram.json"
        chat_id = ""

        if telegram_config_path.exists():
            with open(telegram_config_path) as f:
                tg_config = json.load(f)
            chat_id = tg_config.get("chat_ids", {}).get(channel, "")

        if bot_token and chat_id:
            router = NotificationRouter(bot_token=bot_token, default_chat_id=chat_id)
            router.send(message, severity=severity)
            logger.info(f"Notification sent to {channel} [{severity}]: {message[:80]}...")
        else:
            logger.warning(f"Telegram not configured — notification logged only: [{severity}] {message[:120]}")
    except ImportError:
        logger.warning(f"NotificationRouter not available — [{severity}] {message[:120]}")
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")


def _publish_event(event_type: str, severity: str, payload: dict, source_agent: str = "webhook-listener"):
    """
    Publish an event to the cross-agent event bus.

    Falls back to logging if the event bus is not available.
    """
    try:
        from core.event_bus import EventBus
        bus = EventBus()
        bus.publish(
            source_agent=source_agent,
            event_type=event_type,
            severity=severity,
            payload=payload,
        )
        logger.info(f"Event published: {event_type} [{severity}]")
    except ImportError:
        logger.warning(f"EventBus not available — event logged only: {event_type}")
    except Exception as e:
        logger.error(f"Failed to publish event: {e}")


def _classify_and_tag(order_data: dict) -> dict:
    """
    Run order attribution and tag the customer in Shopify.

    Uses order_intelligence.classify_order_source() for attribution,
    then ShopifyWriter.add_customer_tags() to persist the channel tag.

    Returns the attribution result dict.
    """
    try:
        from core.order_intelligence import classify_order_source, save_order_to_db, get_db
        attribution = classify_order_source(order_data)

        # Save to customer intelligence DB
        customer = order_data.get("customer") or {}
        customer_id = str(customer.get("id", ""))
        order_enriched = {
            "order_id": str(order_data.get("id", "")),
            "customer_id": customer_id,
            "name": order_data.get("name", ""),
            "created": order_data.get("created_at", ""),
            "total": float(order_data.get("total_price", 0) or 0),
            "products": [
                item.get("title", "Unknown")
                for item in order_data.get("line_items", [])
            ],
            "channel": attribution.get("channel", "Unknown"),
            "source": attribution.get("source", "Unknown"),
            "campaign": attribution.get("campaign", ""),
            "confidence": attribution.get("confidence", "low"),
            "discount_code": (order_data.get("discount_codes") or [{}])[0].get("code", "") if order_data.get("discount_codes") else "",
            "discount": float((order_data.get("discount_codes") or [{}])[0].get("amount", 0) or 0) if order_data.get("discount_codes") else 0,
            "customer_type": "returning" if (customer.get("orders_count", 0) or 0) > 1 else "new",
            "location": f"{customer.get('default_address', {}).get('city', '')}, {customer.get('default_address', {}).get('country', '')}" if customer.get("default_address") else "Unknown",
            "customer_raw": customer,
        }

        try:
            conn = get_db()
            save_order_to_db(conn, order_enriched)
            conn.close()
        except Exception as e:
            logger.error(f"Failed to save order to DB: {e}")

        # Tag customer with acquisition channel
        if customer_id:
            try:
                from core.shopify_writer import ShopifyWriter
                writer = ShopifyWriter()
                if writer.available:
                    channel_tag = f"acq:{attribution['channel'].lower().replace(' ', '-')}"
                    writer.add_customer_tags(customer_id, [channel_tag])
                    logger.info(f"Tagged customer {customer_id} with '{channel_tag}'")
            except ImportError:
                logger.debug("ShopifyWriter not available for customer tagging")
            except Exception as e:
                logger.warning(f"Customer tagging failed for {customer_id}: {e}")

        return attribution
    except ImportError:
        logger.warning("order_intelligence module not available — attribution skipped")
        return {"channel": "Unknown", "source": "Unknown", "campaign": "", "confidence": "none"}
    except Exception as e:
        logger.error(f"Attribution failed: {e}")
        return {"channel": "Error", "source": str(e), "campaign": "", "confidence": "none"}


# --- Endpoints ---

@app.get("/health")
async def health_check():
    """Simple health check for Railway monitoring."""
    return {
        "status": "healthy",
        "service": "webhook-listener",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/webhook/shopify/order-created")
async def shopify_order_created(request: Request):
    """
    Handle Shopify order/create webhook.

    1. Verify HMAC signature
    2. Extract customer, order total, line items, UTMs
    3. Run instant attribution via classify_order_source()
    4. Tag customer in Shopify with acquisition channel
    5. Send notification to dbh-marketing (NOTABLE if >$200)
    6. Publish event to cross-agent bus
    """
    body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-SHA256", "")

    if not verify_shopify_hmac(body, hmac_header):
        logger.warning("Shopify order webhook failed HMAC verification")
        return JSONResponse(status_code=401, content={"error": "HMAC verification failed"})

    try:
        order_data = json.loads(body)
    except json.JSONDecodeError:
        logger.error("Shopify order webhook: invalid JSON body")
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    order_id = order_data.get("id", "unknown")
    order_name = order_data.get("name", "N/A")
    order_total = float(order_data.get("total_price", 0) or 0)
    customer = order_data.get("customer") or {}
    customer_id = str(customer.get("id", ""))
    customer_name = f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip() or "Unknown"
    line_items = order_data.get("line_items", [])
    products = [item.get("title", "Unknown") for item in line_items]

    logger.info(f"Shopify order webhook received: {order_name} — ${order_total:.2f} — {customer_name}")

    # Log the raw webhook event
    _log_webhook_event("shopify", "order_created", {
        "order_id": order_id,
        "order_name": order_name,
        "total": order_total,
        "customer_id": customer_id,
    })

    # Run attribution + customer tagging
    attribution = _classify_and_tag(order_data)

    # Determine notification severity
    severity = "NOTABLE" if order_total > HIGH_VALUE_THRESHOLD else "INFO"

    # Build notification message
    product_list = ", ".join(products[:5])
    if len(products) > 5:
        product_list += f" (+{len(products) - 5} more)"

    message = (
        f"NEW ORDER {order_name}\n"
        f"Customer: {customer_name}\n"
        f"Total: ${order_total:.2f}\n"
        f"Products: {product_list}\n"
        f"Channel: {attribution.get('channel', 'Unknown')} ({attribution.get('confidence', 'low')} confidence)\n"
        f"Source: {attribution.get('source', 'Unknown')}"
    )

    if attribution.get("campaign"):
        message += f"\nCampaign: {attribution['campaign']}"

    if order_total > HIGH_VALUE_THRESHOLD:
        message = f"HIGH VALUE ORDER\n{message}"

    _send_notification(message, severity=severity, channel="dbh-marketing")

    # Publish to event bus
    _publish_event(
        event_type="customer.order_placed",
        severity=severity,
        payload={
            "order_id": str(order_id),
            "order_name": order_name,
            "total": order_total,
            "customer_id": customer_id,
            "customer_name": customer_name,
            "channel": attribution.get("channel", "Unknown"),
            "products": products,
        },
    )

    return JSONResponse(content={
        "status": "processed",
        "order": order_name,
        "attribution": attribution,
    })


@app.post("/webhook/shopify/refund")
async def shopify_refund(request: Request):
    """
    Handle Shopify refund webhook.

    1. Verify HMAC signature
    2. Extract customer_id, refund amount, reason
    3. Look up customer LTV from customer_intelligence.db
    4. Send IMPORTANT notification to dbh-marketing with LTV context
    5. Publish churn risk event to event bus
    """
    body = await request.body()
    hmac_header = request.headers.get("X-Shopify-Hmac-SHA256", "")

    if not verify_shopify_hmac(body, hmac_header):
        logger.warning("Shopify refund webhook failed HMAC verification")
        return JSONResponse(status_code=401, content={"error": "HMAC verification failed"})

    try:
        refund_data = json.loads(body)
    except json.JSONDecodeError:
        logger.error("Shopify refund webhook: invalid JSON body")
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    refund_id = refund_data.get("id", "unknown")
    order_id = refund_data.get("order_id", "unknown")
    reason = refund_data.get("note", "") or refund_data.get("reason", "No reason provided")

    # Calculate total refund amount from refund line items
    refund_amount = 0.0
    refund_items = []
    for txn in refund_data.get("transactions", []):
        refund_amount += float(txn.get("amount", 0) or 0)
    for line in refund_data.get("refund_line_items", []):
        item_title = line.get("line_item", {}).get("title", "Unknown item")
        item_qty = line.get("quantity", 0)
        refund_items.append(f"{item_title} x{item_qty}")

    # Extract customer info — Shopify refund payloads include order context
    # but the customer object may be nested under the parent order
    user_id = str(refund_data.get("user_id", ""))

    logger.info(f"Shopify refund webhook received: refund {refund_id} on order {order_id} — ${refund_amount:.2f}")

    # Log the raw webhook event
    _log_webhook_event("shopify", "refund", {
        "refund_id": refund_id,
        "order_id": order_id,
        "amount": refund_amount,
        "reason": reason,
    })

    # Look up customer LTV for context
    ltv_context = ""
    customer_id = str(refund_data.get("user_id", ""))
    # Shopify refund webhooks may not include customer_id directly;
    # try to find it from the order in our DB
    if not customer_id:
        try:
            conn = _get_customer_db()
            row = conn.execute(
                "SELECT shopify_customer_id FROM orders WHERE order_id = ?",
                (str(order_id),),
            ).fetchone()
            conn.close()
            if row:
                customer_id = row["shopify_customer_id"]
        except Exception as e:
            logger.debug(f"Could not look up customer for order {order_id}: {e}")

    if customer_id:
        ltv = _get_customer_ltv(customer_id)
        if ltv:
            ltv_context = (
                f"\nCustomer LTV: ${ltv['total_spent']:.2f} across {ltv['total_orders']} orders"
                f"\nSegment: {ltv['segment']}"
                f"\nFirst order: {ltv['first_order_date']}"
            )

    # Build notification
    items_str = ", ".join(refund_items[:5]) if refund_items else "Not specified"
    message = (
        f"REFUND ALERT\n"
        f"Order: #{order_id}\n"
        f"Refund: ${refund_amount:.2f}\n"
        f"Items: {items_str}\n"
        f"Reason: {reason}"
        f"{ltv_context}"
    )

    _send_notification(message, severity="IMPORTANT", channel="dbh-marketing")

    # Publish churn risk event
    _publish_event(
        event_type="customer.churn_risk",
        severity="IMPORTANT",
        payload={
            "refund_id": str(refund_id),
            "order_id": str(order_id),
            "refund_amount": refund_amount,
            "reason": reason,
            "customer_id": customer_id,
            "ltv": _get_customer_ltv(customer_id) if customer_id else None,
        },
    )

    return JSONResponse(content={
        "status": "processed",
        "refund_id": str(refund_id),
        "order_id": str(order_id),
        "amount": refund_amount,
    })


@app.post("/webhook/klaviyo/event")
async def klaviyo_event(request: Request):
    """
    Handle Klaviyo event webhook.

    1. Parse the event payload
    2. Log to intelligence.db for tracking
    3. If event is "Placed Order", cross-reference with Shopify for attribution verification
    """
    try:
        body = await request.body()
        event_data = json.loads(body)
    except json.JSONDecodeError:
        logger.error("Klaviyo event webhook: invalid JSON body")
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    # Klaviyo webhook payloads vary by event type
    event_name = event_data.get("event", "") or event_data.get("type", "") or event_data.get("metric", {}).get("name", "unknown")
    event_properties = event_data.get("properties", {}) or event_data.get("event_properties", {})
    profile = event_data.get("profile", {}) or event_data.get("person", {})
    email = profile.get("email", "") or profile.get("$email", "")
    timestamp = event_data.get("datetime", "") or event_data.get("timestamp", datetime.utcnow().isoformat())

    logger.info(f"Klaviyo event webhook received: {event_name} — {email}")

    # Log to intelligence.db
    _log_webhook_event("klaviyo", event_name, {
        "email": email,
        "properties": event_properties,
        "timestamp": timestamp,
    })

    # Cross-reference "Placed Order" events with Shopify attribution
    if event_name.lower() in ("placed order", "placed_order"):
        order_value = float(event_properties.get("$value", 0) or event_properties.get("value", 0) or 0)
        order_id = event_properties.get("$event_id", "") or event_properties.get("OrderId", "")

        logger.info(f"Klaviyo Placed Order: {email} — ${order_value:.2f} — verifying Shopify attribution")

        # Check if we already have this order attributed in our DB
        attribution_match = "unverified"
        if order_id:
            try:
                conn = _get_customer_db()
                row = conn.execute(
                    "SELECT channel, source, attribution_confidence FROM orders WHERE order_id = ?",
                    (str(order_id),),
                ).fetchone()
                conn.close()
                if row:
                    attribution_match = f"verified — {row['channel']} via {row['source']} ({row['attribution_confidence']})"
                    logger.info(f"Order {order_id} attribution verified: {attribution_match}")
                else:
                    attribution_match = "order not yet in DB — Shopify webhook may be pending"
                    logger.info(f"Order {order_id} not found in customer DB for cross-reference")
            except Exception as e:
                logger.debug(f"Klaviyo cross-reference failed for order {order_id}: {e}")

        # If it's a Klaviyo-attributed order, publish for tracking
        _publish_event(
            event_type="customer.klaviyo_order_verified",
            severity="INFO",
            payload={
                "email": email,
                "order_id": str(order_id),
                "order_value": order_value,
                "attribution_match": attribution_match,
            },
        )

    return JSONResponse(content={
        "status": "processed",
        "event": event_name,
        "email": email,
    })


# --- Standalone Runner ---

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting webhook listener on port {PORT}")
    uvicorn.run(
        "core.webhook_listener:app",
        host="0.0.0.0",
        port=PORT,
        log_level="info",
        reload=False,
    )
