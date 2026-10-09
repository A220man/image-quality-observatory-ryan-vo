"""Group quality failures.

Two complementary views are produced:

* **Signature groups** – exact sets of failed checks (e.g. ``blurry+low_contrast``),
  which are directly actionable for filtering.
* **Metric clusters** – deterministic k-means over standardised metric vectors,
  which surfaces images that behave alike even when they pass different checks
  (for example a run of slightly soft, dim frames from one camera).

k-means uses k-means++-style farthest-point seeding from the medoid so results
are reproducible without a random seed.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

import numpy as np

FEATURES = ("blur_score", "edge_density", "mean_luma", "shadow_clip", "highlight_clip", "rms_contrast", "dynamic_range")


@dataclass
class SignatureGroup:
    signature: str
    count: int
    image_ids: list[int]
    mean_quality: float
    decisions: dict[str, int]


@dataclass
class Cluster:
    index: int
    size: int
    image_ids: list[int]
    centroid: dict[str, float]
    dominant_failure: str
    failure_rate: float
    description: str = ""


@dataclass
class ClusterResult:
    k: int
    inertia: float
    clusters: list[Cluster] = field(default_factory=list)


def signature_groups(rows: list[dict]) -> list[SignatureGroup]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        buckets[row["signature"]].append(row)
    groups = []
    for signature, members in buckets.items():
        groups.append(
            SignatureGroup(
                signature=signature,
                count=len(members),
                image_ids=sorted(m["id"] for m in members),
                mean_quality=round(sum(m["quality_score"] for m in members) / len(members), 2),
                decisions=dict(Counter(m["decision"] for m in members)),
            )
        )
    groups.sort(key=lambda g: (g.signature == "pass", -g.count, g.signature))
    return groups


def _feature_matrix(rows: list[dict]) -> np.ndarray:
    matrix = np.array([[float(r[f]) for f in FEATURES] for r in rows], dtype=np.float64)
    # Laplacian variance is heavy-tailed; log-compress before scaling.
    matrix[:, 0] = np.log1p(np.maximum(matrix[:, 0], 0.0))
    return matrix


def _standardise(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = matrix.mean(axis=0)
    std = matrix.std(axis=0)
    std[std == 0] = 1.0
    return (matrix - mean) / std, mean, std


def _seed_centroids(x: np.ndarray, k: int) -> np.ndarray:
    centre = x.mean(axis=0)
    first = int(np.argmin(((x - centre) ** 2).sum(axis=1)))
    chosen = [first]
    dist = ((x - x[first]) ** 2).sum(axis=1)
    while len(chosen) < k:
        nxt = int(np.argmax(dist))
        if dist[nxt] == 0:
            break
        chosen.append(nxt)
        dist = np.minimum(dist, ((x - x[nxt]) ** 2).sum(axis=1))
    return x[chosen].copy()


def kmeans(x: np.ndarray, k: int, max_iter: int = 100) -> tuple[np.ndarray, np.ndarray, float]:
    centroids = _seed_centroids(x, k)
    labels = np.zeros(len(x), dtype=int)
    for _ in range(max_iter):
        dists = ((x[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2)
        new_labels = dists.argmin(axis=1)
        if _ > 0 and np.array_equal(new_labels, labels):
            break
        labels = new_labels
        for j in range(len(centroids)):
            members = x[labels == j]
            if len(members):
                centroids[j] = members.mean(axis=0)
    inertia = float(((x - centroids[labels]) ** 2).sum())
    return labels, centroids, inertia


def _describe(centroid: dict[str, float], overall: dict[str, float]) -> str:
    traits = []
    if centroid["blur_score"] < overall["blur_score"] * 0.5:
        traits.append("soft focus")
    elif centroid["blur_score"] > overall["blur_score"] * 1.5:
        traits.append("very sharp")
    if centroid["mean_luma"] < overall["mean_luma"] - 40:
        traits.append("dark")
    elif centroid["mean_luma"] > overall["mean_luma"] + 40:
        traits.append("bright")
    if centroid["rms_contrast"] < overall["rms_contrast"] * 0.6:
        traits.append("flat contrast")
    if max(centroid["shadow_clip"], centroid["highlight_clip"]) > 0.1:
        traits.append("clipping")
    return ", ".join(traits) if traits else "close to collection average"


def cluster_rows(rows: list[dict], k: int) -> ClusterResult:
    if not rows:
        return ClusterResult(k=0, inertia=0.0)
    k = max(1, min(k, len(rows)))
    raw = _feature_matrix(rows)
    x, mean, std = _standardise(raw)
    labels, centroids, inertia = kmeans(x, k)
    raw_centroids = centroids * std + mean
    overall = {f: float(v) for f, v in zip(FEATURES, mean)}
    overall["blur_score"] = float(np.expm1(overall["blur_score"]))
    clusters = []
    for j in range(len(centroids)):
        idx = [i for i, lab in enumerate(labels) if lab == j]
        if not idx:
            continue
        members = [rows[i] for i in idx]
        centroid = {f: round(float(v), 4) for f, v in zip(FEATURES, raw_centroids[j])}
        centroid["blur_score"] = round(float(np.expm1(centroid["blur_score"])), 4)
        failure_counts: Counter[str] = Counter()
        for m in members:
            failure_counts.update(m["failures"])
        failed = sum(1 for m in members if m["failures"])
        clusters.append(
            Cluster(
                index=len(clusters),
                size=len(members),
                image_ids=sorted(m["id"] for m in members),
                centroid=centroid,
                dominant_failure=failure_counts.most_common(1)[0][0] if failure_counts else "none",
                failure_rate=round(failed / len(members), 4),
                description=_describe(centroid, overall),
            )
        )
    clusters.sort(key=lambda c: (-c.failure_rate, -c.size))
    for i, c in enumerate(clusters):
        c.index = i
    return ClusterResult(k=len(clusters), inertia=round(inertia, 4), clusters=clusters)
