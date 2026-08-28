# Traffic Tracking Agent Guide

## Scope

This repository implements a Python 3.10 one-shot pipeline that synchronizes public Ho Chi Minh City traffic-camera metadata, downloads snapshots for cameras whose upstream status is `UP`, runs Ultralytics YOLO vehicle detection, and stores results in the PostgreSQL schema `traffic_tracking`.

CPU and NVIDIA GPU Docker images are supported for the one-shot CLI. Scheduling, Airflow, Cloud Composer, and broader production orchestration remain out of scope until the user starts those phases.

## Commands

```bash
source .venv/bin/activate
pip install -r requirements.txt
python main.py migrate
python main.py sync-cameras
python main.py benchmark --sample-size 50
python main.py run
pytest -q
```

## Architecture and invariants

- Keep the dependency direction: upstream client/parser -> bounded processing pipeline -> detector -> repository/PostgreSQL.
- Never evaluate upstream JavaScript. The AjaxPro response must be parsed with the safe recursive-descent parser.
- Bootstrap the website session before AjaxPro or snapshot requests. Do not log cookies, passwords, or the contents of `.env`.
- Preserve every upstream camera field in `cameras.raw_metadata`; normalized columns are an index/query convenience, not a replacement.
- Store timestamps in UTC and coordinates as longitude/latitude plus PostGIS `Point(4326)`.
- Synchronize all published cameras, but only run image inference for `CamStatus=UP`.
- A successful inference with no vehicles has zero counts. Skipped, fetch-error, and inference-error observations have null counts.
- Keep the default snapshot concurrency at or below four. Higher values require an explicit user decision and a benchmark.
- Snapshot bytes are not retained when `SAVE_IMAGES=false`. Generated files under `photo/` are ignored by Git.
- A duplicate checksum reuses prior results only when the inference signature also matches. Model, threshold, image-size, class, weight, library, or preprocessing changes must force fresh inference.
- Preserve the full original snapshot, but run inference and save annotations in the versioned preprocessed coordinate space. Store enough preprocessing metadata to interpret every bounding box.
- Model, confidence, device, image size, batch size, and download concurrency must remain configurable through environment variables.

## Database rules

- Agents are authorized to use `psql` with the credentials in `.env` to inspect this project's database and to apply project-scoped schema changes explicitly requested by the user.
- Use `psql -X`, `ON_ERROR_STOP=1`, fully qualified object names, and `PGPASSWORD`; never print credentials or include the password in argv/log output.
- Do not run `DROP`, `TRUNCATE`, `DELETE`, or other destructive SQL without a clear user request and an exact target. The approved removal of legacy `public.alembic_version` is limited to the Alembic-to-DDL transition.
- `migrations/schema.sql` is the single forward-only snapshot of the current schema. Apply future changes with `psql` and update this file in the same change; do not add versioned migration or rollback files.
- Application DDL may only create or alter objects in the `traffic_tracking` schema, which must contain exactly the four application tables.
- `python main.py run` must not apply migrations implicitly.
- Per-camera failures must be persisted and isolated. Systemic bootstrap, camera-list, database, or model-initialization failures fail the run.
- Add DDL and tests for every schema change.

## Testing and completion

- Unit-test parser changes with fixtures containing nested AjaxPro `DataTable` constructors.
- Mock network calls by default. Live website tests must be explicitly opted into.
- Tests must use a disposable database or randomized test schema and must not delete unrelated data.
- Before handoff, run `pytest -q` and at least the non-destructive CLI help/config smoke checks.
- Keep README, `.env.example`, CLI help, `migrations/schema.sql`, and this file synchronized with behavior.
