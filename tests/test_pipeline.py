from types import SimpleNamespace

from traffic_tracking.domain import Snapshot
from traffic_tracking.pipeline import is_reusable_duplicate


def test_duplicate_requires_matching_checksum_and_inference_signature() -> None:
    snapshot = Snapshot(camera=SimpleNamespace(camera_id="camera-1"), checksum_sha256="image-hash", content=b"image")
    previous = SimpleNamespace(checksum_sha256="image-hash", inference_signature="config-a")

    assert is_reusable_duplicate(previous, snapshot, "config-a") is True
    assert is_reusable_duplicate(previous, snapshot, "config-b") is False
    previous.checksum_sha256 = "different-image"
    assert is_reusable_duplicate(previous, snapshot, "config-a") is False
    assert is_reusable_duplicate(None, snapshot, "config-a") is False
