from __future__ import annotations

import os

import httpx
import streamlit as st

API_URL = os.getenv("QUAL_ENGINE_API_URL", "http://127.0.0.1:8765")
st.set_page_config(page_title="Event Detail - Qualitative Event Engine", layout="wide")
st.title("Canonical Event Detail")
st.caption("§33.2 side-by-side evidence; no editable field bypasses hard gates.")

try:
    events = httpx.get(f"{API_URL}/events", timeout=10).json()
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
        (f"{row['symbol']} - {str(row.get('headline') or '')[:60]} ({row['event_type']})" for row in events if row["event_id"] == eid),
        eid,
    ),
)

if selected_event_id:
    try:
        bundle = httpx.get(f"{API_URL}/events/{selected_event_id}/evidence", timeout=10).json()
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        st.error(f"Failed to fetch evidence: {exc}")
        st.stop()

    lock = bundle.get("hard_gate_lock", {})
    if lock.get("is_locked"):
        st.error(f"GATE LOCK ACTIVE: {lock.get('reason')}")

    left, right = st.columns(2)
    with left:
        st.subheader("Raw source document and extraction quality")
        st.json(bundle.get("raw_source_document_and_extraction_quality") or bundle.get("document"))
        st.subheader("Timestamps")
        st.json(bundle.get("timestamps_source_publication_system_seen_exchange_seen"))
        st.subheader("Legal entity match")
        st.json(bundle.get("legal_entity_match_and_evidence") or bundle.get("entity"))
        st.subheader("Deterministic facts and cited excerpts")
        st.json(bundle.get("deterministic_facts_and_cited_excerpts") or bundle.get("facts"))
        st.subheader("As-of company dossier")
        st.json(bundle.get("as_of_company_dossier_with_missing_data_warnings") or bundle.get("dossier"))
    with right:
        st.subheader("AI note / model / prompt / invalidating fact")
        st.json(bundle.get("ai_note_model_prompt_version_invalidating_fact") or bundle.get("assessment"))
        st.subheader("Risk-gate result")
        st.json(bundle.get("risk_gate_result_and_reason") or bundle.get("risk_gate"))
        st.subheader("Strategy configuration version")
        st.json(bundle.get("strategy_configuration_version") or bundle.get("configuration"))
        st.subheader("Immutable previous decisions")
        st.json(bundle.get("review_action_and_immutable_previous_decisions") or bundle.get("reviews"))
        st.caption("Review actions are submitted only from the Review Queue. Hard gates cannot be edited here.")
