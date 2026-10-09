"""Learn policy thresholds from human labels and evaluate decisions.

Given images labelled ``good`` or ``bad``, each threshold is fitted with an
exhaustive one-dimensional search over observed metric values that maximises
balanced accuracy for its check in isolation, then the combined policy is
evaluated end-to-end. This is a transparent, auditable learner: every learned
number can be traced to a split point in the labelled data.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .metrics import ImageMetrics
from .policy import Policy, assess

POSITIVE = "bad"  # "positive" = image that should be filtered out


@dataclass
class ConfusionReport:
    support: int
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    precision: float
    recall: float
    f1: float
    accuracy: float

    def as_dict(self) -> dict:
        return asdict(self)


def confusion(predicted_bad: list[bool], actual_bad: list[bool]) -> ConfusionReport:
    tp = sum(p and a for p, a in zip(predicted_bad, actual_bad))
    fp = sum(p and not a for p, a in zip(predicted_bad, actual_bad))
    tn = sum((not p) and (not a) for p, a in zip(predicted_bad, actual_bad))
    fn = sum((not p) and a for p, a in zip(predicted_bad, actual_bad))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    n = len(actual_bad)
    return ConfusionReport(
        support=n,
        true_positive=tp,
        false_positive=fp,
        true_negative=tn,
        false_negative=fn,
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        accuracy=round((tp + tn) / n, 4) if n else 0.0,
    )


def evaluate_policy(samples: list[tuple[ImageMetrics, str]], policy: Policy) -> ConfusionReport:
    """Treat any non-accept decision as a prediction that the image is bad."""
    predicted = [assess(m, policy).decision != "accept" for m, _ in samples]
    actual = [label == POSITIVE for _, label in samples]
    return confusion(predicted, actual)


def _best_split(values: list[float], bad: list[bool], bad_when_below: bool) -> float | None:
    """Return the threshold maximising balanced accuracy, or None if undefined."""
    n_bad = sum(bad)
    n_good = len(bad) - n_bad
    if n_bad == 0 or n_good == 0:
        return None
    candidates = sorted(set(values))
    best_score, best_t = -1.0, None
    # midpoints between consecutive observed values keep splits stable
    splits = [(a + b) / 2 for a, b in zip(candidates, candidates[1:])] or candidates
    for t in splits:
        flagged = [(v < t) if bad_when_below else (v > t) for v in values]
        tpr = sum(f and b for f, b in zip(flagged, bad)) / n_bad
        tnr = sum((not f) and (not b) for f, b in zip(flagged, bad)) / n_good
        score = (tpr + tnr) / 2
        if score > best_score + 1e-12:
            best_score, best_t = score, t
    return best_t


def calibrate(samples: list[tuple[ImageMetrics, str]], base: Policy) -> tuple[Policy, dict[str, str]]:
    """Fit thresholds; checks without informative labels keep the base value."""
    notes: dict[str, str] = {}
    bad = [label == POSITIVE for _, label in samples]
    metrics = [m for m, _ in samples]
    fitted = base.as_dict()

    def fit(name: str, values: list[float], below: bool, lo: float, hi: float) -> None:
        t = _best_split(values, bad, below)
        if t is None:
            notes[name] = "kept: labels contain only one class"
            return
        clamped = min(hi, max(lo, t))
        fitted[name] = round(clamped, 4)
        notes[name] = f"learned split {t:.4f}" + (" (clamped)" if clamped != t else "")

    fit("blur_min", [m.blur_score for m in metrics], True, 0.0, 1e7)
    fit("contrast_min", [m.rms_contrast for m in metrics], True, 0.005, 0.95)
    dark = [m.mean_luma for m in metrics if m.mean_luma < 128]
    bright = [m.mean_luma for m in metrics if m.mean_luma >= 128]
    dark_bad = [b for m, b in zip(metrics, bad) if m.mean_luma < 128]
    bright_bad = [b for m, b in zip(metrics, bad) if m.mean_luma >= 128]
    t_lo = _best_split(dark, dark_bad, True) if dark else None
    t_hi = _best_split(bright, bright_bad, False) if bright else None
    if t_lo is not None:
        fitted["luma_min"] = round(min(127.0, max(0.0, t_lo)), 4)
        notes["luma_min"] = f"learned split {t_lo:.4f}"
    else:
        notes["luma_min"] = "kept: insufficient dark examples of both classes"
    if t_hi is not None:
        fitted["luma_max"] = round(max(128.0, min(255.0, t_hi)), 4)
        notes["luma_max"] = f"learned split {t_hi:.4f}"
    else:
        notes["luma_max"] = "kept: insufficient bright examples of both classes"
    fit("clip_max", [max(m.shadow_clip, m.highlight_clip) for m in metrics], False, 0.001, 1.0)
    policy = Policy(**fitted)
    policy.validate()
    return policy, notes
