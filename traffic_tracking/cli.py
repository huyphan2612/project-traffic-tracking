from __future__ import annotations

import argparse
import asyncio
import logging

from .config import Settings
from .db import make_engine
from .logging_config import configure_logging
from .pipeline import pipeline_lock, run_benchmark, run_pipeline, sync_cameras
from .sql_migrate import SchemaMigrationError, apply_schema


LOGGER = logging.getLogger(__name__)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Traffic camera metadata and YOLO vehicle-counting pipeline")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("migrate", help="Apply the current database schema with psql")
    subcommands.add_parser("sync-cameras", help="Synchronize all published camera metadata")
    benchmark = subcommands.add_parser("benchmark", help="Benchmark downloads and YOLO inference")
    benchmark.add_argument("--sample-size", type=int, default=50)
    subcommands.add_parser("run", help="Run one full camera snapshot and inference cycle")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        print(f"Configuration error: {exc}")
        return 1
    configure_logging(settings.log_level)

    if args.command == "migrate":
        try:
            apply_schema(settings)
            LOGGER.info("Database schema applied successfully")
            return 0
        except SchemaMigrationError as exc:
            LOGGER.error("%s", exc)
            return 1

    engine = make_engine(settings.database_url)
    try:
        with pipeline_lock(engine) as acquired:
            if not acquired:
                LOGGER.error("Another traffic-tracking command is already running")
                return 1
            if args.command == "sync-cameras":
                run_id, cameras, reported_total = asyncio.run(sync_cameras(engine, settings))
                LOGGER.info("run_id=%s rows=%s upstream_total=%s", run_id, len(cameras), reported_total)
                return 0
            if args.command == "benchmark":
                if args.sample_size < 1:
                    LOGGER.error("--sample-size must be >= 1")
                    return 1
                run_id, status = asyncio.run(run_benchmark(engine, settings, args.sample_size))
                LOGGER.info("run_id=%s status=%s", run_id, status)
                return 0 if status == "completed" else 1
            run_id, status, counters = asyncio.run(run_pipeline(engine, settings))
            LOGGER.info("run_id=%s status=%s counters=%s", run_id, status, counters)
            return 0 if status == "completed" else 2 if status == "partial" else 1
    finally:
        engine.dispose()
