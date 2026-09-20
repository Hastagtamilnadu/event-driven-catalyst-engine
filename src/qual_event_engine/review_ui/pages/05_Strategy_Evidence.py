from __future__ import annotations

import os

import httpx
import streamlit as st

API_URL = os.getenv("QUAL_ENGINE_API_URL", "http://127.0.0.1:8765")
st.set_page_config(page_title="Strategy Evidence - Qualitative Event Engine", layout="wide")
st.title("Strategy Scientific Evidence & Acceptance")
st.caption("Section 19 Strategy Acceptance Contract evaluation, CAR analysis, and multi-regime robustness.")

try:
    strategies = httpx.get(f"{API_URL}/strategies", timeout=10).json()
    st.subheader("Configured Strategies & Risk Limits")
    st.json(strategies)

    perf = httpx.get(f"{API_URL}/reports/strategy-performance", timeout=10).json()
    st.subheader("Strategy Realized Performance")
    st.dataframe(perf, use_container_width=True)
except (httpx.HTTPError, ValueError, KeyError) as exc:
    st.error(f"Failed to connect to API at {API_URL}: {exc}")
