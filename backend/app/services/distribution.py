"""Statistical distributions, percentiles and quality health profiling for image datasets."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

DIST_METRICS = (
    'blur',
    'luma_mean',
    'luma_std',
    'clip_shadow',
    'clip_highlight',
    'contrast',
    'quality_score',
)


@dataclass(frozen=True)
class MetricStats:
    count: int
    min: float
    max: float
    mean: float
    std: float
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    iqr: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DecisionBreakdown:
    accept_count: int
    accept_rate: float
    review_count: int
    review_rate: float
    reject_count: int
    reject_rate: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LabelAlignment:
    total_labeled: int
    good_count: int
    bad_count: int
    unlabeled_count: int
    concordant_count: int
    discordant_count: int
    review_count: int
    agreement_rate: float | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FailureFrequency:
    check: str
    count: int
    frequency: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DatasetDistribution:
    total_images: int
    decisions: DecisionBreakdown
    labels: LabelAlignment
    metrics: dict[str, MetricStats]
    top_failures: list[FailureFrequency]
    health_status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            'total_images': self.total_images,
            'decisions': self.decisions.as_dict(),
            'labels': self.labels.as_dict(),
            'metrics': {k: v.as_dict() for k, v in self.metrics.items()},
            'top_failures': [f.as_dict() for f in self.top_failures],
            'health_status': self.health_status,
        }


def compute_distribution(rows: list[dict[str, Any]]) -> DatasetDistribution:
    """Compute statistical percentiles, decision breakdown and health status from image rows."""
    if not rows:
        return DatasetDistribution(
            total_images=0,
            decisions=DecisionBreakdown(0, 0.0, 0, 0.0, 0, 0.0),
            labels=LabelAlignment(0, 0, 0, 0, 0, 0, 0, None),
            metrics={},
            top_failures=[],
            health_status='empty',
        )

    total = len(rows)

    accept_count = sum(1 for r in rows if r.get('decision') == 'accept')
    review_count = sum(1 for r in rows if r.get('decision') == 'review')
    reject_count = sum(1 for r in rows if r.get('decision') == 'reject')
    decisions = DecisionBreakdown(
        accept_count=accept_count,
        accept_rate=round(accept_count / total, 4),
        review_count=review_count,
        review_rate=round(review_count / total, 4),
        reject_count=reject_count,
        reject_rate=round(reject_count / total, 4),
    )

    good_count = sum(1 for r in rows if r.get('label') == 'good')
    bad_count = sum(1 for r in rows if r.get('label') == 'bad')
    unlabeled_count = sum(1 for r in rows if r.get('label') not in {'good', 'bad'})
    total_labeled = good_count + bad_count

    concordant = sum(
        1 for r in rows
        if (r.get('label') == 'good' and r.get('decision') == 'accept')
        or (r.get('label') == 'bad' and r.get('decision') == 'reject')
    )
    discordant = sum(
        1 for r in rows
        if (r.get('label') == 'good' and r.get('decision') == 'reject')
        or (r.get('label') == 'bad' and r.get('decision') == 'accept')
    )
    review_labeled = sum(
        1 for r in rows
        if r.get('label') in {'good', 'bad'} and r.get('decision') == 'review'
    )
    agreement_rate = (
        round(concordant / total_labeled, 4) if total_labeled > 0 else None
    )
    labels = LabelAlignment(
        total_labeled=total_labeled,
        good_count=good_count,
        bad_count=bad_count,
        unlabeled_count=unlabeled_count,
        concordant_count=concordant,
        discordant_count=discordant,
        review_count=review_labeled,
        agreement_rate=agreement_rate,
    )

    metric_stats: dict[str, MetricStats] = {}
    for name in DIST_METRICS:
        vals = [float(r[name]) for r in rows if name in r and r[name] is not None]
        if not vals:
            continue
        arr = np.array(vals, dtype=np.float64)
        q10, q25, q50, q75, q90 = np.percentile(arr, [10, 25, 50, 75, 90])
        metric_stats[name] = MetricStats(
            count=len(arr),
            min=round(float(np.min(arr)), 4),
            max=round(float(np.max(arr)), 4),
            mean=round(float(np.mean(arr)), 4),
            std=round(float(np.std(arr)), 4),
            p10=round(float(q10), 4),
            p25=round(float(q25), 4),
            p50=round(float(q50), 4),
            p75=round(float(q75), 4),
            p90=round(float(q90), 4),
            iqr=round(float(q75 - q25), 4),
        )

    failure_counter: Counter[str] = Counter()
    for r in rows:
        raw_fails = r.get('failures') or []
        if isinstance(raw_fails, str):
            try:
                parsed = json.loads(raw_fails)
                raw_fails = parsed if isinstance(parsed, list) else [str(parsed)]
            except Exception:
                raw_fails = [raw_fails]
        for f in raw_fails:
            if f:
                failure_counter[str(f)] += 1

    top_failures = [
        FailureFrequency(check=k, count=v, frequency=round(v / total, 4))
        for k, v in failure_counter.most_common()
    ]

    reject_rate = reject_count / total
    accept_rate = accept_count / total
    if reject_rate >= 0.30:
        health_status = 'critical'
    elif reject_rate >= 0.10 or accept_rate < 0.75:
        health_status = 'degraded'
    else:
        health_status = 'healthy'

    return DatasetDistribution(
        total_images=total,
        decisions=decisions,
        labels=labels,
        metrics=metric_stats,
        top_failures=top_failures,
        health_status=health_status,
    )
