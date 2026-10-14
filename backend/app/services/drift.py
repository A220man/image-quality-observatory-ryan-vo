"""Dataset drift comparison using two-sample Kolmogorov-Smirnov tests."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

DRIFT_METRICS = (
    'blur_score',
    'mean_luma',
    'edge_density',
    'shadow_clip',
    'highlight_clip',
    'rms_contrast',
    'dynamic_range',
    'quality_score',
)


@dataclass(frozen=True)
class KSTestResult:
    metric: str
    statistic: float
    p_value: float
    sample_a_count: int
    sample_b_count: int
    drift_detected: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DriftComparison:
    batch_a: str
    batch_b: str
    total_a: int
    total_b: int
    ks_results: list[KSTestResult]
    overall_drift: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            'batch_a': self.batch_a,
            'batch_b': self.batch_b,
            'total_a': self.total_a,
            'total_b': self.total_b,
            'ks_results': [r.as_dict() for r in self.ks_results],
            'overall_drift': self.overall_drift,
        }


def ks_two_sample(x: np.ndarray, y: np.ndarray, alpha: float = 0.05) -> tuple[float, float, bool]:
    """
    Two-sample Kolmogorov-Smirnov test.
    Returns (statistic, p_value, drift_detected).
    """
    if len(x) == 0 or len(y) == 0:
        return 0.0, 1.0, False

    x = np.sort(x)
    y = np.sort(y)
    n1, n2 = len(x), len(y)

    # Empirical CDFs
    all_values = np.concatenate([x, y])
    all_values.sort()

    cdf1 = np.searchsorted(x, all_values, side='right') / n1
    cdf2 = np.searchsorted(y, all_values, side='right') / n2

    d = np.max(np.abs(cdf1 - cdf2))

    # Approximate p-value using asymptotic distribution
    en = np.sqrt(n1 * n2 / (n1 + n2))
    lambda_ks = (en + 0.12 + 0.11 / en) * d

    # Kolmogorov distribution approximation
    if lambda_ks < 1e-10:
        p_value = 1.0
    else:
        # Approximation from Stephens (1970)
        p_value = 2 * np.exp(-2 * lambda_ks**2)
        # More terms for better accuracy
        for k in range(2, 6):
            p_value += 2 * (-1)**(k-1) * np.exp(-2 * k**2 * lambda_ks**2)

    p_value = float(min(max(p_value, 0.0), 1.0))
    drift_detected = bool(p_value < alpha)

    return float(d), p_value, drift_detected


def compare_batches(
    rows_a: list[dict[str, Any]],
    rows_b: list[dict[str, Any]],
    batch_a: str,
    batch_b: str,
    alpha: float = 0.05,
) -> DriftComparison:
    """Compare two batches of image quality rows for distribution drift."""
    ks_results = []
    any_drift = False

    for metric in DRIFT_METRICS:
        vals_a = [float(r[metric]) for r in rows_a if metric in r and r[metric] is not None]
        vals_b = [float(r[metric]) for r in rows_b if metric in r and r[metric] is not None]

        if not vals_a or not vals_b:
            ks_results.append(KSTestResult(
                metric=metric,
                statistic=0.0,
                p_value=1.0,
                sample_a_count=len(vals_a),
                sample_b_count=len(vals_b),
                drift_detected=False,
            ))
            continue

        arr_a = np.array(vals_a, dtype=np.float64)
        arr_b = np.array(vals_b, dtype=np.float64)

        stat, p_val, drift = ks_two_sample(arr_a, arr_b, alpha)
        if drift:
            any_drift = True

        ks_results.append(KSTestResult(
            metric=metric,
            statistic=float(round(stat, 4)),
            p_value=float(round(p_val, 4)),
            sample_a_count=int(len(arr_a)),
            sample_b_count=int(len(arr_b)),
            drift_detected=bool(drift),
        ))

    return DriftComparison(
        batch_a=batch_a,
        batch_b=batch_b,
        total_a=len(rows_a),
        total_b=len(rows_b),
        ks_results=ks_results,
        overall_drift=any_drift,
    )