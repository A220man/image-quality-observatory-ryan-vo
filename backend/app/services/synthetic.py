"""Deterministic synthetic benchmark of labelled degraded images.

Base scenes are procedurally generated (gradients, shapes, texture) from a fixed
seed, then degraded with known operations. Labels come from the generating
operation, so provenance is fully reproducible and contains no third-party data.

Degradations and their labels:
    clean          -> good
    mild_blur r=0.8 -> good   (realistic softness that should still pass)
    blur r=3.5     -> bad
    dark x0.25     -> bad
    bright +150    -> bad
    flat x0.2      -> bad    (contrast collapsed around mid-grey)
"""
from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

DEGRADATIONS: dict[str, str] = {
    "clean": "good",
    "mild_blur": "good",
    "blur": "bad",
    "dark": "bad",
    "bright": "bad",
    "flat": "bad",
}


@dataclass(frozen=True)
class SyntheticSample:
    name: str
    degradation: str
    label: str
    png: bytes


def _scene(rng: np.random.Generator, size: int = 256) -> Image.Image:
    y, x = np.mgrid[0:size, 0:size]
    angle = rng.uniform(0, np.pi)
    base = 70 + 110 * ((np.cos(angle) * x + np.sin(angle) * y) / (size * 1.5))
    noise = rng.normal(0, 6, (size, size))
    rgb = np.stack([base + noise, base * 0.9 + noise, base * 1.1 + noise], axis=-1)
    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")
    draw = ImageDraw.Draw(img)
    for _ in range(int(rng.integers(6, 12))):
        x0, y0 = (int(v) for v in rng.integers(0, size - 40, 2))
        w, h = (int(v) for v in rng.integers(15, 80, 2))
        colour = tuple(int(c) for c in rng.integers(10, 245, 3))
        if rng.random() < 0.5:
            draw.rectangle([x0, y0, x0 + w, y0 + h], fill=colour)
        else:
            draw.ellipse([x0, y0, x0 + w, y0 + h], fill=colour)
    for i in range(0, size, int(rng.integers(12, 24))):
        draw.line([(i, 0), (i, size // 6)], fill=(20, 20, 20), width=1)
    return img


def _degrade(img: Image.Image, kind: str) -> Image.Image:
    if kind == "clean":
        return img
    if kind == "mild_blur":
        return img.filter(ImageFilter.GaussianBlur(0.8))
    if kind == "blur":
        return img.filter(ImageFilter.GaussianBlur(3.5))
    if kind == "dark":
        return ImageEnhance.Brightness(img).enhance(0.25)
    if kind == "bright":
        arr = np.asarray(img, dtype=np.int16) + 150
        return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    if kind == "flat":
        return ImageEnhance.Contrast(img).enhance(0.2)
    raise ValueError(f"unknown degradation {kind}")


def generate(scenes: int = 12, seed: int = 7) -> list[SyntheticSample]:
    rng = np.random.default_rng(seed)
    samples = []
    for s in range(scenes):
        scene = _scene(rng)
        for kind, label in DEGRADATIONS.items():
            buf = io.BytesIO()
            _degrade(scene, kind).save(buf, format="PNG")
            samples.append(SyntheticSample(f"scene{s:02d}_{kind}.png", kind, label, buf.getvalue()))
    return samples


def split(samples: list[SyntheticSample]) -> tuple[list[SyntheticSample], list[SyntheticSample]]:
    """Scene-level split: even scenes train, odd scenes test (no scene leakage)."""
    train = [s for s in samples if int(s.name[5:7]) % 2 == 0]
    test = [s for s in samples if int(s.name[5:7]) % 2 == 1]
    return train, test
