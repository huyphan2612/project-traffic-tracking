from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import logging
import math
import os
import platform
import statistics
import time
from typing import Any, Iterator
from uuid import UUID

import psutil
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import Settings
from .db import RunRecord
from .detector import Detector
from .domain import Camera, Snapshot
from .photos import PhotoStore
from .repository import ADVISORY_LOCK_KEY, Repository
from .source import TrafficCameraClient


LOGGER = logging.getLogger(__name__)


@contextmanager
def pipeline_lock(engine) -> Iterator[bool]:
    with engine.connect() as connection:
        acquired = bool(connection.execute(select(func.pg_try_advisory_lock(ADVISORY_LOCK_KEY))).scalar_one())
        try:
            yield acquired
        finally:
            if acquired:
                connection.execute(select(func.pg_advisory_unlock(ADVISORY_LOCK_KEY)))


def _session(engine) -> Session:
    return Session(engine, expire_on_commit=False)


def is_reusable_duplicate(previous: Any, snapshot: Snapshot, inference_signature: str) -> bool:
    return bool(
        previous is not None
        and previous.checksum_sha256 == snapshot.checksum_sha256
        and previous.inference_signature == inference_signature
    )


def _new_run(engine, run_type: str, settings: Settings, extra: dict[str, Any] | None = None) -> UUID:
    config = settings.public_config()
    if extra:
        config.update(extra)
    with _session(engine) as session:
        run = Repository(session).create_run(run_type, config)
        session.commit()
        return run.id


def _finish_run(engine, run_id: UUID, status: str, **values: Any) -> None:
    with _session(engine) as session:
        run = session.get(RunRecord, run_id)
        if run is None:
            raise RuntimeError(f"Run {run_id} does not exist")
        Repository(session).finish_run(run, status, **values)
        session.commit()


async def sync_cameras(engine, settings: Settings) -> tuple[UUID, list[Camera], int | None]:
    run_id = _new_run(engine, "sync", settings)
    try:
        async with TrafficCameraClient(
            settings.base_url,
            settings.download_concurrency,
            settings.snapshot_sizes,
        ) as client:
            cameras, reported_total = await client.list_cameras()
        with _session(engine) as session:
            Repository(session).upsert_cameras(cameras)
            session.commit()
        up_count = sum(camera.status == "UP" for camera in cameras)
        _finish_run(
            engine,
            run_id,
            "completed",
            discovered_count=len(cameras),
            up_count=up_count,
            skipped_count=len(cameras) - up_count,
        )
        LOGGER.info("Synchronized %s cameras (%s UP, upstream total=%s)", len(cameras), up_count, reported_total)
        return run_id, cameras, reported_total
    except Exception as exc:
        _finish_run(engine, run_id, "failed", error_message=str(exc)[:4000])
        raise


async def run_pipeline(engine, settings: Settings) -> tuple[UUID, str, dict[str, int]]:
    run_id = _new_run(engine, "run", settings)
    counters = {"discovered": 0, "up": 0, "skipped": 0, "succeeded": 0, "failed": 0, "duplicate": 0}
    observed_at = datetime.now(timezone.utc)
    photo_store = PhotoStore(settings.photo_dir, str(run_id)) if settings.save_images else None

    try:
        detector = Detector(
            settings.yolo_model,
            settings.yolo_device,
            settings.yolo_confidence,
            settings.yolo_imgsz,
            settings.auto_crop,
        )
        async with TrafficCameraClient(
            settings.base_url,
            settings.download_concurrency,
            settings.snapshot_sizes,
        ) as client:
            cameras, reported_total = await client.list_cameras()
            counters["discovered"] = len(cameras)
            up_cameras = [camera for camera in cameras if camera.status == "UP"]
            skipped_cameras = [camera for camera in cameras if camera.status != "UP"]
            counters["up"] = len(up_cameras)
            counters["skipped"] = len(skipped_cameras)
            LOGGER.info("Run %s discovered=%s upstream_total=%s up=%s", run_id, len(cameras), reported_total, len(up_cameras))

            with _session(engine) as session:
                repository = Repository(session)
                repository.upsert_cameras(cameras, observed_at)
                for camera in skipped_cameras:
                    repository.add_skipped_observation(run_id, camera, observed_at)
                session.commit()

            with _session(engine) as session:
                latest = Repository(session).latest_successes(camera.camera_id for camera in up_cameras)

            batch: list[Snapshot] = []
            async for snapshot in client.iter_snapshots(up_cameras):
                timestamp = snapshot.fetched_at or observed_at
                if not snapshot.ok:
                    with _session(engine) as session:
                        Repository(session).add_fetch_error(run_id, snapshot, timestamp)
                        session.commit()
                    counters["failed"] += 1
                    continue

                previous = latest.get(snapshot.camera.camera_id)
                if is_reusable_duplicate(previous, snapshot, detector.inference_signature):
                    original_path = annotated_path = None
                    if photo_store and snapshot.content:
                        annotated = photo_store.render_existing(
                            snapshot.content,
                            previous.detections,
                            previous.preprocessing,
                        )
                        original_path, annotated_path = photo_store.save(snapshot.camera.camera_id, timestamp, snapshot.content, annotated)
                    with _session(engine) as session:
                        record = Repository(session).add_duplicate(
                            run_id, snapshot, timestamp, previous, original_path, annotated_path,
                        )
                        session.commit()
                    latest[snapshot.camera.camera_id] = record
                    counters["duplicate"] += 1
                    continue

                batch.append(snapshot)
                if len(batch) >= settings.inference_batch_size:
                    await _process_batch(engine, run_id, batch, detector, settings, photo_store, latest, counters)
                    batch = []

            if batch:
                await _process_batch(engine, run_id, batch, detector, settings, photo_store, latest, counters)

        status = "completed" if counters["failed"] == 0 else "partial"
        if counters["up"] > 0 and counters["succeeded"] + counters["duplicate"] == 0:
            status = "failed"
        _finish_run(
            engine,
            run_id,
            status,
            discovered_count=counters["discovered"],
            up_count=counters["up"],
            skipped_count=counters["skipped"],
            succeeded_count=counters["succeeded"],
            failed_count=counters["failed"],
            duplicate_count=counters["duplicate"],
        )
        return run_id, status, counters
    except Exception as exc:
        _finish_run(
            engine,
            run_id,
            "failed",
            discovered_count=counters["discovered"],
            up_count=counters["up"],
            skipped_count=counters["skipped"],
            succeeded_count=counters["succeeded"],
            failed_count=counters["failed"],
            duplicate_count=counters["duplicate"],
            error_message=str(exc)[:4000],
        )
        raise


async def _process_batch(
    engine,
    run_id: UUID,
    batch: list[Snapshot],
    detector: Detector,
    settings: Settings,
    photo_store: PhotoStore | None,
    latest: dict,
    counters: dict[str, int],
) -> None:
    try:
        outputs = detector.infer(batch, render=photo_store is not None)
        pairs = list(zip(batch, outputs))
    except Exception as batch_error:
        LOGGER.warning("Batch inference failed; retrying images individually: %s", batch_error)
        pairs = []
        for snapshot in batch:
            try:
                output = detector.infer([snapshot], render=photo_store is not None)[0]
                pairs.append((snapshot, output))
            except Exception as exc:
                with _session(engine) as session:
                    Repository(session).add_inference_error(run_id, snapshot, snapshot.fetched_at or datetime.now(timezone.utc), exc)
                    session.commit()
                counters["failed"] += 1

    for snapshot, (result, annotated) in pairs:
        timestamp = snapshot.fetched_at or datetime.now(timezone.utc)
        original_path = annotated_path = None
        if photo_store and snapshot.content and annotated:
            original_path, annotated_path = photo_store.save(snapshot.camera.camera_id, timestamp, snapshot.content, annotated)
        with _session(engine) as session:
            record = Repository(session).add_inference(
                run_id=run_id,
                snapshot=snapshot,
                observed_at=timestamp,
                result=result,
                model_name=settings.yolo_model,
                device=detector.device,
                image_size=settings.yolo_imgsz,
                confidence=settings.yolo_confidence,
                inference_signature=detector.inference_signature,
                inference_config=detector.inference_config,
                original_path=original_path,
                annotated_path=annotated_path,
            )
            session.commit()
        latest[snapshot.camera.camera_id] = record
        counters["succeeded"] += 1


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return round(ordered[lower], 3)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower), 3)


def _metrics(latencies: list[float], duration_seconds: float, count: int, failures: int = 0) -> dict[str, Any]:
    return {
        "count": count,
        "failures": failures,
        "duration_seconds": round(duration_seconds, 3),
        "throughput_per_second": round(count / duration_seconds, 3) if duration_seconds > 0 else None,
        "latency_ms_p50": _percentile(latencies, 0.50),
        "latency_ms_p95": _percentile(latencies, 0.95),
        "rss_bytes": psutil.Process().memory_info().rss,
    }


def _host_info() -> dict[str, Any]:
    info = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "memory_bytes": psutil.virtual_memory().total,
    }
    try:
        import torch

        info.update({"torch": torch.__version__, "cuda_available": torch.cuda.is_available()})
        if torch.cuda.is_available():
            info["gpu"] = torch.cuda.get_device_name(0)
    except ImportError:
        info["torch"] = None
    return info


def _stratified_sample(cameras: list[Camera], size: int) -> list[Camera]:
    groups: dict[tuple[str, str], list[Camera]] = {}
    for camera in cameras:
        groups.setdefault((camera.camera_type or "", camera.district or ""), []).append(camera)
    for group in groups.values():
        group.sort(key=lambda camera: hashlib.sha256(f"42:{camera.camera_id}".encode()).hexdigest())
    selected: list[Camera] = []
    keys = sorted(groups)
    while len(selected) < min(size, len(cameras)):
        changed = False
        for key in keys:
            if groups[key] and len(selected) < size:
                selected.append(groups[key].pop(0))
                changed = True
        if not changed:
            break
    return selected


async def run_benchmark(engine, settings: Settings, sample_size: int = 50) -> tuple[UUID, str]:
    run_id = _new_run(engine, "benchmark", settings, {"sample_size": sample_size})
    host_info = _host_info()
    try:
        async with TrafficCameraClient(settings.base_url, settings.download_concurrency, settings.snapshot_sizes) as client:
            cameras, _ = await client.list_cameras()
            with _session(engine) as session:
                Repository(session).upsert_cameras(cameras)
                session.commit()
            sample = _stratified_sample([camera for camera in cameras if camera.status == "UP"], sample_size)
            if not sample:
                raise RuntimeError("No UP cameras available for benchmark")
            camera_ids = [camera.camera_id for camera in sample]
            retained: list[Snapshot] = []
            for concurrency in (1, 2, 4):
                started = time.perf_counter()
                snapshots = await client.fetch_many(sample, concurrency=concurrency)
                duration = time.perf_counter() - started
                successful = [snapshot for snapshot in snapshots if snapshot.ok]
                metrics = _metrics(
                    [snapshot.fetch_ms or 0 for snapshot in successful],
                    duration,
                    len(successful),
                    len(snapshots) - len(successful),
                )
                with _session(engine) as session:
                    Repository(session).add_benchmark(
                        run_id=run_id,
                        scenario_type="download",
                        model_name=None,
                        device=None,
                        image_size=None,
                        batch_size=None,
                        concurrency=concurrency,
                        sample_camera_ids=camera_ids,
                        host_info=host_info,
                        metrics=metrics,
                        status="completed" if successful else "failed",
                        error_message=None if successful else "All downloads failed",
                        created_at=datetime.now(timezone.utc),
                    )
                    session.commit()
                LOGGER.info("Download benchmark concurrency=%s metrics=%s", concurrency, metrics)
                if concurrency == 4:
                    retained = successful

        if not retained:
            raise RuntimeError("No valid snapshots available for inference benchmark")

        photo_store = PhotoStore(settings.photo_dir, str(run_id)) if settings.save_images else None
        for image_size in (640, 1280):
            detector = Detector(
                settings.yolo_model,
                settings.yolo_device,
                settings.yolo_confidence,
                image_size,
                settings.auto_crop,
            )
            for batch_size in (1, 2, 4):
                status = "completed"
                error_message = None
                latencies: list[float] = []
                processed = 0
                started = time.perf_counter()
                try:
                    for offset in range(0, len(retained), batch_size):
                        chunk = retained[offset:offset + batch_size]
                        outputs = detector.infer(chunk, render=photo_store is not None)
                        for snapshot, (result, annotated) in zip(chunk, outputs):
                            latencies.append(result.inference_ms or 0)
                            processed += 1
                            if photo_store and snapshot.content and annotated:
                                photo_store.save(snapshot.camera.camera_id, snapshot.fetched_at or datetime.now(timezone.utc), snapshot.content, annotated)
                except Exception as exc:
                    status = "failed"
                    error_message = str(exc)[:2000]
                duration = time.perf_counter() - started
                metrics = _metrics(latencies, duration, processed, len(retained) - processed)
                with _session(engine) as session:
                    Repository(session).add_benchmark(
                        run_id=run_id,
                        scenario_type="inference",
                        model_name=settings.yolo_model,
                        device=detector.device,
                        image_size=image_size,
                        batch_size=batch_size,
                        concurrency=None,
                        sample_camera_ids=[snapshot.camera.camera_id for snapshot in retained],
                        host_info=host_info,
                        metrics=metrics,
                        status=status,
                        error_message=error_message,
                        created_at=datetime.now(timezone.utc),
                    )
                    session.commit()
                LOGGER.info("Inference benchmark imgsz=%s batch=%s metrics=%s", image_size, batch_size, metrics)

        _finish_run(
            engine,
            run_id,
            "completed",
            discovered_count=len(cameras),
            up_count=sum(camera.status == "UP" for camera in cameras),
            succeeded_count=len(retained),
            failed_count=len(sample) - len(retained),
        )
        return run_id, "completed"
    except Exception as exc:
        _finish_run(engine, run_id, "failed", error_message=str(exc)[:4000])
        raise
