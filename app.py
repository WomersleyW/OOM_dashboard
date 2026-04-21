"""
OOM Dashboard — Streamlit app
"""

import os
import pandas as pd
import streamlit as st
from shopify import ShopifyClient, sales_by_product_by_month
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
    orders = client.get_all_orders(financial_status="paid")
    return orders

with st.spinner("Fetching orders from Shopify…"):
    orders = load_data(store_url, access_token)

st.caption(f"{len(orders)} paid orders loaded  ·  refreshes every 5 minutes")

data = sales_by_product_by_month(orders)

# ── Build DataFrames ──────────────────────────────────────────────────────────

products = sorted(data.keys())
months = sorted({m for p in data.values() for m in p})
month_labels = [datetime.strptime(m, "%Y-%m").strftime("%b %Y") for m in months]

units_rows = {p: [data[p][m]["units"] for m in months] for p in products}
revenue_rows = {p: [round(data[p][m]["revenue"], 2) for m in months] for p in products}

df_units = pd.DataFrame(units_rows, index=month_labels).T
df_revenue = pd.DataFrame(revenue_rows, index=month_labels).T

# Add totals
df_units["Total"] = df_units.sum(axis=1)
df_units.loc["Total"] = df_units.sum()

df_revenue["Total"] = df_revenue.sum(axis=1)
df_revenue.loc["Total"] = df_revenue.sum()

# ── Units table ───────────────────────────────────────────────────────────────

st.subheader("Units sold by product / month")

def highlight_total(df):
    styles = pd.DataFrame("", index=df.index, columns=df.columns)
    styles.iloc[-1, :] = "font-weight: bold; background-color: #f0f0f0"
    styles.iloc[:, -1] = "font-weight: bold; background-color: #f0f0f0"
    return styles

st.dataframe(
    df_units.style
        .apply(highlight_total, axis=None)
        .format("{:.0f}")
        .background_gradient(cmap="Blues", subset=pd.IndexSlice[products, month_labels]),
    use_container_width=True,
    height=250,
)

# ── Revenue table ─────────────────────────────────────────────────────────────

st.subheader("Revenue (£) by product / month")

st.dataframe(
    df_revenue.style
        .apply(highlight_total, axis=None)
        .format("£{:.0f}")
        .background_gradient(cmap="Greens", subset=pd.IndexSlice[products, month_labels]),
    use_container_width=True,
    height=250,
)

# ── Monthly totals bar chart ──────────────────────────────────────────────────

st.subheader("Monthly revenue trend (£)")

chart_data = pd.DataFrame({
    p: [data[p][m]["revenue"] for m in months]
    for p in products
}, index=month_labels)

st.bar_chart(chart_data, use_container_width=True)
