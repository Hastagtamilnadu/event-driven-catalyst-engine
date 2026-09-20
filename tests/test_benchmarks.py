from __future__ import annotations

from benchmarks import BENCHMARK_FIXTURES, test_benchmark_fixture

# Expose test_benchmark_fixture for automated pytest discovery
__all__ = ["BENCHMARK_FIXTURES", "test_benchmark_fixture"]
