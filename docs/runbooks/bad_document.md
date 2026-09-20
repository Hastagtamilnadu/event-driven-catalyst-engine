# Runbook: Bad Document & Parser Failure (RB-06)

## 1. Detection
- Document parser throws unhandled exception during text extraction (e.g. PyMuPDF corrupt stream error).
- Extraction quality classified as `UNSUPPORTED`, `MALICIOUS`, or `OCR_REQUIRED` with extractable text below threshold (< 100 characters for multi-page PDF).
- Document MIME type does not match allowed types (e.g. executable or non-PDF/HTML payload).
- Security scanner detects suspicious macros or prompt-injection patterns in raw text.

## 2. Immediate Freeze Action
- Set document parser status to `QUARANTINED` or `MANUAL_REVIEW_REQUIRED`.
- Isolate the raw file in `data/quarantine/`.
- Block event extraction and prevent event from advancing to `INGESTED` or `REVIEW_PENDING`.
- Log incident in `incident` table.

## 3. Diagnosis
1. Inspect `raw_document` record: check `mime_type`, `bytes`, `extracted_characters`, `extraction_quality`.
2. Inspect raw file bytes: verify PDF header (`%PDF-`) or HTML structure.
3. Test extraction in isolation:
   ```bash
   uv run python -c "import fitz; doc=fitz.open('<path>'); print(len(doc), [len(p.get_text()) for p in doc])"
   ```
4. Check if document is a scanned image without a text layer.

## 4. Recovery
1. If document is a scanned image: queue for OCR processing or manual text entry via review UI.
2. If document is encrypted: check if public announcement has an unencrypted version or exchange text release.
3. If document contains prompt injection: retain payload for security audit; set event state to `REJECTED_MALICIOUS`.
4. Update `raw_document.parser_status` and record extraction quality.

## 5. Reconciliation
1. Verify no corrupt document generated a `canonical_event` or `analyst_assessment`.
2. Ensure raw payload hash is retained in `raw_document` for immutable provenance.

## 6. Closure Evidence
- Document status updated to either `RESOLVED_OCR`, `RESOLVED_MANUAL`, or `PERMANENTLY_BLOCKED`.
- Incident report documented with operator sign-off.

## 7. Prevention Action
- Enforce strict MIME-type sniffing and file magic header checks before parsing.
- Set maximum document size limit (e.g. 50 MB) to prevent denial-of-service via zip bombs.
