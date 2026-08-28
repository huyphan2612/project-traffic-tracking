from traffic_tracking.db import Base, SCHEMA


def test_application_schema_has_exactly_four_tables() -> None:
    assert {
        table.name for table in Base.metadata.tables.values() if table.schema == SCHEMA
    } == {"cameras", "runs", "observations", "benchmarks"}


def test_observations_store_versioned_inference_metadata() -> None:
    columns = Base.metadata.tables[f"{SCHEMA}.observations"].columns

    assert {"inference_signature", "inference_config", "preprocessing"} <= set(columns.keys())
