"""
OOM Dashboard — Streamlit app
"""

import os
import pandas as pd
import streamlit as st
from shopify import ShopifyClient, sales_by_product_by_month, classify_orders
from xero import XeroClient
from datetime import datetime

st.set_page_config(page_title="OOM Dashboard", page_icon="🥤", layout="wide")

st.title("🥤 OOM Sales Dashboard")

# ── Credentials: st.secrets (Streamlit Cloud) with fallback to .env ───────────

store_url = st.secrets.get("SHOPIFY_STORE_URL", os.getenv("SHOPIFY_STORE_URL", ""))
access_token = st.secrets.get("SHOPIFY_ACCESS_TOKEN", os.getenv("SHOPIFY_ACCESS_TOKEN", ""))

# ── Data loading ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_data(_store_url, _access_token):
    client = ShopifyClient(store_url=_store_url, access_token=_access_token)
    return client.get_all_orders(financial_status="any")

with st.spinner("Fetching orders from Shopify…"):
    all_orders = load_data(store_url, access_token)

normal_orders, faire_orders, zero_orders = classify_orders(all_orders)

st.caption(
    f"{len(all_orders)} total orders  ·  "
    f"{len(normal_orders)} standard  ·  "
    f"{len(faire_orders)} Faire  ·  "
    f"{len(zero_orders)} zero-value  ·  "
    f"refreshes every 5 minutes"
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
        with st.spinner("Fetching P&L from Xero…"):
            try:
                report = xero.get_profit_and_loss(str(from_date), str(to_date))
            except Exception as e:
                st.error(f"Xero API error: {e}")
                return

        reports = report.get("Reports", [])
        if not reports:
            st.info("No P&L data returned for this period.")
            return

        rpt = reports[0]

        # ── Parse monthly columns and key rows ────────────────────────────────
        def cell_val(cells, idx):
            try:
                v = cells[idx].get("Value", "") or "0"
                return float(v.replace(",", ""))
            except (ValueError, IndexError):
                return 0.0

        # Header row gives column labels (skip first "Account" cell)
        header_row = next((r for r in rpt["Rows"] if r.get("RowType") == "Header"), None)
        if not header_row:
            st.error("Could not parse P&L header.")
            return
        col_labels = [c.get("Value", "") for c in header_row["Cells"][1:]]

        income_rows   = {}  # {account_name: [val_per_month]}
        expense_rows  = {}
        gross_profit  = [0.0] * len(col_labels)
        net_profit    = [0.0] * len(col_labels)

        INCOME_KEYWORDS  = ("income", "revenue", "trading income", "sales")
        EXPENSE_KEYWORDS = ("expense", "cost", "overhead", "operating", "depreciation", "wages")

        for row in rpt["Rows"]:
            rt    = row.get("RowType", "")
            title = row.get("Title", "").lower()
            cells = row.get("Cells", [])

            if rt == "Row":
                label = cells[0].get("Value", "") if cells else ""
                if "Gross Profit" in label:
                    gross_profit = [cell_val(cells, i + 1) for i in range(len(col_labels))]
                elif "Net Profit" in label or "Net Loss" in label:
                    net_profit = [cell_val(cells, i + 1) for i in range(len(col_labels))]

            if rt == "Section":
                is_income  = any(k in title for k in INCOME_KEYWORDS)
                is_expense = any(k in title for k in EXPENSE_KEYWORDS)
                for sub in row.get("Rows", []):
                    sub_rt    = sub.get("RowType", "")
                    sub_cells = sub.get("Cells", [])
                    if not sub_cells:
                        continue
                    name = sub_cells[0].get("Value", "").strip()
                    vals = [cell_val(sub_cells, i + 1) for i in range(len(col_labels))]
                    if sub_rt == "Row" and name:
                        if is_income:
                            income_rows[name]  = vals
                        elif is_expense:
                            expense_rows[name] = vals

        def make_df(rows_dict):
            if not rows_dict:
                return pd.DataFrame()
            df_out = pd.DataFrame(rows_dict, index=col_labels).T
            df_out = df_out.loc[(df_out != 0).any(axis=1)]
            df_out.loc["Total"] = df_out.sum()
            return df_out

        df_income   = make_df(income_rows)
        df_expenses = make_df(expense_rows)

        # Totals series for margin calc
        income_total  = df_income.loc["Total"]  if not df_income.empty  else pd.Series([0]*len(col_labels), index=col_labels)
        expense_total = df_expenses.loc["Total"] if not df_expenses.empty else pd.Series([0]*len(col_labels), index=col_labels)
        gp_series = pd.Series(gross_profit, index=col_labels)
        np_series = pd.Series(net_profit,   index=col_labels)

        # ── Margin cards — last 6 months ──────────────────────────────────────
        last6_income = income_total.tail(6).replace(0, float("nan"))
        avg_gross_margin = (gp_series.tail(6) / last6_income).mean() * 100
        avg_net_margin   = (np_series.tail(6) / last6_income).mean() * 100

        m1, m2 = st.columns(2)
        m1.metric("Avg Gross Margin (last 6 months)", f"{avg_gross_margin:.1f}%")
        m2.metric("Avg Net Margin (last 6 months)",   f"{avg_net_margin:.1f}%")

        def colour_profit(val):
            if isinstance(val, (int, float)):
                return "color: #2ecc71" if val >= 0 else "color: #e74c3c"
            return ""

        def render_breakdown(df_table, title, cmap):
            if df_table.empty:
                return
            st.subheader(title)
            products = [i for i in df_table.index if i != "Total"]
            st.dataframe(
                df_table.style
                    .format("£{:,.0f}")
                    .background_gradient(cmap=cmap, subset=pd.IndexSlice[products, col_labels])
                    .apply(lambda _: ["font-weight:bold; background-color:#1565C0; color:white"] * len(df_table.columns),
                           subset=pd.IndexSlice[["Total"], :], axis=1),
                use_container_width=True,
                height=min(80 + len(df_table) * 35, 500),
            )

        render_breakdown(df_income,   "Income by account / month",   "Blues")
        render_breakdown(df_expenses, "Expenses by account / month", "Reds")

        # ── Summary comparison table ──────────────────────────────────────────
        st.subheader("Monthly summary")
        df_summary = pd.DataFrame({
            "Income":       income_total.values,
            "Expenses":     expense_total.values,
            "Gross Profit": gross_profit,
            "Net Profit":   net_profit,
        }, index=col_labels)
        df_summary = df_summary[(df_summary != 0).any(axis=1)]

        st.dataframe(
            df_summary.style
                .format("£{:,.0f}")
                .map(colour_profit, subset=["Gross Profit", "Net Profit"])
                .background_gradient(cmap="Blues",  subset=["Income"])
                .background_gradient(cmap="Reds",   subset=["Expenses"]),
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


# ── Tabs ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs([
    f"Standard orders ({len(normal_orders)})",
    f"Faire ({len(faire_orders)})",
    f"Samples ({len(zero_orders)})",
    "Xero",
])

with tab1:
    render_tables(normal_orders)

with tab2:
    render_tables(faire_orders)

with tab3:
    render_zero_orders(zero_orders)

with tab4:
    render_xero()

