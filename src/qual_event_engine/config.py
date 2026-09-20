from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from qual_event_engine.domain.models import StrategyConfig
from qual_event_engine.operations.hashing import sha256_json


class RiskConfig(BaseModel):
    paper_nav_inr: float
    maximum_sector_nav_pct: float
    daily_loss_freeze_pct: float
    drawdown_freeze_pct: float
    negative_blacklist_sessions: int


class StrategyBook(BaseModel):
    strategies: dict[str, StrategyConfig]


def read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"Configuration at {path} must be a YAML mapping")
    return value


def load_strategy_book(project_root: Path) -> tuple[StrategyBook, str]:
    raw = read_yaml(project_root / "configs" / "strategies.yaml")
    return StrategyBook.model_validate(raw), sha256_json(raw)


def load_risk_config(project_root: Path) -> tuple[RiskConfig, str]:
    raw = read_yaml(project_root / "configs" / "risk.yaml")
    return RiskConfig.model_validate(raw), sha256_json(raw)
