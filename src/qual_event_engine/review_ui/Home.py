from __future__ import annotations

import os

import httpx
import streamlit as st

API_URL = os.getenv("QUAL_ENGINE_API_URL", "http://127.0.0.1:8765")

st.set_page_config(page_title="Qualitative Event Engine", layout="wide")
st.title("Qualitative Event Engine")
st.caption("Evidence-bound event research and separate paper portfolios")

try:
    health = httpx.get(f"{API_URL}/health", timeout=5).json()
    st.metric("Engine status", health["status"])
    st.subheader("Source health")
    st.dataframe(health["sources"], use_container_width=True)
    st.subheader("Event states")
    st.dataframe(health["event_states"], use_container_width=True)
    if health["open_incidents"]:
        st.error("Paper-intent freeze is active.")
        st.dataframe(health["open_incidents"], use_container_width=True)
except httpx.HTTPError as exc:
    st.error(f"Cannot reach local API at {API_URL}: {exc}")
