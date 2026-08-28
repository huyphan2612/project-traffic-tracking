from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
from io import BytesIO
import json
import logging
import time
from typing import Any, AsyncIterator, Iterable
from urllib.parse import urlsplit, urlunsplit

import httpx
from PIL import Image, UnidentifiedImageError

from . import ajaxpro
from .domain import Camera, Snapshot


LOGGER = logging.getLogger(__name__)
CAMERA_PATH = "/root/vdms/tangthu/data/layerdata/camera"
CAMERA_FIELDS = [
    "CamId", "Code", "Location", "SnapshotUrl", "CamType", "Disctrict",
    "Publish", "ManagementUnit", "CamStatus", "PTZ", "Angle",
]


class SourceError(RuntimeError):
    pass


def _bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coordinates(location: Any) -> tuple[float | None, float | None]:
    try:
        shape = location["Rows"][0]["Shape"]
        body = shape.removeprefix("POINT(").removesuffix(")")
        longitude, latitude = body.split()
        return float(longitude), float(latitude)
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return None, None


def cameras_from_response(payload: dict[str, Any]) -> tuple[list[Camera], int | None]:
    if "error" in payload:
        message = payload.get("error", {}).get("Message", "Unknown upstream error")
        raise SourceError(message)
    try:
        value = payload["value"]
        nodes = value[1][0]
        table = value[1][1]
        rows = table["Rows"]
        reported_total = value[2]
    except (KeyError, IndexError, TypeError) as exc:
        raise SourceError("Unexpected camera-list response shape") from exc

    nodes_by_path = {
        node.get("Path"): node
        for node in nodes
        if isinstance(node, dict) and node.get("Path")
    }
    cameras: list[Camera] = []
    for row in rows:
        camera_id = row.get("CamId")
        if not camera_id:
            LOGGER.warning("Skipping upstream row without CamId")
            continue
        longitude, latitude = _coordinates(row.get("Location"))
        node = nodes_by_path.get(row.get("Path"))
        cameras.append(Camera(
            camera_id=str(camera_id),
            title=row.get("Title"),
            description=row.get("Description"),
            code=row.get("Code"),
            display_name=row.get("DisplayName") or row.get("Title"),
            longitude=longitude,
            latitude=latitude,
            snapshot_url=row.get("SnapshotUrl"),
            camera_type=row.get("CamType"),
            district=row.get("Disctrict"),
            published=_bool(row.get("Publish")) is not False,
            management_unit=row.get("ManagementUnit"),
            status=row.get("CamStatus"),
            ptz=_bool(row.get("PTZ")),
            angle=_float(row.get("Angle")),
            video_url=row.get("VideoUrl"),
            video_streaming=_bool(row.get("VideoStreaming")),
            data_id=str(row["DataId"]) if row.get("DataId") is not None else None,
            node_id=str(row["NodeId"]) if row.get("NodeId") is not None else None,
            path=row.get("Path"),
            source_created_at=ajaxpro.parse_ajax_date(row.get("CreatedDate")),
            source_modified_at=ajaxpro.parse_ajax_date(row.get("ModifiedDate")),
            raw_metadata={"record": row, "node": node},
        ))
    return cameras, int(reported_total) if isinstance(reported_total, (int, float)) else None


class TrafficCameraClient:
    def __init__(
        self,
        base_url: str,
        concurrency: int = 4,
        snapshot_sizes: tuple[tuple[int, int], ...] = ((1280, 720),),
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        parsed = urlsplit(self.base_url)
        hostname = parsed.hostname or "giaothong.hochiminhcity.gov.vn"
        self.snapshot_base_url = urlunsplit((parsed.scheme, f"{hostname}:8007", "", "", ""))
        self.concurrency = concurrency
        self.snapshot_sizes = snapshot_sizes
        self._bootstrap_lock = asyncio.Lock()
        self._bootstrapped = False
        self.client = httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"User-Agent": "traffic-tracking/0.1 (+public-camera-research)"},
            transport=transport,
        )

    async def __aenter__(self) -> "TrafficCameraClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        await self.client.aclose()

    async def bootstrap(self, force: bool = False) -> None:
        async with self._bootstrap_lock:
            if self._bootstrapped and not force:
                return
            response = await self.client.get(f"{self.base_url}/map.aspx")
            response.raise_for_status()
            self._bootstrapped = True

    async def list_cameras(self) -> tuple[list[Camera], int | None]:
        await self.bootstrap()
        body = {
            "path": CAMERA_PATH,
            "isInTree": False,
            "searchKey": "",
            "layer": ["CAMERA"],
            "detail": True,
            "page": 0,
            "limit": -1,
            "filterQuery": ["Publish:true"],
            "sortby": None,
            "returnFields": CAMERA_FIELDS,
        }
        url = f"{self.base_url}/ajaxpro/VDMS.Web.Library.AJAX.FolderAjax,VDMS.Web.Library.ashx"
        response = await self.client.post(
            url,
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "X-AjaxPro-Method": "SearchQuery",
                "Referer": f"{self.base_url}/map.aspx",
            },
            content=json.dumps(body, separators=(",", ":")),
        )
        response.raise_for_status()
        payload = ajaxpro.parse(response.text)
        if isinstance(payload, dict) and payload.get("error", {}).get("Type") == "System.Security.SecurityException":
            await self.bootstrap(force=True)
            response = await self.client.post(
                url,
                headers={
                    "Content-Type": "text/plain; charset=utf-8",
                    "X-AjaxPro-Method": "SearchQuery",
                    "Referer": f"{self.base_url}/map.aspx",
                },
                content=json.dumps(body, separators=(",", ":")),
            )
            response.raise_for_status()
            payload = ajaxpro.parse(response.text)
        if not isinstance(payload, dict):
            raise SourceError("Camera-list response is not an object")
        return cameras_from_response(payload)

    async def fetch_snapshot(self, camera: Camera) -> Snapshot:
        await self.bootstrap()
        last_error: tuple[str, str, int | None] = ("fetch_failed", "No snapshot size attempted", None)
        start_total = time.perf_counter()
        session_refreshed = False
        for width, height in self.snapshot_sizes:
            for attempt in range(3):
                timestamp = int(time.time() * 1000)
                url = f"{self.snapshot_base_url}/Render/CameraHandler.ashx"
                try:
                    response = await self.client.get(
                        url,
                        params={"id": camera.camera_id, "bg": "black", "w": width, "h": height, "t": timestamp},
                        headers={"Referer": f"{self.base_url}/map.aspx"},
                    )
                    if response.status_code in {401, 403} and not session_refreshed:
                        await self.bootstrap(force=True)
                        session_refreshed = True
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    if not content_type.startswith("image/"):
                        raise SourceError(f"Unexpected content type {content_type or '<missing>'}")
                    with Image.open(BytesIO(response.content)) as image:
                        image.verify()
                    with Image.open(BytesIO(response.content)) as image:
                        actual_width, actual_height = image.size
                    http_date = response.headers.get("date")
                    source_http_date = parsedate_to_datetime(http_date).astimezone(timezone.utc) if http_date else None
                    return Snapshot(
                        camera=camera,
                        content=response.content,
                        content_type=content_type,
                        checksum_sha256=hashlib.sha256(response.content).hexdigest(),
                        requested_width=width,
                        requested_height=height,
                        actual_width=actual_width,
                        actual_height=actual_height,
                        byte_size=len(response.content),
                        http_status=response.status_code,
                        source_http_date=source_http_date,
                        fetched_at=datetime.now(timezone.utc),
                        fetch_ms=(time.perf_counter() - start_total) * 1000,
                    )
                except (httpx.HTTPError, SourceError, UnidentifiedImageError, OSError, ValueError) as exc:
                    status = getattr(getattr(exc, "response", None), "status_code", None)
                    last_error = ("invalid_snapshot" if isinstance(exc, (SourceError, UnidentifiedImageError, OSError)) else "http_error", str(exc), status)
                    if attempt < 2:
                        await asyncio.sleep(2 ** attempt)
        return Snapshot(
            camera=camera,
            requested_width=self.snapshot_sizes[-1][0],
            requested_height=self.snapshot_sizes[-1][1],
            http_status=last_error[2],
            fetched_at=datetime.now(timezone.utc),
            fetch_ms=(time.perf_counter() - start_total) * 1000,
            error_code=last_error[0],
            error_message=last_error[1][:2000],
        )

    async def fetch_many(self, cameras: Iterable[Camera], concurrency: int | None = None) -> list[Snapshot]:
        semaphore = asyncio.Semaphore(concurrency or self.concurrency)

        async def fetch(camera: Camera) -> Snapshot:
            async with semaphore:
                return await self.fetch_snapshot(camera)

        return await asyncio.gather(*(fetch(camera) for camera in cameras))

    async def iter_snapshots(self, cameras: Iterable[Camera]) -> AsyncIterator[Snapshot]:
        camera_list = list(cameras)
        input_queue: asyncio.Queue[Camera | None] = asyncio.Queue()
        output_queue: asyncio.Queue[Snapshot] = asyncio.Queue(maxsize=max(2, self.concurrency * 2))
        for camera in camera_list:
            input_queue.put_nowait(camera)
        for _ in range(self.concurrency):
            input_queue.put_nowait(None)

        async def worker() -> None:
            while True:
                camera = await input_queue.get()
                try:
                    if camera is None:
                        return
                    await output_queue.put(await self.fetch_snapshot(camera))
                finally:
                    input_queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(self.concurrency)]
        completed = False
        try:
            for _ in camera_list:
                yield await output_queue.get()
            completed = True
        finally:
            if not completed:
                for worker_task in workers:
                    worker_task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
