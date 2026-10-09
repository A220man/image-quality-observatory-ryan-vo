"""Deterministic image-quality measurement engine.

Every metric is computed on a luminance image downscaled so the longest side
is at most ``ANALYSIS_SIDE`` pixels, which makes scores comparable across
resolutions and keeps analysis time bounded.

Metrics
-------
blur_score       Variance of the 4-neighbour Laplacian (higher = sharper).
edge_density     Fraction of pixels whose Sobel gradient magnitude exceeds a
                 fixed threshold; a second, scale-robust sharpness signal.
mean_luma        Mean BT.601 luminance in [0, 255].
shadow_clip      Fraction of pixels <= 5 (crushed shadows).
highlight_clip   Fraction of pixels >= 250 (blown highlights).
rms_contrast     Standard deviation of normalised luminance in [0, 1].
dynamic_range    5th-to-95th percentile spread of luminance in [0, 255].
"""
from __future__ import annotations

import hashlib
import io
from dataclasses import asdict, dataclass

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

ANALYSIS_SIDE = 512
SOBEL_EDGE_THRESHOLD = 40.0
SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP", "BMP", "TIFF", "GIF"}


class ImageDecodeError(ValueError):
    """Raised when bytes cannot be decoded into a supported raster image."""


@dataclass(frozen=True)
class ImageMetrics:
    blur_score: float
    edge_density: float
    mean_luma: float
    shadow_clip: float
    highlight_clip: float
    rms_contrast: float
    dynamic_range: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class DecodedImage:
    sha256: str
    width: int
    height: int
    format: str
    luma: np.ndarray


def decode_image(data: bytes, max_pixels: int = 40_000_000) -> DecodedImage:
    if not data:
        raise ImageDecodeError("Empty file")
    try:
        with Image.open(io.BytesIO(data)) as probe:
            fmt = (probe.format or "").upper()
            width, height = probe.size
            if fmt not in SUPPORTED_FORMATS:
                raise ImageDecodeError(f"Unsupported image format: {fmt or 'unknown'}")
            if width * height > max_pixels:
                raise ImageDecodeError(f"Image exceeds {max_pixels} pixel limit")
            img = ImageOps.exif_transpose(probe)
            img.load()
    except ImageDecodeError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ImageDecodeError("File is not a decodable image") from exc
    gray = img.convert("L")
    gray.thumbnail((ANALYSIS_SIDE, ANALYSIS_SIDE), Image.Resampling.LANCZOS)
    luma = np.asarray(gray, dtype=np.float64)
    if luma.shape[0] < 3 or luma.shape[1] < 3:
        raise ImageDecodeError("Image must be at least 3x3 pixels")
    return DecodedImage(
        sha256=hashlib.sha256(data).hexdigest(),
        width=width,
        height=height,
        format=fmt,
        luma=luma,
    )


def laplacian_variance(luma: np.ndarray) -> float:
    centre = luma[1:-1, 1:-1]
    lap = (
        luma[:-2, 1:-1] + luma[2:, 1:-1] + luma[1:-1, :-2] + luma[1:-1, 2:] - 4.0 * centre
    )
    return float(lap.var())


def sobel_edge_density(luma: np.ndarray, threshold: float = SOBEL_EDGE_THRESHOLD) -> float:
    gx = (
        luma[:-2, 2:] + 2 * luma[1:-1, 2:] + luma[2:, 2:]
        - luma[:-2, :-2] - 2 * luma[1:-1, :-2] - luma[2:, :-2]
    )
    gy = (
        luma[2:, :-2] + 2 * luma[2:, 1:-1] + luma[2:, 2:]
        - luma[:-2, :-2] - 2 * luma[:-2, 1:-1] - luma[:-2, 2:]
    )
    magnitude = np.hypot(gx, gy) / 4.0
    return float((magnitude > threshold).mean())


def measure_luma(luma: np.ndarray) -> ImageMetrics:
    p5, p95 = np.percentile(luma, [5, 95])
    return ImageMetrics(
        blur_score=round(laplacian_variance(luma), 4),
        edge_density=round(sobel_edge_density(luma), 6),
        mean_luma=round(float(luma.mean()), 4),
        shadow_clip=round(float((luma <= 5).mean()), 6),
        highlight_clip=round(float((luma >= 250).mean()), 6),
        rms_contrast=round(float((luma / 255.0).std()), 6),
        dynamic_range=round(float(p95 - p5), 4),
    )


def measure_bytes(data: bytes, max_pixels: int = 40_000_000) -> tuple[DecodedImage, ImageMetrics]:
    decoded = decode_image(data, max_pixels=max_pixels)
    return decoded, measure_luma(decoded.luma)
