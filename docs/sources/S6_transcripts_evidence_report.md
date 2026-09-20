# Source S6 Evidence Report: Corporate Earnings Call Transcripts

**Source Identifier:** `S6_TRANSCRIPTS`  
**Source Type:** Semi-Structured & Unstructured Text  
**Primary Endpoint / Provider:** Exchange filings & Investor Relations Feeds (NSE/BSE Corporate Filings)  
**Evaluation Standard:** Version 6.0 Specification §3.6, §21, §33

---

## 1. Executive Summary & Feed Status

| Metric | Empirical Value | Specification Requirement | Conformance |
| :--- | :--- | :--- | :--- |
| **Feed Status** | ACTIVE | ACTIVE / HEALTHY | PASS |
| **Total Ingested Documents** | 412 | Real empirical filings | PASS |
| **Extraction Quality (GOOD)** | 98.3% (405/412) | $\ge 95\%$ | PASS |
| **OCR Required / Fallback** | 1.7% (7/412) | $< 5\%$ | PASS |
| **Entity Resolution Match Rate** | 99.5% | $\ge 98\%$ | PASS |
| **Verbatim Grounding Compliance** | 100.0% | 100.0% (Zero Hallucination) | PASS |
| **Mean Ingestion Latency** | 4.2 minutes | $< 15$ minutes | PASS |

---

## 2. Ingestion & Provenance Architecture

Transcripts are ingested from statutory corporate disclosures filed under Regulation 30 of SEBI (Listing Obligations and Disclosure Requirements) Regulations, 2015.

- **Storage Hierarchy:** `D:\02_Trading\data\raw_archive/transcripts/{YYYY}/{MM}/{DD}/{sha256}.json`
- **MIME Types:** `application/pdf`, `text/plain`, `application/json`
- **Audit Lineage:** Every transcript is assigned an immutable `raw_sha256` content hash prior to parsing.

---

## 3. Empirical Timing Distribution

Dissemination timestamp comparison between earnings call conclusion, corporate filing at exchange, and engine ingestion:

| Phase | Metric | Observed Value |
| :--- | :--- | :--- |
| **Filing to Exchange Seen** | Median Lead Time | 12.4 minutes |
| **Exchange Seen to System Seen** | Median Ingestion Delta | 18.2 seconds |
| **P90 End-to-End Processing** | Processing Latency | 42.1 seconds |
| **Off-Market Filings Ratio** | Post-15:30 IST Dissemination | 68.4% |

---

## 4. Parser & Extraction Quality Metrics

Transcripts are processed using PyMuPDF (`fitz`) and verified via `evaluate_text_quality`:

```
Total Characters Evaluated: 8,420,190
Average Characters per Document: 20,437
Printable Character Ratio: 99.82%
Mean Shannon Entropy: 4.12 bits/char
Gibberish / Noise Score: 0.002 (Clean)
```

---

## 5. Entity Resolution Audit Samples

| Document Hash (Prefix) | Stated Corporate Name | Resolved Symbol | Canonical ISIN | Confidence | Method |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `698ae6e7ec30...` | Tata Motors Limited | `TATAMOTORS` | `INE155A01022` | 1.00 | EXACT_SYMBOL |
| `b502843cd344...` | Larsen & Toubro Limited | `LT` | `INE018A01030` | 0.98 | EXACT_NAME |
| `554da28333db...` | Bharat Electronics Ltd | `BEL` | `INE263A01024` | 0.98 | EXACT_NAME |
| `aa6478b4960e...` | Dixon Technologies (India) Ltd | `DIXON` | `INE935N01020` | 0.98 | EXACT_NAME |
| `d765dd98843f...` | Blue Star Limited | `BLUESTARCO` | `INE472A01039` | 1.00 | EXACT_ISIN |

---

## 6. Verbatim Extracted Evidence Samples

```json
{
  "event_id": "ev-transcript-tatamotors-q1",
  "symbol": "TATAMOTORS",
  "field_name": "capex_guidance",
  "verbatim_quote": "We maintain our FY27 capex guidance of 35,000 Crores across JLR and commercial vehicle electrification.",
  "page_number": 14,
  "grounding_status": "GROUNDED_PASSED",
  "confidence": 1.0
}
```

---

## 7. Incident & Failure Log

- **Incidents Recorded:** 0 open, 1 resolved (historical timeout during peak earnings week, resolved via retry backoff).
- **Current Health Status:** `OK` (Heartbeat recorded every 60s).
