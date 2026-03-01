#!/usr/bin/env python3
"""
Exception Router -- Catch and Resolve, Don't Report.

The autonomous immune system for Tom's Command Center.
When something goes wrong (or unusually right), this module detects it,
runs the auto-resolution playbook, and only escalates to Tom when it
genuinely needs a human decision.

Philosophy: Make problems impossible to ignore and incredibly easy to resolve.
Every exception includes exactly what needs to happen and who needs to do it.

Exception types and their auto-resolution playbooks:

  stock.low               -> Check inventory thresholds, alert or reorder
  campaign.roas_drop      -> Auto-pause low ROAS ad sets, create creative refresh task
  campaign.budget_overspend -> Reduce daily budget by 20%, alert Tom
  order.high_value        -> Flag VIP, tag in Shopify, trigger Klaviyo VIP flow
  order.refund_request    -> Create Asana task, log to learning DB
  customer.churn_risk     -> Trigger win-back flow in Klaviyo
  email.deliverability_drop -> Alert Tom immediately (CRITICAL)
  system.api_failure      -> Log, retry 3x, alert if persistent
  invoice.missing_docs    -> Route to relevant person with full context

Each exception carries:
  - Detection criteria (how the agent identifies it)
  - Auto-resolution steps (what to do WITHOUT human approval)
  - Escalation criteria (when to involve Tom)
  - Context package (what info Tom needs to resolve it if escalated)
  - Resolution deadline (how long before auto-escalation)

Resolution state machine:
  OPEN -> RESOLVING -> RESOLVED
                    -> ESCALATED -> RESOLVED

Database: data/exceptions.db (SQLite, persistent across restarts)

Usage:
    from core.exception_router import ExceptionRouter

    router = ExceptionRouter()
    router.detect_exception("stock.low", {
        "product": "Marine Collagen 300g",
        "sku": "MC-300",
        "current_stock": 12,
        "daily_velocity": 4.2,
    }, agent_name="dbh-marketing")

    # For morning briefings
    brief = router.format_exception_brief()

    # For PREP Monday review
    summary = router.get_weekly_summary()
"""

import sqlite3
import json
import os
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# Resolve paths relative to this file's location (works in Docker + local)
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "exceptions.db"

# ---- Severity & Status Constants ----

SEVERITIES = ("CRITICAL", "IMPORTANT", "NOTABLE", "INFO")

STATUSES = ("open", "resolving", "resolved", "escalated")

# Escalation deadlines: if an exception stays open longer than this,
# auto-escalate to Tom. Values in minutes.
DEFAULT_ESCALATION_MINUTES = {
    "CRITICAL": 15,
    "IMPORTANT": 120,     # 2 hours
    "NOTABLE": 1440,      # 24 hours
    "INFO": 10080,        # 7 days (effectively: weekly review)
}


# ============================================================================
# EXCEPTION PLAYBOOKS
#
# Each playbook defines:
#   severity:           Default severity when detected
#   auto_resolution:    List of action dicts describing autonomous steps
#   escalation_criteria: Human-readable conditions for escalation
#   context_template:   What info Tom gets if escalated (format string)
#   deadline_minutes:   Override for escalation deadline
#   description:        What this exception type means
# ============================================================================

PLAYBOOKS = {

    # ---- INVENTORY ----

    "stock.low": {
        "severity": "IMPORTANT",
        "description": "Product inventory has dropped below safe threshold",
        "auto_resolution": [
            {
                "action": "check_inventory",
                "description": "Verify current stock levels via Shopify API",
                "client": "shopify_writer",
                "method": "get_inventory_level",
                "requires_approval": False,
            },
            {
                "action": "publish_event",
                "description": "Publish inventory.low_stock event to event bus",
                "event_type": "inventory.low_stock",
                "event_severity": "IMPORTANT",
                "requires_approval": False,
            },
        ],
        "escalation_criteria": (
            "Stock < 3 days of supply based on daily velocity, "
            "OR product is a top-5 revenue generator, "
            "OR no reorder has been placed in 48 hours"
        ),
        "context_template": (
            "LOW STOCK ALERT\n"
            "Product: {product}\n"
            "SKU: {sku}\n"
            "Current stock: {current_stock} units\n"
            "Daily velocity: {daily_velocity} units/day\n"
            "Days remaining: {days_remaining:.1f} days\n"
            "\n"
            "ACTION NEEDED: Place reorder with supplier or adjust marketing spend "
            "to reduce velocity until restock arrives."
        ),
        "deadline_minutes": 120,
    },

    # ---- CAMPAIGN PERFORMANCE ----

    "campaign.roas_drop": {
        "severity": "IMPORTANT",
        "description": "Campaign ROAS has dropped below acceptable threshold",
        "auto_resolution": [
            {
                "action": "pause_ad_set",
                "description": "Auto-pause ad set if ROAS < 2.0x (protective action)",
                "client": "meta_ads_writer",
                "method": "pause_ad_set",
                "condition": "roas < 2.0",
                "requires_approval": False,
            },
            {
                "action": "create_asana_task",
                "description": "Create Asana task for creative refresh",
                "client": "asana_writer",
                "method": "create_task_from_agent",
                "task_title": "Creative Refresh: {campaign} (ROAS dropped to {roas}x)",
                "task_description": (
                    "Campaign '{campaign}' ROAS dropped from {prev_roas}x to {roas}x.\n"
                    "Channel: {channel}\n\n"
                    "Recommended actions:\n"
                    "1. Review creative fatigue indicators\n"
                    "2. Test new creative angles from playbook\n"
                    "3. Check audience overlap with other campaigns\n"
                    "4. Consider new hook or UGC content"
                ),
                "requires_approval": False,
            },
            {
                "action": "publish_event",
                "description": "Publish performance drop to event bus for other agents",
                "event_type": "campaign.performance_drop",
                "event_severity": "IMPORTANT",
                "requires_approval": False,
            },
        ],
        "escalation_criteria": (
            "ROAS < 1.0x (losing money), "
            "OR campaign spend > $200/day, "
            "OR drop is > 60% from previous period"
        ),
        "context_template": (
            "CAMPAIGN ROAS DROP\n"
            "Campaign: {campaign}\n"
            "Channel: {channel}\n"
            "Current ROAS: {roas}x\n"
            "Previous ROAS: {prev_roas}x\n"
            "Drop: {drop_pct}%\n"
            "Daily spend: ${daily_spend}\n"
            "\n"
            "AUTO-ACTIONS TAKEN:\n"
            "- Ad set paused (if ROAS < 2.0x)\n"
            "- Asana task created for creative refresh\n"
            "\n"
            "DECISION NEEDED: Resume with new creative, reallocate budget, "
            "or kill campaign entirely?"
        ),
        "deadline_minutes": 60,
    },

    "campaign.budget_overspend": {
        "severity": "IMPORTANT",
        "description": "Campaign has exceeded its daily budget allocation",
        "auto_resolution": [
            {
                "action": "reduce_budget",
                "description": "Reduce daily budget by 20% as protective measure",
                "client": "meta_ads_writer",
                "method": "update_campaign_budget",
                "budget_reduction_pct": 20,
                "requires_approval": False,
            },
            {
                "action": "alert_tom",
                "description": "Send immediate alert to Tom via notification router",
                "severity": "IMPORTANT",
                "requires_approval": False,
            },
        ],
        "escalation_criteria": (
            "Overspend > 30% of daily budget, "
            "OR cumulative overspend > $500 this week, "
            "OR multiple campaigns overspending simultaneously"
        ),
        "context_template": (
            "BUDGET OVERSPEND ALERT\n"
            "Campaign: {campaign}\n"
            "Daily budget: ${daily_budget}\n"
            "Actual spend: ${actual_spend}\n"
            "Overspend: ${overspend} ({overspend_pct}%)\n"
            "\n"
            "AUTO-ACTION TAKEN:\n"
            "- Daily budget reduced by 20% to ${new_budget}\n"
            "\n"
            "DECISION NEEDED: Approve new budget level, restore original, "
            "or pause campaign?"
        ),
        "deadline_minutes": 60,
    },

    # ---- ORDER EVENTS ----

    "order.high_value": {
        "severity": "NOTABLE",
        "description": "High-value order detected (above VIP threshold)",
        "auto_resolution": [
            {
                "action": "tag_vip",
                "description": "Add VIP tag to customer in Shopify",
                "client": "shopify_writer",
                "method": "add_customer_tags",
                "tags": ["VIP", "high-value-order"],
                "requires_approval": False,
            },
            {
                "action": "trigger_vip_flow",
                "description": "Trigger VIP welcome flow in Klaviyo",
                "client": "klaviyo_writer",
                "method": "create_event",
                "event_name": "VIP Order Placed",
                "requires_approval": False,
            },
            {
                "action": "publish_event",
                "description": "Publish VIP milestone to event bus",
                "event_type": "customer.vip_milestone",
                "event_severity": "NOTABLE",
                "requires_approval": False,
            },
        ],
        "escalation_criteria": (
            "Order value > $1,000 (personal thank-you warranted), "
            "OR customer is first-time buyer with large order (potential B2B)"
        ),
        "context_template": (
            "HIGH-VALUE ORDER\n"
            "Order: {order_name}\n"
            "Customer: {customer_name} ({customer_email})\n"
            "Value: ${order_value}\n"
            "Items: {items}\n"
            "Customer lifetime orders: {lifetime_orders}\n"
            "Customer lifetime value: ${lifetime_value}\n"
            "\n"
            "AUTO-ACTIONS TAKEN:\n"
            "- Customer tagged as VIP in Shopify\n"
            "- VIP flow triggered in Klaviyo\n"
            "\n"
            "OPTIONAL: Send personal thank-you message?"
        ),
        "deadline_minutes": 1440,
    },

    "order.refund_request": {
        "severity": "IMPORTANT",
        "description": "Customer has requested a refund",
        "auto_resolution": [
            {
                "action": "create_asana_task",
                "description": "Create Asana task for refund processing",
                "client": "asana_writer",
                "method": "create_task_from_agent",
                "task_title": "Refund Request: {order_name} - {customer_name}",
                "task_description": (
                    "Refund requested for order {order_name}.\n"
                    "Customer: {customer_name} ({customer_email})\n"
                    "Order value: ${order_value}\n"
                    "Reason: {reason}\n"
                    "Items: {items}\n\n"
                    "Process:\n"
                    "1. Review refund reason\n"
                    "2. Check if product can be resold\n"
                    "3. Process refund via Shopify\n"
                    "4. Update customer profile with refund flag"
                ),
                "priority": "high",
                "requires_approval": False,
            },
            {
                "action": "log_to_learning_db",
                "description": "Record refund in learning DB for pattern analysis",
                "domain": "customer_satisfaction",
                "requires_approval": False,
            },
        ],
        "escalation_criteria": (
            "Refund value > $200, "
            "OR customer has previous refunds (pattern), "
            "OR reason suggests product quality issue"
        ),
        "context_template": (
            "REFUND REQUEST\n"
            "Order: {order_name}\n"
            "Customer: {customer_name} ({customer_email})\n"
            "Value: ${order_value}\n"
            "Reason: {reason}\n"
            "\n"
            "AUTO-ACTIONS TAKEN:\n"
            "- Asana task created for processing\n"
            "- Logged to learning DB\n"
            "\n"
            "DECISION NEEDED: Approve refund? Offer exchange/store credit instead?"
        ),
        "deadline_minutes": 240,
    },

    # ---- CUSTOMER LIFECYCLE ----

    "customer.churn_risk": {
        "severity": "NOTABLE",
        "description": "Customer identified as at risk of churning",
        "auto_resolution": [
            {
                "action": "trigger_winback_flow",
                "description": "Trigger win-back flow in Klaviyo",
                "client": "klaviyo_writer",
                "method": "create_event",
                "event_name": "Churn Risk Detected",
                "requires_approval": False,
            },
            {
                "action": "tag_customer",
                "description": "Tag customer as churn-risk in Shopify",
                "client": "shopify_writer",
                "method": "add_customer_tags",
                "tags": ["churn-risk", "needs-winback"],
                "requires_approval": False,
            },
            {
                "action": "publish_event",
                "description": "Publish churn risk event to event bus",
                "event_type": "customer.churn_risk",
                "event_severity": "NOTABLE",
                "requires_approval": False,
            },
        ],
        "escalation_criteria": (
            "Customer lifetime value > $500 (high-value at risk), "
            "OR customer was previously recovered and re-churning, "
            "OR batch of 10+ customers churning simultaneously (systemic issue)"
        ),
        "context_template": (
            "CHURN RISK DETECTED\n"
            "Customer: {customer_name} ({customer_email})\n"
            "Last order: {last_order_date}\n"
            "Days since last order: {days_since_order}\n"
            "Expected reorder window: {expected_reorder_days} days\n"
            "Lifetime value: ${lifetime_value}\n"
            "Total orders: {total_orders}\n"
            "\n"
            "AUTO-ACTIONS TAKEN:\n"
            "- Win-back flow triggered in Klaviyo\n"
            "- Customer tagged as churn-risk in Shopify\n"
            "\n"
            "OPTIONAL: Personal outreach for high-value customers?"
        ),
        "deadline_minutes": 4320,  # 3 days
    },

    # ---- EMAIL HEALTH ----

    "email.deliverability_drop": {
        "severity": "CRITICAL",
        "description": "Email deliverability has dropped below safe threshold",
        "auto_resolution": [
            {
                "action": "alert_tom",
                "description": "Send CRITICAL alert to Tom immediately",
                "severity": "CRITICAL",
                "requires_approval": False,
            },
            {
                "action": "publish_event",
                "description": "Publish deliverability alert to event bus",
                "event_type": "email.deliverability_drop",
                "event_severity": "CRITICAL",
                "requires_approval": False,
            },
        ],
        "escalation_criteria": (
            "ALWAYS escalate -- deliverability issues can destroy the email channel. "
            "This is auto-escalated on detection."
        ),
        "context_template": (
            "EMAIL DELIVERABILITY DROP -- CRITICAL\n"
            "Current rate: {deliverability_rate}%\n"
            "Previous rate: {prev_rate}%\n"
            "Drop: {drop_pct}%\n"
            "Bounce rate: {bounce_rate}%\n"
            "Spam complaint rate: {spam_rate}%\n"
            "\n"
            "NO AUTO-RESOLUTION -- requires human investigation.\n"
            "\n"
            "IMMEDIATE ACTIONS NEEDED:\n"
            "1. Pause all non-essential email sends\n"
            "2. Check sender reputation (Google Postmaster Tools)\n"
            "3. Review recent list imports for bad addresses\n"
            "4. Check DNS records (SPF, DKIM, DMARC)\n"
            "5. Contact Klaviyo support if spam rate > 0.1%"
        ),
        "deadline_minutes": 15,
    },

    # ---- SYSTEM HEALTH ----

    "system.api_failure": {
        "severity": "NOTABLE",
        "description": "An API call to an external service has failed",
        "auto_resolution": [
            {
                "action": "retry",
                "description": "Retry the failed API call up to 3 times with backoff",
                "max_retries": 3,
                "backoff_seconds": [2, 10, 60],
                "requires_approval": False,
            },
            {
                "action": "log_failure",
                "description": "Log failure details for pattern detection",
                "requires_approval": False,
            },
        ],
        "escalation_criteria": (
            "3 consecutive failures for the same service, "
            "OR same service fails across multiple agents, "
            "OR failure blocks a CRITICAL business process"
        ),
        "context_template": (
            "API FAILURE\n"
            "Service: {service}\n"
            "Endpoint: {endpoint}\n"
            "Error: {error}\n"
            "HTTP status: {status_code}\n"
            "Consecutive failures: {failure_count}\n"
            "First failure: {first_failure_at}\n"
            "\n"
            "AUTO-ACTIONS TAKEN:\n"
            "- Retried {retry_count}x with exponential backoff\n"
            "- Failure logged for pattern analysis\n"
            "\n"
            "ACTION NEEDED: Check service status page, review API credentials, "
            "or contact support."
        ),
        "deadline_minutes": 30,
    },

    # ---- FINANCE / INVOICING ----

    "invoice.missing_docs": {
        "severity": "NOTABLE",
        "description": "Invoice or financial document is missing required information",
        "auto_resolution": [
            {
                "action": "create_asana_task",
                "description": "Create Asana task for the responsible person",
                "client": "asana_writer",
                "method": "create_task_from_agent",
                "task_title": "Missing Invoice Docs: {invoice_ref}",
                "task_description": (
                    "Invoice {invoice_ref} is missing required documentation.\n"
                    "Missing items: {missing_items}\n"
                    "Vendor: {vendor}\n"
                    "Amount: ${amount}\n"
                    "Due date: {due_date}\n\n"
                    "Please locate and attach the missing documents."
                ),
                "requires_approval": False,
            },
        ],
        "escalation_criteria": (
            "Invoice due within 5 business days, "
            "OR amount > $5,000, "
            "OR vendor has flagged as overdue"
        ),
        "context_template": (
            "MISSING INVOICE DOCUMENTS\n"
            "Invoice: {invoice_ref}\n"
            "Vendor: {vendor}\n"
            "Amount: ${amount}\n"
            "Due date: {due_date}\n"
            "Missing: {missing_items}\n"
            "Assigned to: {assigned_to}\n"
            "\n"
            "AUTO-ACTIONS TAKEN:\n"
            "- Asana task created and assigned to {assigned_to}\n"
            "\n"
            "ACTION NEEDED: Locate documents or contact vendor."
        ),
        "deadline_minutes": 2880,  # 48 hours
    },
}


class ExceptionRouter:
    """
    Autonomous exception detection, resolution, and escalation engine.

    Catches problems, runs playbooks, and only bothers Tom when
    it genuinely needs a human decision.
    """

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    # ---- Schema ----

    def _init_schema(self):
        """Create tables if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS exceptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exception_type TEXT NOT NULL,
                severity TEXT NOT NULL DEFAULT 'NOTABLE',
                status TEXT NOT NULL DEFAULT 'open',
                detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                detected_by TEXT,
                payload TEXT DEFAULT '{}',
                auto_resolution_log TEXT DEFAULT '[]',
                resolution_notes TEXT,
                escalation_reason TEXT,
                escalated_at TIMESTAMP,
                resolved_at TIMESTAMP,
                deadline_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS resolution_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                exception_id INTEGER NOT NULL,
                action_name TEXT NOT NULL,
                action_description TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                result TEXT,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                FOREIGN KEY (exception_id) REFERENCES exceptions(id)
            );

            CREATE INDEX IF NOT EXISTS idx_exceptions_status
                ON exceptions(status);
            CREATE INDEX IF NOT EXISTS idx_exceptions_type
                ON exceptions(exception_type);
            CREATE INDEX IF NOT EXISTS idx_exceptions_severity
                ON exceptions(severity);
            CREATE INDEX IF NOT EXISTS idx_exceptions_detected
                ON exceptions(detected_at);
            CREATE INDEX IF NOT EXISTS idx_exceptions_deadline
                ON exceptions(deadline_at);
            CREATE INDEX IF NOT EXISTS idx_resolution_exception
                ON resolution_actions(exception_id);
            CREATE INDEX IF NOT EXISTS idx_resolution_status
                ON resolution_actions(status);
        """)
        self.conn.commit()

    # ---- Core API: Detection ----

    def detect_exception(self, exception_type: str, payload: dict,
                         agent_name: str = None) -> dict:
        """
        Detect an exception, create a record, and run its auto-resolution playbook.

        This is the main entry point. An agent calls this when it detects
        something that matches an exception pattern.

        Args:
            exception_type: One of the PLAYBOOKS keys (e.g. "stock.low")
            payload:        Dict with context-specific data matching the
                           playbook's context_template fields
            agent_name:     The agent that detected this (e.g. "dbh-marketing")

        Returns:
            Dict with: id, status, severity, actions_taken, escalated
        """
        playbook = PLAYBOOKS.get(exception_type)
        if not playbook:
            logger.warning(
                f"Unknown exception type '{exception_type}'. "
                f"Valid types: {', '.join(PLAYBOOKS.keys())}"
            )
            # Still record it, just without a playbook
            playbook = {
                "severity": "NOTABLE",
                "description": f"Unknown exception: {exception_type}",
                "auto_resolution": [],
                "escalation_criteria": "Unknown type -- always escalate",
                "context_template": "Exception payload: {payload}",
                "deadline_minutes": 60,
            }

        severity = playbook["severity"]
        deadline_minutes = playbook.get(
            "deadline_minutes",
            DEFAULT_ESCALATION_MINUTES.get(severity, 120)
        )
        deadline_at = (
            datetime.now() + timedelta(minutes=deadline_minutes)
        ).isoformat()

        # Insert exception record
        cursor = self.conn.execute(
            """INSERT INTO exceptions
               (exception_type, severity, status, detected_by, payload, deadline_at)
               VALUES (?, ?, 'open', ?, ?, ?)""",
            (
                exception_type,
                severity,
                agent_name or "system",
                json.dumps(payload),
                deadline_at,
            )
        )
        self.conn.commit()
        exception_id = cursor.lastrowid

        logger.info(
            f"EXCEPTION #{exception_id} detected: [{severity}] {exception_type} "
            f"by {agent_name or 'system'} -- deadline: {deadline_minutes}m"
        )

        # Run auto-resolution playbook
        actions_taken = self._run_auto_resolution(
            exception_id, exception_type, payload, playbook
        )

        # Check if this should be immediately escalated
        escalated = False
        if severity == "CRITICAL":
            escalated = True
            self._escalate(
                exception_id,
                reason=f"Auto-escalated: {severity} severity exception",
                payload=payload,
                playbook=playbook,
            )

        # Check if all auto-resolution actions completed
        if not escalated and actions_taken:
            all_ok = all(a.get("status") == "completed" for a in actions_taken)
            if all_ok:
                self._update_status(exception_id, "resolving")

        return {
            "id": exception_id,
            "type": exception_type,
            "severity": severity,
            "status": self._get_status(exception_id),
            "actions_taken": actions_taken,
            "escalated": escalated,
            "deadline_minutes": deadline_minutes,
        }

    # ---- Core API: Resolution ----

    def resolve_exception(self, exception_id: int, notes: str = "") -> bool:
        """
        Mark an exception as resolved.

        Args:
            exception_id: The exception ID to resolve
            notes:        Resolution notes describing what was done

        Returns:
            True if successfully resolved, False if not found
        """
        row = self.conn.execute(
            "SELECT id, status FROM exceptions WHERE id = ?",
            (exception_id,)
        ).fetchone()

        if not row:
            logger.warning(f"Exception #{exception_id} not found")
            return False

        if row["status"] == "resolved":
            logger.info(f"Exception #{exception_id} already resolved")
            return True

        self.conn.execute(
            """UPDATE exceptions
               SET status = 'resolved',
                   resolution_notes = ?,
                   resolved_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (notes, exception_id)
        )
        self.conn.commit()
        logger.info(f"Exception #{exception_id} resolved: {notes[:80]}")
        return True

    # ---- Core API: Queries ----

    def get_open_exceptions(self) -> list:
        """
        Get all open/resolving/escalated exceptions.
        Used for briefing injection and status dashboards.

        Returns:
            List of exception dicts, ordered by severity then recency
        """
        rows = self.conn.execute(
            """SELECT * FROM exceptions
               WHERE status IN ('open', 'resolving', 'escalated')
               ORDER BY
                 CASE severity
                   WHEN 'CRITICAL' THEN 0
                   WHEN 'IMPORTANT' THEN 1
                   WHEN 'NOTABLE' THEN 2
                   WHEN 'INFO' THEN 3
                 END,
                 detected_at DESC"""
        ).fetchall()

        results = []
        for row in rows:
            exc = dict(row)
            exc["payload"] = json.loads(exc["payload"])
            exc["auto_resolution_log"] = json.loads(exc["auto_resolution_log"])
            results.append(exc)
        return results

    def get_exception(self, exception_id: int) -> Optional[dict]:
        """Get a single exception by ID."""
        row = self.conn.execute(
            "SELECT * FROM exceptions WHERE id = ?",
            (exception_id,)
        ).fetchone()
        if not row:
            return None
        exc = dict(row)
        exc["payload"] = json.loads(exc["payload"])
        exc["auto_resolution_log"] = json.loads(exc["auto_resolution_log"])
        return exc

    def get_exceptions_by_type(self, exception_type: str,
                                status: str = None,
                                limit: int = 20) -> list:
        """Get exceptions filtered by type and optionally status."""
        if status:
            rows = self.conn.execute(
                """SELECT * FROM exceptions
                   WHERE exception_type = ? AND status = ?
                   ORDER BY detected_at DESC LIMIT ?""",
                (exception_type, status, limit)
            ).fetchall()
        else:
            rows = self.conn.execute(
                """SELECT * FROM exceptions
                   WHERE exception_type = ?
                   ORDER BY detected_at DESC LIMIT ?""",
                (exception_type, limit)
            ).fetchall()

        results = []
        for row in rows:
            exc = dict(row)
            exc["payload"] = json.loads(exc["payload"])
            exc["auto_resolution_log"] = json.loads(exc["auto_resolution_log"])
            results.append(exc)
        return results

    # ---- Core API: Briefing Formats ----

    def format_exception_brief(self) -> str:
        """
        Generate a formatted exception brief for morning briefings.

        Returns a formatted string suitable for injection into Oracle's
        daily briefing or any agent's context. Returns empty string if
        no open exceptions.
        """
        exceptions = self.get_open_exceptions()
        if not exceptions:
            return ""

        lines = []
        lines.append("=== ACTIVE EXCEPTIONS ===")

        # Group by severity
        by_severity = {}
        for exc in exceptions:
            sev = exc["severity"]
            by_severity.setdefault(sev, []).append(exc)

        for severity in SEVERITIES:
            group = by_severity.get(severity, [])
            if not group:
                continue

            lines.append(f"\n--- {severity} ({len(group)}) ---")
            for exc in group:
                age = self._format_age(exc["detected_at"])
                playbook = PLAYBOOKS.get(exc["exception_type"], {})
                description = playbook.get(
                    "description", exc["exception_type"]
                )

                lines.append(
                    f"  #{exc['id']} [{exc['status'].upper()}] "
                    f"{description}"
                )
                lines.append(f"    Type: {exc['exception_type']}")
                lines.append(f"    Detected: {age} by {exc['detected_by']}")

                # Show key payload fields (compact)
                payload = exc["payload"]
                if payload:
                    key_fields = self._extract_key_fields(
                        exc["exception_type"], payload
                    )
                    if key_fields:
                        lines.append(f"    Context: {key_fields}")

                # Show deadline proximity
                if exc["deadline_at"]:
                    deadline_status = self._format_deadline(exc["deadline_at"])
                    lines.append(f"    Deadline: {deadline_status}")

                # Show what was already done
                action_log = exc["auto_resolution_log"]
                if action_log:
                    done = [a["action"] for a in action_log
                            if a.get("status") == "completed"]
                    if done:
                        lines.append(
                            f"    Auto-resolved: {', '.join(done)}"
                        )

                lines.append("")

        total = len(exceptions)
        escalated = sum(
            1 for e in exceptions if e["status"] == "escalated"
        )
        lines.append(
            f"Total: {total} active exception(s), "
            f"{escalated} escalated to Tom"
        )
        lines.append("")

        return "\n".join(lines)

    def format_escalation_message(self, exception_id: int) -> str:
        """
        Format a complete escalation message for Tom.

        Includes the context template filled with payload data,
        plus escalation criteria so Tom knows exactly what to do.

        Returns empty string if exception not found.
        """
        exc = self.get_exception(exception_id)
        if not exc:
            return ""

        playbook = PLAYBOOKS.get(exc["exception_type"], {})
        payload = exc["payload"]

        # Fill context template with payload data
        template = playbook.get("context_template", "")
        try:
            # Use safe formatting: missing keys become {key} literally
            context = template.format_map(_SafeDict(payload))
        except Exception:
            context = f"Raw payload: {json.dumps(payload, indent=2)}"

        lines = []
        lines.append(f"EXCEPTION #{exc['id']} -- ESCALATED")
        lines.append(f"Type: {exc['exception_type']}")
        lines.append(f"Severity: {exc['severity']}")
        lines.append(f"Detected by: {exc['detected_by']}")
        lines.append(f"Detected at: {exc['detected_at']}")
        lines.append("")
        lines.append(context)
        lines.append("")
        lines.append(f"ESCALATION CRITERIA MET:")
        lines.append(playbook.get("escalation_criteria", "N/A"))
        lines.append("")
        lines.append(
            f"To resolve: reply with the action taken, and it will be "
            f"logged. Or use: resolve_exception({exc['id']}, 'notes')"
        )

        return "\n".join(lines)

    # ---- Core API: Weekly Summary ----

    def get_weekly_summary(self, weeks_back: int = 1) -> dict:
        """
        Generate a weekly summary of exceptions for PREP Monday review.

        Args:
            weeks_back: How many weeks back to summarize (default 1)

        Returns:
            Dict with structured summary data:
            {
                "period": "2026-02-24 to 2026-03-02",
                "total": 15,
                "auto_resolved": 12,
                "escalated": 2,
                "still_open": 1,
                "by_type": {...},
                "by_severity": {...},
                "avg_resolution_minutes": 45.2,
                "fastest_resolution": "stock.low #42 (3m)",
                "slowest_resolution": "order.refund_request #38 (1440m)",
                "narrative": "...",
            }
        """
        cutoff = (
            datetime.now() - timedelta(weeks=weeks_back)
        ).isoformat()

        rows = self.conn.execute(
            """SELECT * FROM exceptions
               WHERE detected_at >= ?
               ORDER BY detected_at ASC""",
            (cutoff,)
        ).fetchall()

        exceptions = []
        for row in rows:
            exc = dict(row)
            exc["payload"] = json.loads(exc["payload"])
            exc["auto_resolution_log"] = json.loads(exc["auto_resolution_log"])
            exceptions.append(exc)

        total = len(exceptions)
        auto_resolved = sum(
            1 for e in exceptions
            if e["status"] == "resolved" and not e.get("escalated_at")
        )
        escalated = sum(
            1 for e in exceptions if e["status"] == "escalated"
            or e.get("escalated_at")
        )
        still_open = sum(
            1 for e in exceptions
            if e["status"] in ("open", "resolving")
        )

        # Group by type
        by_type = {}
        for exc in exceptions:
            t = exc["exception_type"]
            by_type.setdefault(t, {"total": 0, "resolved": 0, "escalated": 0})
            by_type[t]["total"] += 1
            if exc["status"] == "resolved":
                by_type[t]["resolved"] += 1
            if exc["status"] == "escalated" or exc.get("escalated_at"):
                by_type[t]["escalated"] += 1

        # Group by severity
        by_severity = {}
        for exc in exceptions:
            s = exc["severity"]
            by_severity.setdefault(s, 0)
            by_severity[s] += 1

        # Resolution time analysis
        resolution_minutes = []
        for exc in exceptions:
            if exc["status"] == "resolved" and exc.get("resolved_at"):
                try:
                    detected = datetime.fromisoformat(exc["detected_at"])
                    resolved = datetime.fromisoformat(exc["resolved_at"])
                    delta = (resolved - detected).total_seconds() / 60
                    resolution_minutes.append({
                        "id": exc["id"],
                        "type": exc["exception_type"],
                        "minutes": delta,
                    })
                except (ValueError, TypeError):
                    pass

        avg_minutes = 0.0
        fastest = None
        slowest = None
        if resolution_minutes:
            avg_minutes = sum(
                r["minutes"] for r in resolution_minutes
            ) / len(resolution_minutes)
            fastest = min(resolution_minutes, key=lambda r: r["minutes"])
            slowest = max(resolution_minutes, key=lambda r: r["minutes"])

        # Build narrative
        period_start = (
            datetime.now() - timedelta(weeks=weeks_back)
        ).strftime("%Y-%m-%d")
        period_end = datetime.now().strftime("%Y-%m-%d")

        narrative_parts = []
        if total == 0:
            narrative_parts.append(
                "No exceptions detected this week. All systems nominal."
            )
        else:
            narrative_parts.append(
                f"{total} exception(s) detected this week."
            )
            if auto_resolved > 0:
                pct = (auto_resolved / total) * 100
                narrative_parts.append(
                    f"{auto_resolved} ({pct:.0f}%) resolved autonomously "
                    f"without human intervention."
                )
            if escalated > 0:
                narrative_parts.append(
                    f"{escalated} required escalation to Tom."
                )
            if still_open > 0:
                narrative_parts.append(
                    f"{still_open} still open and being tracked."
                )
            if avg_minutes > 0:
                if avg_minutes < 60:
                    narrative_parts.append(
                        f"Average resolution time: {avg_minutes:.0f} minutes."
                    )
                else:
                    narrative_parts.append(
                        f"Average resolution time: "
                        f"{avg_minutes / 60:.1f} hours."
                    )

            # Highlight the most frequent type
            if by_type:
                most_common = max(by_type.items(), key=lambda x: x[1]["total"])
                if most_common[1]["total"] > 1:
                    narrative_parts.append(
                        f"Most frequent: {most_common[0]} "
                        f"({most_common[1]['total']} occurrences)."
                    )

        summary = {
            "period": f"{period_start} to {period_end}",
            "total": total,
            "auto_resolved": auto_resolved,
            "escalated": escalated,
            "still_open": still_open,
            "by_type": by_type,
            "by_severity": by_severity,
            "avg_resolution_minutes": round(avg_minutes, 1),
            "fastest_resolution": (
                f"{fastest['type']} #{fastest['id']} "
                f"({fastest['minutes']:.0f}m)"
                if fastest else None
            ),
            "slowest_resolution": (
                f"{slowest['type']} #{slowest['id']} "
                f"({slowest['minutes']:.0f}m)"
                if slowest else None
            ),
            "narrative": " ".join(narrative_parts),
        }

        return summary

    def format_weekly_summary(self, weeks_back: int = 1) -> str:
        """
        Format the weekly summary as a readable string for PREP.

        Args:
            weeks_back: How many weeks back to summarize

        Returns:
            Formatted multi-line summary string
        """
        summary = self.get_weekly_summary(weeks_back=weeks_back)

        lines = []
        lines.append("=== EXCEPTION ROUTER -- WEEKLY SUMMARY ===")
        lines.append(f"Period: {summary['period']}")
        lines.append("")

        lines.append(f"Total exceptions:    {summary['total']}")
        lines.append(f"Auto-resolved:       {summary['auto_resolved']}")
        lines.append(f"Escalated to Tom:    {summary['escalated']}")
        lines.append(f"Still open:          {summary['still_open']}")
        lines.append("")

        if summary["by_severity"]:
            lines.append("By severity:")
            for sev in SEVERITIES:
                count = summary["by_severity"].get(sev, 0)
                if count > 0:
                    lines.append(f"  {sev:12s} {count:>4d}")
            lines.append("")

        if summary["by_type"]:
            lines.append("By type:")
            for etype, counts in sorted(
                summary["by_type"].items(),
                key=lambda x: x[1]["total"],
                reverse=True
            ):
                lines.append(
                    f"  {etype:30s} "
                    f"total={counts['total']} "
                    f"resolved={counts['resolved']} "
                    f"escalated={counts['escalated']}"
                )
            lines.append("")

        if summary["avg_resolution_minutes"] > 0:
            lines.append(
                f"Avg resolution: {summary['avg_resolution_minutes']}m"
            )
            if summary["fastest_resolution"]:
                lines.append(
                    f"Fastest: {summary['fastest_resolution']}"
                )
            if summary["slowest_resolution"]:
                lines.append(
                    f"Slowest: {summary['slowest_resolution']}"
                )
            lines.append("")

        lines.append(f"Summary: {summary['narrative']}")
        lines.append("")

        return "\n".join(lines)

    # ---- Deadline Enforcement ----

    def check_deadlines(self) -> list:
        """
        Check for exceptions that have passed their deadline without resolution.
        Auto-escalates any that are past due.

        Returns:
            List of exception IDs that were auto-escalated
        """
        now = datetime.now().isoformat()
        rows = self.conn.execute(
            """SELECT * FROM exceptions
               WHERE status IN ('open', 'resolving')
               AND deadline_at IS NOT NULL
               AND deadline_at < ?""",
            (now,)
        ).fetchall()

        escalated_ids = []
        for row in rows:
            exc = dict(row)
            exc["payload"] = json.loads(exc["payload"])
            playbook = PLAYBOOKS.get(exc["exception_type"], {})

            self._escalate(
                exc["id"],
                reason=(
                    f"Auto-escalated: deadline passed "
                    f"({exc['deadline_at']})"
                ),
                payload=exc["payload"],
                playbook=playbook,
            )
            escalated_ids.append(exc["id"])
            logger.warning(
                f"Exception #{exc['id']} ({exc['exception_type']}) "
                f"auto-escalated: deadline passed"
            )

        return escalated_ids

    # ---- Stats ----

    def get_stats(self) -> dict:
        """Get overall exception router statistics."""
        stats = {}

        stats["total"] = self.conn.execute(
            "SELECT COUNT(*) FROM exceptions"
        ).fetchone()[0]
        stats["open"] = self.conn.execute(
            "SELECT COUNT(*) FROM exceptions WHERE status = 'open'"
        ).fetchone()[0]
        stats["resolving"] = self.conn.execute(
            "SELECT COUNT(*) FROM exceptions WHERE status = 'resolving'"
        ).fetchone()[0]
        stats["resolved"] = self.conn.execute(
            "SELECT COUNT(*) FROM exceptions WHERE status = 'resolved'"
        ).fetchone()[0]
        stats["escalated"] = self.conn.execute(
            "SELECT COUNT(*) FROM exceptions WHERE status = 'escalated'"
        ).fetchone()[0]

        # By type (last 7 days)
        cutoff = (datetime.now() - timedelta(days=7)).isoformat()
        rows = self.conn.execute(
            """SELECT exception_type, COUNT(*) as cnt FROM exceptions
               WHERE detected_at > ? GROUP BY exception_type
               ORDER BY cnt DESC""",
            (cutoff,)
        ).fetchall()
        stats["recent_by_type"] = {r["exception_type"]: r["cnt"] for r in rows}

        # Autonomy rate (resolved without escalation / total resolved)
        total_resolved = self.conn.execute(
            "SELECT COUNT(*) FROM exceptions WHERE status = 'resolved'"
        ).fetchone()[0]
        auto_resolved = self.conn.execute(
            """SELECT COUNT(*) FROM exceptions
               WHERE status = 'resolved' AND escalated_at IS NULL"""
        ).fetchone()[0]
        if total_resolved > 0:
            stats["autonomy_rate"] = round(
                auto_resolved / total_resolved * 100, 1
            )
        else:
            stats["autonomy_rate"] = 100.0

        return stats

    # ---- Internal: Auto-Resolution Engine ----

    def _run_auto_resolution(self, exception_id: int, exception_type: str,
                             payload: dict, playbook: dict) -> list:
        """
        Execute the auto-resolution steps defined in a playbook.

        This method does NOT actually call external APIs (those are
        not yet wired). Instead, it records what WOULD be done and
        logs the intent. When write-back clients are wired into
        the orchestrator, these actions will execute for real.

        Returns:
            List of action result dicts
        """
        steps = playbook.get("auto_resolution", [])
        if not steps:
            return []

        self._update_status(exception_id, "resolving")
        action_results = []

        for step in steps:
            action_name = step.get("action", "unknown")
            description = step.get("description", "")

            # Record the action attempt
            cursor = self.conn.execute(
                """INSERT INTO resolution_actions
                   (exception_id, action_name, action_description, status)
                   VALUES (?, ?, ?, 'pending')""",
                (exception_id, action_name, description)
            )
            action_id = cursor.lastrowid

            # Execute the action (or record intent if client not available)
            result = self._execute_action(step, payload, exception_type)

            # Update action record
            status = "completed" if result.get("success") else "failed"
            self.conn.execute(
                """UPDATE resolution_actions
                   SET status = ?, result = ?, completed_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                (status, json.dumps(result), action_id)
            )

            action_results.append({
                "action": action_name,
                "description": description,
                "status": status,
                "result": result,
            })

            logger.info(
                f"  Action '{action_name}' for exception #{exception_id}: "
                f"{status}"
            )

        # Store action log on the exception record
        self.conn.execute(
            "UPDATE exceptions SET auto_resolution_log = ? WHERE id = ?",
            (json.dumps(action_results), exception_id)
        )
        self.conn.commit()

        return action_results

    def _execute_action(self, step: dict, payload: dict,
                        exception_type: str) -> dict:
        """
        Execute a single auto-resolution action.

        Currently records intent; actual API calls happen when
        write-back clients are wired into the orchestrator.

        Returns:
            Dict with: success (bool), message (str), details (dict)
        """
        action = step.get("action", "unknown")

        try:
            if action == "publish_event":
                return self._action_publish_event(step, payload)

            elif action == "log_failure":
                return self._action_log_failure(payload)

            elif action == "log_to_learning_db":
                return self._action_log_to_learning_db(
                    step, payload, exception_type
                )

            elif action == "alert_tom":
                return self._action_alert_tom(step, payload, exception_type)

            elif action in (
                "check_inventory", "pause_ad_set", "reduce_budget",
                "create_asana_task", "tag_vip", "trigger_vip_flow",
                "trigger_winback_flow", "tag_customer", "retry",
            ):
                # These require write-back clients. Record intent for now.
                return self._action_record_intent(step, payload)

            else:
                return {
                    "success": True,
                    "message": f"Unknown action '{action}' -- recorded",
                    "details": step,
                }

        except Exception as e:
            logger.error(
                f"Action '{action}' failed: {e}", exc_info=True
            )
            return {
                "success": False,
                "message": f"Action failed: {str(e)}",
                "details": {"error": str(e)},
            }

    def _action_publish_event(self, step: dict, payload: dict) -> dict:
        """Publish an event to the event bus."""
        try:
            from core.event_bus import EventBus
            bus = EventBus()
            event_type = step.get("event_type", "system.exception")
            severity = step.get("event_severity", "NOTABLE")
            event_id = bus.publish(
                source_agent="exception-router",
                event_type=event_type,
                severity=severity,
                payload=payload,
            )
            bus.close()
            return {
                "success": True,
                "message": f"Published event #{event_id}: {event_type}",
                "details": {"event_id": event_id},
            }
        except Exception as e:
            logger.error(f"Failed to publish event: {e}")
            return {
                "success": False,
                "message": f"Event publish failed: {str(e)}",
                "details": {"error": str(e)},
            }

    def _action_log_failure(self, payload: dict) -> dict:
        """Log an API failure for pattern analysis."""
        # Failures are already tracked in the exceptions table.
        # This action confirms the intent is recorded.
        return {
            "success": True,
            "message": "Failure logged in exceptions database",
            "details": {
                "service": payload.get("service", "unknown"),
                "endpoint": payload.get("endpoint", "unknown"),
            },
        }

    def _action_log_to_learning_db(self, step: dict, payload: dict,
                                   exception_type: str) -> dict:
        """Log an insight to the learning loop database."""
        try:
            from core.learning_loop import get_db as get_learning_db

            conn = get_learning_db()
            conn.execute(
                """INSERT INTO insights
                   (agent, domain, insight, evidence, confidence, source, tags)
                   VALUES (?, ?, ?, ?, 'EMERGING', ?, ?)""",
                (
                    "exception-router",
                    step.get("domain", "operations"),
                    f"Exception detected: {exception_type}",
                    json.dumps(payload),
                    f"exception:{exception_type}",
                    json.dumps([exception_type, "auto-detected"]),
                )
            )
            conn.commit()
            conn.close()
            return {
                "success": True,
                "message": "Insight logged to learning DB",
                "details": {"domain": step.get("domain", "operations")},
            }
        except Exception as e:
            logger.error(f"Failed to log to learning DB: {e}")
            return {
                "success": False,
                "message": f"Learning DB log failed: {str(e)}",
                "details": {"error": str(e)},
            }

    def _action_alert_tom(self, step: dict, payload: dict,
                          exception_type: str) -> dict:
        """Send an alert to Tom via the notification router."""
        try:
            from core.notification_router import route_notification
            import os

            bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
            chat_id = os.environ.get("TELEGRAM_OWNER_ID", "")

            if not bot_token or not chat_id:
                return {
                    "success": False,
                    "message": (
                        "Alert not sent: TELEGRAM_BOT_TOKEN or "
                        "TELEGRAM_OWNER_ID not set"
                    ),
                    "details": {"recorded": True},
                }

            severity = step.get("severity", "IMPORTANT")
            playbook = PLAYBOOKS.get(exception_type, {})
            template = playbook.get("context_template", "")

            try:
                message = template.format_map(_SafeDict(payload))
            except Exception:
                message = (
                    f"Exception: {exception_type}\n"
                    f"Payload: {json.dumps(payload, indent=2)}"
                )

            route_notification(
                chat_id=chat_id,
                text=message,
                bot_token=bot_token,
                severity=severity,
                agent="exception-router",
            )

            return {
                "success": True,
                "message": f"Alert sent to Tom ({severity})",
                "details": {"severity": severity, "chat_id": chat_id},
            }
        except Exception as e:
            logger.error(f"Failed to alert Tom: {e}")
            return {
                "success": False,
                "message": f"Alert failed: {str(e)}",
                "details": {"error": str(e)},
            }

    def _action_record_intent(self, step: dict, payload: dict) -> dict:
        """
        Record the intent of an action that requires a write-back client.

        When the write-back clients are wired into the orchestrator,
        this method will be replaced with actual API calls. For now,
        it documents exactly what would happen.
        """
        client = step.get("client", "unknown")
        method = step.get("method", "unknown")

        # Build a human-readable intent description
        intent_parts = [
            f"INTENT: {client}.{method}()",
        ]

        # Include any templated fields
        for key in ("task_title", "task_description", "tags",
                    "event_name", "budget_reduction_pct"):
            if key in step:
                value = step[key]
                if isinstance(value, str) and "{" in value:
                    try:
                        value = value.format_map(_SafeDict(payload))
                    except Exception:
                        pass
                intent_parts.append(f"  {key}: {value}")

        return {
            "success": True,
            "message": (
                f"Action recorded (client not yet wired): "
                f"{client}.{method}"
            ),
            "details": {
                "client": client,
                "method": method,
                "intent": "\n".join(intent_parts),
                "requires_wiring": True,
            },
        }

    # ---- Internal: Status Management ----

    def _update_status(self, exception_id: int, status: str):
        """Update the status of an exception."""
        self.conn.execute(
            "UPDATE exceptions SET status = ? WHERE id = ?",
            (status, exception_id)
        )
        self.conn.commit()

    def _get_status(self, exception_id: int) -> str:
        """Get the current status of an exception."""
        row = self.conn.execute(
            "SELECT status FROM exceptions WHERE id = ?",
            (exception_id,)
        ).fetchone()
        return row["status"] if row else "unknown"

    def _escalate(self, exception_id: int, reason: str,
                  payload: dict, playbook: dict):
        """Escalate an exception to Tom."""
        self.conn.execute(
            """UPDATE exceptions
               SET status = 'escalated',
                   escalation_reason = ?,
                   escalated_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (reason, exception_id)
        )
        self.conn.commit()

        logger.warning(
            f"Exception #{exception_id} ESCALATED: {reason}"
        )

        # Attempt to send escalation alert to Tom
        try:
            self._action_alert_tom(
                {"severity": "CRITICAL"},
                payload,
                # Find exception type from the record
                self.conn.execute(
                    "SELECT exception_type FROM exceptions WHERE id = ?",
                    (exception_id,)
                ).fetchone()["exception_type"],
            )
        except Exception as e:
            logger.error(
                f"Failed to send escalation alert for #{exception_id}: {e}"
            )

    # ---- Internal: Formatting Helpers ----

    @staticmethod
    def _format_age(detected_at_str: str) -> str:
        """Format detection time as human-readable age."""
        try:
            detected = datetime.fromisoformat(detected_at_str)
            delta = datetime.now() - detected
            total_seconds = int(delta.total_seconds())
            if total_seconds < 60:
                return f"{total_seconds}s ago"
            elif total_seconds < 3600:
                return f"{total_seconds // 60}m ago"
            elif total_seconds < 86400:
                hours = total_seconds // 3600
                mins = (total_seconds % 3600) // 60
                return f"{hours}h {mins}m ago"
            else:
                days = total_seconds // 86400
                hours = (total_seconds % 86400) // 3600
                return f"{days}d {hours}h ago"
        except (ValueError, TypeError):
            return "unknown"

    @staticmethod
    def _format_deadline(deadline_str: str) -> str:
        """Format deadline as time remaining or overdue."""
        try:
            deadline = datetime.fromisoformat(deadline_str)
            delta = deadline - datetime.now()
            total_seconds = int(delta.total_seconds())

            if total_seconds < 0:
                overdue = abs(total_seconds)
                if overdue < 3600:
                    return f"OVERDUE by {overdue // 60}m"
                else:
                    return f"OVERDUE by {overdue // 3600}h"
            elif total_seconds < 3600:
                return f"{total_seconds // 60}m remaining"
            elif total_seconds < 86400:
                return f"{total_seconds // 3600}h remaining"
            else:
                return f"{total_seconds // 86400}d remaining"
        except (ValueError, TypeError):
            return "unknown"

    @staticmethod
    def _extract_key_fields(exception_type: str, payload: dict) -> str:
        """Extract the most important fields from a payload for brief display."""
        # Define key fields per exception type for compact display
        key_field_map = {
            "stock.low": ["product", "current_stock", "days_remaining"],
            "campaign.roas_drop": ["campaign", "roas", "prev_roas"],
            "campaign.budget_overspend": [
                "campaign", "daily_budget", "actual_spend"
            ],
            "order.high_value": [
                "order_name", "customer_name", "order_value"
            ],
            "order.refund_request": [
                "order_name", "customer_name", "order_value", "reason"
            ],
            "customer.churn_risk": [
                "customer_name", "days_since_order", "lifetime_value"
            ],
            "email.deliverability_drop": [
                "deliverability_rate", "prev_rate", "bounce_rate"
            ],
            "system.api_failure": ["service", "endpoint", "failure_count"],
            "invoice.missing_docs": [
                "invoice_ref", "vendor", "amount", "due_date"
            ],
        }

        fields = key_field_map.get(exception_type, [])
        if not fields:
            # Fallback: show first 3 keys
            fields = list(payload.keys())[:3]

        parts = []
        for field in fields:
            if field in payload:
                value = payload[field]
                # Compact display
                if isinstance(value, float):
                    parts.append(f"{field}={value:.1f}")
                else:
                    val_str = str(value)
                    if len(val_str) > 40:
                        val_str = val_str[:37] + "..."
                    parts.append(f"{field}={val_str}")

        return ", ".join(parts) if parts else ""

    # ---- Cleanup ----

    def close(self):
        """Close the database connection."""
        self.conn.close()


# ---- Safe Dict for Template Formatting ----

class _SafeDict(dict):
    """
    Dict subclass that returns '{key}' for missing keys
    instead of raising KeyError. Used for safe .format_map() calls.
    """
    def __missing__(self, key):
        return "{" + key + "}"


# ---- CLI ----

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    router = ExceptionRouter()

    def print_usage():
        print("Exception Router CLI")
        print("=" * 60)
        print("Commands:")
        print("  python exception_router.py detect <type> <payload_json> [agent]")
        print("                                -- Detect an exception")
        print("  python exception_router.py open")
        print("                                -- Show all open exceptions")
        print("  python exception_router.py brief")
        print("                                -- Show formatted brief for briefings")
        print("  python exception_router.py resolve <id> [notes]")
        print("                                -- Mark exception as resolved")
        print("  python exception_router.py escalate-msg <id>")
        print("                                -- Show escalation message")
        print("  python exception_router.py deadlines")
        print("                                -- Check and enforce deadlines")
        print("  python exception_router.py weekly")
        print("                                -- Show weekly summary")
        print("  python exception_router.py stats")
        print("                                -- Show statistics")
        print("  python exception_router.py types")
        print("                                -- List all exception types")
        print("  python exception_router.py test")
        print("                                -- Run test scenarios")
        print()
        print("Exception types:")
        for etype, pb in PLAYBOOKS.items():
            print(f"  {etype:30s} [{pb['severity']}] {pb['description']}")

    if len(sys.argv) < 2:
        print_usage()
        router.close()
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "detect":
        if len(sys.argv) < 4:
            print(
                "Usage: python exception_router.py detect <type> "
                "'<payload_json>' [agent_name]"
            )
            print(
                "Example: python exception_router.py detect stock.low "
                "'{\"product\":\"Marine Collagen\",\"current_stock\":12,"
                "\"daily_velocity\":4.2,\"days_remaining\":2.9}' "
                "dbh-marketing"
            )
            router.close()
            sys.exit(1)

        etype = sys.argv[2]
        try:
            payload = json.loads(sys.argv[3])
        except json.JSONDecodeError as e:
            print(f"Invalid JSON payload: {e}")
            router.close()
            sys.exit(1)

        agent = sys.argv[4] if len(sys.argv) > 4 else None
        result = router.detect_exception(etype, payload, agent_name=agent)
        print(f"\nException #{result['id']} detected:")
        print(f"  Type:     {result['type']}")
        print(f"  Severity: {result['severity']}")
        print(f"  Status:   {result['status']}")
        print(f"  Escalated: {result['escalated']}")
        print(f"  Deadline: {result['deadline_minutes']}m")
        if result["actions_taken"]:
            print(f"\n  Auto-resolution actions:")
            for action in result["actions_taken"]:
                print(
                    f"    [{action['status'].upper()}] {action['action']}: "
                    f"{action['description']}"
                )
                if action["result"].get("message"):
                    print(f"      -> {action['result']['message']}")

    elif cmd == "open":
        exceptions = router.get_open_exceptions()
        if not exceptions:
            print("No open exceptions. All clear.")
        else:
            print(f"\n{len(exceptions)} open exception(s):\n")
            for exc in exceptions:
                print(
                    f"  #{exc['id']} [{exc['severity']}] [{exc['status'].upper()}] "
                    f"{exc['exception_type']}"
                )
                print(f"    Detected by: {exc['detected_by']}")
                print(f"    Detected at: {exc['detected_at']}")
                if exc.get("deadline_at"):
                    deadline_status = ExceptionRouter._format_deadline(
                        exc["deadline_at"]
                    )
                    print(f"    Deadline: {deadline_status}")
                print()

    elif cmd == "brief":
        brief = router.format_exception_brief()
        if brief:
            print(brief)
        else:
            print("No active exceptions to report.")

    elif cmd == "resolve":
        if len(sys.argv) < 3:
            print("Usage: python exception_router.py resolve <id> [notes]")
            router.close()
            sys.exit(1)
        exc_id = int(sys.argv[2])
        notes = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else ""
        success = router.resolve_exception(exc_id, notes)
        if success:
            print(f"Exception #{exc_id} resolved.")
        else:
            print(f"Exception #{exc_id} not found.")

    elif cmd == "escalate-msg":
        if len(sys.argv) < 3:
            print(
                "Usage: python exception_router.py escalate-msg <id>"
            )
            router.close()
            sys.exit(1)
        exc_id = int(sys.argv[2])
        msg = router.format_escalation_message(exc_id)
        if msg:
            print(msg)
        else:
            print(f"Exception #{exc_id} not found.")

    elif cmd == "deadlines":
        escalated = router.check_deadlines()
        if escalated:
            print(
                f"Auto-escalated {len(escalated)} exception(s): "
                f"{escalated}"
            )
        else:
            print("No exceptions past deadline.")

    elif cmd == "weekly":
        print(router.format_weekly_summary())

    elif cmd == "stats":
        stats = router.get_stats()
        print("Exception Router Statistics")
        print("=" * 40)
        print(f"  Total exceptions:  {stats['total']:>6d}")
        print(f"  Open:              {stats['open']:>6d}")
        print(f"  Resolving:         {stats['resolving']:>6d}")
        print(f"  Resolved:          {stats['resolved']:>6d}")
        print(f"  Escalated:         {stats['escalated']:>6d}")
        print(f"  Autonomy rate:     {stats['autonomy_rate']:>5.1f}%")
        if stats["recent_by_type"]:
            print()
            print("Recent exceptions by type (last 7 days):")
            for etype, cnt in stats["recent_by_type"].items():
                print(f"  {etype:30s} {cnt:>4d}")

    elif cmd == "types":
        print("Exception Types and Playbooks")
        print("=" * 60)
        for etype, pb in PLAYBOOKS.items():
            print(f"\n{etype}")
            print(f"  Severity: {pb['severity']}")
            print(f"  Description: {pb['description']}")
            print(f"  Deadline: {pb.get('deadline_minutes', '?')}m")
            print(f"  Auto-resolution steps:")
            for step in pb.get("auto_resolution", []):
                client = step.get("client", "")
                method = step.get("method", "")
                approval = "NO" if not step.get("requires_approval") else "YES"
                if client:
                    print(
                        f"    - {step['description']} "
                        f"[{client}.{method}] "
                        f"(approval: {approval})"
                    )
                else:
                    print(
                        f"    - {step['description']} "
                        f"(approval: {approval})"
                    )
            print(f"  Escalation criteria:")
            print(f"    {pb['escalation_criteria']}")

    elif cmd == "test":
        print("=== Exception Router Test Scenarios ===\n")

        # Test 1: Low stock
        print("1. Low stock detection:")
        result = router.detect_exception("stock.low", {
            "product": "Marine Collagen 300g",
            "sku": "MC-300",
            "current_stock": 12,
            "daily_velocity": 4.2,
            "days_remaining": 2.9,
        }, agent_name="dbh-marketing")
        print(
            f"   #{result['id']} [{result['severity']}] "
            f"status={result['status']} "
            f"escalated={result['escalated']}"
        )
        print(
            f"   Actions: {len(result['actions_taken'])} taken"
        )

        # Test 2: ROAS drop
        print("\n2. Campaign ROAS drop:")
        result = router.detect_exception("campaign.roas_drop", {
            "campaign": "GLM March Promo",
            "channel": "meta",
            "roas": 1.3,
            "prev_roas": 5.4,
            "drop_pct": -76,
            "daily_spend": 150,
        }, agent_name="dbh-marketing")
        print(
            f"   #{result['id']} [{result['severity']}] "
            f"status={result['status']} "
            f"escalated={result['escalated']}"
        )
        print(
            f"   Actions: {len(result['actions_taken'])} taken"
        )

        # Test 3: High-value order
        print("\n3. High-value order:")
        result = router.detect_exception("order.high_value", {
            "order_name": "#DBH-4521",
            "customer_name": "Jane Smith",
            "customer_email": "jane@example.com",
            "order_value": 450.00,
            "items": "Marine Collagen x3, Joint Formula x2",
            "lifetime_orders": 8,
            "lifetime_value": 2340.00,
        }, agent_name="order-intelligence")
        print(
            f"   #{result['id']} [{result['severity']}] "
            f"status={result['status']} "
            f"escalated={result['escalated']}"
        )

        # Test 4: CRITICAL -- deliverability drop
        print("\n4. Email deliverability drop (CRITICAL):")
        result = router.detect_exception("email.deliverability_drop", {
            "deliverability_rate": 82.3,
            "prev_rate": 97.1,
            "drop_pct": -15.2,
            "bounce_rate": 8.4,
            "spam_rate": 0.15,
        }, agent_name="dbh-marketing")
        print(
            f"   #{result['id']} [{result['severity']}] "
            f"status={result['status']} "
            f"escalated={result['escalated']}"
        )

        # Test 5: API failure
        print("\n5. API failure:")
        result = router.detect_exception("system.api_failure", {
            "service": "Klaviyo",
            "endpoint": "/api/campaigns",
            "error": "Connection timeout after 30s",
            "status_code": 504,
            "failure_count": 3,
            "first_failure_at": "2026-03-02T08:15:00",
            "retry_count": 3,
        }, agent_name="command-center")
        print(
            f"   #{result['id']} [{result['severity']}] "
            f"status={result['status']} "
            f"escalated={result['escalated']}"
        )

        # Show brief
        print("\n" + "=" * 60)
        brief = router.format_exception_brief()
        if brief:
            print(brief)

        # Show escalation message for the CRITICAL one
        print("=" * 60)
        print("Escalation message for deliverability drop:")
        msg = router.format_escalation_message(result["id"] - 1)
        if msg:
            print(msg)

        # Show weekly summary
        print("=" * 60)
        print(router.format_weekly_summary())

        # Show stats
        print("=" * 60)
        stats = router.get_stats()
        print(f"Autonomy rate: {stats['autonomy_rate']}%")

        # Resolve a couple
        router.resolve_exception(1, "Reorder placed with supplier")
        router.resolve_exception(3, "VIP flow confirmed active")

        print("\nAfter resolving #1 and #3:")
        stats = router.get_stats()
        print(f"  Open: {stats['open']}, Resolved: {stats['resolved']}, "
              f"Escalated: {stats['escalated']}")
        print(f"  Autonomy rate: {stats['autonomy_rate']}%")

    else:
        print(f"Unknown command: {cmd}")
        print()
        print_usage()

    router.close()
