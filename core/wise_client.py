#!/usr/bin/env python3
"""
Wise (TransferWise) Business API Client -- Bearer token authenticated client
for multi-currency account management, transfers, and financial reporting.

Uses Wise Platform API v1/v3/v4.

API Base URLs:
  - Production: https://api.wise.com
  - Sandbox:    https://api.sandbox.wise.com

Authentication:
  - API token generated from Wise Business Settings > API tokens
  - Bearer token in Authorization header
  - Token stored in env var WISE_API_TOKEN or ~/.wise_tokens.json

Rate Limits:
  - Wise applies rate limiting per API token
  - 429 response when limit exceeded with Retry-After header

What can be done WITHOUT human approval (SAFE -- read-only):
  - Get profiles (personal/business)
  - Get all currency balances
  - Get exchange rates
  - List transfers and transfer details
  - Get account statements
  - Generate financial snapshots

What NEEDS human approval:
  - Create quotes (pre-transfer pricing)
  - Create transfers (financial commitment)
  - Fund transfers (money movement)
"""

import os
import json
import time
import uuid
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

TOKEN_FILE = Path.home() / ".wise_tokens.json"


class WiseClient:
    """
    Bearer token authenticated client for Wise Platform API.

    Handles multi-currency balances, transfers, exchange rates,
    and account statements for business and personal profiles.
    """

    API_URL = "https://api.wise.com"
    SANDBOX_URL = "https://api.sandbox.wise.com"

    def __init__(self, token_file: str = None, sandbox: bool = False):
        self._api_token = os.environ.get("WISE_API_TOKEN")
        self.token_file = Path(token_file) if token_file else TOKEN_FILE
        self._sandbox = sandbox
        self._base_url = self.SANDBOX_URL if sandbox else self.API_URL
        self._profiles_cache = None
        self._profiles_cache_time = 0

        # Fall back to token file if env var not set
        if not self._api_token:
            self._load_token()

    @property
    def available(self) -> bool:
        """Check if Wise credentials are configured."""
        return bool(self._api_token)

    # ===================================================================
    # TOKEN MANAGEMENT
    # ===================================================================

    def _load_token(self):
        """Load API token from file."""
        try:
            if self.token_file.exists():
                with open(self.token_file) as f:
                    data = json.load(f)
                self._api_token = data.get("api_token") or data.get("token")
                if self._api_token:
                    logger.info("Wise API token loaded from file")
        except Exception as e:
            logger.warning(f"Could not load Wise token: {e}")
            self._api_token = None

    def save_token(self, api_token: str):
        """
        Save API token to file for persistence.

        Args:
            api_token: Wise API token from Business Settings
        """
        try:
            data = {"api_token": api_token, "saved_at": datetime.now().isoformat()}
            with open(self.token_file, "w") as f:
                json.dump(data, f, indent=2)
            self.token_file.chmod(0o600)
            self._api_token = api_token
            logger.info(f"Wise token saved to {self.token_file}")
        except Exception as e:
            logger.error(f"Could not save Wise token: {e}")

    # ===================================================================
    # INTERNAL HTTP METHODS
    # ===================================================================

    def _request(self, method: str, path: str, data: dict = None,
                 params: dict = None, max_retries: int = 3) -> dict:
        """Make an authenticated API request with retry logic."""
        import requests

        if not self._api_token:
            raise Exception("No Wise API token. Set WISE_API_TOKEN env var or save token to ~/.wise_tokens.json")

        url = f"{self._base_url}/{path.lstrip('/')}"

        headers = {
            "Authorization": f"Bearer {self._api_token}",
            "Content-Type": "application/json",
        }

        for attempt in range(max_retries):
            try:
                resp = requests.request(
                    method, url, headers=headers,
                    json=data, params=params, timeout=30
                )

                # Handle rate limiting
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", 60))
                    logger.warning(f"Wise rate limited. Waiting {retry_after}s (attempt {attempt + 1})")
                    time.sleep(retry_after)
                    continue

                # Handle auth failure
                if resp.status_code == 401:
                    raise Exception("Wise authentication failed -- check API token")

                # Handle forbidden
                if resp.status_code == 403:
                    raise Exception("Wise access forbidden -- token may lack required permissions")

                resp.raise_for_status()
                return resp.json() if resp.content else {}

            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"Wise {method} {path} failed after {max_retries} attempts: {e}")
                    raise
                wait_time = 2 ** attempt
                logger.warning(f"Wise request failed, retrying in {wait_time}s: {e}")
                time.sleep(wait_time)

        return {}

    def _get(self, path: str, params: dict = None) -> dict:
        return self._request("GET", path, params=params)

    def _post(self, path: str, data: dict = None) -> dict:
        return self._request("POST", path, data=data)

    # ===================================================================
    # 1. PROFILES
    #    Endpoint: GET /v2/profiles
    #    Autonomy: SAFE -- read-only
    # ===================================================================

    def get_profiles(self) -> list:
        """
        List all profiles (personal and business) for the authenticated user.

        GET /v2/profiles

        Returns:
            List of profile objects with id, type, fullName, etc.

        Example response item:
            {"id": 12345, "type": "BUSINESS", "details": {"name": "Deep Blue Health"}}
        """
        # Cache profiles for 5 minutes to reduce API calls
        now = time.time()
        if self._profiles_cache and (now - self._profiles_cache_time) < 300:
            return self._profiles_cache

        result = self._get("v2/profiles")
        profiles = result if isinstance(result, list) else []
        self._profiles_cache = profiles
        self._profiles_cache_time = now
        logger.info(f"Fetched {len(profiles)} Wise profile(s)")
        return profiles

    def get_business_profile_id(self) -> Optional[int]:
        """
        Get the first business profile ID.
        Convenience method -- most operations need a profile ID.

        Returns:
            Business profile ID or None
        """
        for p in self.get_profiles():
            if p.get("type") == "BUSINESS":
                return p["id"]
        # Fall back to personal if no business profile
        profiles = self.get_profiles()
        if profiles:
            return profiles[0]["id"]
        return None

    def get_personal_profile_id(self) -> Optional[int]:
        """
        Get the personal profile ID.

        Returns:
            Personal profile ID or None
        """
        for p in self.get_profiles():
            if p.get("type") == "PERSONAL":
                return p["id"]
        return None

    # ===================================================================
    # 2. BALANCES
    #    Endpoint: GET /v4/profiles/{profileId}/balances?types=STANDARD
    #    Autonomy: SAFE -- read-only
    # ===================================================================

    def get_balances(self, profile_id: int = None,
                     balance_types: str = "STANDARD") -> list:
        """
        Get all currency balances for a profile.

        GET /v4/profiles/{profileId}/balances?types={types}

        Args:
            profile_id: Profile ID (defaults to business profile)
            balance_types: Comma-separated types: "STANDARD", "SAVINGS",
                          or "STANDARD,SAVINGS" for both

        Returns:
            List of balance objects:
                {
                    "id": 200001,
                    "currency": "NZD",
                    "type": "STANDARD",
                    "amount": {"value": 1234.56, "currency": "NZD"},
                    "reservedAmount": {"value": 0, "currency": "NZD"},
                    "cashAmount": {"value": 1234.56, "currency": "NZD"},
                    "totalWorth": {"value": 1234.56, "currency": "NZD"}
                }
        """
        if not profile_id:
            profile_id = self.get_business_profile_id()
        if not profile_id:
            raise Exception("No Wise profile found")

        result = self._get(
            f"v4/profiles/{profile_id}/balances",
            params={"types": balance_types}
        )
        balances = result if isinstance(result, list) else []
        logger.info(f"Fetched {len(balances)} balance(s) for profile {profile_id}")
        return balances

    def get_balance_summary(self, profile_id: int = None) -> str:
        """
        Get formatted multi-currency balance overview.

        Args:
            profile_id: Profile ID (defaults to business profile)

        Returns:
            Formatted text with all currency balances
        """
        try:
            balances = self.get_balances(profile_id)
            if not balances:
                return "[No Wise balances found]"

            lines = ["WISE ACCOUNT BALANCES"]

            for bal in sorted(balances, key=lambda b: b.get("currency", "")):
                currency = bal.get("currency", "???")
                amount_obj = bal.get("amount", {})
                amount = amount_obj.get("value", 0) if isinstance(amount_obj, dict) else 0
                reserved_obj = bal.get("reservedAmount", {})
                reserved = reserved_obj.get("value", 0) if isinstance(reserved_obj, dict) else 0
                bal_type = bal.get("type", "STANDARD")

                line = f"  - {currency}: {amount:,.2f}"
                if reserved > 0:
                    line += f" (reserved: {reserved:,.2f})"
                if bal_type != "STANDARD":
                    line += f" [{bal_type}]"
                lines.append(line)

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Balance summary error: {e}")
            return f"[Wise balance error: {str(e)}]"

    def format_balance_for_briefing(self, profile_id: int = None) -> str:
        """
        Agent-ready balance text for Telegram briefings.
        Uses bullet points, no tables.

        Args:
            profile_id: Profile ID (defaults to business profile)

        Returns:
            Formatted text suitable for Telegram messages
        """
        try:
            balances = self.get_balances(profile_id)
            if not balances:
                return "Wise: No balances available"

            lines = ["Wise Multi-Currency Balances:"]

            for bal in sorted(balances, key=lambda b: b.get("currency", "")):
                currency = bal.get("currency", "???")
                amount_obj = bal.get("amount", {})
                amount = amount_obj.get("value", 0) if isinstance(amount_obj, dict) else 0

                if amount == 0:
                    continue  # Skip zero balances in briefings

                cash_obj = bal.get("cashAmount", {})
                cash = cash_obj.get("value", 0) if isinstance(cash_obj, dict) else 0
                reserved_obj = bal.get("reservedAmount", {})
                reserved = reserved_obj.get("value", 0) if isinstance(reserved_obj, dict) else 0

                line = f"  - {currency}: {amount:,.2f}"
                if reserved > 0:
                    line += f" (held: {reserved:,.2f})"
                lines.append(line)

            if len(lines) == 1:
                lines.append("  - All balances at zero")

            return "\n".join(lines)

        except Exception as e:
            return f"Wise: Unavailable ({str(e)})"

    # ===================================================================
    # 3. TRANSFERS
    #    Endpoint: GET /v1/transfers (list), GET /v1/transfers/{id} (detail)
    #    Endpoint: POST /v1/transfers (create) -- NEEDS APPROVAL
    #    Autonomy: Reads = SAFE, Creates = NEEDS APPROVAL
    # ===================================================================

    def get_transfers(self, profile_id: int = None, status: str = None,
                      limit: int = 10, offset: int = 0,
                      created_date_start: str = None,
                      created_date_end: str = None) -> list:
        """
        List recent transfers.

        GET /v1/transfers

        Args:
            profile_id: Profile ID (defaults to business profile)
            status: Filter by status (comma-separated):
                    "incoming_payment_waiting", "processing",
                    "funds_converted", "outgoing_payment_sent",
                    "cancelled", "funds_refunded", "bounced_back"
            limit: Max results (default 10, max 100)
            offset: Pagination offset
            created_date_start: Filter from date "YYYY-MM-DD"
            created_date_end: Filter to date "YYYY-MM-DD"

        Returns:
            List of transfer objects
        """
        if not profile_id:
            profile_id = self.get_business_profile_id()

        params = {
            "profile": profile_id,
            "limit": min(limit, 100),
            "offset": offset,
        }
        if status:
            params["status"] = status
        if created_date_start:
            params["createdDateStart"] = created_date_start
        if created_date_end:
            params["createdDateEnd"] = created_date_end

        result = self._get("v1/transfers", params=params)
        transfers = result if isinstance(result, list) else []
        logger.info(f"Fetched {len(transfers)} transfer(s)")
        return transfers

    def get_transfer(self, transfer_id: int) -> dict:
        """
        Get a single transfer's details.

        GET /v1/transfers/{transferId}

        Args:
            transfer_id: Transfer ID

        Returns:
            Transfer object with id, status, sourceCurrency, sourceValue,
            targetCurrency, targetValue, rate, created, reference, etc.
        """
        result = self._get(f"v1/transfers/{transfer_id}")
        return result if isinstance(result, dict) else {}

    def create_quote(self, profile_id: int = None,
                     source_currency: str = "NZD",
                     target_currency: str = "USD",
                     source_amount: float = None,
                     target_amount: float = None,
                     pay_out: str = "BANK_TRANSFER") -> dict:
        """
        Create an exchange rate quote. Required before creating a transfer.

        POST /v3/profiles/{profileId}/quotes

        AUTONOMY: NEEDS APPROVAL -- pre-transfer pricing commitment

        Args:
            profile_id: Profile ID (defaults to business profile)
            source_currency: Source currency code (e.g. "NZD")
            target_currency: Target currency code (e.g. "USD")
            source_amount: Amount in source currency (provide this OR target_amount)
            target_amount: Amount in target currency (provide this OR source_amount)
            pay_out: Payout method: "BANK_TRANSFER", "BALANCE", "SWIFT"

        Returns:
            Quote object with id, rate, fee, sourceAmount, targetAmount, etc.
        """
        if not profile_id:
            profile_id = self.get_business_profile_id()
        if not profile_id:
            raise Exception("No Wise profile found")

        if not source_amount and not target_amount:
            raise ValueError("Must provide either source_amount or target_amount")

        payload = {
            "sourceCurrency": source_currency,
            "targetCurrency": target_currency,
            "payOut": pay_out,
        }
        if source_amount:
            payload["sourceAmount"] = source_amount
        if target_amount:
            payload["targetAmount"] = target_amount

        result = self._post(f"v3/profiles/{profile_id}/quotes", data=payload)
        if result:
            logger.info(
                f"Created quote: {source_currency} -> {target_currency}, "
                f"rate={result.get('rate', '?')}"
            )
        return result

    def create_transfer(self, target_account: int, quote_id: str,
                        reference: str = "",
                        transfer_purpose: str = None) -> dict:
        """
        Create a transfer using an existing quote.

        POST /v1/transfers

        AUTONOMY: NEEDS APPROVAL -- financial commitment, money movement

        Args:
            target_account: Recipient account ID
            quote_id: Quote UUID from create_quote()
            reference: Payment reference visible to recipient
            transfer_purpose: Required for some currency routes

        Returns:
            Transfer object with id, status, amounts, rate, etc.
        """
        payload = {
            "targetAccount": target_account,
            "quoteUuid": quote_id,
            "customerTransactionId": str(uuid.uuid4()),
            "details": {
                "reference": reference,
            }
        }
        if transfer_purpose:
            payload["details"]["transferPurpose"] = transfer_purpose

        result = self._post("v1/transfers", data=payload)
        if result:
            logger.info(
                f"Created transfer {result.get('id', '?')}: "
                f"{result.get('sourceCurrency', '?')} {result.get('sourceValue', '?')} -> "
                f"{result.get('targetCurrency', '?')} {result.get('targetValue', '?')}"
            )
        return result

    # ===================================================================
    # 4. EXCHANGE RATES
    #    Endpoint: GET /v1/rates
    #    Autonomy: SAFE -- read-only
    # ===================================================================

    def get_exchange_rate(self, source: str = "NZD",
                         target: str = "USD",
                         time_at: str = None) -> dict:
        """
        Get current mid-market exchange rate.

        GET /v1/rates?source={source}&target={target}

        Args:
            source: Source currency code
            target: Target currency code
            time_at: Optional ISO timestamp for historical rate

        Returns:
            Rate object: {"rate": 0.6123, "source": "NZD", "target": "USD", "time": "..."}
        """
        params = {"source": source, "target": target}
        if time_at:
            params["time"] = time_at

        result = self._get("v1/rates", params=params)
        rates = result if isinstance(result, list) else []
        if rates:
            rate = rates[0]
            logger.info(f"Rate {source}/{target}: {rate.get('rate', '?')}")
            return rate
        return {}

    def get_exchange_rates_bulk(self, source: str = "NZD",
                                targets: list = None) -> list:
        """
        Get exchange rates for multiple target currencies.

        Args:
            source: Source currency code
            targets: List of target currency codes (e.g. ["USD", "AUD", "GBP"])
                    If None, returns all available rates for source

        Returns:
            List of rate objects
        """
        params = {"source": source}
        result = self._get("v1/rates", params=params)
        rates = result if isinstance(result, list) else []

        if targets:
            rates = [r for r in rates if r.get("target") in targets]

        return rates

    # ===================================================================
    # 5. STATEMENTS
    #    Endpoint: GET /v1/profiles/{profileId}/balance-statements/{balanceId}/statement.json
    #    Autonomy: SAFE -- read-only
    # ===================================================================

    def get_statement(self, profile_id: int = None,
                      currency: str = "NZD",
                      start_date: str = None,
                      end_date: str = None,
                      statement_type: str = "COMPACT") -> dict:
        """
        Get account statement for a specific currency balance.

        GET /v1/profiles/{profileId}/balance-statements/{balanceId}/statement.json

        Args:
            profile_id: Profile ID (defaults to business profile)
            currency: Currency code to get statement for
            start_date: Start date ISO format "YYYY-MM-DDT00:00:00.000Z"
            end_date: End date ISO format "YYYY-MM-DDT23:59:59.999Z"
            statement_type: "COMPACT" or "FLAT" (default COMPACT)

        Returns:
            Statement object with transactions list

        Note: Period between start and end cannot exceed 469 days.
        """
        if not profile_id:
            profile_id = self.get_business_profile_id()
        if not profile_id:
            raise Exception("No Wise profile found")

        # Find the balance ID for the requested currency
        balances = self.get_balances(profile_id)
        balance_id = None
        for bal in balances:
            if bal.get("currency") == currency:
                balance_id = bal.get("id")
                break

        if not balance_id:
            raise Exception(f"No Wise balance found for currency {currency}")

        # Default date range: last 30 days
        if not end_date:
            end_date = datetime.utcnow().strftime("%Y-%m-%dT23:59:59.999Z")
        if not start_date:
            start_dt = datetime.utcnow() - timedelta(days=30)
            start_date = start_dt.strftime("%Y-%m-%dT00:00:00.000Z")

        params = {
            "intervalStart": start_date,
            "intervalEnd": end_date,
            "type": statement_type,
        }

        result = self._get(
            f"v1/profiles/{profile_id}/balance-statements/{balance_id}/statement.json",
            params=params
        )
        logger.info(f"Fetched statement for {currency}: {start_date[:10]} to {end_date[:10]}")
        return result

    def format_recent_transactions(self, days: int = 7,
                                   profile_id: int = None) -> str:
        """
        Get formatted recent transaction activity across all currencies.

        Args:
            days: Number of days to look back (default 7)
            profile_id: Profile ID (defaults to business profile)

        Returns:
            Formatted text with recent transactions (bullet points)
        """
        try:
            if not profile_id:
                profile_id = self.get_business_profile_id()

            balances = self.get_balances(profile_id)
            if not balances:
                return "[No Wise balances to check]"

            end_date = datetime.utcnow().strftime("%Y-%m-%dT23:59:59.999Z")
            start_dt = datetime.utcnow() - timedelta(days=days)
            start_date = start_dt.strftime("%Y-%m-%dT00:00:00.000Z")

            lines = [f"WISE TRANSACTIONS (last {days} days)"]
            total_txns = 0

            for bal in balances:
                currency = bal.get("currency", "???")
                balance_id = bal.get("id")
                amount_obj = bal.get("amount", {})
                amount = amount_obj.get("value", 0) if isinstance(amount_obj, dict) else 0

                # Skip currencies with no balance and likely no activity
                # But still try to fetch -- there could be recent zero-balance activity
                if not balance_id:
                    continue

                try:
                    statement = self._get(
                        f"v1/profiles/{profile_id}/balance-statements/{balance_id}/statement.json",
                        params={
                            "intervalStart": start_date,
                            "intervalEnd": end_date,
                            "type": "COMPACT",
                        }
                    )

                    transactions = statement.get("transactions", [])
                    if not transactions:
                        continue

                    lines.append(f"\n  {currency} ({len(transactions)} transactions):")
                    for txn in transactions[:15]:  # Cap at 15 per currency
                        txn_type = txn.get("type", "UNKNOWN")
                        txn_amount = txn.get("amount", {})
                        value = txn_amount.get("value", 0) if isinstance(txn_amount, dict) else 0
                        txn_currency = txn_amount.get("currency", currency) if isinstance(txn_amount, dict) else currency
                        date_str = txn.get("date", "")[:10]
                        details = txn.get("details", {})
                        description = (
                            details.get("description", "")
                            or details.get("senderName", "")
                            or details.get("recipientName", "")
                            or txn_type
                        )

                        sign = "+" if value > 0 else ""
                        lines.append(
                            f"    - {date_str}: {sign}{value:,.2f} {txn_currency} -- {description}"
                        )
                        total_txns += 1

                except Exception as e:
                    logger.warning(f"Could not fetch statement for {currency}: {e}")
                    continue

            if total_txns == 0:
                lines.append("  No transactions in this period")

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Recent transactions error: {e}")
            return f"[Wise transactions error: {str(e)}]"

    # ===================================================================
    # 6. FINANCIAL SNAPSHOT (Briefing Integration)
    #    Combined view for agent briefings
    #    Autonomy: SAFE -- read-only aggregation
    # ===================================================================

    def get_financial_snapshot(self, profile_id: int = None) -> str:
        """
        Combined financial view: all balances + recent transfers + pending.
        Designed for injection into Oracle/PREP agent briefings.

        Returns formatted text suitable for Telegram (bullet points, no tables).

        Args:
            profile_id: Profile ID (defaults to business profile)

        Returns:
            Formatted multi-section financial overview
        """
        sections = [
            "=== WISE FINANCIAL SNAPSHOT ===",
            "",
        ]

        try:
            if not profile_id:
                profile_id = self.get_business_profile_id()

            if not profile_id:
                return "[Wise: No profile found. Check API token permissions.]"

            # --- Balances ---
            sections.append(self.format_balance_for_briefing(profile_id))
            sections.append("")

            # --- Key Exchange Rates ---
            try:
                key_pairs = [
                    ("NZD", "USD"), ("NZD", "AUD"), ("NZD", "GBP"),
                    ("NZD", "EUR"), ("USD", "NZD"),
                ]
                rate_lines = ["Key Exchange Rates:"]
                for source, target in key_pairs:
                    rate_data = self.get_exchange_rate(source, target)
                    if rate_data:
                        rate_val = rate_data.get("rate", 0)
                        rate_lines.append(f"  - {source}/{target}: {rate_val:.4f}")
                sections.append("\n".join(rate_lines))
                sections.append("")
            except Exception as e:
                sections.append(f"Exchange rates: Unavailable ({e})")
                sections.append("")

            # --- Recent Transfers ---
            try:
                transfers = self.get_transfers(profile_id, limit=10)
                if transfers:
                    sections.append("Recent Transfers:")
                    for t in transfers[:10]:
                        status = t.get("status", "unknown")
                        source_cur = t.get("sourceCurrency", "?")
                        source_val = t.get("sourceValue", 0)
                        target_cur = t.get("targetCurrency", "?")
                        target_val = t.get("targetValue", 0)
                        created = t.get("created", "")[:10]
                        reference = t.get("details", {}).get("reference", "") if isinstance(t.get("details"), dict) else ""

                        line = (
                            f"  - {created}: {source_cur} {source_val:,.2f} -> "
                            f"{target_cur} {target_val:,.2f} [{status}]"
                        )
                        if reference:
                            line += f" -- {reference}"
                        sections.append(line)
                else:
                    sections.append("Recent Transfers: None")
                sections.append("")
            except Exception as e:
                sections.append(f"Transfers: Unavailable ({e})")
                sections.append("")

            # --- Pending Transfers ---
            try:
                pending_statuses = "incoming_payment_waiting,processing,funds_converted"
                pending = self.get_transfers(profile_id, status=pending_statuses, limit=10)
                if pending:
                    sections.append(f"Pending/In-Progress ({len(pending)}):")
                    for t in pending:
                        source_cur = t.get("sourceCurrency", "?")
                        source_val = t.get("sourceValue", 0)
                        target_cur = t.get("targetCurrency", "?")
                        target_val = t.get("targetValue", 0)
                        status = t.get("status", "unknown")
                        sections.append(
                            f"  - {source_cur} {source_val:,.2f} -> "
                            f"{target_cur} {target_val:,.2f} [{status}]"
                        )
                else:
                    sections.append("Pending Transfers: None")
            except Exception as e:
                sections.append(f"Pending: Unavailable ({e})")

        except Exception as e:
            sections.append(f"[Wise snapshot error: {str(e)}]")

        return "\n".join(sections)


# ===================================================================
# CLI
# ===================================================================

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    client = WiseClient()

    if len(sys.argv) < 2:
        print("Wise API Client")
        print()
        print("Usage:")
        print("  python -m core.wise_client balances           Show all currency balances")
        print("  python -m core.wise_client transfers          Recent transfers")
        print("  python -m core.wise_client transfer <id>      Transfer details")
        print("  python -m core.wise_client rate NZD USD       Current exchange rate")
        print("  python -m core.wise_client rates NZD          All rates from NZD")
        print("  python -m core.wise_client statement NZD [days]  Account statement")
        print("  python -m core.wise_client transactions [days]   Recent transactions")
        print("  python -m core.wise_client snapshot           Full financial snapshot")
        print("  python -m core.wise_client profiles           List profiles")
        print("  python -m core.wise_client save-token <token> Save API token")
        print()
        print("Environment:")
        print(f"  WISE_API_TOKEN: {'set' if os.environ.get('WISE_API_TOKEN') else 'not set'}")
        print(f"  Token file: {TOKEN_FILE} ({'exists' if TOKEN_FILE.exists() else 'not found'})")
        print(f"  Available: {client.available}")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "save-token":
        if len(sys.argv) < 3:
            print("Usage: python -m core.wise_client save-token <your-api-token>")
            print("Get your token from: Wise Business Settings > API tokens")
            sys.exit(1)
        client.save_token(sys.argv[2])
        print(f"Token saved to {client.token_file}")

    elif cmd == "profiles":
        if not client.available:
            print("No Wise credentials. Set WISE_API_TOKEN or run: python -m core.wise_client save-token <token>")
            sys.exit(1)
        for p in client.get_profiles():
            p_type = p.get("type", "?")
            p_id = p.get("id", "?")
            details = p.get("details", {})
            name = details.get("name") or f"{details.get('firstName', '')} {details.get('lastName', '')}".strip()
            print(f"  - [{p_type}] ID: {p_id} -- {name}")

    elif cmd == "balances":
        if not client.available:
            print("No Wise credentials configured")
            sys.exit(1)
        print(client.get_balance_summary())

    elif cmd == "transfers":
        if not client.available:
            print("No Wise credentials configured")
            sys.exit(1)
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 10
        transfers = client.get_transfers(limit=limit)
        if not transfers:
            print("No transfers found")
        else:
            print(f"Recent Transfers ({len(transfers)}):")
            for t in transfers:
                status = t.get("status", "?")
                source = f"{t.get('sourceCurrency', '?')} {t.get('sourceValue', 0):,.2f}"
                target = f"{t.get('targetCurrency', '?')} {t.get('targetValue', 0):,.2f}"
                created = t.get("created", "")[:19]
                rate = t.get("rate", 0)
                ref = ""
                if isinstance(t.get("details"), dict):
                    ref = t["details"].get("reference", "")
                line = f"  - {created}: {source} -> {target} @ {rate:.4f} [{status}]"
                if ref:
                    line += f" -- {ref}"
                print(line)

    elif cmd == "transfer" and len(sys.argv) > 2:
        if not client.available:
            print("No Wise credentials configured")
            sys.exit(1)
        t = client.get_transfer(int(sys.argv[2]))
        if t:
            print(f"Transfer #{t.get('id', '?')}")
            print(f"  Status: {t.get('status', '?')}")
            print(f"  Source: {t.get('sourceCurrency', '?')} {t.get('sourceValue', 0):,.2f}")
            print(f"  Target: {t.get('targetCurrency', '?')} {t.get('targetValue', 0):,.2f}")
            print(f"  Rate: {t.get('rate', 0):.6f}")
            print(f"  Created: {t.get('created', '?')}")
            if isinstance(t.get("details"), dict):
                print(f"  Reference: {t['details'].get('reference', 'none')}")
            print(f"  Has issues: {t.get('hasActiveIssues', False)}")
        else:
            print("Transfer not found")

    elif cmd == "rate":
        if not client.available:
            print("No Wise credentials configured")
            sys.exit(1)
        source = sys.argv[2] if len(sys.argv) > 2 else "NZD"
        target = sys.argv[3] if len(sys.argv) > 3 else "USD"
        rate_data = client.get_exchange_rate(source, target)
        if rate_data:
            r = rate_data.get("rate", 0)
            print(f"  {source}/{target}: {r:.6f}")
            print(f"  1 {source} = {r:.4f} {target}")
            if r > 0:
                print(f"  1 {target} = {1/r:.4f} {source}")
            print(f"  Time: {rate_data.get('time', '?')}")
        else:
            print(f"No rate found for {source}/{target}")

    elif cmd == "rates":
        if not client.available:
            print("No Wise credentials configured")
            sys.exit(1)
        source = sys.argv[2] if len(sys.argv) > 2 else "NZD"
        rates = client.get_exchange_rates_bulk(source)
        print(f"Exchange rates from {source}:")
        for r in sorted(rates, key=lambda x: x.get("target", "")):
            print(f"  - {source}/{r.get('target', '?')}: {r.get('rate', 0):.6f}")

    elif cmd == "statement":
        if not client.available:
            print("No Wise credentials configured")
            sys.exit(1)
        currency = sys.argv[2] if len(sys.argv) > 2 else "NZD"
        days = int(sys.argv[3]) if len(sys.argv) > 3 else 30
        end_date = datetime.utcnow().strftime("%Y-%m-%dT23:59:59.999Z")
        start_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00.000Z")
        statement = client.get_statement(currency=currency, start_date=start_date, end_date=end_date)
        if statement:
            txns = statement.get("transactions", [])
            print(f"Statement for {currency} (last {days} days): {len(txns)} transactions")
            for txn in txns[:20]:
                txn_amount = txn.get("amount", {})
                value = txn_amount.get("value", 0) if isinstance(txn_amount, dict) else 0
                date = txn.get("date", "")[:10]
                details = txn.get("details", {})
                desc = (
                    details.get("description", "")
                    or details.get("senderName", "")
                    or details.get("recipientName", "")
                    or txn.get("type", "?")
                )
                sign = "+" if value > 0 else ""
                print(f"  - {date}: {sign}{value:,.2f} {currency} -- {desc}")
            if len(txns) > 20:
                print(f"  ... and {len(txns) - 20} more")
        else:
            print(f"No statement data for {currency}")

    elif cmd == "transactions":
        if not client.available:
            print("No Wise credentials configured")
            sys.exit(1)
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        print(client.format_recent_transactions(days=days))

    elif cmd == "snapshot":
        if not client.available:
            print("No Wise credentials configured")
            sys.exit(1)
        print(client.get_financial_snapshot())

    else:
        print(f"Unknown command: {cmd}")
        print("Run without arguments to see usage")
        sys.exit(1)
