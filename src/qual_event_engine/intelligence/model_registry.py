from __future__ import annotations

"""§31.1 Model Registry — idempotency + schema-failure retention.

§31.1 verbatim:
  "One event revision creates at most one extraction call and one assessment
  call for a specific model/prompt/configuration hash. Retries reuse the
  idempotency key. A schema failure is retained as an artifact and cannot be
  overwritten by a later response."
"""

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, ClassVar


@dataclass(frozen=True, slots=True)
class ModelMetadata:
    model_id: str
    provider: str
    context_window_tokens: int
    cost_per_million_input_usd: float
    cost_per_million_output_usd: float
    supports_structured_json: bool
    default_timeout_seconds: float


class ModelRegistry:
    """Registry of approved LLM models. Also enforces §31.1 call idempotency."""

    _MODELS: ClassVar[dict[str, ModelMetadata]] = {
        "gemini-3.1-flash-lite": ModelMetadata(
            model_id="gemini-3.1-flash-lite",
            provider="google",
            context_window_tokens=1_000_000,
            cost_per_million_input_usd=0.075,
            cost_per_million_output_usd=0.30,
            supports_structured_json=True,
            default_timeout_seconds=45.0,
        ),
        "gemini-1.5-pro": ModelMetadata(
            model_id="gemini-1.5-pro",
            provider="google",
            context_window_tokens=2_000_000,
            cost_per_million_input_usd=3.50,
            cost_per_million_output_usd=10.50,
            supports_structured_json=True,
            default_timeout_seconds=60.0,
        ),
        "gemini-1.5-flash": ModelMetadata(
            model_id="gemini-1.5-flash",
            provider="google",
            context_window_tokens=1_000_000,
            cost_per_million_input_usd=0.075,
            cost_per_million_output_usd=0.30,
            supports_structured_json=True,
            default_timeout_seconds=45.0,
        ),
    }

    @classmethod
    def get_model(cls, model_id: str) -> ModelMetadata:
        if model_id not in cls._MODELS:
            raise KeyError("Model '" + model_id + "' is not registered in ModelRegistry")
        return cls._MODELS[model_id]

    @classmethod
    def list_models(cls) -> list[ModelMetadata]:
        return list(cls._MODELS.values())

    @staticmethod
    def build_idempotency_key(
        event_revision_id: str,
        model_id: str,
        prompt_version: str,
        config_hash: str,
        call_type: str,  # "extraction" | "assessment"
    ) -> str:
        """§31.1: idempotency key = hash of (revision, model, prompt, config, type)."""
        raw = f"{event_revision_id}|{model_id}|{prompt_version}|{config_hash}|{call_type}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def check_existing_result(
        connection: sqlite3.Connection,
        event_revision_id: str,
        model_id: str,
        prompt_version: str,
        config_hash: str,
        call_type: str,
    ) -> dict[str, Any] | None:
        """§31.1: Return existing assessment row if one already exists for this key.

        The idempotency key prevents a second API call for the same revision+config.
        A schema failure row IS returned — it cannot be overwritten.
        """
        input_hash = ModelRegistry.build_idempotency_key(
            event_revision_id, model_id, prompt_version, config_hash, call_type
        )
        row = connection.execute(
            "SELECT assessment_id, schema_valid, semantic_valid, recommendation, "
            "       rationale, output_hash, created_at_utc "
            "FROM analyst_assessment "
            "WHERE event_revision_id = ? AND model_id = ? AND prompt_version = ? "
            "  AND input_hash = ?",
            (event_revision_id, model_id, prompt_version, input_hash),
        ).fetchone()
        if row is None:
            return None
        return dict(row)

    @staticmethod
    def record_result(
        connection: sqlite3.Connection,
        assessment_id: str,
        event_revision_id: str,
        dossier_hash: str,
        model_id: str,
        model_version: str,
        prompt_version: str,
        input_payload: str,
        output_payload: str,
        recommendation: str,
        rationale: str,
        invalidating_fact: str,
        schema_valid: bool,
        semantic_valid: bool,
        latency_ms: int,
        config_hash: str = "",
        call_type: str = "assessment",
    ) -> None:
        """§31.1: Record one assessment result. NEVER overwrites an existing row.

        A schema failure (schema_valid=False) is retained as an immutable artifact.
        Subsequent calls with the same idempotency key are no-ops.
        """
        input_hash = ModelRegistry.build_idempotency_key(
            event_revision_id, model_id, prompt_version, config_hash, call_type
        )
        output_hash = hashlib.sha256(output_payload.encode()).hexdigest()
        now = datetime.now(UTC).isoformat()

        # INSERT OR IGNORE enforces "cannot be overwritten" requirement
        connection.execute(
            """
            INSERT OR IGNORE INTO analyst_assessment
              (assessment_id, event_revision_id, dossier_hash,
               model_id, model_version, prompt_version,
               input_hash, output_hash,
               recommendation, rationale, invalidating_fact,
               schema_valid, semantic_valid, latency_ms, created_at_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                assessment_id,
                event_revision_id,
                dossier_hash,
                model_id,
                model_version,
                prompt_version,
                input_hash,
                output_hash,
                recommendation,
                rationale,
                invalidating_fact,
                int(schema_valid),
                int(semantic_valid),
                latency_ms,
                now,
            ),
        )
