"""Batch UPSERT facility JSON through the Supabase REST API."""

import argparse
from datetime import datetime, time, timezone
import json
from pathlib import Path
import random
import time as time_module
from uuid import uuid4

try:
    from .supabase_rest import create_supabase_client
except ImportError:
    from supabase_rest import create_supabase_client


BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DATASETS = {
    "aed": BACKEND_DIR / "AED" / "aed_nationwide.json",
    "emergency_room": BACKEND_DIR / "medical" / "medical_nationwide.json",
}
DEFAULT_ERROR_LOG = BACKEND_DIR / "import_errors.jsonl"


class RecordError(ValueError):
    """Raised when a source record cannot fit the database contract."""


def parse_optional_timestamp(value, field_name):
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise RecordError(f"{field_name} must be an ISO 8601 string or null")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RecordError(f"{field_name} is not valid ISO 8601") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RecordError(f"{field_name} must include a timezone offset")
    return parsed


def parse_coordinate(value, field_name, minimum, maximum):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise RecordError(f"{field_name} must be numeric or null")
    try:
        coordinate = float(value)
    except (TypeError, ValueError) as error:
        raise RecordError(f"{field_name} must be numeric or null") from error
    if not minimum <= coordinate <= maximum:
        raise RecordError(f"{field_name} is outside its valid range")
    return coordinate


def parse_optional_text(record, field_name):
    value = record.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise RecordError(f"{field_name} must be a string or null")
    return value.strip() or None


def parse_access_hours(values):
    if values is None:
        return []
    if not isinstance(values, list):
        raise RecordError("access_hours must be a list or null")

    hours = []
    seen_weekdays = set()
    for value in values:
        try:
            weekday = value["weekday"]
            opens_at = time.fromisoformat(value["opens_at"])
            closes_at = time.fromisoformat(value["closes_at"])
            ends_next_day = value["ends_next_day"]
            is_24_hours = value["is_24_hours"]
        except (KeyError, TypeError, ValueError) as error:
            raise RecordError("access_hours contains an invalid entry") from error
        if type(weekday) is not int or not 1 <= weekday <= 7 or weekday in seen_weekdays:
            raise RecordError("access_hours weekdays must be unique values from 1 to 7")
        if opens_at.tzinfo is not None or closes_at.tzinfo is not None:
            raise RecordError("access_hours uses Seoul wall-clock time without an offset")
        if not isinstance(ends_next_day, bool) or not isinstance(is_24_hours, bool):
            raise RecordError("access_hours flags must be booleans")
        seen_weekdays.add(weekday)
        hours.append(
            {
                "weekday": weekday,
                "opens_at": opens_at,
                "closes_at": closes_at,
                "ends_next_day": ends_next_day,
                "is_24_hours": is_24_hours,
            }
        )
    return hours


def normalize_record(record, expected_type):
    if not isinstance(record, dict):
        raise RecordError("record must be a JSON object")
    if expected_type not in {"aed", "emergency_room"}:
        raise RecordError("unsupported facility type")
    if record.get("facility_type") != expected_type:
        raise RecordError("facility_type does not match the input dataset")

    source_id = record.get("source_id")
    if not isinstance(source_id, str) or not source_id.strip():
        raise RecordError("source_id is required")

    facility = {
        "facility_type": expected_type,
        "source_id": source_id.strip(),
        "name": parse_optional_text(record, "name"),
        "address": parse_optional_text(record, "address"),
        "latitude": parse_coordinate(record.get("latitude"), "latitude", -90, 90),
        "longitude": parse_coordinate(record.get("longitude"), "longitude", -180, 180),
        "source_updated_at": parse_optional_timestamp(
            record.get("source_updated_at"), "source_updated_at"
        ),
        "data_collected_at": parse_optional_timestamp(
            record.get("data_collected_at"), "data_collected_at"
        ),
        "source_name": parse_optional_text(record, "source_name"),
        "contact_phone": parse_optional_text(record, "contact_phone"),
        "emergency_phone": parse_optional_text(record, "emergency_phone"),
        "installation_detail": parse_optional_text(record, "installation_detail"),
        "schedule_status": parse_optional_text(record, "schedule_status"),
        "sido": parse_optional_text(record, "sido"),
        "gugun": parse_optional_text(record, "gugun"),
    }
    if facility["schedule_status"] not in {None, "known", "partial", "unknown"}:
        raise RecordError("schedule_status is not supported")
    return {
        "facility": facility,
        "access_hours": parse_access_hours(record.get("access_hours")),
    }


def load_dataset(path):
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecordError(f"cannot read JSON dataset: {path}") from error
    if not isinstance(records, list):
        raise RecordError(f"dataset root must be a JSON array: {path}")
    return records


def append_error(error_log, *, facility_type, record_index, source_id, error):
    error_log.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "facility_type": facility_type,
        "record_index": record_index,
        "source_id": source_id,
        "error_type": type(error).__name__,
        "error": str(error)[:500],
    }
    with error_log.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")


def build_rpc_record(item):
    record = dict(item["facility"])
    for field in ("source_updated_at", "data_collected_at"):
        if record[field] is not None:
            record[field] = record[field].isoformat()
    record["access_hours"] = [
        {
            **hour,
            "opens_at": hour["opens_at"].isoformat(),
            "closes_at": hour["closes_at"].isoformat(),
        }
        for hour in item["access_hours"]
    ]
    return record


def upsert_batch(client, batch, *, retries=5, detailed=False):
    records = [build_rpc_record(item) for item in batch]
    params = {"p_records": records}
    if detailed:
        params["p_request_id"] = str(uuid4())
    for attempt in range(retries):
        try:
            response = client.rpc(
                "stage_facility_batch" if detailed else "upsert_facility_batch", params
            ).execute()
            if detailed:
                counts = response.data
                if (not isinstance(counts, dict) or set(counts) != {"inserted", "updated", "held", "unchanged"}
                        or any(type(n) is not int or n < 0 for n in counts.values())
                        or sum(counts.values()) != len(batch)):
                    raise RuntimeError("Invalid guarded import result")
                return counts
            if not isinstance(response.data, int) or response.data != len(batch):
                raise RuntimeError("Supabase RPC returned an unexpected row count")
            return response.data
        except Exception as error:  # noqa: BLE001 - retry is safe due to UPSERT
            if attempt + 1 >= retries:
                raise RuntimeError(
                    f"Supabase batch RPC failed ({type(error).__name__})"
                ) from None
            time_module.sleep(min(2**attempt + random.random(), 20))
    return 0


def import_datasets(client, datasets, *, batch_size=500, error_log=DEFAULT_ERROR_LOG):
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    summary = {
        "input_count": 0,
        "upserted_count": 0,
        "failed_count": 0,
        "batch_failed_count": 0,
        "inserted_count": 0,
        "updated_count": 0,
        "held_count": 0,
        "unchanged_count": 0,
    }

    for facility_type, dataset_path in datasets.items():
        records = load_dataset(dataset_path)
        pending = []

        def flush_batch():
            if not pending:
                return
            try:
                counts = upsert_batch(client, pending, detailed=True)
                for field in ("inserted", "updated", "held", "unchanged"):
                    summary[field + "_count"] += counts[field]
                summary["upserted_count"] += counts["inserted"] + counts["updated"]
            except Exception as error:  # noqa: BLE001 - log and continue by batch
                summary["failed_count"] += len(pending)
                summary["batch_failed_count"] += 1
                append_error(
                    error_log,
                    facility_type=facility_type,
                    record_index=None,
                    source_id=[item["facility"]["source_id"] for item in pending],
                    error=error,
                )
            pending.clear()

        for index, record in enumerate(records, start=1):
            summary["input_count"] += 1
            try:
                pending.append(normalize_record(record, facility_type))
            except RecordError as error:
                summary["failed_count"] += 1
                append_error(
                    error_log,
                    facility_type=facility_type,
                    record_index=index,
                    source_id=record.get("source_id") if isinstance(record, dict) else None,
                    error=error,
                )
                continue
            if len(pending) >= batch_size:
                flush_batch()
        flush_batch()
    return summary


def dry_run(datasets, *, batch_size=500, error_log=DEFAULT_ERROR_LOG):
    """Validate all inputs without opening a Supabase API connection."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    summary = {
        "input_count": 0,
        "valid_count": 0,
        "failed_count": 0,
        "duplicate_source_id_count": 0,
    }
    for facility_type, dataset_path in datasets.items():
        seen_source_ids = set()
        for index, record in enumerate(load_dataset(dataset_path), start=1):
            summary["input_count"] += 1
            try:
                normalize_record(record, facility_type)
                source_id = record["source_id"].strip()
                if source_id in seen_source_ids:
                    summary["duplicate_source_id_count"] += 1
                    raise RecordError("duplicate source_id in input dataset")
                seen_source_ids.add(source_id)
                summary["valid_count"] += 1
            except RecordError as error:
                summary["failed_count"] += 1
                append_error(
                    error_log,
                    facility_type=facility_type,
                    record_index=index,
                    source_id=record.get("source_id") if isinstance(record, dict) else None,
                    error=error,
                )
    return summary


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--aed-json", type=Path, default=DEFAULT_DATASETS["aed"])
    parser.add_argument("--medical-json", type=Path)
    parser.add_argument(
        "--only-medical",
        action="store_true",
        help="Validate or import only the emergency room dataset",
    )
    parser.add_argument("--error-log", type=Path, default=DEFAULT_ERROR_LOG)
    return parser


def resolve_datasets(args):
    if getattr(args, "only_medical", False):
        if not getattr(args, "medical_json", None):
            raise RecordError("--only-medical requires --medical-json")
        return {"emergency_room": args.medical_json}

    datasets = {"aed": args.aed_json}
    if getattr(args, "medical_json", None):
        datasets["emergency_room"] = args.medical_json
    return datasets


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be at least 1")

    try:
        datasets = resolve_datasets(args)
    except RecordError as error:
        raise SystemExit(str(error)) from error
    try:
        if args.dry_run:
            summary = dry_run(datasets, batch_size=args.batch_size, error_log=args.error_log)
            print("JSON validation completed without calling Supabase.")
        else:
            validation = dry_run(datasets, batch_size=args.batch_size, error_log=args.error_log)
            if validation["failed_count"]:
                raise RecordError("Source validation failed; no database writes attempted")
            client = create_supabase_client()
            before_response = client.rpc("get_aed_import_stats", {}).execute()
            before_stats = before_response.data
            if not isinstance(before_stats, dict):
                raise RuntimeError("Supabase returned invalid pre-import statistics")
            summary = import_datasets(
                client, datasets, batch_size=args.batch_size, error_log=args.error_log
            )
            after_response = client.rpc("get_aed_import_stats", {}).execute()
            after_stats = after_response.data
            if not isinstance(after_stats, dict):
                raise RuntimeError("Supabase returned invalid post-import statistics")
            summary["db_aed_count_before"] = before_stats.get("aed_count")
            summary["db_aed_count_after"] = after_stats.get("aed_count")
            summary["db_access_hours_after"] = after_stats.get("access_hours_count")
            summary["db_emergency_room_count_before"] = before_stats.get(
                "emergency_room_count"
            )
            summary["db_emergency_room_count_after"] = after_stats.get(
                "emergency_room_count"
            )
            if "emergency_room" not in datasets and (
                before_stats.get("emergency_room_count")
                != after_stats.get("emergency_room_count")
            ):
                raise RuntimeError(
                    "Emergency-room count changed during the AED import"
                )
            if "aed" not in datasets and (
                before_stats.get("aed_count")
                != after_stats.get("aed_count")
            ):
                raise RuntimeError(
                    "AED count changed during the emergency-room import"
                )
            print("Supabase REST API import completed.")
    except RecordError as error:
        raise SystemExit(str(error)) from error
    except Exception as error:  # noqa: BLE001 - never print SDK details or secrets
        raise SystemExit(f"Supabase operation failed ({type(error).__name__}); details hidden") from None

    for key, value in summary.items():
        print(f"{key}: {value}")
    if summary["failed_count"]:
        print(f"Error log: {args.error_log}")
        raise SystemExit(f"{summary['failed_count']} records failed; inspect the error log")
    if summary.get("held_count"):
        raise SystemExit("Suspicious changes are pending administrator review; import is not complete")


if __name__ == "__main__":
    main()
