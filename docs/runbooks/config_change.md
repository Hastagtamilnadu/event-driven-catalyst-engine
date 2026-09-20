# Runbook: Configuration Change & Versioning (RB-08)

## 1. Detection
- Strategy parameter adjustment requested (e.g. stop-loss %, holding periods, firmness thresholds).
- Risk limits modified (e.g. max sector exposure %, daily drawdown freeze %).
- Source polling intervals or health bounds modified in `configs/sources.yaml`.

## 2. Immediate Freeze Action
- Parameter changes must NEVER be applied to a running session or live trading hours.
- Hold configuration updates until after market close (post 16:00 IST) and after daily reconciliation passes.
- Do NOT edit configuration files directly in production without a version bump.

## 3. Diagnosis & Change Governance
1. Verify change rationale, reviewer approval, and out-of-sample justification.
2. Confirm new configuration passes schema validation (`load_strategy_book` / `load_risk_config`).
3. Compute SHA-256 hash of the modified YAML file.

## 4. Recovery / Deployment Procedure
1. Create new version entry in `configs/strategies.yaml` or relevant config file with:
   - `effective_from`: Date/time of deployment.
   - `owner`: Responsible researcher/operator.
   - `change_reason`: Documented reason.
2. Run configuration validation:
   ```bash
   uv run python -c "from qual_event_engine.config import load_strategy_book, load_risk_config; from pathlib import Path; load_strategy_book(Path('.')); load_risk_config(Path('.'))"
   ```
3. Run full test suite: `uv run pytest`.
4. Commit configuration changes with immutable Git commit hash.

## 5. Reconciliation
1. Verify that ongoing position lots opened under prior version retain their `stop_policy_version` and original parameters.
2. Ensure new orders reference the updated `strategy_version` and `decision_snapshot_hash`.
3. Confirm existing historical reports remain intact and reproducible.

## 6. Closure Evidence
- New configuration hash recorded in `job_run` table on next execution.
- All unit, integration, and replay tests pass cleanly.
- Change approval documented in change management audit trail.

## 7. Prevention Action
- Enforce CI gate preventing unversioned or invalid YAML configuration commits.
- Restrict write permissions on `configs/` directory in production.
