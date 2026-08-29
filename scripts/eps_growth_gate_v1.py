from __future__ import annotations

"""EPS growth guardrail used by the 存股作戰地圖 P3 pipeline.

Purpose
-------
Traditional YoY = current / prior - 1 becomes economically misleading when
prior EPS is negative or zero. This module provides a parameter-free robust
transform for ranking, plus QA regime labels. It is a data-definition fix,
not a model-weight optimization.

Frozen production rule (v1)
---------------------------
robust_growth = (current - prior) / (abs(current) + abs(prior))

Range: [-1, 1]. For positive->positive EPS this transform is monotonic in the
ordinary YoY ratio, so cross-sectional ranking is preserved. It also gives the
correct economic direction across zero and for negative bases.
"""

from dataclasses import dataclass
from statistics import median
from typing import Iterable, Optional


@dataclass(frozen=True)
class EPSGrowthResult:
    current: float
    prior: float
    ordinary_yoy: Optional[float]
    robust_growth: float
    regime: str
    small_base: bool
    small_base_threshold: float


def robust_eps_growth(current: float, prior: float) -> float:
    den = abs(current) + abs(prior)
    if den == 0:
        return 0.0
    return (current - prior) / den


def classify_eps_regime(current: float, prior: float) -> str:
    if prior > 0 and current >= 0:
        return "NORMAL_POSITIVE"
    if prior < 0 and current > 0:
        return "TURNAROUND"
    if prior > 0 and current < 0:
        return "LOSS_TURN"
    if prior < 0 and current < 0 and current > prior:
        return "NEGATIVE_IMPROVING"
    if prior < 0 and current < 0 and current < prior:
        return "NEGATIVE_WORSENING"
    if prior == 0 and current > 0:
        return "ZERO_TO_PROFIT"
    if prior == 0 and current < 0:
        return "ZERO_TO_LOSS"
    if prior < 0 and current == 0:
        return "LOSS_TO_ZERO"
    return "ZERO_FLAT"


def small_base_threshold(prior_eps_history: Iterable[float]) -> float:
    vals = [abs(float(x)) for x in prior_eps_history]
    med = median(vals) if vals else 0.0
    # QA-only flag: not used in the score. Stock-specific and scale-aware.
    return max(0.05, 0.10 * med)


def evaluate_eps_growth(
    current: float,
    prior: float,
    prior_eps_history: Iterable[float] = (),
) -> EPSGrowthResult:
    threshold = small_base_threshold(prior_eps_history)
    ordinary = None if prior == 0 else current / prior - 1.0
    return EPSGrowthResult(
        current=current,
        prior=prior,
        ordinary_yoy=ordinary,
        robust_growth=robust_eps_growth(current, prior),
        regime=classify_eps_regime(current, prior),
        small_base=abs(prior) < threshold,
        small_base_threshold=threshold,
    )


def _self_test() -> None:
    # Positive bases keep economic direction.
    assert robust_eps_growth(2.0, 1.0) > 0
    assert robust_eps_growth(1.0, 2.0) < 0
    # Cross-zero direction is correct, unlike traditional YoY.
    assert robust_eps_growth(0.76, -0.80) == 1.0
    assert classify_eps_regime(0.76, -0.80) == "TURNAROUND"
    assert robust_eps_growth(-0.80, 0.76) == -1.0
    assert classify_eps_regime(-0.80, 0.76) == "LOSS_TURN"
    # Negative loss narrowing should be improvement.
    assert robust_eps_growth(-0.4, -0.8) > 0
    assert classify_eps_regime(-0.4, -0.8) == "NEGATIVE_IMPROVING"
    # Zero/zero is defined and finite.
    assert robust_eps_growth(0.0, 0.0) == 0.0


if __name__ == "__main__":
    _self_test()
    print("eps_growth_gate_v1 self-test PASS")
