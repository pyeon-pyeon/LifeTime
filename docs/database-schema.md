# Facilities database schema

## Source review

Historical local snapshots were documented as containing 63,473 AED records and 530 emergency-room records. Those nationwide files are excluded from Git and are absent in the current checkout; these numbers are not current database counts. Their shared normalized fields are `facility_type`, `source_id`, `name`, `address`, `latitude`, `longitude`, `source_updated_at`, `data_collected_at`, and `source_name`. AED records also contain `sido`, `gugun`, `installation_detail`, `contact_phone`, `schedule_status`, and `access_hours`. Emergency-room records contain `contact_phone` and `emergency_phone`. Missing values remain SQL NULL. See [field-mapping.md](field-mapping.md) for API-source mappings.

The `GET /api/facilities/nearby` envelope remains `{ "facilities": [], "count": 0 }` when no rows match. The follow-up migration `20261020140000_nearby_facilities.sql` supplies the read-only spatial RPC used by the backend. It returns distance in meters, filters by facility type, and does not persist the search origin. No walking duration is synthesized. Detail responses include the facility fields and `access_hours`. API timestamps are serialized with the Asia/Seoul offset; weekday access hours are local Seoul wall-clock times.

## Schema choices

- `public.facilities` holds common and source-specific scalar details. Facility identity is unique by `(facility_type, source_id)`.
- `public.facility_access_hours` stores one AED row per weekday, including start/end `time`, overnight-end flag, and 24-hour flag. `facilities.schedule_status` preserves `known`, `partial`, or `unknown`, including the case with no schedule rows.
- `public.upsert_facility_batch(jsonb)` performs each REST API import batch in one transaction, replacing the facility's schedule together with the parent UPSERT. `public.get_aed_import_stats()` returns aggregate counts for post-load validation. Both RPC functions are executable by `service_role` only.
- Latitude and longitude are WGS84 degrees. With PostGIS installed, a trigger creates `geography(Point, 4326)` using X=longitude and Y=latitude. Its GiST index supports meter-based `ST_DWithin` queries. If PostGIS is unavailable, the core table and scalar indexes remain usable, but the migration still requires PostGIS for the geography column; provisioning PostGIS is therefore a preflight requirement.
- No user location is stored. No real-time emergency-room capacity or availability is modeled.

## Access control

RLS is enabled for both tables. `anon` and `authenticated` receive SELECT only. `PUBLIC` and both client roles have all table privileges revoked before SELECT is granted. There are no client write policies. `service_role` receives server-side CRUD grants and must never be exposed to a browser. Administrative writes must go through the project's existing reviewed/approved server process; no admin API is added here.

## Preflight SQL

Run before applying the migration, after confirming the target Supabase project ref in the dashboard:

```sql
SELECT current_database(), current_user;
SELECT to_regclass('public.facilities'), to_regclass('public.facility_access_hours');
SELECT extname, extnamespace::regnamespace AS schema_name
FROM pg_extension WHERE extname = 'postgis';
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('facilities', 'facility_access_hours')
ORDER BY table_name, ordinal_position;

SELECT conrelid::regclass AS table_name, conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid IN (to_regclass('public.facilities'),
                   to_regclass('public.facility_access_hours'))
ORDER BY table_name, conname;

SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN ('facilities', 'facility_access_hours')
ORDER BY tablename, indexname;

SELECT schemaname, tablename, policyname, roles, cmd, qual, with_check
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename IN ('facilities', 'facility_access_hours');

SELECT tgrelid::regclass AS table_name, tgname, pg_get_triggerdef(oid)
FROM pg_trigger
WHERE tgrelid IN (to_regclass('public.facilities'),
                  to_regclass('public.facility_access_hours'))
  AND NOT tgisinternal;

SELECT grantee, table_name, privilege_type
FROM information_schema.role_table_grants
WHERE table_schema = 'public'
  AND table_name IN ('facilities', 'facility_access_hours')
ORDER BY table_name, grantee, privilege_type;

```

First run the object-existence query. If `public.facilities` exists, run this baseline count query and save the results to compare after applying the migration:

```sql
SELECT facility_type, count(*) AS row_count,
       count(DISTINCT source_id) AS distinct_source_ids
FROM public.facilities
GROUP BY facility_type ORDER BY facility_type;
```

If either target table exists, compare its columns, constraints, indexes, policies, triggers, and grants with this migration before proceeding. The migration aborts on incompatible existing columns, missing facility unique constraint, and conflicting same-named policy/trigger. Do not resolve a conflict by dropping a table.

## Post-apply verification SQL

```sql
SELECT tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public'
  AND tablename IN ('facilities', 'facility_access_hours');

SELECT conrelid::regclass AS table_name, conname, pg_get_constraintdef(oid)
FROM pg_constraint
WHERE conrelid IN ('public.facilities'::regclass,
                   'public.facility_access_hours'::regclass)
ORDER BY table_name, conname;

SELECT tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname = 'public'
  AND tablename IN ('facilities', 'facility_access_hours')
ORDER BY tablename, indexname;

SELECT schemaname, tablename, policyname, roles, cmd, qual, with_check
FROM pg_policies
WHERE schemaname = 'public'
  AND tablename IN ('facilities', 'facility_access_hours');

SELECT grantee, table_name, privilege_type
FROM information_schema.role_table_grants
WHERE table_schema = 'public'
  AND table_name IN ('facilities', 'facility_access_hours')
ORDER BY table_name, grantee, privilege_type;

SELECT facility_type, count(*) AS row_count,
       count(DISTINCT source_id) AS distinct_source_ids,
       count(*) FILTER (WHERE latitude IS NULL OR longitude IS NULL) AS missing_coordinates
FROM public.facilities
GROUP BY facility_type ORDER BY facility_type;

SELECT count(*) AS aed_access_hours_count
FROM public.facility_access_hours h
JOIN public.facilities f ON f.id = h.facility_id
WHERE f.facility_type = 'aed';

SELECT role_name,
       has_table_privilege(role_name, 'public.facilities', 'SELECT') AS can_select,
       has_table_privilege(role_name, 'public.facilities', 'INSERT') AS can_insert,
       has_table_privilege(role_name, 'public.facilities', 'UPDATE') AS can_update,
       has_table_privilege(role_name, 'public.facilities', 'DELETE') AS can_delete
FROM unnest(ARRAY['anon', 'authenticated', 'service_role']) AS role_name;
```

Verify that client roles have SELECT only, there are no client write policies, the composite unique constraint and coordinate checks exist, and `facilities_location_gist` exists when PostGIS is available.

## Failure and recovery

This migration does not drop either table or delete rows. It uses `CREATE ... IF NOT EXISTS` for tables/indexes, preserves existing same-named policies and triggers, and aborts when a table, trigger, or policy is recognized as incompatible. Inspect the SQL Editor error and database objects before retrying. Do not run a blanket rollback or drop command. If a later approved change needs rollback, prepare a separate reviewed migration that restores prior grants/policies while preserving facility data.

## SQL Editor application

This project applies the reviewed SQL through the Supabase Dashboard SQL Editor. First confirm the project ref, run the preflight queries above, and compare existing objects. Review the migration file and proposed effects with the user; do not apply until the user explicitly approves. Paste `supabase/migrations/20261020130000_facilities_schema.sql` into the SQL Editor, execute it once, then run the post-apply verification queries above. The migration is designed to avoid dropping tables, policies, or triggers. Existing same-named policies/triggers are preserved and a conflicting policy definition aborts the migration.
