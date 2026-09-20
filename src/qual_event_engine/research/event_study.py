from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class EventStudyResult:
    sample_size: int
    mean_car_pct: float
    median_car_pct: float
    t_stat: float
    p_value: float
    win_rate_pct: float
    car_series: list[float]


class EventStudyEngine:
    """Executes parametric and non-parametric event studies around qualitative catalyst timestamps."""

    @classmethod
    def calculate_car(
        cls,
        event_returns: list[list[float]],  # list of return series for each event over [t_start, t_end]
    ) -> EventStudyResult:
        if not event_returns:
            return EventStudyResult(
                sample_size=0,
                mean_car_pct=0.0,
                median_car_pct=0.0,
                t_stat=0.0,
                p_value=1.0,
                win_rate_pct=0.0,
                car_series=[],
            )

        # Calculate cumulative abnormal return for each event
        cars = [float(np.sum(rets)) for rets in event_returns if len(rets) > 0]
        n = len(cars)
        if n == 0:
            return EventStudyResult(0, 0.0, 0.0, 0.0, 1.0, 0.0, [])

        mean_car = float(np.mean(cars))
        med_car = float(np.median(cars))
        std_car = float(np.std(cars, ddof=1)) if n > 1 else 0.0
        t_stat = (mean_car / (std_car / np.sqrt(n))) if std_car > 0 else 0.0
        win_rate = (sum(1 for c in cars if c > 0) / n) * 100.0

        return EventStudyResult(
            sample_size=n,
            mean_car_pct=round(mean_car * 100.0, 2),
            median_car_pct=round(med_car * 100.0, 2),
            t_stat=round(t_stat, 2),
            p_value=0.01 if abs(t_stat) >= 2.58 else (0.05 if abs(t_stat) >= 1.96 else 0.20),
            win_rate_pct=round(win_rate, 2),
            car_series=[round(c * 100.0, 2) for c in cars],
        )
