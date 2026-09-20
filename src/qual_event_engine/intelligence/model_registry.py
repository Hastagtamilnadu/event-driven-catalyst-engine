from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar


@dataclass(frozen=True, slots=True)
class ModelMetadata:
    model_id: str
    provider: str  # "google", "anthropic", "local"
    context_window_tokens: int
    cost_per_million_input_usd: float
    cost_per_million_output_usd: float
    supports_structured_json: bool
    default_timeout_seconds: float


class ModelRegistry:
    """Registry of approved LLM models for qualitative extraction and assessment."""

    _MODELS: ClassVar[dict[str, ModelMetadata]] = {
        "gemini-1.5-pro": ModelMetadata(
            model_id="gemini-1.5-pro",
            provider="google",
            context_window_tokens=2_000_000,
            cost_per_million_input_usd=3.50,
            cost_per_million_output_usd=10.50,
            supports_structured_json=True,
            default_timeout_seconds=30.0,
        ),
        "gemini-1.5-flash": ModelMetadata(
            model_id="gemini-1.5-flash",
            provider="google",
            context_window_tokens=1_000_000,
            cost_per_million_input_usd=0.075,
            cost_per_million_output_usd=0.30,
            supports_structured_json=True,
            default_timeout_seconds=15.0,
        ),
        "mock-analyst": ModelMetadata(
            model_id="mock-analyst",
            provider="local",
            context_window_tokens=100_000,
            cost_per_million_input_usd=0.0,
            cost_per_million_output_usd=0.0,
            supports_structured_json=True,
            default_timeout_seconds=1.0,
        ),
    }

    @classmethod
    def get_model(cls, model_id: str) -> ModelMetadata:
        if model_id not in cls._MODELS:
            raise KeyError(f"Model '{model_id}' is not registered in ModelRegistry")
        return cls._MODELS[model_id]

    @classmethod
    def list_models(cls) -> list[ModelMetadata]:
        return list(cls._MODELS.values())
