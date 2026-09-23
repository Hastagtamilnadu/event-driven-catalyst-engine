from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    gross_profit_inr: float
    gross_loss_inr: float
    net_pnl_inr: float
    profit_factor: float
    expectancy_inr: float
    max_drawdown_pct: float
    sharpe_ratio: float


class PerformanceCalculator:
    """Calculates comprehensive trading performance metrics and risk-adjusted ratios."""

    @classmethod
    def calculate_metrics(
        cls,
        trade_pnls: list[float],
        nav_series: list[float] | None = None,
        risk_free_rate_pct: float = 6.5,
    ) -> PerformanceMetrics:
        if not trade_pnls:
            return PerformanceMetrics(
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate_pct=0.0,
                gross_profit_inr=0.0,
                gross_loss_inr=0.0,
                net_pnl_inr=0.0,
                profit_factor=0.0,
                expectancy_inr=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
            )

        n = len(trade_pnls)
        wins = [p for p in trade_pnls if p > 0]
        losses = [p for p in trade_pnls if p < 0]
        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        net_pnl = sum(trade_pnls)
        win_rate = (len(wins) / n) * 100.0 if n > 0 else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)
        expectancy = net_pnl / n if n > 0 else 0.0

        # Drawdown calculation
        max_dd = 0.0
        if nav_series and len(nav_series) > 1:
            peak = nav_series[0]
            for val in nav_series:
                peak = max(peak, val)
                dd = (peak - val) / peak if peak > 0 else 0.0
                max_dd = max(max_dd, dd)

        # Sharpe ratio
        std_pnl = float(np.std(trade_pnls, ddof=1)) if n > 1 else 0.0
        sharpe = ((expectancy / std_pnl) * math.sqrt(252)) if std_pnl > 0 else 0.0

        return PerformanceMetrics(
            total_trades=n,
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate_pct=round(win_rate, 2),
            gross_profit_inr=round(gross_profit, 2),
            gross_loss_inr=round(gross_loss, 2),
            net_pnl_inr=round(net_pnl, 2),
            profit_factor=round(profit_factor, 2),
            expectancy_inr=round(expectancy, 2),
            max_drawdown_pct=round(max_dd * 100.0, 2),
            sharpe_ratio=round(sharpe, 2),
        )


@dataclass(frozen=True, slots=True)
class StrategyBenchmarkReport:
    """§18.2: every strategy defines its benchmark before measurement."""

    strategy_id: str
    benchmark_id: str
    window: str
    raw_return: float
    sector_or_nifty_benchmark_return: float
    matched_market_cap_liquidity_control_return: float
    event_day_gap: float
    maximum_favourable_excursion: float
    maximum_adverse_excursion: float
    holding_period: int
    gross_return: float
    net_return: float


def strategy_benchmark_report(
    *,
    strategy_id: str,
    benchmark_id: str,
    window: str,
    entry_price: float,
    exit_price: float,
    high_while_held: float,
    low_while_held: float,
    holding_period: int,
    sector_or_nifty_benchmark_return: float,
    matched_market_cap_liquidity_control_return: float,
    event_day_gap: float,
    total_cost_inr: float,
    quantity: int,
) -> StrategyBenchmarkReport:
    if not benchmark_id or not window:
        raise ValueError("Excess return is never used without a benchmark and time window")
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")
    raw = (exit_price - entry_price) / entry_price
    mfe = (high_while_held - entry_price) / entry_price
    mae = (low_while_held - entry_price) / entry_price
    gross = raw
    net_pnl = (exit_price - entry_price) * quantity - total_cost_inr
    net = net_pnl / (entry_price * quantity) if quantity else gross
    return StrategyBenchmarkReport(
        strategy_id=strategy_id,
        benchmark_id=benchmark_id,
        window=window,
        raw_return=raw,
        sector_or_nifty_benchmark_return=sector_or_nifty_benchmark_return,
        matched_market_cap_liquidity_control_return=matched_market_cap_liquidity_control_return,
        event_day_gap=event_day_gap,
        maximum_favourable_excursion=mfe,
        maximum_adverse_excursion=mae,
        holding_period=holding_period,
        gross_return=gross,
        net_return=net,
    )


def strategy_benchmark_report_as_dict(report: StrategyBenchmarkReport) -> dict[str, Any]:
    return {
        "strategy_id": report.strategy_id,
        "benchmark_id": report.benchmark_id,
        "window": report.window,
        "raw_return": report.raw_return,
        "sector_or_nifty_benchmark_return": report.sector_or_nifty_benchmark_return,
        "matched_market_cap_liquidity_control_return": report.matched_market_cap_liquidity_control_return,
        "event_day_gap": report.event_day_gap,
        "maximum_favourable_excursion": report.maximum_favourable_excursion,
        "maximum_adverse_excursion": report.maximum_adverse_excursion,
        "holding_period": report.holding_period,
        "gross_return": report.gross_return,
        "net_return": report.net_return,
    }
