"""
OOM Dashboard — Streamlit app
"""

import os
import pandas as pd
import streamlit as st
from shopify import ShopifyClient, sales_by_product_by_month, classify_orders
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
    styles.iloc[-1, :] = "font-weight: bold; background-color: #f0f0f0"
    styles.iloc[:, -1] = "font-weight: bold; background-color: #f0f0f0"
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
    month_labels = [datetime.strptime(m, "%Y-%m").strftime("%b %Y") for m in months]
    chart_data = pd.DataFrame(
        {p: [data[p][m]["revenue"] for m in months] for p in sorted(data)},
        index=month_labels,
    )
    st.bar_chart(chart_data, use_container_width=True)


def render_zero_orders(orders):
    if not orders:
        st.info("No zero-value orders.")
        return

    rows = []
    for o in sorted(orders, key=lambda x: x["created_at"], reverse=True):
        rows.append({
            "Order #":    f"#{o['order_number']}",
            "Date":       o["created_at"][:10],
            "Source":     o.get("source_name", ""),
            "Tags":       o.get("tags", ""),
            "Items":      ", ".join(f"{i['title']} x{i['quantity']}" for i in o.get("line_items", [])),
            "Financial":  o.get("financial_status", ""),
        })

    st.dataframe(pd.DataFrame(rows), use_container_width=True, height=500)


# ── Tabs ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3 = st.tabs([
    f"Standard orders ({len(normal_orders)})",
    f"Faire ({len(faire_orders)})",
    f"Zero-value ({len(zero_orders)})",
])

with tab1:
    render_tables(normal_orders)

with tab2:
    render_tables(faire_orders)

with tab3:
    render_zero_orders(zero_orders)
