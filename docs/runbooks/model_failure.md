# Runbook: Model Failure (RB-03)

## 1. Detection
- Gemini API returns HTTP 4xx/5xx (e.g. 429 Quota Exceeded, 503 Service Unavailable, 400 Bad Request).
- JSON schema validation fails on model output (`schema_valid = 0`).
- Semantic validator detects ungrounded fact citation or hallucination (`semantic_valid = 0` or `hallucination_detected = True`).
- Model assessment latency exceeds configured timeout (`gemini_timeout_seconds`).

## 2. Immediate Freeze Action
- Mark affected event revision as `ASSESSMENT_FAILED`.
- Block event from advancing to `REVIEW_PENDING` or `APPROVED`.
- Record failed model response and raw text as an immutable artifact; do NOT overwrite.
- If consecutive model failures exceed 5, pause AI assessment pipeline and alert operator.

## 3. Diagnosis
1. Inspect `analyst_assessment` table for `schema_valid`, `semantic_valid`, and `latency_ms`.
2. Inspect `data/logs/YYYY/MM/DD/` for HTTP response payloads and Gemini error details.
3. If quota error (429), check project quota limits and rate-limiting tier.
4. If hallucination, check raw document text vs extracted quote offsets in `extracted_fact`.

## 4. Recovery
1. If transient 503 or 429, retry with exponential backoff and jitter.
2. If schema violation, verify prompt template version against model ID.
3. Re-run assessment: `uv run qual-engine process-events`.
4. If model version is deprecated, update `GEMINI_MODEL_ID` in `.env` after benchmark testing.

## 5. Reconciliation
1. Verify failed event revisions have not generated downstream paper orders.
2. Verify input hash and output hash are recorded in `analyst_assessment`.
3. Check that no hallucinated fact remains in `extracted_fact`.

## 6. Closure Evidence
- Event successfully evaluated with `schema_valid = 1` and `semantic_valid = 1`.
- Benchmark test suite `tests/test_benchmarks.py` passes 20/20 fixtures.
- Incident marked `RESOLVED`.

## 7. Prevention Action
- Ensure monthly benchmark suite runs before any prompt or model version bump.
- Maintain API quota headroom and implement client-side token bucket rate-limiting.
