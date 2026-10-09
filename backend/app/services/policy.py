"""Policy evaluation: turn raw metrics into failures, a decision and a score."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math

from .metrics import ImageMetrics

FAILURE_CODES = ("blurry", "underexposed", "overexposed", "clipped", "low_contrast")
DECISIONS = ("accept", "review", "reject")


@dataclass(frozen=True)
class Policy:
    blur_min: float = 100.0
    luma_min: float = 50.0
    luma_max: float = 205.0
    clip_max: float = 0.08
    contrast_min: float = 0.10
    review_margin: float = 0.15

    def as_dict(self) -> dict[str, float]:
        return asdict(self)

    def validate(self) -> None:
        if any(not math.isfinite(value) for value in self.as_dict().values()):
            raise ValueError("Policy thresholds must be finite")
        if self.blur_min < 0:
            raise ValueError("blur_min must be non-negative")
        if not 0 <= self.luma_min < self.luma_max <= 255:
            raise ValueError("luma thresholds must satisfy 0 <= luma_min < luma_max <= 255")
        if not 0 < self.clip_max <= 1:
            raise ValueError("clip_max must be in (0, 1]")
        if not 0 < self.contrast_min < 1:
            raise ValueError("contrast_min must be in (0, 1)")
        if not 0 <= self.review_margin < 1:
            raise ValueError("review_margin must be in [0, 1)")


@dataclass(frozen=True)
class Assessment:
    failures: tuple[str, ...]
    borderline: tuple[str, ...]
    decision: str
    quality_score: float


def _ratio_low(value: float, threshold: float) -> float:
    """How far a value sits above a lower bound, as a ratio (1 = exactly at it)."""
    return value / threshold if threshold > 0 else float("inf")


def _component_scores(m: ImageMetrics, p: Policy) -> dict[str, float]:
    """Per-check health in [0, 1]; 0.5 is exactly at threshold."""

    def squash(ratio: float) -> float:
        return max(0.0, min(1.0, ratio / 2.0))

    luma_mid = (p.luma_min + p.luma_max) / 2
    luma_half = (p.luma_max - p.luma_min) / 2
    luma_health = 1.0 - min(1.0, abs(m.mean_luma - luma_mid) / (2 * luma_half))
    clip = max(m.shadow_clip, m.highlight_clip)
    return {
        "sharpness": squash(_ratio_low(m.blur_score, p.blur_min)),
        "exposure": luma_health,
        "clipping": max(0.0, 1.0 - clip / (2 * p.clip_max)),
        "contrast": squash(_ratio_low(m.rms_contrast, p.contrast_min)),
    }


def assess(m: ImageMetrics, p: Policy) -> Assessment:
    failures: list[str] = []
    borderline: list[str] = []
    margin = p.review_margin

    def check(code: str, failed: bool, near: bool) -> None:
        if failed:
            failures.append(code)
        elif near:
            borderline.append(code)

    check("blurry", m.blur_score < p.blur_min, m.blur_score < p.blur_min * (1 + margin))
    span = p.luma_max - p.luma_min
    check("underexposed", m.mean_luma < p.luma_min, m.mean_luma < p.luma_min + span * margin / 2)
    check("overexposed", m.mean_luma > p.luma_max, m.mean_luma > p.luma_max - span * margin / 2)
    clip = max(m.shadow_clip, m.highlight_clip)
    check("clipped", clip > p.clip_max, clip > p.clip_max * (1 - margin))
    check("low_contrast", m.rms_contrast < p.contrast_min, m.rms_contrast < p.contrast_min * (1 + margin))

    components = _component_scores(m, p)
    score = round(100 * sum(components.values()) / len(components), 2)
    if failures:
        decision = "reject" if len(failures) > 1 or "blurry" in failures else "review"
    elif borderline:
        decision = "review"
    else:
        decision = "accept"
    return Assessment(tuple(failures), tuple(borderline), decision, score)


def failure_signature(failures: list[str] | tuple[str, ...]) -> str:
    ordered = [code for code in FAILURE_CODES if code in failures]
    return "+".join(ordered) if ordered else "pass"
