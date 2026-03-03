#!/usr/bin/env python3
"""
Data Audit Framework — Reconcile across all business data sources.
Compares: Shopify orders, Meta spend, Xero financials, Klaviyo events.
Flags discrepancies, creates unified source of truth.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import sqlite3

logger = logging.getLogger(__name__)


class DataAudit:
    """Systematic framework to audit business data sources."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.audit_db = base_dir / "data" / "audit.db"
        self.audit_log = base_dir / "agents" / "shared" / "audit_log.md"
        self._init_db()

    def _init_db(self):
        """Initialize audit database."""
        conn = sqlite3.connect(self.audit_db)
        c = conn.cursor()

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_runs (
                id INTEGER PRIMARY KEY,
                run_date TIMESTAMP,
                source TEXT,
                metric TEXT,
                expected_value REAL,
                actual_value REAL,
                discrepancy REAL,
                status TEXT,
                notes TEXT
            )
        """
        )

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS reconciliation_status (
                source TEXT PRIMARY KEY,
                last_reconciled TIMESTAMP,
                status TEXT,
                discrepancies_count INTEGER,
                is_trusted INTEGER
            )
        """
        )

        conn.commit()
        conn.close()

    def audit_shopify_orders(self, start_date: str, end_date: str) -> Dict:
        """
        Audit Shopify order data.
        Checks: order counts, revenue, customer attribution.
        """
        result = {
            "source": "shopify",
            "period": f"{start_date} to {end_date}",
            "checks": [],
            "issues": [],
        }

        try:
            # Would import data_fetcher to get actual Shopify data
            # For now, return structure
            result["checks"] = [
                {"metric": "order_count", "status": "pending", "note": "Need Shopify API call"},
                {"metric": "total_revenue", "status": "pending", "note": "Need Shopify API call"},
                {"metric": "refund_count", "status": "pending", "note": "Need Shopify API call"},
            ]

            logger.info(f"Shopify audit for {start_date}-{end_date}")

        except Exception as e:
            result["issues"].append(f"Shopify audit error: {e}")

        return result

    def audit_meta_spend(self, start_date: str, end_date: str) -> Dict:
        """
        Audit Meta Ads spend data.
        Checks: total spend, ROAS, cost per acquisition.
        """
        result = {
            "source": "meta",
            "period": f"{start_date} to {end_date}",
            "checks": [],
            "issues": [],
        }

        try:
            result["checks"] = [
                {"metric": "total_spend", "status": "pending", "note": "Need Meta API call"},
                {"metric": "impressions", "status": "pending", "note": "Need Meta API call"},
                {"metric": "conversions", "status": "pending", "note": "Need Meta API call"},
            ]

            logger.info(f"Meta audit for {start_date}-{end_date}")

        except Exception as e:
            result["issues"].append(f"Meta audit error: {e}")

        return result

    def audit_xero_financials(self, start_date: str, end_date: str) -> Dict:
        """
        Audit Xero financial records.
        Checks: invoice totals, payments reconciled, expense categories.
        """
        result = {
            "source": "xero",
            "period": f"{start_date} to {end_date}",
            "checks": [],
            "issues": [],
        }

        try:
            result["checks"] = [
                {"metric": "total_invoices", "status": "pending", "note": "Need Xero API call"},
                {"metric": "payments_received", "status": "pending", "note": "Need Xero API call"},
                {"metric": "reconciliation_status", "status": "CRITICAL", "note": "Check if period is reconciled"},
            ]

            logger.warning("Xero: Many periods are unreconciled. Only trust past reconciled data.")
            result["issues"].append("WARNING: Xero period may not be fully reconciled")

        except Exception as e:
            result["issues"].append(f"Xero audit error: {e}")

        return result

    def audit_klaviyo_events(self, start_date: str, end_date: str) -> Dict:
        """
        Audit Klaviyo event tracking.
        Checks: event counts, list growth, email engagement.
        """
        result = {
            "source": "klaviyo",
            "period": f"{start_date} to {end_date}",
            "checks": [],
            "issues": [],
        }

        try:
            result["checks"] = [
                {"metric": "event_count", "status": "pending", "note": "Need Klaviyo API call"},
                {"metric": "list_subscribers", "status": "pending", "note": "Need Klaviyo API call"},
                {"metric": "email_opens", "status": "pending", "note": "Need Klaviyo API call"},
            ]

            logger.info(f"Klaviyo audit for {start_date}-{end_date}")

        except Exception as e:
            result["issues"].append(f"Klaviyo audit error: {e}")

        return result

    def cross_source_reconciliation(self, start_date: str, end_date: str) -> Dict:
        """
        Reconcile data across sources.
        Example: Shopify revenue should match Meta spend ROAS + Xero invoices.
        """
        result = {
            "period": f"{start_date} to {end_date}",
            "reconciliations": [],
            "discrepancies": [],
        }

        try:
            # Check 1: Shopify revenue vs Xero invoices
            result["reconciliations"].append(
                {
                    "check": "Shopify revenue vs Xero invoices",
                    "status": "pending",
                    "note": "Need API calls to compare",
                }
            )

            # Check 2: Meta spend vs Shopify attribution
            result["reconciliations"].append(
                {
                    "check": "Meta spend vs Shopify attributed revenue",
                    "status": "pending",
                    "note": "Verify ROAS calculation",
                }
            )

            # Check 3: Klaviyo events vs Shopify events
            result["reconciliations"].append(
                {
                    "check": "Klaviyo purchases vs Shopify orders",
                    "status": "pending",
                    "note": "Verify event tracking accuracy",
                }
            )

            logger.info(f"Cross-source reconciliation for {start_date}-{end_date}")

        except Exception as e:
            result["discrepancies"].append(f"Reconciliation error: {e}")

        return result

    def run_full_audit(self, start_date: str, end_date: str) -> Dict:
        """Run complete audit across all sources."""
        audit_result = {
            "timestamp": datetime.now().isoformat(),
            "period": f"{start_date} to {end_date}",
            "sources": {},
            "cross_source": {},
            "summary": {},
        }

        # Individual source audits
        audit_result["sources"]["shopify"] = self.audit_shopify_orders(start_date, end_date)
        audit_result["sources"]["meta"] = self.audit_meta_spend(start_date, end_date)
        audit_result["sources"]["xero"] = self.audit_xero_financials(start_date, end_date)
        audit_result["sources"]["klaviyo"] = self.audit_klaviyo_events(start_date, end_date)

        # Cross-source reconciliation
        audit_result["cross_source"] = self.cross_source_reconciliation(start_date, end_date)

        # Summary
        total_checks = sum(
            len(src.get("checks", [])) for src in audit_result["sources"].values()
        )
        total_issues = sum(
            len(src.get("issues", [])) for src in audit_result["sources"].values()
        )

        audit_result["summary"] = {
            "total_checks": total_checks,
            "total_issues": total_issues,
            "status": "PENDING_MANUAL_REVIEW" if total_issues > 0 else "CLEAN",
            "recommended_action": "Review all pending checks with actual API data",
        }

        logger.info(f"Audit complete: {total_checks} checks, {total_issues} issues")
        return audit_result

    def log_audit_result(self, audit_result: Dict) -> bool:
        """Log audit result to database and markdown."""
        try:
            # Log to database
            conn = sqlite3.connect(self.audit_db)
            c = conn.cursor()

            for source, data in audit_result.get("sources", {}).items():
                for check in data.get("checks", []):
                    c.execute(
                        """
                        INSERT INTO audit_runs
                        (run_date, source, metric, status, notes)
                        VALUES (?, ?, ?, ?, ?)
                    """,
                        (
                            audit_result["timestamp"],
                            source,
                            check.get("metric", "unknown"),
                            check.get("status", "unknown"),
                            check.get("note", ""),
                        ),
                    )

            conn.commit()
            conn.close()

            # Log to markdown
            self._write_audit_log(audit_result)

            logger.info(f"Audit result logged: {audit_result['summary']}")
            return True

        except Exception as e:
            logger.error(f"Logging error: {e}")
            return False

    def _write_audit_log(self, audit_result: Dict):
        """Write audit result to markdown log."""
        # Ensure directory exists
        self.audit_log.parent.mkdir(parents=True, exist_ok=True)

        with open(self.audit_log, "a") as f:
            f.write(f"\n## Audit — {audit_result['timestamp']}\n\n")
            f.write(f"**Period:** {audit_result['period']}\n\n")

            for source, data in audit_result.get("sources", {}).items():
                f.write(f"### {source.upper()}\n")
                f.write(f"- Status: {data.get('checks', [{}])[0].get('status', 'unknown')}\n")
                f.write(f"- Issues: {len(data.get('issues', []))}\n\n")

            f.write(f"**Summary:** {audit_result['summary']['status']}\n\n")

    def get_reconciliation_status(self) -> Dict:
        """Get overall reconciliation status across all sources."""
        try:
            conn = sqlite3.connect(self.audit_db)
            c = conn.cursor()

            c.execute("SELECT source, last_reconciled, status FROM reconciliation_status")
            status = {row[0]: {"last_reconciled": row[1], "status": row[2]} for row in c.fetchall()}

            conn.close()
            return status

        except Exception as e:
            logger.error(f"Status check error: {e}")
            return {}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    base_dir = Path(__file__).resolve().parent.parent
    audit = DataAudit(base_dir)

    print("\n=== DATA AUDIT FRAMEWORK ===")
    # Run last 7 days
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=7)

    result = audit.run_full_audit(str(start_date), str(end_date))
    print(json.dumps(result, indent=2))
