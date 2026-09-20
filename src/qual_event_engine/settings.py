from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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
    gemini_timeout_seconds: float

    @classmethod
    def from_env(cls) -> Settings:
        data_root = _path("QUAL_ENGINE_DATA_ROOT", r"D:\02_Trading\data")
        return cls(
            data_root=data_root,
            db_path=_path("QUAL_ENGINE_DB_PATH", str(data_root / "qualitative_event_ledger.db")),
            archive_root=_path("QUAL_ENGINE_ARCHIVE_ROOT", str(data_root / "raw_archive")),
            manual_drop_root=_path("QUAL_ENGINE_MANUAL_DROP_ROOT", str(data_root / "manual_drop")),
            log_root=_path("QUAL_ENGINE_LOG_ROOT", str(data_root / "logs")),
            backup_root=_path("QUAL_ENGINE_BACKUP_ROOT", str(data_root / "backups")),
            gemini_api_key=os.getenv("GEMINI_API_KEY") or None,
            gemini_model_id=os.getenv("GEMINI_MODEL_ID", "gemini-3.1-flash-lite"),
            gemini_timeout_seconds=float(os.getenv("GEMINI_TIMEOUT_SECONDS", "45")),
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
