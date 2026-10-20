-- Read-only. Run after both migrations. Record actual results, not expected counts.
SELECT tablename, rowsecurity FROM pg_tables
WHERE schemaname = 'public' AND tablename IN ('facilities', 'facility_access_hours');

SELECT COUNT(*) AS aed_count FROM public.facilities WHERE facility_type = 'aed';

SELECT facility_type, count(*) AS total_count,
    count(*) FILTER (WHERE latitude IS NULL) AS missing_latitude,
    count(*) FILTER (WHERE longitude IS NULL) AS missing_longitude,
    count(*) FILTER (WHERE NOT (latitude BETWEEN -90 AND 90)
        OR NOT (longitude BETWEEN -180 AND 180)) AS invalid_coordinates,
    count(*) FILTER (WHERE latitude IS NOT NULL AND longitude IS NOT NULL
        AND NOT (latitude BETWEEN 32 AND 39.5 AND longitude BETWEEN 124 AND 132)) AS korea_bounds_review
FROM public.facilities GROUP BY facility_type;

SELECT facility_type, source_id, count(*) FROM public.facilities
GROUP BY facility_type, source_id HAVING count(*) > 1;

SELECT id, facility_type, source_id, name, address, latitude, longitude, source_name,
    source_updated_at AT TIME ZONE 'Asia/Seoul' AS source_updated_seoul,
    data_collected_at AT TIME ZONE 'Asia/Seoul' AS collected_seoul
FROM public.facilities ORDER BY facility_type, source_id LIMIT 10;

SELECT role_name, table_name,
    has_table_privilege(role_name, 'public.' || table_name, 'SELECT') AS can_select,
    has_table_privilege(role_name, 'public.' || table_name, 'INSERT') AS can_insert,
    has_table_privilege(role_name, 'public.' || table_name, 'UPDATE') AS can_update,
    has_table_privilege(role_name, 'public.' || table_name, 'DELETE') AS can_delete
FROM unnest(ARRAY['anon','authenticated','service_role']) AS role_name
CROSS JOIN unnest(ARRAY['facilities','facility_access_hours']) AS table_name;

SELECT * FROM public.nearby_facilities(37.5665, 126.9780, 'aed', 3000);

SELECT conrelid::regclass AS table_name, conname, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid IN (to_regclass('public.facilities'), to_regclass('public.facility_access_hours'))
ORDER BY table_name, conname;

SELECT tablename, indexname, indexdef FROM pg_indexes
WHERE schemaname = 'public' AND tablename IN ('facilities', 'facility_access_hours');

SELECT tablename, policyname, roles, cmd, qual, with_check FROM pg_policies
WHERE schemaname = 'public' AND tablename IN ('facilities', 'facility_access_hours');

SELECT tgrelid::regclass AS table_name, tgname, pg_get_triggerdef(oid) AS definition
FROM pg_trigger
WHERE tgrelid IN (to_regclass('public.facilities'), to_regclass('public.facility_access_hours'))
  AND NOT tgisinternal;

SELECT p.oid::regprocedure AS function_signature, p.prosecdef AS security_definer,
       role_name, has_function_privilege(role_name, p.oid, 'EXECUTE') AS can_execute
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
CROSS JOIN unnest(ARRAY['anon','authenticated','service_role']) AS role_name
WHERE n.nspname = 'public' AND p.proname IN (
    'upsert_facility_batch', 'get_aed_import_stats', 'nearby_facilities'
)
ORDER BY function_signature, role_name;

SELECT count(*) AS access_hours_total FROM public.facility_access_hours;
SELECT count(*) AS coordinate_location_mismatches
FROM public.facilities
WHERE (latitude IS NOT NULL AND longitude IS NOT NULL AND location IS NULL)
   OR ((latitude IS NULL OR longitude IS NULL) AND location IS NOT NULL)
   OR (location IS NOT NULL AND (
       extensions.ST_X(location::extensions.geometry) IS DISTINCT FROM longitude
       OR extensions.ST_Y(location::extensions.geometry) IS DISTINCT FROM latitude
   ));
