"""
Shopify API client for the OOM Dashboard.
"""

import os
import time
import requests
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlencode
from dotenv import load_dotenv, set_key, find_dotenv

load_dotenv()

STORE_URL = os.getenv("SHOPIFY_STORE_URL", "")
ACCESS_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN", "")
API_VERSION = "2025-01"


class ShopifyClient:
    def __init__(self, store_url: str = STORE_URL, access_token: str = ACCESS_TOKEN):
        self._access_token = access_token
        self.base_url = f"https://{store_url}/admin/api/{API_VERSION}"
        self.session = requests.Session()
        self._apply_token(access_token)

    def _apply_token(self, access_token: str) -> None:
        self._access_token = access_token
        self.session.headers.update({
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        })

    def _reload_token(self) -> bool:
        """Re-read SHOPIFY_ACCESS_TOKEN from .env; returns True if the token changed."""
        load_dotenv(override=True)
        new_token = os.getenv("SHOPIFY_ACCESS_TOKEN", "")
        if new_token and new_token != self._access_token:
            self._apply_token(new_token)
            return True
        return False

    def _request(self, method: str, endpoint: str, **kwargs) -> Optional[Dict]:
        url = f"{self.base_url}{endpoint}"
        for attempt in range(3):
            response = self.session.request(method, url, **kwargs)
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", 2))
                time.sleep(retry_after)
                continue
            if response.status_code == 401 and attempt == 0:
                if self._reload_token():
                    continue
            if not response.ok:
                print(f"  [{response.status_code}] {method} {endpoint} — {response.text[:120]}")
                return None
            return response.json()
        return None

    def get(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        return self._request("GET", endpoint, params=params)

    def post(self, endpoint: str, data: Dict) -> Optional[Dict]:
        return self._request("POST", endpoint, json=data)

    def put(self, endpoint: str, data: Dict) -> Optional[Dict]:
        return self._request("PUT", endpoint, json=data)

    def delete(self, endpoint: str) -> Optional[Dict]:
        return self._request("DELETE", endpoint)

    # ── Shop ──────────────────────────────────────────────────────────────────

    def get_shop(self) -> Optional[Dict]:
        r = self.get("/shop.json")
        return r.get("shop") if r else None

    # ── Orders ────────────────────────────────────────────────────────────────

    def get_orders(self, limit: int = 250, status: str = "any",
                   financial_status: str = "any", **kwargs) -> List[Dict]:
        params = {"limit": min(limit, 250), "status": status,
                  "financial_status": financial_status, **kwargs}
        r = self.get("/orders.json", params=params)
        return r.get("orders", []) if r else []

    def get_all_orders(self, status: str = "any", financial_status: str = "paid",
                       created_at_min: Optional[str] = None) -> List[Dict]:
        """Fetch every order, following Shopify cursor pagination."""
        params: Dict = {"limit": 250, "status": status, "financial_status": financial_status}
        if created_at_min:
            params["created_at_min"] = created_at_min
        all_orders: List[Dict] = []
        url = f"{self.base_url}/orders.json"
        token_reloaded = False
        while url:
            response = self.session.get(url, params=params)
            if response.status_code == 429:
                time.sleep(float(response.headers.get("Retry-After", 2)))
                continue
            if response.status_code == 401 and not token_reloaded:
                token_reloaded = True
                if self._reload_token():
                    continue
            if not response.ok:
                raise RuntimeError(f"[{response.status_code}] GET /orders — {response.text[:200]}")

            all_orders.extend(response.json().get("orders", []))
            # Follow the next-page cursor from the Link header
            link = response.headers.get("Link", "")
            url, params = self._next_page(link)
        return all_orders

    @staticmethod
    def _next_page(link_header: str) -> Tuple[Optional[str], Dict]:
        """Parse Shopify's Link header and return the next page URL (params cleared)."""
        for part in link_header.split(","):
            if 'rel="next"' in part:
                next_url = part.split(";")[0].strip().strip("<>")
                return next_url, {}
        return None, {}

    def get_order(self, order_id: int) -> Optional[Dict]:
        r = self.get(f"/orders/{order_id}.json")
        return r.get("order") if r else None

    # ── Products ──────────────────────────────────────────────────────────────

    def get_products(self, limit: int = 250, status: str = "active", **kwargs) -> List[Dict]:
        params = {"limit": min(limit, 250), "status": status, **kwargs}
        r = self.get("/products.json", params=params)
        return r.get("products", []) if r else []

    def get_product(self, product_id: int) -> Optional[Dict]:
        r = self.get(f"/products/{product_id}.json")
        return r.get("product") if r else None

    # ── Customers ─────────────────────────────────────────────────────────────

    def get_customers(self, limit: int = 250, **kwargs) -> List[Dict]:
        params = {"limit": min(limit, 250), **kwargs}
        r = self.get("/customers.json", params=params)
        return r.get("customers", []) if r else []

    def get_customer(self, customer_id: int) -> Optional[Dict]:
        r = self.get(f"/customers/{customer_id}.json")
        return r.get("customer") if r else None

    # ── Inventory ─────────────────────────────────────────────────────────────

    def get_inventory_levels(self, location_ids: Optional[List[int]] = None) -> List[Dict]:
        params = {}
        if location_ids:
            params["location_ids"] = ",".join(str(i) for i in location_ids)
        r = self.get("/inventory_levels.json", params=params)
        return r.get("inventory_levels", []) if r else []

    def get_locations(self) -> List[Dict]:
        r = self.get("/locations.json")
        return r.get("locations", []) if r else []

    # ── Themes ────────────────────────────────────────────────────────────────

    def get_themes(self) -> List[Dict]:
        r = self.get("/themes.json")
        return r.get("themes", []) if r else []

    def get_theme_asset(self, theme_id: int, key: str) -> Optional[Dict]:
        r = self.get(f"/themes/{theme_id}/assets.json", params={"asset[key]": key})
        return r.get("asset") if r else None

    def put_theme_asset(self, theme_id: int, key: str, value: str) -> Optional[Dict]:
        return self.put(f"/themes/{theme_id}/assets.json",
                        {"asset": {"key": key, "value": value}})

    # ── Collections ───────────────────────────────────────────────────────────

    def get_custom_collections(self, limit: int = 250) -> List[Dict]:
        r = self.get("/custom_collections.json", params={"limit": min(limit, 250)})
        return r.get("custom_collections", []) if r else []

    def get_smart_collections(self, limit: int = 250) -> List[Dict]:
        r = self.get("/smart_collections.json", params={"limit": min(limit, 250)})
        return r.get("smart_collections", []) if r else []


# ── Shopify OAuth 2.0 ─────────────────────────────────────────────────────────

SHOPIFY_SCOPES = "read_orders,read_products"


class ShopifyOAuth:
    """
    Handles the Shopify OAuth 2.0 authorisation-code flow for custom apps.

    Flow:
      1. Redirect user to get_auth_url()
      2. Shopify POSTs back with ?code=...
      3. Call exchange_code(code) → returns {"access_token": "shpat_...", "scope": "..."}
      4. Optionally call save_to_env() to persist the token across restarts.

    Shopify offline access tokens never expire, so there is no refresh step.
    """

    def __init__(self, client_id: str, client_secret: str,
                 redirect_uri: str, shop: str = ""):
        self.client_id     = client_id
        self.client_secret = client_secret
        self.redirect_uri  = redirect_uri
        self.shop          = shop  # e.g. "mystore.myshopify.com"
        self.access_token: Optional[str] = None

    def get_auth_url(self, state: str = "shopify_auth") -> str:
        params = urlencode({
            "client_id":    self.client_id,
            "scope":        SHOPIFY_SCOPES,
            "redirect_uri": self.redirect_uri,
            "state":        state,
        })
        return f"https://{self.shop}/admin/oauth/authorize?{params}"

    def exchange_code(self, code: str) -> Dict:
        """POST client_id + client_secret + code to receive the access token."""
        url = f"https://{self.shop}/admin/oauth/access_token"
        r = requests.post(url, data={
            "client_id":     self.client_id,
            "client_secret": self.client_secret,
            "code":          code,
        })
        if not r.ok:
            raise RuntimeError(f"{r.status_code} {r.reason} — {r.text}")
        data = r.json()
        if "access_token" not in data:
            raise RuntimeError(f"No access_token in response: {data}")
        self.access_token = data["access_token"]
        return data

    def save_to_env(self) -> None:
        """Write access token back to .env so it survives app restarts."""
        env_file = find_dotenv() or ".env"
        set_key(env_file, "SHOPIFY_ACCESS_TOKEN", self.access_token)

    def is_authenticated(self) -> bool:
        return bool(self.access_token)


PRODUCT_ALIASES = {
    "balance": "OOM Balance",
    "calm":    "OOM Calm",
    "focus":   "OOM Focus",
    "mix":     "OOM Mix",
}

def _normalise_product(title: str) -> Optional[str]:
    """Map historical product name variants to a canonical name. Returns None to skip."""
    t = title.lower()
    for keyword, canonical in PRODUCT_ALIASES.items():
        if keyword in t:
            return canonical
    return None  # skip one-off / custom line items


def classify_orders(orders: List[Dict]):
    """Split orders into (normal, faire, zero) buckets."""
    normal, faire, zero = [], [], []
    for o in orders:
        if float(o.get("total_price", 0)) == 0:
            zero.append(o)
        elif o.get("source_name", "").lower() == "faire":
            faire.append(o)
        else:
            normal.append(o)
    return normal, faire, zero


def sales_by_product_by_month(orders: List[Dict]) -> Dict[str, Dict[str, Dict]]:
    """
    Returns {product_title: {YYYY-MM: {units: int, revenue: float}}}.
    Only counts paid/fulfilled line items; skips refunded quantities.
    """
    data: Dict[str, Dict[str, Dict]] = defaultdict(lambda: defaultdict(lambda: {"units": 0, "revenue": 0.0}))
    for order in orders:
        month = order["created_at"][:7]  # YYYY-MM
        for item in order.get("line_items", []):
            title = _normalise_product(item["title"])
            if not title:
                continue
            qty = item["quantity"]
            price = float(item["price"]) * qty
            data[title][month]["units"] += qty
            data[title][month]["revenue"] += price
    return data


def print_sales_table(data: Dict[str, Dict[str, Dict]], currency: str = "GBP") -> None:
    symbol = "£" if currency == "GBP" else "$"
    # Collect and sort all months present
    months = sorted({m for product in data.values() for m in product})
    if not months:
        print("No sales data found.")
        return

    col_w = 12
    name_w = 28

    def month_label(m: str) -> str:
        return datetime.strptime(m, "%Y-%m").strftime("%b %Y")

    headers = [month_label(m) for m in months]

    # ── Units table ───────────────────────────────────────────────────────────
    print("\n" + "=" * (name_w + col_w * len(months) + 2))
    print("UNITS SOLD BY PRODUCT / MONTH")
    print("=" * (name_w + col_w * len(months) + 2))
    print(f"{'Product':<{name_w}}" + "".join(f"{h:>{col_w}}" for h in headers))
    print("-" * (name_w + col_w * len(months)))
    totals = defaultdict(int)
    for product in sorted(data):
        row = f"{product:<{name_w}}"
        for m in months:
            units = data[product][m]["units"]
            totals[m] += units
            row += f"{units:>{col_w}}"
        print(row)
    print("-" * (name_w + col_w * len(months)))
    print(f"{'TOTAL':<{name_w}}" + "".join(f"{totals[m]:>{col_w}}" for m in months))

    # ── Revenue table ─────────────────────────────────────────────────────────
    print("\n" + "=" * (name_w + col_w * len(months) + 2))
    print(f"REVENUE ({symbol}) BY PRODUCT / MONTH")
    print("=" * (name_w + col_w * len(months) + 2))
    print(f"{'Product':<{name_w}}" + "".join(f"{h:>{col_w}}" for h in headers))
    print("-" * (name_w + col_w * len(months)))
    rev_totals: Dict[str, float] = defaultdict(float)
    for product in sorted(data):
        row = f"{product:<{name_w}}"
        for m in months:
            rev = data[product][m]["revenue"]
            rev_totals[m] += rev
            row += f"{symbol}{rev:>10.0f}"
        print(row)
    print("-" * (name_w + col_w * len(months)))
    print(f"{'TOTAL':<{name_w}}" + "".join(f"{symbol}{rev_totals[m]:>10.0f}" for m in months))


if __name__ == "__main__":
    client = ShopifyClient()

    shop = client.get_shop()
    currency = "GBP"
    if shop:
        print(f"Connected to: {shop['name']} ({shop['domain']})")
        currency = shop.get("currency", "GBP")

    print("\nFetching all paid orders…")
    orders = client.get_all_orders(financial_status="paid")
    print(f"  {len(orders)} orders retrieved")

    data = sales_by_product_by_month(orders)
    print_sales_table(data, currency=currency)
