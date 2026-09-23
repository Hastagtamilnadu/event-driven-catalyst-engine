from __future__ import annotations

import asyncio

from qual_event_engine.operations.health import record_source_health
from qual_event_engine.persistence.database import transaction
from qual_event_engine.settings import Settings
from qual_event_engine.sources.registry import VALID_ADAPTERS


async def main() -> None:
    settings = Settings.from_env()
    print("Running health checks for all 9 source adapters (S1-S9)...")
    
    results = []
    for source_id, adapter_cls in VALID_ADAPTERS.items():
        adapter = adapter_cls(drop_root=settings.manual_drop_root)
        try:
            health = await adapter.health_check()
            results.append(health)
            print(f"  [{health.source_id}] {health.status} ({health.latency_ms:.1f}ms): {health.message}")
        except Exception as exc:  # noqa: BLE001
            print(f"  [{source_id}] FAILED: {exc}")
            
    with transaction(settings.db_path) as conn:
        for h in results:
            doc_count_row = conn.execute(
                "SELECT COUNT(*) FROM source_observation WHERE source_id=?", (h.source_id,)
            ).fetchone()
            doc_count = doc_count_row[0] if doc_count_row else 0
            record_source_health(
                conn,
                source_id=h.source_id,
                status=h.status,
                document_count=doc_count,
                detail=f"{h.message} (latency={h.latency_ms}ms)",
            )
            
    print(f"\nSuccessfully recorded health checks for {len(results)} adapters into source_health table.")

if __name__ == "__main__":
    asyncio.run(main())
