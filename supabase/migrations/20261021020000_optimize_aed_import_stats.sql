-- Keep the get_aed_import_stats() contract while avoiding redundant AED scans.
-- Apply only after 20261020130000_facilities_schema.sql and its reviewed follow-up migrations.
BEGIN;

CREATE OR REPLACE FUNCTION public.get_aed_import_stats()
RETURNS jsonb
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $$
    WITH aed_rollup AS MATERIALIZED (
        SELECT
            coalesce(schedule_status, 'null') AS schedule_status,
            GROUPING(schedule_status) AS is_total,
            count(*) AS row_count,
            count(*) FILTER (
                WHERE latitude IS NULL OR longitude IS NULL
            ) AS missing_coordinate_count,
            count(*) FILTER (
                WHERE latitude NOT BETWEEN -90 AND 90
                   OR longitude NOT BETWEEN -180 AND 180
            ) AS out_of_range_coordinate_count
        FROM public.facilities
        WHERE facility_type = 'aed'
        GROUP BY GROUPING SETS ((schedule_status), ())
    ),
    aed_totals AS (
        SELECT
            row_count AS aed_count,
            row_count AS distinct_source_id_count,
            missing_coordinate_count,
            out_of_range_coordinate_count
        FROM aed_rollup
        WHERE is_total = 1
    ),
    schedule_counts AS (
        SELECT coalesce(
            jsonb_object_agg(schedule_status, row_count),
            '{}'::jsonb
        ) AS value
        FROM aed_rollup
        WHERE is_total = 0
    )
    SELECT jsonb_build_object(
        'emergency_room_count', (
            SELECT count(*)
            FROM public.facilities
            WHERE facility_type = 'emergency_room'
        ),
        'aed_count', aed_totals.aed_count,
        -- (facility_type, source_id) is unique, so this equals AED row count.
        'distinct_source_id_count', aed_totals.distinct_source_id_count,
        'missing_coordinate_count', aed_totals.missing_coordinate_count,
        'out_of_range_coordinate_count', aed_totals.out_of_range_coordinate_count,
        'access_hours_count', (
            SELECT count(*)
            FROM public.facility_access_hours h
            WHERE EXISTS (
                SELECT 1
                FROM public.facilities f
                WHERE f.id = h.facility_id
                  AND f.facility_type = 'aed'
            )
        ),
        'schedule_status_counts', schedule_counts.value
    )
    FROM aed_totals
    CROSS JOIN schedule_counts;
$$;

REVOKE ALL ON FUNCTION public.get_aed_import_stats() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_aed_import_stats() TO service_role;

COMMIT;
