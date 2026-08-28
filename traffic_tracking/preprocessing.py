from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any

import numpy as np
from PIL import Image


PREPROCESSING_VERSION = "black_canvas_v1"
OUTER_MARGIN = 5
BLACK_THRESHOLD = 25
ACTIVE_RATIO = 0.05
MIN_CROP_WIDTH = 160
MIN_CROP_HEIGHT = 90
MAX_CROP_AREA_RATIO = 0.90


@dataclass(slots=True)
class PreprocessedImage:
    image: Image.Image
    metadata: dict[str, Any]


def preprocessing_config(enabled: bool) -> dict[str, Any]:
    return {
        "version": PREPROCESSING_VERSION,
        "enabled": enabled,
        "outer_margin": OUTER_MARGIN,
        "black_threshold": BLACK_THRESHOLD,
        "active_ratio": ACTIVE_RATIO,
        "min_crop_size": [MIN_CROP_WIDTH, MIN_CROP_HEIGHT],
        "max_crop_area_ratio": MAX_CROP_AREA_RATIO,
    }


def preprocess_bytes(content: bytes, enabled: bool = True) -> PreprocessedImage:
    image = Image.open(BytesIO(content)).convert("RGB")
    return preprocess_image(image, enabled)


def preprocess_image(image: Image.Image, enabled: bool = True) -> PreprocessedImage:
    image = image.convert("RGB")
    width, height = image.size
    metadata: dict[str, Any] = {
        "version": PREPROCESSING_VERSION,
        "enabled": enabled,
        "applied": False,
        "source_size": [width, height],
        "crop_box_xyxy": [0, 0, width, height],
        "output_size": [width, height],
        "bbox_coordinate_space": "preprocessed_image",
    }
    if not enabled:
        metadata["reason"] = "disabled"
        return PreprocessedImage(image, metadata)
    if width <= OUTER_MARGIN * 2 or height <= OUTER_MARGIN * 2:
        metadata["reason"] = "image_too_small"
        return PreprocessedImage(image, metadata)

    pixels = np.asarray(image)
    active = pixels.max(axis=2) > BLACK_THRESHOLD
    inner = active[OUTER_MARGIN:-OUTER_MARGIN, OUTER_MARGIN:-OUTER_MARGIN]
    rows = np.flatnonzero(inner.mean(axis=1) > ACTIVE_RATIO) + OUTER_MARGIN
    if not len(rows):
        metadata["reason"] = "no_active_rows"
        return PreprocessedImage(image, metadata)
    y0, y1 = int(rows[0]), int(rows[-1] + 1)
    columns = np.flatnonzero(
        active[y0:y1, OUTER_MARGIN:-OUTER_MARGIN].mean(axis=0) > ACTIVE_RATIO
    ) + OUTER_MARGIN
    if not len(columns):
        metadata["reason"] = "no_active_columns"
        return PreprocessedImage(image, metadata)
    x0, x1 = int(columns[0]), int(columns[-1] + 1)
    crop_width, crop_height = x1 - x0, y1 - y0
    area_ratio = (crop_width * crop_height) / (width * height)
    if crop_width < MIN_CROP_WIDTH or crop_height < MIN_CROP_HEIGHT:
        metadata["reason"] = "crop_too_small"
        return PreprocessedImage(image, metadata)
    if area_ratio >= MAX_CROP_AREA_RATIO:
        metadata["reason"] = "content_already_fills_frame"
        return PreprocessedImage(image, metadata)

    metadata.update({
        "applied": True,
        "crop_box_xyxy": [x0, y0, x1, y1],
        "output_size": [crop_width, crop_height],
        "crop_area_ratio": round(area_ratio, 6),
    })
    return PreprocessedImage(image.crop((x0, y0, x1, y1)), metadata)


def apply_recorded_crop(content: bytes, metadata: dict[str, Any] | None) -> Image.Image:
    image = Image.open(BytesIO(content)).convert("RGB")
    if not metadata or not metadata.get("applied"):
        return image
    box = metadata.get("crop_box_xyxy")
    if not isinstance(box, list) or len(box) != 4 or not all(isinstance(value, int) for value in box):
        return image
    x0, y0, x1, y1 = box
    if x0 < 0 or y0 < 0 or x1 > image.width or y1 > image.height or x0 >= x1 or y0 >= y1:
        return image
    return image.crop((x0, y0, x1, y1))
