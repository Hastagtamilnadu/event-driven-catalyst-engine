from __future__ import annotations

import os

import httpx
import streamlit as st

API_URL = os.getenv("QUAL_ENGINE_API_URL", "http://127.0.0.1:8765")
st.set_page_config(page_title="Source Health - Qualitative Event Engine", layout="wide")
st.title("Source Adapter Health & Heartbeat Console")
st.caption("Status of 9 primary data feeds, error rates, and observation ingestion latency.")

try:
    health = httpx.get(f"{API_URL}/sources/health", timeout=10).json()
    st.subheader("Adapter Health Records")
    st.dataframe(health, use_container_width=True)

    lead_times = httpx.get(f"{API_URL}/reports/lead-time", timeout=10).json()
    st.subheader("Source Dissemination Lead Times")
    st.dataframe(lead_times, use_container_width=True)
except (httpx.HTTPError, ValueError, KeyError) as exc:
    st.error(f"Failed to connect to API at {API_URL}: {exc}")
