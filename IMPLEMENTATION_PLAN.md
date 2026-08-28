# Implementation Plan

## Phase 1 — one-shot local script

- [x] Safely parse the website's AjaxPro camera response without executing JavaScript.
- [x] Bootstrap and reuse the website session for metadata and snapshot requests.
- [x] Synchronize normalized camera fields, coordinates, and complete raw metadata.
- [x] Create a forward-only PostgreSQL/PostGIS DDL snapshot for `cameras`, `runs`, `observations`, and `benchmarks`.
- [x] Process only cameras whose current upstream status is `UP`.
- [x] Request 1280x720 snapshots with progressively smaller fallbacks and record requested/actual sizes.
- [x] Bound snapshot concurrency (default 4), retry transient/invalid responses, and isolate per-camera failures.
- [x] Run YOLO26m COCO inference for bicycle, car, motorcycle, bus, and truck.
- [x] Crop the black renderer canvas before inference and version the preprocessing metadata.
- [x] Include model weights and inference/preprocessing settings in duplicate detection.
- [x] Store per-snapshot counts, detections, timings, model config, camera/run references, and errors.
- [x] Detect identical snapshots by SHA-256 and copy the prior inference into a linked observation.
- [x] Add optional original and annotated dev images under `photo/<run-id>/`; default off and Git-ignored.
- [x] Add deterministic benchmark scenarios for download concurrency and inference size/batch.
- [x] Add CLI commands: psql-backed `migrate`, `sync-cameras`, `benchmark`, and `run`.
- [x] Add unit tests, README, `.env.example`, and `AGENTS.md`.
- [x] Verify migrations, live metadata sync, live snapshot download, and YOLO smoke inference.

## Deployment phase

- [ ] Run the 50-camera benchmark on the target GPU server and choose image/batch settings from measured results plus human review.
- [ ] Validate a labeled image set and decide whether COCO weights need fine-tuning for Ho Chi Minh City camera viewpoints.
- [x] Add Ubuntu PM2 scheduling with one CPU Docker instance and a two-minute delay after each cycle.
- [x] Add Docker build targets for CPU and NVIDIA GPU runtimes.

## Deferred production work

- [ ] Add Airflow/Cloud Composer orchestration only after the one-shot job is accepted.
- [ ] Define production monitoring, alerting, retention/partitioning, and backup policies.
