from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExitTrigger:
    should_exit: bool
    reason: str  # STOP_LOSS, TIME_STOP, NEGATIVE_CATALYST, TARGET_REACHED, NONE
    exit_price: float | None = None


class ExitEvaluator:
    """Evaluates stop-loss, time-based, and catalyst-based exit criteria for open positions."""

    @classmethod
    def evaluate_exit(
        cls,
        entry_price: float,
        current_price: float,
        stop_loss_pct: float,
        holding_sessions: int,
        max_time_stop_sessions: int,
        target_return_pct: float | None = None,
    ) -> ExitTrigger:
        if entry_price <= 0:
            return ExitTrigger(should_exit=False, reason="NONE")

        pnl_pct = ((current_price - entry_price) / entry_price) * 100.0

        # 1. Stop loss
        if pnl_pct <= -abs(stop_loss_pct):
            return ExitTrigger(
                should_exit=True,
                reason=f"STOP_LOSS_HIT: return {pnl_pct:.2f}% <= -{stop_loss_pct}%",
                exit_price=current_price,
            )

        # 2. Profit target
        if target_return_pct and pnl_pct >= target_return_pct:
            return ExitTrigger(
                should_exit=True,
                reason=f"TARGET_REACHED: return {pnl_pct:.2f}% >= {target_return_pct}%",
                exit_price=current_price,
            )

        # 3. Time stop
        if holding_sessions >= max_time_stop_sessions:
            return ExitTrigger(
                should_exit=True,
                reason=f"TIME_STOP_EXPIRED: holding {holding_sessions} sessions >= {max_time_stop_sessions}",
                exit_price=current_price,
            )

        return ExitTrigger(should_exit=False, reason="NONE")
