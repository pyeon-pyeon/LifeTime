-- LifeTime public facility data. Apply only through a reviewed Supabase migration.
-- Existing objects are checked and reused; incompatible objects fail explicitly.
BEGIN;

CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA extensions;

DO $$
BEGIN
    IF to_regclass('public.facilities') IS NOT NULL
       AND EXISTS (
           SELECT 1
           FROM (VALUES
               ('id', 'uuid'), ('facility_type', 'text'), ('source_id', 'text'),
               ('name', 'text'), ('address', 'text'), ('sido', 'text'), ('gugun', 'text'),
               ('latitude', 'float8'), ('longitude', 'float8'),
               ('source_updated_at', 'timestamptz'), ('data_collected_at', 'timestamptz'),
               ('source_name', 'text'), ('contact_phone', 'text'),
               ('emergency_phone', 'text'), ('installation_detail', 'text'),
               ('schedule_status', 'text'), ('location', 'geography'),
               ('created_at', 'timestamptz'), ('updated_at', 'timestamptz')
           ) AS expected(column_name, udt_name)
           LEFT JOIN information_schema.columns actual
             ON actual.table_schema = 'public'
            AND actual.table_name = 'facilities'
            AND actual.column_name = expected.column_name
           WHERE actual.column_name IS NULL OR actual.udt_name <> expected.udt_name
       ) THEN
        RAISE EXCEPTION 'public.facilities exists with an incompatible schema';
    END IF;
    IF to_regclass('public.facilities') IS NOT NULL
       AND NOT EXISTS (
           SELECT 1 FROM pg_constraint
           WHERE conrelid = to_regclass('public.facilities')
             AND contype = 'u'
             AND pg_get_constraintdef(oid) = 'UNIQUE (facility_type, source_id)'
       ) THEN
        RAISE EXCEPTION 'public.facilities exists without the required unique constraint';
    END IF;
    IF to_regclass('public.facility_access_hours') IS NOT NULL
       AND EXISTS (
           SELECT 1
           FROM (VALUES
               ('facility_id', 'uuid'), ('weekday', 'int2'),
               ('opens_at', 'time'), ('closes_at', 'time'),
               ('ends_next_day', 'bool'), ('is_24_hours', 'bool')
           ) AS expected(column_name, udt_name)
           LEFT JOIN information_schema.columns actual
             ON actual.table_schema = 'public'
            AND actual.table_name = 'facility_access_hours'
            AND actual.column_name = expected.column_name
           WHERE actual.column_name IS NULL OR actual.udt_name <> expected.udt_name
       ) THEN
        RAISE EXCEPTION 'public.facility_access_hours exists with an incompatible schema';
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.facilities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    facility_type text NOT NULL,
    source_id text NOT NULL,
    name text,
    address text,
    sido text,
    gugun text,
    latitude double precision,
    longitude double precision,
    source_updated_at timestamptz,
    data_collected_at timestamptz,
    source_name text,
    contact_phone text,
    emergency_phone text,
    installation_detail text,
    schedule_status text,
    location extensions.geography(Point, 4326),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT facilities_type_check
        CHECK (facility_type IN ('aed', 'emergency_room')),
    CONSTRAINT facilities_latitude_check
        CHECK (latitude IS NULL OR latitude BETWEEN -90 AND 90),
    CONSTRAINT facilities_longitude_check
        CHECK (longitude IS NULL OR longitude BETWEEN -180 AND 180),
    CONSTRAINT facilities_schedule_status_check
        CHECK (schedule_status IS NULL OR schedule_status IN ('known', 'partial', 'unknown')),
    CONSTRAINT facilities_type_source_id_unique UNIQUE (facility_type, source_id)
);

CREATE TABLE IF NOT EXISTS public.facility_access_hours (
    facility_id uuid NOT NULL REFERENCES public.facilities(id) ON DELETE CASCADE,
    weekday smallint NOT NULL CHECK (weekday BETWEEN 1 AND 7),
    opens_at time NOT NULL,
    closes_at time NOT NULL,
    ends_next_day boolean NOT NULL DEFAULT false,
    is_24_hours boolean NOT NULL DEFAULT false,
    PRIMARY KEY (facility_id, weekday),
    CONSTRAINT facility_access_hours_24h_check CHECK (
        NOT is_24_hours OR (
            opens_at = TIME '00:00' AND closes_at = TIME '00:00'
            AND ends_next_day
        )
    )
);

CREATE INDEX IF NOT EXISTS facilities_type_idx
    ON public.facilities (facility_type);
-- The unique constraint already supplies a btree index on (facility_type, source_id).
CREATE INDEX IF NOT EXISTS facilities_source_id_idx
    ON public.facilities (source_id);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_extension WHERE extname = 'postgis'
    ) THEN
        EXECUTE 'CREATE INDEX IF NOT EXISTS facilities_location_gist '
             || 'ON public.facilities USING gist (location) WHERE location IS NOT NULL';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.set_facility_location_and_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
    IF NEW.latitude IS NULL OR NEW.longitude IS NULL THEN
        NEW.location := NULL;
    ELSE
        NEW.location := extensions.ST_SetSRID(
            extensions.ST_MakePoint(NEW.longitude, NEW.latitude), 4326
        )::extensions.geography;
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgrelid = 'public.facilities'::regclass
          AND tgname = 'facilities_location_updated_at_trigger'
          AND NOT tgisinternal
          AND (
              tgfoid <> 'public.set_facility_location_and_updated_at()'::regprocedure
              OR tgtype <> 23
          )
    ) THEN
        RAISE EXCEPTION 'facilities_location_updated_at_trigger exists with a different function';
    ELSIF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgrelid = 'public.facilities'::regclass
          AND tgname = 'facilities_location_updated_at_trigger'
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER facilities_location_updated_at_trigger
            BEFORE INSERT OR UPDATE ON public.facilities
            FOR EACH ROW EXECUTE FUNCTION public.set_facility_location_and_updated_at();
    END IF;
END;
$$;

ALTER TABLE public.facilities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.facility_access_hours ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'facilities'
          AND policyname = 'facilities_public_read'
          AND (cmd <> 'SELECT' OR roles <> ARRAY['anon', 'authenticated']::name[]
               OR qual <> 'true' OR with_check IS NOT NULL)
    ) THEN
        RAISE EXCEPTION 'facilities_public_read exists with an incompatible definition';
    ELSIF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname = 'public'
          AND tablename = 'facilities' AND policyname = 'facilities_public_read'
    ) THEN
        CREATE POLICY facilities_public_read ON public.facilities
            FOR SELECT TO anon, authenticated USING (true);
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public' AND tablename = 'facility_access_hours'
          AND policyname = 'facility_access_hours_public_read'
          AND (cmd <> 'SELECT' OR roles <> ARRAY['anon', 'authenticated']::name[]
               OR qual <> 'true' OR with_check IS NOT NULL)
    ) THEN
        RAISE EXCEPTION 'facility_access_hours_public_read exists with an incompatible definition';
    ELSIF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE schemaname = 'public'
          AND tablename = 'facility_access_hours'
          AND policyname = 'facility_access_hours_public_read'
    ) THEN
        CREATE POLICY facility_access_hours_public_read ON public.facility_access_hours
            FOR SELECT TO anon, authenticated USING (true);
    END IF;
END;
$$;

REVOKE ALL ON TABLE public.facilities FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.facility_access_hours FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE public.facilities TO anon, authenticated;
GRANT SELECT ON TABLE public.facility_access_hours TO anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.facilities TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.facility_access_hours TO service_role;

-- Atomic per-batch REST import: facilities and AED schedules commit together.
CREATE OR REPLACE FUNCTION public.upsert_facility_batch(p_records jsonb)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
    rec record;
    hour_rec record;
    facility_uuid uuid;
    processed integer := 0;
BEGIN
    IF jsonb_typeof(p_records) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'p_records must be a JSON array';
    END IF;

    FOR rec IN
        SELECT * FROM jsonb_to_recordset(p_records) AS x(
            facility_type text, source_id text, name text, address text,
            latitude double precision, longitude double precision,
            source_updated_at timestamptz, data_collected_at timestamptz,
            source_name text, contact_phone text, emergency_phone text,
            installation_detail text, schedule_status text, sido text,
            gugun text, access_hours jsonb
        )
    LOOP
        INSERT INTO public.facilities (
            facility_type, source_id, name, address, latitude, longitude,
            source_updated_at, data_collected_at, source_name, contact_phone,
            emergency_phone, installation_detail, schedule_status, sido, gugun
        ) VALUES (
            rec.facility_type, rec.source_id, rec.name, rec.address,
            rec.latitude, rec.longitude, rec.source_updated_at,
            rec.data_collected_at, rec.source_name, rec.contact_phone,
            rec.emergency_phone, rec.installation_detail, rec.schedule_status,
            rec.sido, rec.gugun
        )
        ON CONFLICT (facility_type, source_id) DO UPDATE SET
            name = EXCLUDED.name,
            address = EXCLUDED.address,
            latitude = EXCLUDED.latitude,
            longitude = EXCLUDED.longitude,
            source_updated_at = EXCLUDED.source_updated_at,
            data_collected_at = EXCLUDED.data_collected_at,
            source_name = EXCLUDED.source_name,
            contact_phone = EXCLUDED.contact_phone,
            emergency_phone = EXCLUDED.emergency_phone,
            installation_detail = EXCLUDED.installation_detail,
            schedule_status = EXCLUDED.schedule_status,
            sido = EXCLUDED.sido,
            gugun = EXCLUDED.gugun
        RETURNING id INTO facility_uuid;

        DELETE FROM public.facility_access_hours
        WHERE facility_id = facility_uuid;

        IF rec.facility_type = 'aed' AND rec.access_hours IS NOT NULL THEN
            IF jsonb_typeof(rec.access_hours) IS DISTINCT FROM 'array' THEN
                RAISE EXCEPTION 'access_hours must be a JSON array';
            END IF;
            FOR hour_rec IN
                SELECT * FROM jsonb_to_recordset(rec.access_hours) AS h(
                    weekday smallint, opens_at time, closes_at time,
                    ends_next_day boolean, is_24_hours boolean
                )
            LOOP
                INSERT INTO public.facility_access_hours (
                    facility_id, weekday, opens_at, closes_at,
                    ends_next_day, is_24_hours
                ) VALUES (
                    facility_uuid, hour_rec.weekday, hour_rec.opens_at,
                    hour_rec.closes_at, hour_rec.ends_next_day, hour_rec.is_24_hours
                );
            END LOOP;
        END IF;
        processed := processed + 1;
    END LOOP;
    RETURN processed;
END;
$$;

REVOKE ALL ON FUNCTION public.upsert_facility_batch(jsonb) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.upsert_facility_batch(jsonb) TO service_role;

CREATE OR REPLACE FUNCTION public.get_aed_import_stats()
RETURNS jsonb
LANGUAGE sql
SECURITY DEFINER
SET search_path = ''
AS $$
    SELECT jsonb_build_object(
        'emergency_room_count', (
            SELECT count(*) FROM public.facilities
            WHERE facility_type = 'emergency_room'
        ),
        'aed_count', count(*),
        'distinct_source_id_count', count(DISTINCT source_id),
        'missing_coordinate_count', count(*) FILTER (
            WHERE latitude IS NULL OR longitude IS NULL
        ),
        'out_of_range_coordinate_count', count(*) FILTER (
            WHERE latitude NOT BETWEEN -90 AND 90
               OR longitude NOT BETWEEN -180 AND 180
        ),
        'access_hours_count', (
            SELECT count(*) FROM public.facility_access_hours h
            JOIN public.facilities f ON f.id = h.facility_id
            WHERE f.facility_type = 'aed'
        ),
        'schedule_status_counts', (
            SELECT coalesce(jsonb_object_agg(schedule_status, amount), '{}'::jsonb)
            FROM (
                SELECT coalesce(schedule_status, 'null') AS schedule_status,
                       count(*) AS amount
                FROM public.facilities WHERE facility_type = 'aed'
                GROUP BY schedule_status
            ) status_counts
        )
    )
    FROM public.facilities
    WHERE facility_type = 'aed';
$$;

REVOKE ALL ON FUNCTION public.get_aed_import_stats() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_aed_import_stats() TO service_role;

-- Supabase SQL Editor preflight (run before applying):
-- SELECT to_regclass('public.facilities'), to_regclass('public.facility_access_hours');
-- SELECT extname FROM pg_extension WHERE extname = 'postgis';
-- SELECT grantee, table_name, privilege_type FROM information_schema.role_table_grants
-- WHERE table_schema = 'public' AND table_name IN ('facilities', 'facility_access_hours');

-- Post-apply checks are documented in docs/database-schema.md.
COMMIT;
