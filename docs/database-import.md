# Supabase REST API schema and data import

## Schema

- `public.facilities` stores common and source-specific scalar fields. `(facility_type, source_id)` is unique.
- `public.facility_access_hours` stores AED weekday schedules. The batch RPC replaces each facility's schedule in the same PostgreSQL transaction as its facility upsert.
- `public.upsert_facility_batch(jsonb)` is executable only by `service_role`. It makes each REST RPC batch atomic and idempotent.
- `public.get_aed_import_stats()` returns aggregate import-verification values and is executable only by `service_role`.
- Client roles receive public SELECT only. Keep `SUPABASE_SECRET_KEY` server-side; never bundle it in browser code.

The SQL Editor migration is [20261020130000_facilities_schema.sql](../supabase/migrations/20261020130000_facilities_schema.sql). Review the preflight and post-apply SQL in [database-schema.md](database-schema.md). Do not run the migration until the target project and existing objects have been checked and the proposed changes approved.

## Environment

Set these local values in `backend/.env`:

```dotenv
SUPABASE_URL=https://qjjllzqhljuivburjrqd.supabase.co
SUPABASE_SECRET_KEY=sb_secret_<server_only_key>
```

The key must be a current server-only Secret API Key. The REST importer does not use `DATABASE_URL` or a PostgreSQL password. The Supabase URL and key are loaded by `backend/scripts/supabase_rest.py`, which validates the project ref and never prints credentials.

Install dependencies from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

## Read-only API check and source validation

From `backend`:

```powershell
..\.venv\Scripts\python.exe scripts\check_supabase_api.py
..\.venv\Scripts\python.exe scripts\import_facilities.py --dry-run
```

The API check makes a read-only request. Dry-run reads the nationwide AED JSON, validates rows and reports duplicate source IDs without contacting Supabase.

## Apply schema using SQL Editor

After confirming the project ref and reviewing the preflight results, open the project's Supabase SQL Editor and paste the contents of the migration file. The migration is non-destructive but creates tables, indexes, a trigger, policies and two server-only RPC functions, and sets table grants. Wait for the user-approved SQL Editor application and run the post-apply checks before importing data.

## AED import (M3-4)

Guarded-import prerequisite: after review and separate approval, apply `20261021010000_facility_change_review.sql` after both existing migrations. The CLI now calls `stage_facility_batch` and distinguishes inserted, updated, held and unchanged records. A held candidate leaves published data intact and makes the command exit unsuccessfully until reviewed. Per-batch retry UUIDs preserve the original result after transport failures. Do not switch back to a direct UPSERT to bypass review; the historical RPC is also guarded after applying the migration. The new SQL has not been applied by this code change.

Only AED records are imported by default. Emergency medical records require an explicit `--medical-json` option and remain out of scope for this task.

```powershell
..\.venv\Scripts\python.exe scripts\import_facilities.py --batch-size 500
..\.venv\Scripts\python.exe scripts\verify_aed_import.py
```

The importer calls `upsert_facility_batch` via supabase-py. Each 500-record RPC is transactional for both parent facilities and AED hours. Retrying a batch is safe; failures are retried with backoff and recorded in `backend/import_errors.jsonl`. The importer records facility counts before and after and stops reporting success if the emergency-room count changed during the AED import. The verifier compares exact AED count, distinct source IDs, missing/out-of-range coordinates, schedule status totals and schedule-row count against the JSON source.

No import is complete unless every batch succeeds and verification passes. The original JSON files are read-only inputs and are not rewritten.
