from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class Camera:
    camera_id: str
    title: str | None
    description: str | None
    code: str | None
    display_name: str | None
    longitude: float | None
    latitude: float | None
    snapshot_url: str | None
    camera_type: str | None
    district: str | None
    published: bool
    management_unit: str | None
    status: str | None
    ptz: bool | None
    angle: float | None
    video_url: str | None
    video_streaming: bool | None
    data_id: str | None
    node_id: str | None
    path: str | None
    source_created_at: datetime | None
    source_modified_at: datetime | None
    raw_metadata: dict[str, Any]


@dataclass(slots=True)
class Snapshot:
    camera: Camera
    content: bytes | None = None
    content_type: str | None = None
    checksum_sha256: str | None = None
    requested_width: int | None = None
    requested_height: int | None = None
    actual_width: int | None = None
    actual_height: int | None = None
    byte_size: int | None = None
    http_status: int | None = None
    source_http_date: datetime | None = None
    fetched_at: datetime | None = None
    fetch_ms: float | None = None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.content is not None and self.error_code is None


@dataclass(slots=True)
class Detection:
    class_id: int
    class_name: str
    confidence: float
    bbox_xyxy: list[float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "class_id": self.class_id,
            "class_name": self.class_name,
            "confidence": self.confidence,
            "bbox_xyxy": self.bbox_xyxy,
        }


@dataclass(slots=True)
class InferenceResult:
    detections: list[Detection] = field(default_factory=list)
    inference_ms: float | None = None
    preprocessing: dict[str, Any] = field(default_factory=dict)

    @property
    def counts(self) -> dict[str, int]:
        names = ("bicycle", "car", "motorcycle", "bus", "truck")
        counts = {name: 0 for name in names}
        for detection in self.detections:
            if detection.class_name in counts:
                counts[detection.class_name] += 1
        counts["other_vehicle"] = counts["bicycle"] + counts["bus"] + counts["truck"]
        counts["total_vehicle"] = sum(counts[name] for name in names)
        return counts
