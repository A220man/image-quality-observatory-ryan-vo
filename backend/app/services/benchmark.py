"""Run the reproducible offline benchmark (no network, no LLM).

Usage: PYTHONPATH=backend python -m app.services.benchmark
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .calibration import calibrate, evaluate_policy
from .metrics import ImageMetrics, measure_bytes
from .policy import Policy, assess
from .synthetic import generate, split


@dataclass
class BenchmarkResult:
    train_size: int
    test_size: int
    default_policy: dict
    calibrated_policy: dict
    calibration_notes: dict
    default_test: dict
    calibrated_test: dict
    failure_cases: list[dict]

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _measure(samples) -> list[tuple[ImageMetrics, str, str]]:
    return [(measure_bytes(s.png)[1], s.label, s.name) for s in samples]


def run_benchmark(scenes: int = 12, seed: int = 7) -> BenchmarkResult:
    train, test = split(generate(scenes, seed))
    train_m = _measure(train)
    test_m = _measure(test)
    default = Policy()
    calibrated, notes = calibrate([(m, lab) for m, lab, _ in train_m], default)
    failures = []
    for m, lab, name in test_m:
        decision = assess(m, calibrated).decision
        if (decision != "accept") != (lab == "bad"):
            failures.append({"name": name, "label": lab, "decision": decision, "metrics": m.as_dict()})
    return BenchmarkResult(
        train_size=len(train_m),
        test_size=len(test_m),
        default_policy=default.as_dict(),
        calibrated_policy=calibrated.as_dict(),
        calibration_notes=notes,
        default_test=evaluate_policy([(m, lab) for m, lab, _ in test_m], default).as_dict(),
        calibrated_test=evaluate_policy([(m, lab) for m, lab, _ in test_m], calibrated).as_dict(),
        failure_cases=failures,
    )


if __name__ == "__main__":
    print(json.dumps(run_benchmark().as_dict(), indent=2))
