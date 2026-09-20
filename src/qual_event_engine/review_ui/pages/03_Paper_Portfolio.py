from __future__ import annotations

import os

import httpx
import streamlit as st

API_URL = os.getenv("QUAL_ENGINE_API_URL", "http://127.0.0.1:8765")
st.set_page_config(page_title="Paper Portfolios - Qualitative Event Engine", layout="wide")
st.title("Paper Portfolios & Position Ledger")
st.caption("Live simulated positions, fills, executions, and daily cash reconciliation.")

try:
    positions = httpx.get(f"{API_URL}/positions", timeout=10).json()
    orders = httpx.get(f"{API_URL}/orders", timeout=10).json()
    performance = httpx.get(f"{API_URL}/reports/performance", timeout=10).json()

    st.subheader("Open Positions")
    st.dataframe(positions, use_container_width=True)

    st.subheader("Recent Orders & Fills")
    st.dataframe(orders, use_container_width=True)

    st.subheader("Strategy Execution Summary")
    st.dataframe(performance.get("strategy_performance", []), use_container_width=True)

    st.subheader("Cash Reconciliation")
    st.dataframe(performance.get("reconciliation", {}).get("cash_by_strategy", []), use_container_width=True)
except (httpx.HTTPError, ValueError, KeyError) as exc:
    st.error(f"Failed to connect to API at {API_URL}: {exc}")
