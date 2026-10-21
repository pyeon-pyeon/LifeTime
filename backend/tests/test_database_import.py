from datetime import time, timezone
import json
from pathlib import Path

import pytest

from scripts.import_facilities import (
    DEFAULT_DATASETS,
    RecordError,
    build_parser,
    build_rpc_record,
    dry_run,
    main,
    normalize_record,
    parse_optional_timestamp,
    resolve_datasets,
    upsert_batch,
)

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20261020130000_facilities_schema.sql"
).read_text(encoding="utf-8")


def test_normalize_aed_preserves_hours_and_extra_fields():
    record = {
        "facility_type": "aed",
        "source_id": "AED-1",
        "name": "AED 위치",
        "address": None,
        "latitude": 37.5,
        "longitude": 127.0,
        "source_updated_at": None,
        "data_collected_at": "2026-10-20T01:00:00+00:00",
        "source_name": "AED source",
        "contact_phone": None,
        "installation_detail": "1층 로비",
        "schedule_status": "known",
        "sido": None,
        "gugun": None,
        "access_hours": [
            {
                "weekday": weekday,
                "opens_at": "00:00",
                "closes_at": "00:00",
                "ends_next_day": True,
                "is_24_hours": True,
            }
            for weekday in range(1, 8)
        ],
    }

    normalized = normalize_record(record, "aed")

    assert normalized["facility"]["address"] is None
    assert normalized["facility"]["installation_detail"] == "1층 로비"
    assert normalized["facility"]["data_collected_at"].utcoffset() == timezone.utc.utcoffset(None)
    assert normalized["access_hours"][0]["opens_at"] == time(0, 0)
    assert len(normalized["access_hours"]) == 7
    assert normalized["access_hours"][0]["is_24_hours"] is True


def test_normalize_emergency_room_keeps_extra_phone_and_nulls():
    record = {
        "facility_type": "emergency_room",
        "source_id": "HOSPITAL-1",
        "name": "병원",
        "address": "주소",
        "latitude": 35.5,
        "longitude": 129.3,
        "contact_phone": "000-0000",
        "emergency_phone": "000-1199",
        "source_updated_at": None,
        "data_collected_at": "2026-10-20T01:00:00Z",
    }

    normalized = normalize_record(record, "emergency_room")

    assert normalized["facility"]["emergency_phone"] == "000-1199"
    assert normalized["facility"]["source_updated_at"] is None
    assert normalized["access_hours"] == []


@pytest.mark.parametrize(
    "timestamp",
    ["2026-10-20T01:00:00", "not-a-date", 123],
)
def test_timestamps_require_offset_iso8601(timestamp):
    with pytest.raises(RecordError):
        parse_optional_timestamp(timestamp, "data_collected_at")


@pytest.mark.parametrize(
    "field,value",
    [("latitude", 91), ("longitude", -181), ("latitude", "bad")],
)
def test_invalid_coordinates_are_rejected(field, value):
    record = {
        "facility_type": "aed",
        "source_id": "AED-1",
        "latitude": 37.0,
        "longitude": 127.0,
    }
    record[field] = value
    with pytest.raises(RecordError):
        normalize_record(record, "aed")


def test_duplicate_key_uses_upsert():
    assert "ON CONFLICT (facility_type, source_id) DO UPDATE" in MIGRATION


def test_rpc_record_keeps_nulls_and_serializes_timestamps_and_hours():
    normalized = normalize_record(
        {
            "facility_type": "aed",
            "source_id": "AED-1",
            "name": None,
            "data_collected_at": "2026-10-20T01:00:00Z",
            "access_hours": [
                {
                    "weekday": 1,
                    "opens_at": "09:00",
                    "closes_at": "18:00",
                    "ends_next_day": False,
                    "is_24_hours": False,
                }
            ],
        },
        "aed",
    )
    record = build_rpc_record(normalized)
    assert record["name"] is None
    assert record["data_collected_at"] == "2026-10-20T01:00:00+00:00"
    assert record["access_hours"][0]["opens_at"] == "09:00:00"


def test_rest_batch_calls_atomic_upsert_rpc():
    class Response:
        data = 1

    class Request:
        def execute(self):
            return Response()

    class Client:
        def rpc(self, function_name, params):
            assert function_name == "upsert_facility_batch"
            assert len(params["p_records"]) == 1
            return Request()

    normalized = normalize_record(
        {"facility_type": "aed", "source_id": "AED-1"}, "aed"
    )
    assert upsert_batch(Client(), [normalized]) == 1


def test_schema_has_unique_key_coordinate_checks_gist_and_read_only_rls():
    assert "UNIQUE (facility_type, source_id)" in MIGRATION
    assert "latitude BETWEEN -90 AND 90" in MIGRATION
    assert "longitude BETWEEN -180 AND 180" in MIGRATION
    assert "USING gist (location)" in MIGRATION
    assert "ALTER TABLE public.facilities ENABLE ROW LEVEL SECURITY" in MIGRATION
    assert "facilities_public_read" in MIGRATION
    assert "facility_access_hours_public_read" in MIGRATION
    assert "FOR INSERT TO anon" not in MIGRATION
    assert "FOR UPDATE TO authenticated" not in MIGRATION
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.facilities TO service_role" in MIGRATION


def test_schema_has_client_select_only_and_auxiliary_indexes():
    assert "REVOKE ALL ON TABLE public.facilities FROM PUBLIC, anon, authenticated" in MIGRATION
    assert "GRANT SELECT ON TABLE public.facilities TO anon, authenticated" in MIGRATION
    assert "GRANT SELECT ON TABLE public.facility_access_hours TO anon, authenticated" in MIGRATION
    assert "facilities_source_id_idx" in MIGRATION
    assert "facilities_type_idx" in MIGRATION
    assert "CREATE INDEX IF NOT EXISTS facilities_location_gist" in MIGRATION
    assert "extensions.ST_MakePoint(NEW.longitude, NEW.latitude)" in MIGRATION
    assert "geography(Point, 4326)" in MIGRATION


def test_schema_guards_existing_incompatible_tables():
    assert "public.facilities exists with an incompatible schema" in MIGRATION
    assert "public.facility_access_hours exists with an incompatible schema" in MIGRATION
    assert "CREATE OR REPLACE FUNCTION public.upsert_facility_batch(p_records jsonb)" in MIGRATION
    assert "REVOKE ALL ON FUNCTION public.upsert_facility_batch(jsonb) FROM PUBLIC, anon, authenticated" in MIGRATION
    assert "GRANT EXECUTE ON FUNCTION public.upsert_facility_batch(jsonb) TO service_role" in MIGRATION


def test_migration_does_not_drop_tables_or_replace_existing_policies():
    assert "DROP TABLE" not in MIGRATION.upper()
    assert "TRUNCATE " not in MIGRATION.upper()
    assert "DROP POLICY" not in MIGRATION.upper()


def test_dry_run_validates_without_database(tmp_path):
    source = tmp_path / "aed.json"
    source.write_text(
        json.dumps(
            [
                {
                    "facility_type": "aed",
                    "source_id": "AED-1",
                    "latitude": 37.0,
                    "longitude": 127.0,
                },
                {"facility_type": "aed", "source_id": ""},
            ]
        ),
        encoding="utf-8",
    )
    error_log = tmp_path / "import-errors.jsonl"

    summary = dry_run({"aed": source}, batch_size=1, error_log=error_log)

    assert summary == {
        "input_count": 2,
        "valid_count": 1,
        "failed_count": 1,
        "duplicate_source_id_count": 0,
    }
    errors = [json.loads(line) for line in error_log.read_text().splitlines()]
    assert errors[0]["error_type"] == "RecordError"


def test_dry_run_counts_duplicate_source_ids(tmp_path):
    source = tmp_path / "aed.json"
    row = {"facility_type": "aed", "source_id": "AED-1"}
    source.write_text(json.dumps([row, row]), encoding="utf-8")

    summary = dry_run({"aed": source}, error_log=tmp_path / "errors.jsonl")

    assert summary["input_count"] == 2
    assert summary["valid_count"] == 1
    assert summary["duplicate_source_id_count"] == 1
    assert summary["failed_count"] == 1


def test_resolve_datasets_default_aed_only():
    parser = build_parser()
    args = parser.parse_args([])
    datasets = resolve_datasets(args)

    assert set(datasets.keys()) == {"aed"}
    assert datasets["aed"] == DEFAULT_DATASETS["aed"]


def test_resolve_datasets_concurrent_aed_and_medical():
    parser = build_parser()
    custom_medical = Path("medical/sample.json")
    args = parser.parse_args(["--medical-json", str(custom_medical)])
    datasets = resolve_datasets(args)

    assert set(datasets.keys()) == {"aed", "emergency_room"}
    assert datasets["aed"] == DEFAULT_DATASETS["aed"]
    assert datasets["emergency_room"] == custom_medical


def test_resolve_datasets_only_medical_requires_medical_json():
    parser = build_parser()
    args = parser.parse_args(["--only-medical"])

    with pytest.raises(RecordError, match="--only-medical requires --medical-json"):
        resolve_datasets(args)


def test_resolve_datasets_only_medical_selects_emergency_room_only():
    parser = build_parser()
    custom_medical = Path("medical/sample.json")
    args = parser.parse_args(["--only-medical", "--medical-json", str(custom_medical)])
    datasets = resolve_datasets(args)

    assert datasets == {"emergency_room": custom_medical}
    assert "aed" not in datasets


def test_only_medical_dry_run_selects_and_validates_530_emergency_rooms(tmp_path):
    medical_path = DEFAULT_DATASETS["emergency_room"]
    assert medical_path.exists()

    parser = build_parser()
    args = parser.parse_args(["--only-medical", "--medical-json", str(medical_path), "--dry-run"])
    datasets = resolve_datasets(args)
    assert datasets == {"emergency_room": medical_path}

    summary = dry_run(datasets, error_log=tmp_path / "errors.jsonl")
    assert summary == {
        "input_count": 530,
        "valid_count": 530,
        "failed_count": 0,
        "duplicate_source_id_count": 0,
    }


def test_main_only_medical_cli_dry_run(capsys):
    medical_path = DEFAULT_DATASETS["emergency_room"]
    main(["--only-medical", "--medical-json", str(medical_path), "--dry-run"])
    captured = capsys.readouterr().out

    assert "input_count: 530" in captured
    assert "valid_count: 530" in captured
    assert "failed_count: 0" in captured
    assert "duplicate_source_id_count: 0" in captured


def test_main_only_medical_cli_without_medical_json_exits():
    with pytest.raises(SystemExit) as exc_info:
        main(["--only-medical", "--dry-run"])
    assert "--only-medical requires --medical-json" in str(exc_info.value)
