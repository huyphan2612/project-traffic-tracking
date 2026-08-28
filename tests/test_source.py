from io import BytesIO

import httpx
from PIL import Image
import pytest

from traffic_tracking.domain import Camera
from traffic_tracking.source import TrafficCameraClient, cameras_from_response


def camera(camera_id: str = "cam-1") -> Camera:
    return Camera(
        camera_id=camera_id, title="A", description=None, code="C1", display_name="A",
        longitude=106.7, latitude=10.8, snapshot_url=None, camera_type="CAMERA",
        district="1", published=True, management_unit=None, status="UP", ptz=False,
        angle=None, video_url=None, video_streaming=False, data_id=None, node_id=None,
        path="/camera/cam-1", source_created_at=None, source_modified_at=None,
        raw_metadata={},
    )


def jpeg_bytes(size: tuple[int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, "white").save(output, "JPEG")
    return output.getvalue()


def test_normalizes_camera_metadata_and_coordinates() -> None:
    row = {
        "CamId": "cam-1", "DisplayName": "Ngã tư A", "CamStatus": "UP",
        "Publish": True, "Path": "/camera/cam-1",
        "Location": {"Rows": [{"Shape": "POINT(106.7 10.8)"}]},
    }
    payload = {"value": [None, [[{"Path": "/camera/cam-1", "Title": "node"}], {"Rows": [row]}], 1]}

    cameras, total = cameras_from_response(payload)

    assert total == 1
    assert (cameras[0].longitude, cameras[0].latitude) == (106.7, 10.8)
    assert cameras[0].raw_metadata["node"]["Title"] == "node"


@pytest.mark.asyncio
async def test_snapshot_falls_back_and_records_actual_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    image = jpeg_bytes((646, 366))

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, request.url.params.get("w", "")))
        if request.url.path == "/map.aspx":
            return httpx.Response(200, headers={"set-cookie": "sid=test"}, text="ok")
        assert request.headers["referer"].endswith("/map.aspx")
        if request.url.params["w"] == "1280":
            return httpx.Response(200, headers={"content-type": "text/html"}, text="unavailable")
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=image)

    async def no_sleep(_delay: float) -> None:
        return None

    monkeypatch.setattr("traffic_tracking.source.asyncio.sleep", no_sleep)
    client = TrafficCameraClient(
        "https://giaothong.hochiminhcity.gov.vn",
        snapshot_sizes=((1280, 720), (640, 360)),
        transport=httpx.MockTransport(handler),
    )
    async with client:
        snapshot = await client.fetch_snapshot(camera())

    assert snapshot.ok
    assert (snapshot.requested_width, snapshot.requested_height) == (640, 360)
    assert (snapshot.actual_width, snapshot.actual_height) == (646, 366)
    assert [width for path, width in calls if path.endswith("CameraHandler.ashx")] == ["1280"] * 3 + ["640"]


@pytest.mark.asyncio
async def test_snapshot_iterator_can_close_early_without_deadlock(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TrafficCameraClient("https://example.test", concurrency=2)

    async def fake_fetch(item: Camera):
        from traffic_tracking.domain import Snapshot
        return Snapshot(camera=item, content=b"x")

    monkeypatch.setattr(client, "fetch_snapshot", fake_fetch)
    iterator = client.iter_snapshots([camera("a"), camera("b"), camera("c")])
    await anext(iterator)
    await iterator.aclose()
    await client.client.aclose()
