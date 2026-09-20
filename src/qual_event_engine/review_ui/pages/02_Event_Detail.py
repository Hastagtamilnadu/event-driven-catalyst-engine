from __future__ import annotations

import os

import httpx
import streamlit as st

API_URL = os.getenv("QUAL_ENGINE_API_URL", "http://127.0.0.1:8765")
st.set_page_config(page_title="Event Detail - Qualitative Event Engine", layout="wide")
st.title("Canonical Event Detail & Verbatim Evidence")
st.caption("Inspect raw text grounding, extraction confidence, and immutable audit trails.")

try:
    events = httpx.get(f"{API_URL}/events", params={"limit": 100}, timeout=10).json()
except (httpx.HTTPError, ValueError, KeyError) as exc:
    st.error(f"Failed to connect to API at {API_URL}: {exc}")
    st.stop()

if not events:
    st.warning("No canonical events found.")
    st.stop()

selected_event_id = st.selectbox(
    "Select Event",
    [row["event_id"] for row in events],
    format_func=lambda eid: next(
        (f"{row['symbol']} - {row['headline'][:60]} ({row['event_type']})" for row in events if row["event_id"] == eid),
        eid,
    ),
)

if selected_event_id:
    ev = next(e for e in events if e["event_id"] == selected_event_id)
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("Event Metadata")
        st.json(ev)

    with col2:
        st.subheader("Evidence & Verbatim Grounding")
        try:
            bundle = httpx.get(f"{API_URL}/events/{selected_event_id}/evidence", timeout=10).json()
            st.write("Verbatim Quote / Excerpt:")
            st.info(bundle.get("document", {}).get("extracted_characters", "No text extracted"))
            st.write("Extracted Facts:")
            st.json(bundle.get("assessment", {}))
        except (httpx.HTTPError, ValueError, KeyError):
            st.write("Evidence bundle not available via API.")
