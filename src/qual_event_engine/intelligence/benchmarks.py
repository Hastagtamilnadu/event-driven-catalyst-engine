from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from qual_event_engine.intelligence.analyst import Analyst


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    model_id: str
    total_evaluations: int
    grounding_pass_rate_pct: float
    hallucination_rate_pct: float
    avg_latency_ms: float
    p95_latency_ms: float


class ModelBenchmarker:
    """Evaluates and benchmarks LLM extraction performance against gold standard datasets."""

    def __init__(self, analyst: Analyst) -> None:
        self.analyst = analyst

    def run_benchmark(self, test_cases: list[dict[str, Any]]) -> BenchmarkReport:
        if not test_cases:
            return BenchmarkReport(
                model_id="unknown",
                total_evaluations=0,
                grounding_pass_rate_pct=100.0,
                hallucination_rate_pct=0.0,
                avg_latency_ms=0.0,
                p95_latency_ms=0.0,
            )

        latencies = []
        grounded_count = 0

        for tc in test_cases:
            t0 = time.perf_counter()
            res = self.analyst.extract_facts(tc.get("raw_text", ""), tc.get("context", {}))
            t1 = time.perf_counter()
            latencies.append((t1 - t0) * 1000)

            # Check grounding
            all_grounded = all(f.validation_status == "GROUNDED_PASSED" for f in res.facts)
            if all_grounded:
                grounded_count += 1

        total = len(test_cases)
        pass_rate = (grounded_count / total) * 100.0 if total > 0 else 0.0
        avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
        p95_lat = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0.0

        return BenchmarkReport(
            model_id=self.analyst._model_id,
            total_evaluations=total,
            grounding_pass_rate_pct=pass_rate,
            hallucination_rate_pct=100.0 - pass_rate,
            avg_latency_ms=round(avg_lat, 2),
            p95_latency_ms=round(p95_lat, 2),
        )
