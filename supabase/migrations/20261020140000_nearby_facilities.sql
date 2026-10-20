-- Apply after 20261020130000_facilities_schema.sql. No location history is stored.
BEGIN;
CREATE OR REPLACE FUNCTION public.nearby_facilities(
    p_latitude double precision,
    p_longitude double precision,
    p_facility_type text DEFAULT NULL,
    p_radius_m integer DEFAULT 3000
)
-- A single JSON array avoids PostgREST's row cap silently truncating count.
RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY INVOKER
SET search_path = ''
AS $$
DECLARE
    origin extensions.geography;
BEGIN
    IF p_latitude IS NULL OR NOT (p_latitude BETWEEN -90 AND 90)
       OR p_longitude IS NULL OR NOT (p_longitude BETWEEN -180 AND 180)
       OR p_radius_m IS NULL OR p_radius_m NOT BETWEEN 1 AND 20000
       OR (p_facility_type IS NOT NULL AND p_facility_type NOT IN ('aed', 'emergency_room')) THEN
        RAISE EXCEPTION 'Invalid facility search parameters';
    END IF;
    origin := extensions.ST_SetSRID(extensions.ST_MakePoint(p_longitude, p_latitude), 4326)::extensions.geography;
    RETURN (
        SELECT coalesce(jsonb_agg(item ORDER BY distance, id), '[]'::jsonb)
        FROM (
            SELECT (to_jsonb(f) - 'location') || jsonb_build_object(
                'distance_m', extensions.ST_Distance(f.location, origin)
            ) AS item, extensions.ST_Distance(f.location, origin) AS distance, f.id
            FROM public.facilities f
            WHERE f.location IS NOT NULL
              AND (p_facility_type IS NULL OR f.facility_type = p_facility_type)
              AND extensions.ST_DWithin(f.location, origin, p_radius_m)
        ) matches
    );
END;
$$;
REVOKE ALL ON FUNCTION public.nearby_facilities(double precision, double precision, text, integer)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.nearby_facilities(double precision, double precision, text, integer)
    TO service_role;
COMMIT;
