from __future__ import annotations

import os

import httpx
import streamlit as st

API_URL = os.getenv("QUAL_ENGINE_API_URL", "http://127.0.0.1:8765")
st.set_page_config(page_title="Review Queue - Qualitative Event Engine", layout="wide")
st.title("Review Queue & Forensic Evidence Console")
st.caption("Section 33.2 side-by-side evidence panes and immutable gate locks")

# Fetch review queue events
try:
    events = httpx.get(f"{API_URL}/events", params={"state": "REVIEW_PENDING", "limit": 200}, timeout=10).json()
except (httpx.HTTPError, ValueError) as exc:
    st.error(f"Failed to connect to API at {API_URL}: {exc}")
    st.stop()

if not events:
    # If no REVIEW_PENDING, allow selecting from all recent events to inspect evidence
    st.info("No events currently in REVIEW_PENDING state. Showing recent ingested/assessed events.")
    events = httpx.get(f"{API_URL}/events", params={"limit": 50}, timeout=10).json()

if not events:
    st.warning("No events available in the system.")
    st.stop()

selected_event_id = st.selectbox(
    "Select Event for Review",
    [row["event_id"] for row in events],
    format_func=lambda eid: next(
        f"{row['symbol']} - {row['headline'][:70]}... ({row['event_state']})"
        for row in events
        if row["event_id"] == eid
    ),
)

if selected_event_id:
    try:
        bundle = httpx.get(f"{API_URL}/events/{selected_event_id}/evidence", timeout=10).json()
    except (httpx.HTTPError, ValueError) as exc:
        st.error(f"Failed to fetch evidence bundle: {exc}")
        st.stop()

    event = bundle.get("event", {})
    doc = bundle.get("document", {})
    entity = bundle.get("entity", {})
    dossier = bundle.get("dossier", {})
    assessment = bundle.get("assessment", {})
    risk_gate = bundle.get("risk_gate", {})
    config = bundle.get("configuration", {})
    reviews = bundle.get("reviews", [])
    hard_lock = bundle.get("hard_gate_lock", {})

    st.markdown("---")

    # Hard gate lock alert
    if hard_lock.get("is_locked"):
        st.error(f"🔒 **GATE LOCK ACTIVE**: {hard_lock.get('reason')}")
    else:
        st.success("🟢 **GATE UNLOCKED**: Event satisfies all preliminary risk filters.")

    # Side-by-side layout: 3 columns per §33.2
    col1, col2, col3 = st.columns([1.2, 1.2, 1.1])

    with col1:
        st.subheader("1. Source & Entity Dossier")
        with st.container(border=True):
            st.markdown("#### Raw Document & Provenance")
            st.markdown(f"**Source Native ID:** `{doc.get('source_native_id', 'N/A')}`")
            st.markdown(f"**Source URL:** [{doc.get('source_url', 'Link')}]({doc.get('source_url', '#')})")
            st.markdown(f"**Extraction Quality:** `{doc.get('extraction_quality', 'UNKNOWN')}`")
            st.markdown(f"**Document SHA-256:** `{doc.get('raw_sha256', 'N/A')}`")
            st.markdown(f"**File Size:** `{doc.get('bytes', 0):,} bytes` | **MIME:** `{doc.get('mime_type', 'N/A')}`")

            st.markdown("---")
            st.markdown("#### Timestamps (§2.1, §32.2)")
            st.markdown(f"**Source Published At:** `{doc.get('source_published_at_utc', 'N/A')}`")
            st.markdown(f"**Exchange Seen At:** `{doc.get('exchange_first_seen_at_utc', 'N/A')}`")
            st.markdown(f"**System Seen At:** `{doc.get('system_first_seen_at_utc', 'N/A')}`")

            st.markdown("---")
            st.markdown("#### Legal Entity & Relationships (§28)")
            st.markdown(f"**Legal Name:** {entity.get('legal_name', event.get('legal_name', 'N/A'))}")
            st.markdown(f"**Symbol:** `{entity.get('primary_symbol', event.get('symbol', 'N/A'))}` | **ISIN:** `{entity.get('primary_isin', event.get('isin', 'N/A'))}`")
            st.markdown(f"**Entity Status:** `{entity.get('status', 'ACTIVE')}`")
            if bundle.get("relationships"):
                st.markdown("**Relationships:**")
                for rel in bundle["relationships"]:
                    st.markdown(f"- {rel.get('relationship_type')} ({rel.get('ownership_pct')}%)")

            st.markdown("---")
            st.markdown("#### As-Of Company Dossier")
            mem = dossier.get("membership", {})
            st.markdown(f"**Eligible:** `{bool(mem.get('eligible', False))}`")
            st.markdown(f"**Market Cap:** ₹{mem.get('market_cap_inr', 0):,.0f}" if mem.get("market_cap_inr") else "**Market Cap:** N/A")
            st.markdown(f"**ADT20:** ₹{mem.get('adt20_inr', 0):,.0f}" if mem.get("adt20_inr") else "**ADT20:** N/A")

            warnings = dossier.get("missing_data_warnings", [])
            if warnings:
                for w in warnings:
                    st.warning(f"⚠️ {w}")
            else:
                st.info("No missing data warnings.")

    with col2:
        st.subheader("2. Evidence & AI Assessment")
        with st.container(border=True):
            st.markdown("#### Deterministic Facts & Cited Excerpts (§31)")
            facts = bundle.get("facts", [])
            if facts:
                for f in facts:
                    badge = "✅" if f.get("validation_status") == "VERIFIED" else "❌"
                    st.markdown(f"{badge} **{f.get('field_name')}:** `{f.get('value_json', '')}`")
                    st.caption(f"Cited excerpt: *\"{f.get('evidence_text', '')}\"*")
            else:
                st.caption("No structured facts extracted.")

            st.markdown("---")
            st.markdown("#### AI Research Note (§31.3)")
            if assessment:
                rec = assessment.get("recommendation", "UNKNOWN")
                color = "green" if rec == "BUY_CANDIDATE" else "orange" if rec == "WATCH" else "red"
                st.markdown(f"**Recommendation:** :{color}[**{rec}**] (Confidence: `{assessment.get('confidence', 'N/A')}`)")
                st.markdown(f"**Rationale:** {assessment.get('rationale', 'N/A')}")
                st.markdown(f"**Invalidating Fact:** `{assessment.get('invalidating_fact', 'N/A')}`")
                st.caption(f"Model: `{assessment.get('model_id')}` | Prompt: `{assessment.get('prompt_version')}` | Latency: `{assessment.get('latency_ms')} ms`")
            else:
                st.caption("No AI assessment performed.")

            st.markdown("---")
            st.markdown("#### Risk-Gate Result (§15, §31.4)")
            gate_pass = risk_gate.get("passed", False)
            if gate_pass:
                st.success(f"Gate Check: PASS ({risk_gate.get('reason')})")
            else:
                st.error(f"Gate Check: FAIL ({risk_gate.get('reason')})")

            st.markdown("---")
            st.markdown("#### Strategy & Risk Versioning")
            st.caption(f"Strategy Book Hash: `{config.get('strategy_book_hash', 'N/A')[:16]}...`")
            st.caption(f"Risk Config Hash: `{config.get('risk_config_hash', 'N/A')[:16]}...`")

    with col3:
        st.subheader("3. Decisions & Actions")
        with st.container(border=True):
            st.markdown("#### Immutable Previous Decisions")
            if reviews:
                for r in reviews:
                    st.markdown(f"**{r.get('decision')}** by `{r.get('reviewer')}` at `{r.get('reviewed_at_utc')}`")
                    st.caption(f"Rationale: {r.get('rationale')}")
                    st.markdown("---")
            else:
                st.caption("No previous review decisions recorded.")

            st.markdown("#### Operator Review Action")
            # Section 33.2: "The interface has no editable field that can bypass a blocked entity, disabled strategy, stale data freeze, or incident freeze."
            if hard_lock.get("is_locked"):
                st.error("🚫 Review submission is locked. Hard risk gates, incident freeze, or blocked entity prevent override.")
            else:
                reviewer = st.text_input("Reviewer Name", key="reviewer_name")
                decision = st.selectbox(
                    "Decision",
                    ["APPROVE", "REJECT", "REQUEST_MORE_EVIDENCE", "OVERRIDE_TO_WATCH"],
                    key="review_decision_val",
                )
                rationale = st.text_area("Review Rationale", key="review_rationale")
                version = st.text_input("Review Version", value="1", key="review_version")

                if st.button("Submit Immutable Decision", type="primary"):
                    if not reviewer or not rationale or not version:
                        st.error("Reviewer, Rationale, and Version are required.")
                    else:
                        headers = {}
                        token = os.getenv("QUAL_ENGINE_LOCAL_API_TOKEN")
                        if token:
                            headers["X-Qual-Token"] = token
                        resp = httpx.post(
                            f"{API_URL}/events/{selected_event_id}/review",
                            json={
                                "reviewer": reviewer,
                                "decision": decision,
                                "rationale": rationale,
                                "version": version,
                            },
                            headers=headers,
                            timeout=10,
                        )
                        if resp.is_success:
                            st.success("Decision recorded successfully!")
                            st.rerun()
                        else:
                            st.error(f"Failed to record decision: {resp.text}")
