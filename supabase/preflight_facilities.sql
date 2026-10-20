-- Read-only catalog inspection. Safe even when the target tables are absent.
-- First confirm Dashboard project ref against the locally configured project.
SELECT current_database(), current_user;
SELECT to_regclass('public.facilities') AS facilities,
       to_regclass('public.facility_access_hours') AS facility_access_hours;
SELECT extname, extnamespace::regnamespace AS installed_schema
FROM pg_extension WHERE extname = 'postgis';

SELECT table_name, column_name, udt_schema, udt_name, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name IN ('facilities', 'facility_access_hours')
ORDER BY table_name, ordinal_position;

SELECT conrelid::regclass AS table_name, conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid IN (to_regclass('public.facilities'), to_regclass('public.facility_access_hours'))
ORDER BY table_name, conname;

SELECT tablename, indexname, indexdef FROM pg_indexes
WHERE schemaname = 'public' AND tablename IN ('facilities', 'facility_access_hours')
ORDER BY tablename, indexname;

SELECT tablename, policyname, roles, cmd, qual, with_check FROM pg_policies
WHERE schemaname = 'public' AND tablename IN ('facilities', 'facility_access_hours');

SELECT tgrelid::regclass AS table_name, tgname, pg_get_triggerdef(oid) AS definition
FROM pg_trigger
WHERE tgrelid IN (to_regclass('public.facilities'), to_regclass('public.facility_access_hours'))
  AND NOT tgisinternal;

SELECT grantee, table_name, privilege_type FROM information_schema.role_table_grants
WHERE table_schema = 'public' AND table_name IN ('facilities', 'facility_access_hours')
ORDER BY table_name, grantee, privilege_type;

-- Existing same-named functions are replaced by the migrations. Review before applying.
SELECT p.oid::regprocedure AS function_signature, p.prosecdef AS security_definer,
       pg_get_function_result(p.oid) AS result_type, p.proacl,
       pg_get_functiondef(p.oid) AS definition
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public' AND p.proname IN (
    'set_facility_location_and_updated_at', 'upsert_facility_batch',
    'get_aed_import_stats', 'nearby_facilities'
);

-- If facilities EXISTS and its columns match, separately save these baseline counts:
-- SELECT facility_type, count(*) FROM public.facilities GROUP BY facility_type;
-- SELECT count(*) FROM public.facility_access_hours;
