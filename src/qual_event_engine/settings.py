from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    for candidate in (
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[3] / ".env",
        Path(r"D:\02_Trading\qual_event_engine\.env"),
    ):
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip("'\"")
                if key and key not in os.environ:
                    os.environ[key] = val
            break


def _path(name: str, default: str) -> Path:
    return Path(os.getenv(name, default)).expanduser()


@dataclass(frozen=True, slots=True)
class Settings:
    data_root: Path
    db_path: Path
    archive_root: Path
    manual_drop_root: Path
    log_root: Path
    backup_root: Path
    gemini_api_key: str | None
    gemini_model_id: str
    gemini_fallback_models: tuple[str, ...] = ()
    gemini_timeout_seconds: float | None = None

    @classmethod
    def from_env(cls) -> Settings:
        _load_dotenv()
        data_root = _path("QUAL_ENGINE_DATA_ROOT", r"D:\02_Trading\data")
        raw_fallbacks = os.getenv("GEMINI_FALLBACK_MODELS", "")
        fallbacks = tuple(m.strip() for m in raw_fallbacks.split(",") if m.strip())
        raw_timeout = os.getenv("GEMINI_TIMEOUT_SECONDS")
        timeout_val = float(raw_timeout) if raw_timeout else None
        return cls(
            data_root=data_root,
            db_path=_path("QUAL_ENGINE_DB_PATH", str(data_root / "qualitative_event_ledger.db")),
            archive_root=_path("QUAL_ENGINE_ARCHIVE_ROOT", str(data_root / "raw_archive")),
            manual_drop_root=_path("QUAL_ENGINE_MANUAL_DROP_ROOT", str(data_root / "manual_drop")),
            log_root=_path("QUAL_ENGINE_LOG_ROOT", str(data_root / "logs")),
            backup_root=_path("QUAL_ENGINE_BACKUP_ROOT", str(data_root / "backups")),
            gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
            gemini_model_id=os.getenv("GEMINI_MODEL_ID", "gemini-3.8-flash"),
            gemini_fallback_models=fallbacks,
            gemini_timeout_seconds=timeout_val,
        )

    def ensure_directories(self) -> None:
        for directory in (
            self.data_root,
            self.archive_root,
            self.manual_drop_root,
            self.log_root,
            self.backup_root,
            self.db_path.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)
