"""
OOM Dashboard — Streamlit app
"""

import os
import time
import pandas as pd
import streamlit as st
from collections import defaultdict
from shopify import ShopifyClient, ShopifyOAuth, sales_by_product_by_month, classify_orders
from xero import XeroClient
from datetime import datetime

st.set_page_config(page_title="OOM Dashboard", page_icon="🥤", layout="wide")

st.title("🥤 OOM Sales Dashboard")

# ── Credentials: st.secrets (Streamlit Cloud) with fallback to .env ───────────

store_url     = st.secrets.get("SHOPIFY_STORE_URL",      os.getenv("SHOPIFY_STORE_URL", ""))
client_id     = st.secrets.get("SHOPIFY_CLIENT_ID",      os.getenv("SHOPIFY_CLIENT_ID", ""))
client_secret = st.secrets.get("SHOPIFY_CLIENT_SECRET",  os.getenv("SHOPIFY_CLIENT_SECRET", ""))
redirect_uri  = st.secrets.get("SHOPIFY_REDIRECT_URI",   os.getenv("SHOPIFY_REDIRECT_URI", "http://localhost:8501"))

# Session state token takes priority — set after a successful OAuth exchange
# and survives reruns within the same session (Streamlit Cloud can't write secrets at runtime)
access_token = (
    st.session_state.get("shopify_access_token")
    or st.secrets.get("SHOPIFY_ACCESS_TOKEN", os.getenv("SHOPIFY_ACCESS_TOKEN", ""))
)

shopify_oauth = ShopifyOAuth(client_id, client_secret, redirect_uri, shop=store_url)

# ── Shopify OAuth callback — ?code=... returned by Shopify after authorisation ─
_qp = st.query_params
if "code" in _qp and client_id:
    with st.spinner("Connecting to Shopify…"):
        try:
            data = shopify_oauth.exchange_code(_qp["code"])
            shopify_oauth.save_to_env()
            st.session_state["shopify_access_token"] = shopify_oauth.access_token
            access_token = shopify_oauth.access_token
            st.query_params.clear()
            st.success(f"Shopify connected ✓  scope: {data.get('scope', '')}")
            st.rerun()
        except Exception as e:
            st.error(f"Shopify OAuth error: {e}")
            st.query_params.clear()

# ── Data loading ──────────────────────────────────────────────────────────────

AUTO_REFRESH_INTERVAL = 300  # seconds

@st.cache_data(ttl=AUTO_REFRESH_INTERVAL)
def load_data(_store_url, _access_token):
    client = ShopifyClient(store_url=_store_url, access_token=_access_token)
    return client.get_all_orders(financial_status="any")

# ── Auto-refresh timer ────────────────────────────────────────────────────────
if "next_refresh" not in st.session_state:
    st.session_state.next_refresh = time.time() + AUTO_REFRESH_INTERVAL

col_btn, col_timer = st.columns([1, 3])
with col_btn:
    if st.button("🔄 Refresh data"):
        st.cache_data.clear()
        st.session_state.next_refresh = time.time() + AUTO_REFRESH_INTERVAL
        st.rerun()
with col_timer:
    secs_left = max(0, int(st.session_state.next_refresh - time.time()))
    st.caption(f"Next auto-refresh in {secs_left // 60}m {secs_left % 60:02d}s")

if time.time() >= st.session_state.next_refresh:
    st.cache_data.clear()
    st.session_state.next_refresh = time.time() + AUTO_REFRESH_INTERVAL
    st.rerun()

def _show_shopify_connect():
    st.subheader("Connect to Shopify")
    if not client_id:
        st.warning("Add `SHOPIFY_CLIENT_ID` and `SHOPIFY_CLIENT_SECRET` to Streamlit Cloud secrets to enable OAuth.")
        st.code(
            "SHOPIFY_CLIENT_ID = \"your_api_key\"\n"
            "SHOPIFY_CLIENT_SECRET = \"your_api_secret\"\n"
            "SHOPIFY_REDIRECT_URI = \"https://your-app.streamlit.app/\"",
            language="toml",
        )
        return
    if not store_url:
        st.warning("SHOPIFY_STORE_URL is not set in secrets.")
        return
    auth_url = shopify_oauth.get_auth_url()
    st.markdown("Authorise the dashboard to read your Shopify orders.")
    st.link_button("Connect to Shopify", auth_url, type="primary")
    with st.expander("Debug — authorisation URL"):
        st.code(auth_url)

if not access_token:
    _show_shopify_connect()
    st.stop()

with st.spinner("Fetching orders from Shopify…"):
    try:
        all_orders = load_data(store_url, access_token)
    except Exception as e:
        if "401" in str(e):
            st.error("Shopify token invalid or revoked.")
            _show_shopify_connect()
        else:
            st.error(f"Shopify load error: {e}")
        st.stop()

if not all_orders:
    st.error("No orders returned.")
    st.write("Store URL:", store_url or "⚠️ NOT SET")
    st.write("Token:", ("✓ set (" + access_token[:8] + "...)") if access_token else "⚠️ NOT SET")
    _show_shopify_connect()
    st.stop()

normal_orders, faire_orders, zero_orders = classify_orders(all_orders)

st.caption(
    f"{len(all_orders)} total orders  ·  "
    f"{len(normal_orders)} standard  ·  "
    f"{len(faire_orders)} Faire  ·  "
    f"{len(zero_orders)} zero-value  ·  "
    f"auto-refreshes every 5 min · token reloads from env on 401"
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def build_dataframes(orders):
    data = sales_by_product_by_month(orders)
    if not data:
        return None, None, []

    products = sorted(data.keys())
    months = sorted({m for p in data.values() for m in p})
    labels = [datetime.strptime(m, "%Y-%m").strftime("%b %Y") for m in months]

    units_rows  = {p: [data[p][m]["units"]   for m in months] for p in products}
    rev_rows    = {p: [round(data[p][m]["revenue"], 2) for m in months] for p in products}

    df_u = pd.DataFrame(units_rows, index=labels).T
    df_r = pd.DataFrame(rev_rows,   index=labels).T

    for df in (df_u, df_r):
        df["Total"] = df.sum(axis=1)
        df.loc["Total"] = df.sum()

    return df_u, df_r, labels


def highlight_total(df):
    styles = pd.DataFrame("", index=df.index, columns=df.columns)
    styles.iloc[-1, :] = "font-weight: bold; background-color: #1565C0; color: white"
    styles.iloc[:, -1] = "font-weight: bold; background-color: #1565C0; color: white"
    return styles


def render_tables(orders, currency="GBP"):
    symbol = "£" if currency == "GBP" else "$"
    df_u, df_r, labels = build_dataframes(orders)

    if df_u is None:
        st.info("No orders in this category.")
        return

    products = [i for i in df_u.index if i != "Total"]

    st.subheader("Units sold by product / month")
    st.dataframe(
        df_u.style
            .apply(highlight_total, axis=None)
            .format("{:.0f}")
            .background_gradient(cmap="Blues", subset=pd.IndexSlice[products, labels]),
        use_container_width=True,
        height=250,
    )

    st.subheader(f"Revenue ({symbol}) by product / month")
    st.dataframe(
        df_r.style
            .apply(highlight_total, axis=None)
            .format(f"{symbol}{{:.0f}}")
            .background_gradient(cmap="Greens", subset=pd.IndexSlice[products, labels]),
        use_container_width=True,
        height=250,
    )

    st.subheader("Monthly revenue trend")
    data = sales_by_product_by_month(orders)
    months = sorted({m for p in data.values() for m in p})
    chart_data = pd.DataFrame(
        {p: [data[p][m]["revenue"] for m in months] for p in sorted(data)},
        index=pd.to_datetime(months),
    )
    st.bar_chart(chart_data, use_container_width=True)


def render_zero_orders(orders):
    if not orders:
        st.info("No zero-value orders.")
        return

    # ── Monthly sample can totals ─────────────────────────────────────────────
    monthly_cans: dict = {}
    for o in orders:
        month = datetime.strptime(o["created_at"][:7], "%Y-%m").strftime("%b %Y")
        for item in o.get("line_items", []):
            title = item["title"].strip()
            if title and title[0] in ("3", "6") and (len(title) == 1 or not title[1].isdigit()):
                cans = int(title[0]) * item["quantity"]
                monthly_cans[month] = monthly_cans.get(month, 0) + cans

    if monthly_cans:
        st.subheader("Sample cans distributed by month")
        all_months = sorted(
            monthly_cans.keys(),
            key=lambda m: datetime.strptime(m, "%b %Y")
        )
        df_cans = pd.DataFrame(
            {"Cans": [monthly_cans[m] for m in all_months]},
            index=all_months,
        ).T
        df_cans["Total"] = df_cans.sum(axis=1)
        st.dataframe(
            df_cans.style
                .format("{:.0f}")
                .background_gradient(cmap="Oranges", subset=all_months),
            use_container_width=True,
            height=100,
        )
        chart_df = pd.DataFrame(
            {"Cans": [monthly_cans[m] for m in all_months]},
            index=pd.to_datetime([datetime.strptime(m, "%b %Y") for m in all_months]),
        )
        st.bar_chart(chart_df, use_container_width=True)

    st.subheader("All sample orders")
    rows = []
    for o in sorted(orders, key=lambda x: x["created_at"], reverse=True):
        rows.append({
            "Order #":   f"#{o['order_number']}",
            "Date":      o["created_at"][:10],
            "Source":    o.get("source_name", ""),
            "Tags":      o.get("tags", ""),
            "Items":     ", ".join(f"{i['title']} x{i['quantity']}" for i in o.get("line_items", [])),
            "Financial": o.get("financial_status", ""),
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, height=400)


# ── Xero OAuth + rendering ────────────────────────────────────────────────────

XERO_CLIENT_ID     = st.secrets.get("XERO_CLIENT_ID",     os.getenv("XERO_CLIENT_ID", ""))
XERO_CLIENT_SECRET = st.secrets.get("XERO_CLIENT_SECRET", os.getenv("XERO_CLIENT_SECRET", ""))
XERO_REDIRECT_URI  = st.secrets.get("XERO_REDIRECT_URI",  os.getenv("XERO_REDIRECT_URI", "http://localhost:8502"))

xero = XeroClient(XERO_CLIENT_ID, XERO_CLIENT_SECRET, XERO_REDIRECT_URI)

# Restore tokens from session state if available
if "xero_access_token" in st.session_state:
    xero.load_tokens(
        st.session_state["xero_access_token"],
        st.session_state["xero_refresh_token"],
        st.session_state["xero_token_expiry"],
        st.session_state["xero_tenant_id"],
    )

# Handle OAuth callback — Xero redirects back with ?code=...
params = st.query_params
if "code" in params and not xero.is_authenticated():
    with st.spinner("Connecting to Xero…"):
        try:
            xero.exchange_code(params["code"])
            tenants = xero.get_tenants()
            if tenants:
                xero.tenant_id = tenants[0]["tenantId"]
                st.session_state["xero_access_token"]  = xero.access_token
                st.session_state["xero_refresh_token"]  = xero.refresh_token
                st.session_state["xero_token_expiry"]   = xero._token_expiry
                st.session_state["xero_tenant_id"]      = xero.tenant_id
                st.query_params.clear()
                st.rerun()
        except Exception as e:
            st.error(f"Xero auth failed: {e}")


def render_xero():
    if not XERO_CLIENT_ID:
        st.warning("XERO_CLIENT_ID not configured in secrets.")
        return

    if not xero.is_authenticated():
        st.subheader("Connect to Xero")
        st.markdown("Authorise OOM Dashboard to read your Xero accounting data.")
        auth_url = xero.get_auth_url()
        st.link_button("Connect to Xero", auth_url, type="primary")
        return

    org = xero.get_organisation()
    if org:
        st.caption(f"Connected to: **{org.get('Name', '')}**")

    col1, col2 = st.columns(2)
    with col1:
        from_date = st.date_input("From", value=datetime(2025, 1, 1))
    with col2:
        to_date = st.date_input("To", value=datetime.today())

    if st.button("Load P&L"):
        with st.spinner("Fetching monthly P&L from Xero… (one call per month)"):
            try:
                monthly_reports = xero.get_profit_and_loss_monthly(str(from_date), str(to_date))
            except Exception as e:
                st.error(f"Xero API error: {e}")
                return

        if not monthly_reports:
            st.info("No P&L data returned for this period.")
            return

        # ── Parse each single-month report ────────────────────────────────────
        def cell_val(cells, idx):
            try:
                v = cells[idx].get("Value", "") or "0"
                return float(v.replace(",", ""))
            except (ValueError, IndexError):
                return 0.0

        TURNOVER_ACCOUNTS = ("shopify sales", "sales by product", "sales of product income")
        COGS_KW  = ("cost of sales", "direct costs", "cost of goods", "cogs")
        ADMIN_KW = ("operating", "overhead", "administrative", "admin",
                    "expense", "depreciation", "wages", "staff")

        def parse_single(rpt):
            """
            Turnover  = income accounts matching TURNOVER_ACCOUNTS.
            Cost of Sales = all other income accounts + any explicit CoS sections.
            Admin     = operating/expense sections.
            """
            turnover, cogs, admin = {}, {}, {}
            gp, np_ = 0.0, 0.0
            INCOME_KW = ("income", "revenue", "trading income", "sales", "turnover")
            for row in rpt.get("Rows", []):
                rt    = row.get("RowType", "")
                title = row.get("Title", "").lower()
                cells = row.get("Cells", [])
                if rt == "Row":
                    label = cells[0].get("Value", "") if cells else ""
                    if "Gross Profit" in label:
                        gp = cell_val(cells, 1)
                    elif "Net Profit" in label or "Net Loss" in label:
                        np_ = cell_val(cells, 1)
                if rt == "Section":
                    is_income = any(k in title for k in INCOME_KW)
                    is_cogs   = any(k in title for k in COGS_KW)
                    is_admin  = any(k in title for k in ADMIN_KW) and not is_cogs
                    for sub in row.get("Rows", []):
                        if sub.get("RowType") != "Row":
                            continue
                        sc   = sub.get("Cells", [])
                        name = sc[0].get("Value", "").strip() if sc else ""
                        val  = cell_val(sc, 1)
                        if not name:
                            continue
                        if is_income:
                            if any(t in name.lower() for t in TURNOVER_ACCOUNTS):
                                turnover[name] = val
                            else:
                                cogs[name] = val   # other income → cost of sales
                        elif is_cogs:
                            cogs[name] = val
                        elif is_admin:
                            admin[name] = val
            return turnover, cogs, admin, gp, np_

        col_labels     = [m["label"] for m in monthly_reports]
        turnover_rows  = {}
        cogs_rows      = {}
        admin_rows     = {}
        gross_profits  = []
        net_profits    = []

        for m in monthly_reports:
            rpt_data = m["report"].get("Reports", [{}])[0]
            turnover, cogs, admin, gp, np_ = parse_single(rpt_data)
            gross_profits.append(gp)
            net_profits.append(np_)
            idx = col_labels.index(m["label"])
            for bucket, store in [(turnover, turnover_rows), (cogs, cogs_rows), (admin, admin_rows)]:
                for k, v in bucket.items():
                    store.setdefault(k, [0.0] * len(col_labels))
                    store[k][idx] = v

        def make_df(rows_dict):
            if not rows_dict:
                return pd.DataFrame()
            df_out = pd.DataFrame(rows_dict, index=col_labels).T
            df_out = df_out.loc[(df_out != 0).any(axis=1)]
            df_out.loc["Total"] = df_out.sum()
            return df_out

        df_turnover = make_df(turnover_rows)
        df_cogs     = make_df(cogs_rows)
        df_admin    = make_df(admin_rows)

        # Totals series for margin calc
        income_total  = df_turnover.loc["Total"] if not df_turnover.empty else pd.Series([0.0]*len(col_labels), index=col_labels)
        expense_total = (
            (df_cogs.loc["Total"]  if not df_cogs.empty  else pd.Series([0.0]*len(col_labels), index=col_labels)) +
            (df_admin.loc["Total"] if not df_admin.empty else pd.Series([0.0]*len(col_labels), index=col_labels))
        )
        # ── Derived profit figures ────────────────────────────────────────────
        cogs_total  = df_cogs.loc["Total"]  if not df_cogs.empty  else pd.Series([0.0]*len(col_labels), index=col_labels)
        admin_total = df_admin.loc["Total"] if not df_admin.empty else pd.Series([0.0]*len(col_labels), index=col_labels)
        gp_series   = income_total - cogs_total
        np_series   = gp_series - admin_total

        # ── Margin cards — last 6 months ──────────────────────────────────────
        last6_income     = income_total.tail(6).replace(0, float("nan"))
        avg_gross_margin = (gp_series.tail(6) / last6_income).mean() * 100
        avg_net_margin   = (np_series.tail(6) / last6_income).mean() * 100

        m1, m2 = st.columns(2)
        m1.metric("Avg Gross Margin (last 6 months)", f"{avg_gross_margin:.1f}%")
        m2.metric("Avg Net Margin (last 6 months)",   f"{avg_net_margin:.1f}%")

        def colour_profit(val):
            if isinstance(val, (int, float)):
                return "color: #2ecc71" if val >= 0 else "color: #e74c3c"
            return ""

        def stacked_bar(df_table, title):
            if df_table.empty:
                st.info(f"No {title} data found.")
                return
            st.subheader(title)
            accounts = [i for i in df_table.index if i != "Total"]
            try:
                dt_idx = pd.to_datetime(col_labels, format="%b %Y")
            except Exception:
                dt_idx = col_labels
            chart_df = df_table.loc[accounts].T.copy()
            chart_df.index = dt_idx
            st.bar_chart(chart_df, use_container_width=True, stack=True)

        stacked_bar(df_turnover, "Turnover")
        stacked_bar(df_cogs,     "Cost of Sales")
        stacked_bar(df_admin,    "Administrative Costs")

        # ── Summary comparison table ──────────────────────────────────────────
        st.subheader("Monthly summary")
        df_summary = pd.DataFrame({
            "Turnover":      income_total.values,
            "Cost of Sales": cogs_total.values,
            "Admin Costs":   admin_total.values,
            "Gross Profit":  gp_series.values,
            "Net Profit":    np_series.values,
        }, index=col_labels)
        df_summary = df_summary[(df_summary != 0).any(axis=1)]

        st.dataframe(
            df_summary.style
                .format("£{:,.0f}")
                .map(colour_profit, subset=["Gross Profit", "Net Profit"])
                .background_gradient(cmap="Blues", subset=["Turnover"])
                .background_gradient(cmap="Reds",  subset=["Cost of Sales", "Admin Costs"]),
            use_container_width=True,
            height=min(80 + len(df_summary) * 35, 500),
        )

        # ── Trend line chart ──────────────────────────────────────────────────
        try:
            dt_index = pd.to_datetime(df_summary.index, format="%b %Y")
        except Exception:
            dt_index = df_summary.index

        st.subheader("Trend")
        st.line_chart(df_summary.set_index(dt_index), use_container_width=True)


# ── Combined tab ──────────────────────────────────────────────────────────────

def render_combined():
    st.subheader("Combined sales by product / month")
    st.caption("Shopify (direct) + Faire ÷ 12 + Xero invoices (CLF items ÷ 12, all others as units)  ·  matched by Focus / Balance / Calm / Mix")

    c1, c2 = st.columns(2)
    with c1:
        clf_from = st.date_input("Xero CLF from", value=datetime(2025, 1, 1), key="clf_from")
    with c2:
        clf_to = st.date_input("Xero CLF to", value=datetime.today(), key="clf_to")

    # ── Build unified data structure ───────────────────────────────────────────
    combined = defaultdict(lambda: defaultdict(lambda: {
        "shopify": 0.0, "shopify_rev": 0.0,
        "faire":   0.0, "faire_rev":   0.0,
        "xero":    0.0, "xero_rev":    0.0,
    }))
    # channel totals accumulated separately to avoid defaultdict access artefacts
    ch_units = {"Shopify": defaultdict(float), "Faire": defaultdict(float), "Xero": defaultdict(float)}
    ch_rev   = {"Shopify": defaultdict(float), "Faire": defaultdict(float), "Xero": defaultdict(float)}

    shopify_data = sales_by_product_by_month(normal_orders)
    for product, mdata in shopify_data.items():
        for month, vals in mdata.items():
            combined[product][month]["shopify"]     += vals["units"]
            combined[product][month]["shopify_rev"] += vals["revenue"]
            ch_units["Shopify"][month] += vals["units"]
            ch_rev["Shopify"][month]   += vals["revenue"]

    faire_data = sales_by_product_by_month(faire_orders)
    for product, mdata in faire_data.items():
        for month, vals in mdata.items():
            combined[product][month]["faire"]     += vals["units"]   / 12
            combined[product][month]["faire_rev"] += vals["revenue"] / 12
            ch_units["Faire"][month] += vals["units"]   / 12
            ch_rev["Faire"][month]   += vals["revenue"] / 12

    if xero.is_authenticated():
        with st.spinner("Fetching Xero invoice sales…"):
            try:
                xero_data = xero.get_invoice_sales_monthly(str(clf_from), str(clf_to))
                for raw_product, mdata in xero_data.items():
                    n = raw_product.lower()
                    if   "focus"   in n: canonical = "OOM Focus"
                    elif "balance" in n: canonical = "OOM Balance"
                    elif "calm"    in n: canonical = "OOM Calm"
                    elif "mix"     in n: canonical = "OOM Mix"
                    else: continue
                    is_clf  = "clf" in n or any(v.get("clf") for v in mdata.values())
                    divisor = 12 if is_clf else 1
                    for month, vals in mdata.items():
                        combined[canonical][month]["xero"]     += vals["units"]   / divisor
                        combined[canonical][month]["xero_rev"] += vals["revenue"] / divisor
                        ch_units["Xero"][month] += vals["units"]   / divisor
                        ch_rev["Xero"][month]   += vals["revenue"] / divisor
            except Exception as e:
                st.warning(f"Could not load Xero data: {e}")
    else:
        st.info("Connect Xero in the Xero tab to include invoice data.")

    if not combined:
        st.info("No sales data found.")
        return

    # ── Build totals DataFrame ─────────────────────────────────────────────────
    products = sorted(combined.keys())
    months   = sorted({m for p in combined.values() for m in p})
    labels   = [datetime.strptime(m, "%Y-%m").strftime("%b %Y") for m in months]

    rows = {}
    for product in products:
        rows[product] = [
            combined[product][m]["shopify"] +
            combined[product][m]["faire"] +
            combined[product][m]["xero"]
            for m in months
        ]

    df = pd.DataFrame(rows, index=labels).T
    df["Total"] = df.sum(axis=1)
    df.loc["Total"] = df.sum()

    st.dataframe(
        df.style
            .format("{:.1f}")
            .apply(highlight_total, axis=None)
            .background_gradient(cmap="Blues",
                                  subset=pd.IndexSlice[[p for p in products], labels]),
        use_container_width=True,
        height=min(80 + len(df) * 35, 400),
    )

    # ── Breakdown toggle ───────────────────────────────────────────────────────
    if st.toggle("Show source breakdown"):
        for product in products:
            st.markdown(f"**{product}**")
            bk = pd.DataFrame({
                "Shopify":   [combined[product][m]["shopify"] for m in months],
                "Faire ÷12": [combined[product][m]["faire"]   for m in months],
                "Xero":      [combined[product][m]["xero"]    for m in months],
            }, index=labels).T
            st.dataframe(bk.style.format("{:.1f}"), use_container_width=True, height=145)

    # ── Bar chart: units by product ───────────────────────────────────────────
    st.subheader("Combined units by product / month")
    chart_df = pd.DataFrame(rows, index=pd.to_datetime(months))
    st.bar_chart(chart_df, use_container_width=True, stack=True)

    # ── Table + bar chart: units by channel ──────────────────────────────────
    st.subheader("Units by channel / month")
    all_months = sorted({m for ch in ch_units.values() for m in ch})
    ch_labels  = [datetime.strptime(m, "%Y-%m").strftime("%b %Y") for m in all_months]
    df_ch = pd.DataFrame({
        "Shopify": [ch_units["Shopify"].get(m, 0) for m in all_months],
        "Faire":   [ch_units["Faire"].get(m, 0)   for m in all_months],
        "Xero":    [ch_units["Xero"].get(m, 0)    for m in all_months],
    }, index=ch_labels).T
    df_ch["Total"] = df_ch.sum(axis=1)
    df_ch.loc["Total"] = df_ch.sum()
    st.dataframe(
        df_ch.style
            .format("{:.1f}")
            .apply(highlight_total, axis=None)
            .background_gradient(cmap="Blues", subset=pd.IndexSlice[["Shopify", "Faire", "Xero"], ch_labels]),
        use_container_width=True,
        height=185,
    )
    dt_idx_ch  = pd.to_datetime(all_months)
    channel_df = pd.DataFrame(
        {ch: [ch_units[ch].get(m, 0) for m in all_months] for ch in ("Shopify", "Faire", "Xero")},
        index=dt_idx_ch,
    )
    st.bar_chart(channel_df, use_container_width=True, stack=False)

    # ── Line chart: average unit price by channel ─────────────────────────────
    st.subheader("Average unit price by channel / month (£)")
    avg_rows = {"Shopify": [], "Faire": [], "Xero": [], "Total": []}
    for m in all_months:
        for ch in ("Shopify", "Faire", "Xero"):
            u = ch_units[ch].get(m, 0)
            r = ch_rev[ch].get(m, 0)
            avg_rows[ch].append(r / u / 12 if u else None)
        total_u = sum(ch_units[ch].get(m, 0) for ch in ("Shopify", "Faire", "Xero"))
        total_r = sum(ch_rev[ch].get(m, 0)   for ch in ("Shopify", "Faire", "Xero"))
        avg_rows["Total"].append(total_r / total_u / 12 if total_u else None)
    avg_df = pd.DataFrame(avg_rows, index=dt_idx_ch)
    st.line_chart(avg_df, use_container_width=True)


PRODUCT_ALIASES_MAP = {
    "OOM Balance": "balance",
    "OOM Calm":    "calm",
    "OOM Focus":   "focus",
    "OOM Mix":     "mix",
}

# ── Tabs ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    f"Standard orders ({len(normal_orders)})",
    f"Faire ({len(faire_orders)})",
    f"Samples ({len(zero_orders)})",
    "Xero",
    "Combined",
])

with tab1:
    render_tables(normal_orders)

with tab2:
    render_tables(faire_orders)

with tab3:
    render_zero_orders(zero_orders)

with tab4:
    render_xero()

with tab5:
    render_combined()

