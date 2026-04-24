"""
Xero OAuth 2.0 client for the OOM Dashboard.
"""

import time
import requests
from typing import Dict, List, Optional
from urllib.parse import urlencode

AUTH_URL  = "https://login.xero.com/identity/connect/authorize"
TOKEN_URL = "https://identity.xero.com/connect/token"
API_BASE  = "https://api.xero.com/api.xro/2.0"
SCOPES = (
    "openid profile email offline_access "
    "accounting.invoices.read "
    "accounting.payments.read "
    "accounting.banktransactions.read "
    "accounting.settings.read "
    "accounting.reports.profitandloss.read "
    "accounting.reports.balancesheet.read "
    "accounting.reports.executivesummary.read"
)


class XeroClient:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id     = client_id
        self.client_secret = client_secret
        self.redirect_uri  = redirect_uri
        self.access_token  = None
        self.refresh_token = None
        self.tenant_id     = None
        self._token_expiry = 0

    # ── OAuth flow ────────────────────────────────────────────────────────────

    def get_auth_url(self, state: str = "xero_auth") -> str:
        params = {
            "response_type": "code",
            "client_id":     self.client_id,
            "redirect_uri":  self.redirect_uri,
            "scope":         SCOPES,
            "state":         state,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, code: str) -> Dict:
        r = requests.post(
            TOKEN_URL,
            auth=(self.client_id, self.client_secret),
            data={"grant_type": "authorization_code", "code": code,
                  "redirect_uri": self.redirect_uri},
        )
        r.raise_for_status()
        return self._store_tokens(r.json())

    def refresh_access_token(self) -> Dict:
        r = requests.post(
            TOKEN_URL,
            auth=(self.client_id, self.client_secret),
            data={"grant_type": "refresh_token", "refresh_token": self.refresh_token},
        )
        r.raise_for_status()
        return self._store_tokens(r.json())

    def _store_tokens(self, data: Dict) -> Dict:
        self.access_token  = data["access_token"]
        self.refresh_token = data.get("refresh_token", self.refresh_token)
        self._token_expiry = time.time() + data.get("expires_in", 1800) - 60
        return data

    def load_tokens(self, access_token: str, refresh_token: str,
                    expiry: float, tenant_id: str) -> None:
        """Restore tokens from session state."""
        self.access_token  = access_token
        self.refresh_token = refresh_token
        self._token_expiry = expiry
        self.tenant_id     = tenant_id

    def is_authenticated(self) -> bool:
        return bool(self.access_token and self.tenant_id)

    def _ensure_fresh(self) -> None:
        if self.refresh_token and time.time() > self._token_expiry:
            self.refresh_access_token()

    # ── Tenant ────────────────────────────────────────────────────────────────

    def get_tenants(self) -> List[Dict]:
        self._ensure_fresh()
        r = requests.get(
            "https://api.xero.com/connections",
            headers={"Authorization": f"Bearer {self.access_token}",
                     "Content-Type": "application/json"},
        )
        r.raise_for_status()
        return r.json()

    # ── API requests ──────────────────────────────────────────────────────────

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        self._ensure_fresh()
        r = requests.get(
            f"{API_BASE}/{endpoint}",
            headers={
                "Authorization":  f"Bearer {self.access_token}",
                "Xero-tenant-id": self.tenant_id,
                "Accept":         "application/json",
            },
            params=params,
        )
        if not r.ok:
            raise RuntimeError(f"[{r.status_code}] {endpoint}: {r.text[:300]}")
        return r.json()

    # ── Reports ───────────────────────────────────────────────────────────────

    def get_profit_and_loss(self, from_date: str, to_date: str) -> Optional[Dict]:
        return self._get("Reports/ProfitAndLoss", {
            "fromDate": from_date,
            "toDate":   to_date,
        })

    def get_balance_sheet(self, date: str) -> Optional[Dict]:
        return self._get("Reports/BalanceSheet", {"date": date})

    # ── Transactions ──────────────────────────────────────────────────────────

    def get_invoices(self, status: str = "AUTHORISED",
                     page: int = 1) -> List[Dict]:
        r = self._get("Invoices", {"Status": status, "page": page,
                                    "order": "Date DESC"})
        return r.get("Invoices", []) if r else []

    def get_all_invoices(self, status: str = "AUTHORISED") -> List[Dict]:
        all_inv, page = [], 1
        while True:
            batch = self.get_invoices(status=status, page=page)
            if not batch:
                break
            all_inv.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return all_inv

    def get_bank_transactions(self, page: int = 1) -> List[Dict]:
        r = self._get("BankTransactions", {"page": page})
        return r.get("BankTransactions", []) if r else []

    def get_accounts(self) -> List[Dict]:
        r = self._get("Accounts")
        return r.get("Accounts", []) if r else []

    def get_organisation(self) -> Optional[Dict]:
        r = self._get("Organisations")
        orgs = r.get("Organisations", []) if r else []
        return orgs[0] if orgs else None
