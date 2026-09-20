from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QualityGate:
    name: str
    description: str
    command: list[str]


GATES: list[QualityGate] = [
    QualityGate(
        name="1. Environment & Smoke Test",
        description="Verifies Python 3.11, directories, database initialisation, and configuration loading",
        command=["uv", "run", "pytest", "tests/test_smoke.py", "-v"],
    ),
    QualityGate(
        name="2. Database Migrations",
        description="Verifies database migrations, repeatable initialisation, and schema parity",
        command=["uv", "run", "pytest", "tests/test_migrations.py", "-v"],
    ),
    QualityGate(
        name="3. Source Adapters & Fixtures",
        description="Tests all 9 source adapters with TLS verification and drop fixtures",
        command=["uv", "run", "pytest", "tests/test_sources.py", "-v"],
    ),
    QualityGate(
        name="4. Replay & Idempotency & Zero Lookahead",
        description="Tests zero look-ahead bias, market bar chronological fences, and replay idempotency",
        command=[
            "uv",
            "run",
            "pytest",
            "tests/test_adversarial_lookahead.py",
            "tests/test_end_to_end_replay.py",
            "tests/test_production_pipeline_integration.py",
            "-v",
        ],
    ),
    QualityGate(
        name="5. Full Pytest Suite",
        description="Executes all unit, integration, and algorithm tests across the platform",
        command=["uv", "run", "pytest", "-v"],
    ),
    QualityGate(
        name="6. Static Analysis (Ruff)",
        description="Executes ruff linter asserting zero code quality, syntax, or styling defects",
        command=["uv", "run", "ruff", "check", "."],
    ),
    QualityGate(
        name="7. Type Checking (Mypy Strict)",
        description="Executes mypy in strict mode across all source and test files",
        command=["uv", "run", "mypy", "src", "tests"],
    ),
    QualityGate(
        name="8. Secret Scan",
        description="Scans repository for exposed API keys, credentials, or private certificates",
        command=["uv", "run", "python", "scripts/secret_scan.py"],
    ),
]


def run_release_gates() -> int:
    print("=" * 80)
    print("QUALITATIVE EVENT ENGINE — ENFORCEABLE RELEASE GATE RUNNER")
    print("=" * 80)

    overall_start = time.perf_counter()
    failed_gates: list[tuple[str, str]] = []

    for idx, gate in enumerate(GATES, start=1):
        print(f"\n[{idx}/{len(GATES)}] Running: {gate.name}")
        print(f"    Description: {gate.description}")
        print(f"    Command: {' '.join(gate.command)}")

        gate_start = time.perf_counter()
        res = subprocess.run(gate.command, capture_output=True, text=True, check=False)
        elapsed = time.perf_counter() - gate_start

        if res.returncode == 0:
            print(f"    -> PASS ({elapsed:.2f}s)")
        else:
            print(f"    -> FAIL ({elapsed:.2f}s) — Exit Code: {res.returncode}")
            error_preview = (res.stderr or res.stdout).strip()[-500:]
            print(f"       Error output:\n{error_preview}")
            failed_gates.append((gate.name, error_preview))

    total_elapsed = time.perf_counter() - overall_start
    print("\n" + "=" * 80)
    print("RELEASE GATE SUMMARY")
    print("=" * 80)
    print(f"Total Gates: {len(GATES)}")
    print(f"Passed:      {len(GATES) - len(failed_gates)}")
    print(f"Failed:      {len(failed_gates)}")
    print(f"Duration:    {total_elapsed:.2f}s")

    if failed_gates:
        print("\nFAILED GATES:")
        for name, err in failed_gates:
            print(f"  - {name}")
        print("\nRELEASE GATE FAILED: DO NOT DEPLOY.")
        return 1

    print("\nALL RELEASE GATES PASSED CLEANLY: CERTIFIED FOR RELEASE.")
    return 0


if __name__ == "__main__":
    sys.exit(run_release_gates())
