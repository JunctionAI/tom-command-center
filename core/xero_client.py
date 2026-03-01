#!/usr/bin/env python3
"""
Xero API Client -- OAuth 2.0 authenticated client for accounting operations.

Handles the full OAuth 2.0 flow with automatic token refresh,
invoice creation, bank reconciliation, P&L reports, and expense management.

Uses Xero Accounting API v2.0.

Rate Limits:
  - 5 concurrent API calls per organisation per app
  - 60 API calls per minute per organisation per app
  - 5,000 API calls per day per organisation per app
  - 10,000 app-wide calls per minute across all tenancies
  - Response headers: X-DayLimit-Remaining, X-MinLimit-Remaining,
    X-AppMinLimit-Remaining
  - 429 response when any limit exceeded

Authentication (OAuth 2.0):
  - Register app at https://developer.xero.com/app/manage
  - Client ID + Client Secret
  - Authorization Code flow for initial token
  - Refresh tokens for ongoing access (tokens expire every 30 minutes)
  - Required scopes: openid, profile, email, accounting.transactions,
    accounting.contacts, accounting.reports.read, accounting.settings,
    accounting.attachments, offline_access

Token Storage:
  - Tokens stored in ~/.xero_tokens.json
  - Auto-refreshed when access token expires
  - Refresh tokens valid for 60 days

What can be done WITHOUT human approval:
  - Pull P&L reports, balance sheet, trial balance
  - Read bank transactions and reconciliation status
  - Read invoice status and payment history
  - Read expense categories
  - Generate GST/tax reports

What NEEDS human approval:
  - Create invoices (financial commitment)
  - Create bank transactions (financial records)
  - Reconcile bank statements (accounting decisions)
  - Categorize expenses (affects financial reporting)
  - Void or credit invoices
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

TOKEN_FILE = Path.home() / ".xero_tokens.json"


class XeroClient:
    """
    OAuth 2.0 authenticated client for Xero Accounting API.

    Handles token management, automatic refresh, and all accounting operations.
    """

    AUTH_URL = "https://login.xero.com/identity/connect/authorize"
    TOKEN_URL = "https://identity.xero.com/connect/token"
    API_URL = "https://api.xero.com/api.xro/2.0"
    CONNECTIONS_URL = "https://api.xero.com/connections"

    # Required scopes
    SCOPES = [
        "openid", "profile", "email", "offline_access",
        "accounting.transactions",
        "accounting.transactions.read",
        "accounting.contacts",
        "accounting.contacts.read",
        "accounting.reports.read",
        "accounting.settings",
        "accounting.settings.read",
        "accounting.attachments",
    ]

    def __init__(self, token_file: str = None):
        self.client_id = os.environ.get("XERO_CLIENT_ID")
        self.client_secret = os.environ.get("XERO_CLIENT_SECRET")
        self.redirect_uri = os.environ.get("XERO_REDIRECT_URI", "http://localhost:8080/callback")
        self.token_file = Path(token_file) if token_file else TOKEN_FILE
        self._tokens = None
        self._tenant_id = None
        self._load_tokens()

    @property
    def available(self) -> bool:
        return bool(self.client_id and self.client_secret and self._tokens)

    @property
    def tenant_id(self) -> str:
        if not self._tenant_id:
            self._fetch_tenant_id()
        return self._tenant_id

    # ===================================================================
    # OAUTH 2.0 TOKEN MANAGEMENT
    # ===================================================================

    def get_authorization_url(self, state: str = "xero_auth") -> str:
        """
        Generate the OAuth 2.0 authorization URL.
        User must visit this URL to grant access.

        Returns:
            Authorization URL string
        """
        params = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "scope": " ".join(self.SCOPES),
            "state": state,
        }
        return f"{self.AUTH_URL}?{urlencode(params)}"

    def exchange_code_for_tokens(self, authorization_code: str) -> dict:
        """
        Exchange an authorization code for access + refresh tokens.
        Call this after the user authorizes at the authorization URL.

        Args:
            authorization_code: The code from the redirect callback

        Returns:
            Token dict with access_token, refresh_token, expires_in
        """
        import requests

        resp = requests.post(self.TOKEN_URL, data={
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": self.redirect_uri,
        }, auth=(self.client_id, self.client_secret), timeout=30)

        resp.raise_for_status()
        tokens = resp.json()
        tokens["expires_at"] = time.time() + tokens.get("expires_in", 1800)
        self._tokens = tokens
        self._save_tokens()
        logger.info("Xero tokens obtained successfully")
        return tokens

    def _refresh_tokens(self) -> bool:
        """
        Refresh the access token using the refresh token.
        Called automatically when access token expires.

        Returns:
            True if refresh successful, False otherwise
        """
        import requests

        if not self._tokens or not self._tokens.get("refresh_token"):
            logger.error("No refresh token available. Re-authorization required.")
            return False

        try:
            resp = requests.post(self.TOKEN_URL, data={
                "grant_type": "refresh_token",
                "refresh_token": self._tokens["refresh_token"],
            }, auth=(self.client_id, self.client_secret), timeout=30)

            resp.raise_for_status()
            tokens = resp.json()
            tokens["expires_at"] = time.time() + tokens.get("expires_in", 1800)
            self._tokens = tokens
            self._save_tokens()
            logger.info("Xero tokens refreshed successfully")
            return True

        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            return False

    def _ensure_valid_token(self):
        """Ensure we have a valid access token, refreshing if needed."""
        if not self._tokens:
            raise Exception("No Xero tokens. Run authorization flow first.")

        expires_at = self._tokens.get("expires_at", 0)
        if time.time() > expires_at - 60:  # Refresh 60s before expiry
            if not self._refresh_tokens():
                raise Exception("Failed to refresh Xero token. Re-authorize.")

    def _load_tokens(self):
        """Load tokens from file."""
        try:
            if self.token_file.exists():
                with open(self.token_file) as f:
                    self._tokens = json.load(f)
        except Exception as e:
            logger.warning(f"Could not load Xero tokens: {e}")
            self._tokens = None

    def _save_tokens(self):
        """Save tokens to file."""
        try:
            with open(self.token_file, "w") as f:
                json.dump(self._tokens, f, indent=2)
            # Restrict file permissions
            self.token_file.chmod(0o600)
        except Exception as e:
            logger.error(f"Could not save Xero tokens: {e}")

    def _fetch_tenant_id(self):
        """Fetch the Xero tenant (organisation) ID."""
        import requests

        self._ensure_valid_token()
        resp = requests.get(self.CONNECTIONS_URL, headers={
            "Authorization": f"Bearer {self._tokens['access_token']}",
            "Content-Type": "application/json",
        }, timeout=15)
        resp.raise_for_status()
        connections = resp.json()
        if connections:
            self._tenant_id = connections[0]["tenantId"]
            logger.info(f"Xero tenant: {connections[0].get('tenantName', '?')}")
        else:
            raise Exception("No Xero organisations connected")

    # --- Internal HTTP Methods ---

    def _request(self, method: str, path: str, data: dict = None,
                 params: dict = None, max_retries: int = 3) -> dict:
        """Make an authenticated API request with retry logic."""
        import requests

        self._ensure_valid_token()
        url = f"{self.API_URL}/{path}"

        headers = {
            "Authorization": f"Bearer {self._tokens['access_token']}",
            "Xero-Tenant-Id": self.tenant_id,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        for attempt in range(max_retries):
            try:
                resp = requests.request(
                    method, url, headers=headers,
                    json=data, params=params, timeout=30
                )

                # Log remaining limits
                day_remaining = resp.headers.get("X-DayLimit-Remaining")
                min_remaining = resp.headers.get("X-MinLimit-Remaining")
                if day_remaining:
                    remaining = int(day_remaining)
                    if remaining < 500:
                        logger.warning(f"Xero daily limit low: {remaining} remaining")

                # Handle rate limiting
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", 60))
                    logger.warning(f"Xero rate limited. Waiting {retry_after}s (attempt {attempt + 1})")
                    time.sleep(retry_after)
                    continue

                # Handle token expiry mid-request
                if resp.status_code == 401:
                    if self._refresh_tokens():
                        headers["Authorization"] = f"Bearer {self._tokens['access_token']}"
                        continue
                    raise Exception("Xero authentication failed")

                resp.raise_for_status()
                return resp.json() if resp.content else {}

            except Exception as e:
                if attempt == max_retries - 1:
                    logger.error(f"Xero {method} {path} failed after {max_retries} attempts: {e}")
                    raise
                wait_time = 2 ** attempt
                logger.warning(f"Xero request failed, retrying in {wait_time}s: {e}")
                time.sleep(wait_time)

        return {}

    def _get(self, path: str, params: dict = None) -> dict:
        return self._request("GET", path, params=params)

    def _post(self, path: str, data: dict) -> dict:
        return self._request("POST", path, data=data)

    def _put(self, path: str, data: dict) -> dict:
        return self._request("PUT", path, data=data)

    # ===================================================================
    # 1. INVOICE MANAGEMENT
    #    Endpoint: PUT /Invoices (create), POST /Invoices (update)
    #    Autonomy: NEEDS APPROVAL -- financial commitment
    # ===================================================================

    def create_invoice(self, contact_name: str, line_items: list,
                        invoice_type: str = "ACCREC",
                        due_date: str = None, reference: str = "",
                        status: str = "DRAFT",
                        currency_code: str = "NZD") -> dict:
        """
        Create an invoice.

        PUT /Invoices

        Args:
            contact_name: Customer/supplier name (must exist in Xero contacts)
            line_items: List of dicts:
                [{
                    "Description": "Green Lipped Mussel 60caps",
                    "Quantity": 2,
                    "UnitAmount": 39.95,
                    "AccountCode": "200",  # Sales revenue account
                    "TaxType": "OUTPUT2",  # GST on sales (15% NZ)
                }]
            invoice_type: "ACCREC" (accounts receivable / sales)
                         or "ACCPAY" (accounts payable / bills)
            due_date: Due date "YYYY-MM-DD" (defaults to 30 days)
            reference: External reference (e.g. Shopify order number)
            status: "DRAFT", "SUBMITTED", "AUTHORISED"
            currency_code: "NZD", "USD", "AUD", etc.

        Returns:
            Created invoice object

        Example:
            client.create_invoice(
                contact_name="John Smith",
                line_items=[{
                    "Description": "Green Lipped Mussel 60 Capsules x2",
                    "Quantity": 2,
                    "UnitAmount": 39.95,
                    "AccountCode": "200",
                    "TaxType": "OUTPUT2",
                }],
                reference="DBH-#1234",
                status="AUTHORISED",
            )
        """
        if not due_date:
            due_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

        invoice_data = {
            "Invoices": [{
                "Type": invoice_type,
                "Contact": {"Name": contact_name},
                "LineItems": line_items,
                "DueDate": due_date,
                "Reference": reference,
                "Status": status,
                "CurrencyCode": currency_code,
                "LineAmountTypes": "Exclusive",  # Amounts exclude GST
            }]
        }

        result = self._put("Invoices", data=invoice_data)
        invoices = result.get("Invoices", [])
        if invoices:
            inv = invoices[0]
            logger.info(
                f"Created invoice {inv.get('InvoiceNumber', '?')} for "
                f"{contact_name}: ${inv.get('Total', 0)}"
            )
            return inv
        return {}

    def create_invoice_from_shopify_order(self, order: dict) -> dict:
        """
        Convenience: Create a Xero invoice from a Shopify order object.

        Args:
            order: Shopify order dict (from orders.json API)

        Returns:
            Created invoice object
        """
        # Build contact name
        customer = order.get("customer", {})
        contact_name = f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip()
        if not contact_name:
            contact_name = order.get("email", "Unknown Customer")

        # Build line items
        line_items = []
        for item in order.get("line_items", []):
            line_items.append({
                "Description": item.get("title", "Product"),
                "Quantity": item.get("quantity", 1),
                "UnitAmount": float(item.get("price", 0)),
                "AccountCode": "200",  # Revenue account -- adjust as needed
                "TaxType": "OUTPUT2",  # GST 15% -- adjust for tax-exempt
            })

        # Add shipping as a line item if present
        for shipping in order.get("shipping_lines", []):
            if float(shipping.get("price", 0)) > 0:
                line_items.append({
                    "Description": f"Shipping: {shipping.get('title', 'Standard')}",
                    "Quantity": 1,
                    "UnitAmount": float(shipping.get("price", 0)),
                    "AccountCode": "200",
                    "TaxType": "OUTPUT2",
                })

        # Add discounts as negative line items
        total_discount = float(order.get("total_discounts", 0))
        if total_discount > 0:
            codes = [d.get("code", "") for d in order.get("discount_codes", [])]
            line_items.append({
                "Description": f"Discount ({', '.join(codes) or 'applied'})",
                "Quantity": 1,
                "UnitAmount": -total_discount,
                "AccountCode": "200",
                "TaxType": "OUTPUT2",
            })

        reference = order.get("name", order.get("order_number", ""))

        return self.create_invoice(
            contact_name=contact_name,
            line_items=line_items,
            invoice_type="ACCREC",
            reference=f"Shopify {reference}",
            status="AUTHORISED",
        )

    def get_invoices(self, status: str = None, since: str = None,
                      page: int = 1) -> list:
        """
        Get invoices, optionally filtered.

        GET /Invoices

        Args:
            status: Filter by status ("DRAFT", "SUBMITTED", "AUTHORISED",
                    "PAID", "VOIDED")
            since: Modified since date "YYYY-MM-DD"
            page: Page number (100 invoices per page)

        Returns:
            List of invoice objects
        """
        params = {"page": page}
        if status:
            params["Statuses"] = status
        if since:
            params["where"] = f'Date >= DateTime({since.replace("-", ",")})'

        result = self._get("Invoices", params=params)
        return result.get("Invoices", [])

    # ===================================================================
    # 2. BANK TRANSACTIONS & RECONCILIATION
    #    Endpoint: PUT /BankTransactions (create)
    #    Endpoint: GET /BankTransactions (read)
    #    Autonomy: NEEDS APPROVAL for writes, SAFE for reads
    # ===================================================================

    def get_bank_transactions(self, since: str = None,
                                page: int = 1) -> list:
        """
        Get bank transactions.

        GET /BankTransactions

        Args:
            since: Modified since "YYYY-MM-DD"
            page: Page number

        Returns:
            List of bank transaction objects
        """
        params = {"page": page}
        if since:
            params["where"] = f'Date >= DateTime({since.replace("-", ",")})'

        result = self._get("BankTransactions", params=params)
        return result.get("BankTransactions", [])

    def create_bank_transaction(self, bank_account_code: str,
                                  contact_name: str,
                                  description: str,
                                  amount: float,
                                  account_code: str,
                                  transaction_type: str = "RECEIVE",
                                  date: str = None,
                                  reference: str = "") -> dict:
        """
        Create a bank transaction (spend or receive money).

        PUT /BankTransactions

        Args:
            bank_account_code: Bank account code in Xero (e.g. "090")
            contact_name: Payee/payer name
            description: Transaction description
            amount: Transaction amount (always positive)
            account_code: Category account code (e.g. "200" for sales)
            transaction_type: "RECEIVE" (money in) or "SPEND" (money out)
            date: Transaction date "YYYY-MM-DD" (defaults to today)
            reference: External reference

        Returns:
            Created bank transaction object
        """
        if not date:
            date = datetime.now().strftime("%Y-%m-%d")

        txn_data = {
            "BankTransactions": [{
                "Type": transaction_type,
                "Contact": {"Name": contact_name},
                "BankAccount": {"Code": bank_account_code},
                "LineItems": [{
                    "Description": description,
                    "Quantity": 1,
                    "UnitAmount": abs(amount),
                    "AccountCode": account_code,
                    "TaxType": "OUTPUT2" if transaction_type == "RECEIVE" else "INPUT2",
                }],
                "Date": date,
                "Reference": reference,
                "LineAmountTypes": "Exclusive",
            }]
        }

        result = self._put("BankTransactions", data=txn_data)
        txns = result.get("BankTransactions", [])
        if txns:
            logger.info(f"Created bank transaction: {transaction_type} ${amount:.2f}")
            return txns[0]
        return {}

    def get_bank_statements(self, bank_account_id: str,
                              from_date: str = None,
                              to_date: str = None) -> list:
        """
        Get bank statement lines (for reconciliation).

        GET /BankStatements

        Args:
            bank_account_id: Xero bank account ID
            from_date: Start date
            to_date: End date

        Returns:
            List of bank statement line objects
        """
        params = {"BankAccountID": bank_account_id}
        if from_date:
            params["fromDate"] = from_date
        if to_date:
            params["toDate"] = to_date

        result = self._get("BankStatements", params=params)
        return result.get("BankStatements", [])

    # ===================================================================
    # 3. REPORTS (P&L, Balance Sheet, GST)
    #    Endpoint: GET /Reports/ProfitAndLoss
    #    Endpoint: GET /Reports/BalanceSheet
    #    Endpoint: GET /Reports/GST
    #    Autonomy: SAFE -- read-only reporting
    # ===================================================================

    def get_profit_and_loss(self, from_date: str = None,
                              to_date: str = None,
                              periods: int = None,
                              timeframe: str = None) -> dict:
        """
        Get Profit & Loss report.

        GET /Reports/ProfitAndLoss

        Args:
            from_date: Start date "YYYY-MM-DD" (defaults to start of financial year)
            to_date: End date "YYYY-MM-DD" (defaults to today)
            periods: Number of periods to compare (e.g. 3 for 3 months)
            timeframe: Period type: "MONTH", "QUARTER", "YEAR"

        Returns:
            P&L report object with rows of data
        """
        params = {}
        if from_date:
            params["fromDate"] = from_date
        if to_date:
            params["toDate"] = to_date
        if periods:
            params["periods"] = periods
        if timeframe:
            params["timeframe"] = timeframe

        result = self._get("Reports/ProfitAndLoss", params=params)
        reports = result.get("Reports", [])
        if reports:
            logger.info(f"Fetched P&L report: {from_date or 'FY start'} to {to_date or 'today'}")
            return reports[0]
        return {}

    def get_balance_sheet(self, date: str = None) -> dict:
        """
        Get Balance Sheet report.

        GET /Reports/BalanceSheet

        Args:
            date: Report date "YYYY-MM-DD" (defaults to today)

        Returns:
            Balance sheet report object
        """
        params = {}
        if date:
            params["date"] = date

        result = self._get("Reports/BalanceSheet", params=params)
        reports = result.get("Reports", [])
        if reports:
            logger.info(f"Fetched balance sheet: {date or 'today'}")
            return reports[0]
        return {}

    def get_gst_report(self, from_date: str = None,
                         to_date: str = None) -> dict:
        """
        Get GST report (NZ/AU tax return data).

        GET /Reports/GST

        NOTE: Xero refers to this as the "TaxReport" for some regions.
        For NZ GST, this returns the data needed for IRD GST returns.

        Args:
            from_date: Period start "YYYY-MM-DD"
            to_date: Period end "YYYY-MM-DD"

        Returns:
            GST report object
        """
        params = {}
        if from_date:
            params["fromDate"] = from_date
        if to_date:
            params["toDate"] = to_date

        # Try GST report first (NZ/AU), fall back to TaxReport
        try:
            result = self._get("Reports/GST", params=params)
        except Exception:
            result = self._get("Reports/TaxReport", params=params)

        reports = result.get("Reports", [])
        if reports:
            logger.info(f"Fetched GST report: {from_date} to {to_date}")
            return reports[0]
        return {}

    def get_trial_balance(self, date: str = None) -> dict:
        """
        Get Trial Balance report.

        GET /Reports/TrialBalance

        Args:
            date: Report date "YYYY-MM-DD"

        Returns:
            Trial balance report object
        """
        params = {}
        if date:
            params["date"] = date

        result = self._get("Reports/TrialBalance", params=params)
        reports = result.get("Reports", [])
        return reports[0] if reports else {}

    # ===================================================================
    # 4. CONTACTS
    #    Endpoint: PUT /Contacts (create), POST /Contacts (update)
    #    Autonomy: SAFE for reads, APPROVAL for creates
    # ===================================================================

    def get_contacts(self, search: str = None, page: int = 1) -> list:
        """
        Get contacts, optionally filtered by name.

        GET /Contacts

        Args:
            search: Search string (matches name, email)
            page: Page number

        Returns:
            List of contact objects
        """
        params = {"page": page}
        if search:
            params["where"] = f'Name.Contains("{search}")'

        result = self._get("Contacts", params=params)
        return result.get("Contacts", [])

    def create_contact(self, name: str, email: str = None,
                         phone: str = None,
                         address: dict = None) -> dict:
        """
        Create a contact in Xero.

        PUT /Contacts

        Args:
            name: Contact name
            email: Email address
            phone: Phone number
            address: Address dict with keys:
                AddressType, AddressLine1, City, Region, PostalCode, Country

        Returns:
            Created contact object
        """
        contact = {"Name": name}
        if email:
            contact["EmailAddress"] = email
        if phone:
            contact["Phones"] = [{"PhoneType": "DEFAULT", "PhoneNumber": phone}]
        if address:
            contact["Addresses"] = [address]

        result = self._put("Contacts", data={"Contacts": [contact]})
        contacts = result.get("Contacts", [])
        if contacts:
            logger.info(f"Created contact: {name}")
            return contacts[0]
        return {}

    # ===================================================================
    # 5. EXPENSE CATEGORIZATION
    #    Endpoint: GET /Accounts (chart of accounts)
    #    Endpoint: POST /BankTransactions (update category)
    #    Autonomy: Read = SAFE, Categorize = NEEDS APPROVAL
    # ===================================================================

    def get_accounts(self, account_type: str = None) -> list:
        """
        Get chart of accounts (expense categories).

        GET /Accounts

        Args:
            account_type: Filter by type: "REVENUE", "EXPENSE", "BANK",
                          "CURRENT", "EQUITY", etc.

        Returns:
            List of account objects
        """
        params = {}
        if account_type:
            params["where"] = f'Type=="{account_type}"'

        result = self._get("Accounts", params=params)
        return result.get("Accounts", [])

    def get_expense_categories(self) -> list:
        """Get all expense account categories."""
        return self.get_accounts(account_type="EXPENSE")

    # ===================================================================
    # CONVENIENCE / FORMATTED REPORTS
    # ===================================================================

    def format_pnl_summary(self, months: int = 1) -> str:
        """
        Get a formatted P&L summary for injection into agent prompts.

        Args:
            months: Number of months to report on

        Returns:
            Formatted text string
        """
        to_date = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=months * 30)).strftime("%Y-%m-%d")

        try:
            report = self.get_profit_and_loss(from_date, to_date)
            if not report:
                return "[Xero P&L unavailable]"

            lines = [
                f"XERO P&L -- {from_date} to {to_date}",
                f"  Report: {report.get('ReportName', 'P&L')}",
            ]

            for row_group in report.get("Rows", []):
                row_type = row_group.get("RowType", "")
                title = row_group.get("Title", "")

                if title:
                    lines.append(f"\n  {title}:")

                for row in row_group.get("Rows", []):
                    cells = row.get("Cells", [])
                    if len(cells) >= 2:
                        label = cells[0].get("Value", "")
                        value = cells[1].get("Value", "")
                        if label and value:
                            lines.append(f"    {label}: {value}")

                # Summary row
                if row_type == "SummaryRow":
                    cells = row_group.get("Cells", [])
                    if cells:
                        lines.append(f"  TOTAL: {cells[-1].get('Value', '')}")

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"P&L summary error: {e}")
            return f"[Xero P&L error: {str(e)}]"

    def format_balance_sheet_summary(self) -> str:
        """Get a formatted balance sheet summary."""
        try:
            report = self.get_balance_sheet()
            if not report:
                return "[Xero Balance Sheet unavailable]"

            lines = [
                f"XERO BALANCE SHEET -- {datetime.now().strftime('%Y-%m-%d')}",
            ]

            for row_group in report.get("Rows", []):
                title = row_group.get("Title", "")
                if title:
                    lines.append(f"\n  {title}:")

                for row in row_group.get("Rows", []):
                    cells = row.get("Cells", [])
                    if len(cells) >= 2:
                        label = cells[0].get("Value", "")
                        value = cells[1].get("Value", "")
                        if label and value:
                            lines.append(f"    {label}: {value}")

            return "\n".join(lines)

        except Exception as e:
            return f"[Xero Balance Sheet error: {str(e)}]"

    def get_financial_health_snapshot(self) -> str:
        """
        Get a comprehensive financial health snapshot.
        Designed for injection into PREP/Oracle agent briefings.

        Returns:
            Formatted text with P&L, balance sheet, and recent invoices
        """
        sections = [
            "=== XERO FINANCIAL SNAPSHOT ===",
            "",
        ]

        # P&L (last month)
        sections.append(self.format_pnl_summary(months=1))
        sections.append("")

        # Balance sheet
        sections.append(self.format_balance_sheet_summary())
        sections.append("")

        # Recent unpaid invoices
        try:
            unpaid = self.get_invoices(status="AUTHORISED")
            if unpaid:
                sections.append("OUTSTANDING INVOICES:")
                total_outstanding = 0
                for inv in unpaid[:10]:
                    amount = float(inv.get("AmountDue", 0))
                    total_outstanding += amount
                    due = inv.get("DueDate", "")[:10]
                    sections.append(
                        f"  {inv.get('InvoiceNumber', '?')}: "
                        f"${amount:,.2f} due {due} -- {inv.get('Contact', {}).get('Name', '?')}"
                    )
                sections.append(f"  TOTAL OUTSTANDING: ${total_outstanding:,.2f}")
        except Exception as e:
            sections.append(f"[Invoice data unavailable: {e}]")

        return "\n".join(sections)


# --- CLI ---

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    client = XeroClient()

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python xero_client.py auth           -- Start OAuth flow")
        print("  python xero_client.py callback <code> -- Exchange auth code")
        print("  python xero_client.py pnl [months]    -- Profit & Loss report")
        print("  python xero_client.py balance          -- Balance Sheet")
        print("  python xero_client.py gst              -- GST report")
        print("  python xero_client.py invoices [status] -- List invoices")
        print("  python xero_client.py snapshot          -- Full financial snapshot")
        print("  python xero_client.py accounts          -- Chart of accounts")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "auth":
        if not client.client_id:
            print("Set XERO_CLIENT_ID and XERO_CLIENT_SECRET environment variables")
            print("Register app at: https://developer.xero.com/app/manage")
            sys.exit(1)
        url = client.get_authorization_url()
        print(f"\nVisit this URL to authorize:\n\n{url}\n")
        print("After authorizing, run:")
        print("  python xero_client.py callback <authorization_code>")

    elif cmd == "callback" and len(sys.argv) > 2:
        code = sys.argv[2]
        tokens = client.exchange_code_for_tokens(code)
        print(f"Tokens saved to {client.token_file}")
        print(f"Access token expires in {tokens.get('expires_in', '?')} seconds")

    elif cmd == "pnl":
        months = int(sys.argv[2]) if len(sys.argv) > 2 else 1
        print(client.format_pnl_summary(months))

    elif cmd == "balance":
        print(client.format_balance_sheet_summary())

    elif cmd == "gst":
        from_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        to_date = datetime.now().strftime("%Y-%m-%d")
        report = client.get_gst_report(from_date, to_date)
        print(json.dumps(report, indent=2) if report else "No GST data")

    elif cmd == "invoices":
        status = sys.argv[2] if len(sys.argv) > 2 else None
        for inv in client.get_invoices(status=status):
            print(
                f"  {inv.get('InvoiceNumber', '?')}: "
                f"${inv.get('Total', 0):,.2f} ({inv.get('Status', '?')}) "
                f"-- {inv.get('Contact', {}).get('Name', '?')}"
            )

    elif cmd == "snapshot":
        print(client.get_financial_health_snapshot())

    elif cmd == "accounts":
        for acc in client.get_accounts():
            print(f"  [{acc.get('Code', '?')}] {acc.get('Name', '?')} ({acc.get('Type', '?')})")

    else:
        print(f"Unknown command: {cmd}")
