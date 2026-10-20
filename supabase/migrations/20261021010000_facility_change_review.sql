-- Additive review/audit storage. Apply only after explicit approval, after both prior migrations.
-- No test data is inserted. The former importer is reused privately, not duplicated.
BEGIN;
CREATE SCHEMA IF NOT EXISTS lifetime_private;
REVOKE ALL ON SCHEMA lifetime_private FROM PUBLIC, anon, authenticated, service_role;

-- Version stamps must change even for writes in the same transaction.
CREATE OR REPLACE FUNCTION public.set_facility_location_and_updated_at()
RETURNS trigger LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    NEW.location := CASE WHEN NEW.latitude IS NULL OR NEW.longitude IS NULL THEN NULL
        ELSE extensions.ST_SetSRID(extensions.ST_MakePoint(NEW.longitude, NEW.latitude),4326)::extensions.geography END;
    NEW.updated_at := CASE WHEN TG_OP='UPDATE' THEN greatest(clock_timestamp(), OLD.updated_at + INTERVAL '1 microsecond')
                          ELSE clock_timestamp() END;
    RETURN NEW;
END;
$$;

CREATE TABLE IF NOT EXISTS public.facility_change_settings (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    movement_review_m double precision NOT NULL DEFAULT 500 CHECK (movement_review_m > 0 AND movement_review_m < 1000000)
);
-- 500m is an initial review threshold, not a confirmed operating policy.
INSERT INTO public.facility_change_settings(singleton) VALUES (true) ON CONFLICT DO NOTHING;

CREATE TABLE IF NOT EXISTS public.facility_change_requests (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id uuid UNIQUE NOT NULL,
    facility_id uuid NOT NULL REFERENCES public.facilities(id),
    before_data jsonb,
    after_data jsonb NOT NULL,
    base_updated_at timestamptz,
    applied_updated_at timestamptz,
    reasons text[] NOT NULL,
    status text NOT NULL CHECK (status IN ('pending','applied','approved','rejected','restored','unchanged')),
    submitted_by uuid,
    reviewed_by uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    reviewed_at timestamptz
);
CREATE INDEX IF NOT EXISTS facility_changes_facility_idx ON public.facility_change_requests(facility_id, created_at DESC);
CREATE TABLE IF NOT EXISTS public.facility_change_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    change_id uuid NOT NULL REFERENCES public.facility_change_requests(id),
    request_id uuid UNIQUE NOT NULL,
    action text NOT NULL CHECK (action IN ('proposed','applied','approve','reject','restore')),
    actor_id uuid,
    reason text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.facility_import_batches (
    request_id uuid PRIMARY KEY,
    records jsonb NOT NULL,
    result jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.facility_change_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.facility_change_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.facility_change_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.facility_import_batches ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.facility_change_settings, public.facility_change_requests, public.facility_change_events, public.facility_import_batches
    FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON public.facility_change_settings, public.facility_change_requests, public.facility_change_events, public.facility_import_batches TO service_role;
-- Only trusted reviewed server configuration can change the threshold.
GRANT UPDATE ON public.facility_change_settings TO service_role;

-- Move the original atomic UPSERT behind the review layer. A rerun never moves the wrapper.
DO $$ BEGIN
    IF to_regprocedure('lifetime_private.upsert_facility_batch(jsonb)') IS NULL THEN
        ALTER FUNCTION public.upsert_facility_batch(jsonb) SET SCHEMA lifetime_private;
    ELSIF to_regprocedure('public.upsert_facility_batch(jsonb)') IS NULL
       OR position('public.stage_facility_batch(p_records)' IN pg_get_functiondef(to_regprocedure('public.upsert_facility_batch(jsonb)')))=0 THEN
        RAISE EXCEPTION 'Existing private importer conflicts with the review migration';
    END IF;
END $$;
REVOKE ALL ON FUNCTION lifetime_private.upsert_facility_batch(jsonb) FROM PUBLIC, anon, authenticated, service_role;

CREATE OR REPLACE FUNCTION lifetime_private.normalize_facility(p_record jsonb)
RETURNS jsonb LANGUAGE sql SET search_path = '' AS $$
    SELECT to_jsonb(x) - 'access_hours' || jsonb_build_object('access_hours', (
        SELECT coalesce(jsonb_agg(to_jsonb(h) ORDER BY weekday), '[]'::jsonb)
        FROM jsonb_to_recordset(coalesce(nullif(x.access_hours, 'null'::jsonb), '[]'::jsonb)) AS h(
            weekday smallint, opens_at time, closes_at time, ends_next_day boolean, is_24_hours boolean)
    ))
    FROM jsonb_to_record(p_record) AS x(
        facility_type text, source_id text, name text, address text, latitude double precision,
        longitude double precision, source_updated_at timestamptz, data_collected_at timestamptz,
        source_name text, contact_phone text, emergency_phone text, installation_detail text,
        schedule_status text, sido text, gugun text, access_hours jsonb
    );
$$;

CREATE OR REPLACE FUNCTION lifetime_private.facility_snapshot(p_id uuid)
RETURNS jsonb LANGUAGE sql STABLE SET search_path = '' AS $$
    SELECT lifetime_private.normalize_facility(to_jsonb(f) || jsonb_build_object('access_hours', (
        SELECT coalesce(jsonb_agg(to_jsonb(h) ORDER BY weekday), '[]'::jsonb)
        FROM public.facility_access_hours h WHERE h.facility_id=f.id
    ))) FROM public.facilities f WHERE f.id=p_id;
$$;

CREATE OR REPLACE FUNCTION lifetime_private.invalid_facility(p_record jsonb)
RETURNS boolean LANGUAGE plpgsql SET search_path = '' AS $$
DECLARE h record; seen smallint[] := '{}'; amount integer := 0; st text;
BEGIN
    IF p_record->>'facility_type' IS NULL OR p_record->>'facility_type' NOT IN ('aed','emergency_room')
       OR coalesce(trim(p_record->>'source_id'),'')='' THEN RETURN true; END IF;
    IF (p_record->>'latitude' IS NOT NULL AND NOT ((p_record->>'latitude')::float8 BETWEEN -90 AND 90))
       OR (p_record->>'longitude' IS NOT NULL AND NOT ((p_record->>'longitude')::float8 BETWEEN -180 AND 180)) THEN RETURN true; END IF;
    FOR h IN SELECT * FROM jsonb_to_recordset(p_record->'access_hours') AS x(
        weekday smallint, opens_at time, closes_at time, ends_next_day boolean, is_24_hours boolean)
    LOOP
        IF h.weekday IS NULL OR h.weekday NOT BETWEEN 1 AND 7 OR h.weekday=ANY(seen)
           OR h.opens_at IS NULL OR h.closes_at IS NULL OR h.ends_next_day IS NULL OR h.is_24_hours IS NULL
           OR h.opens_at=TIME '24:00' OR h.closes_at=TIME '24:00' THEN RETURN true; END IF;
        IF h.is_24_hours THEN
            IF NOT (h.opens_at=TIME '00:00' AND h.closes_at=TIME '00:00' AND h.ends_next_day) THEN RETURN true; END IF;
        ELSIF (h.ends_next_day AND h.closes_at >= h.opens_at)
              OR (NOT h.ends_next_day AND h.closes_at <= h.opens_at) THEN RETURN true;
        END IF;
        seen := array_append(seen,h.weekday); amount := amount+1;
    END LOOP;
    st := p_record->>'schedule_status';
    RETURN coalesce((st IS NOT NULL AND st NOT IN ('known','partial','unknown'))
       OR (st='known' AND amount<>7) OR (st='partial' AND amount NOT BETWEEN 1 AND 6)
       OR (st='unknown' AND amount<>0) OR (p_record->>'facility_type'='emergency_room' AND amount<>0),false);
END;
$$;

CREATE OR REPLACE FUNCTION lifetime_private.change_reasons(p_before jsonb, p_after jsonb)
RETURNS text[] LANGUAGE plpgsql SET search_path = '' AS $$
DECLARE reasons text[] := '{}'; field text; threshold float8;
BEGIN
    IF lifetime_private.invalid_facility(p_after) THEN reasons := array_append(reasons,'invalid_record'); END IF;
    IF p_before IS NULL THEN RETURN reasons; END IF;
    FOREACH field IN ARRAY ARRAY['name','address','latitude','longitude'] LOOP
        IF p_before->>field IS NOT NULL AND p_after->>field IS NULL THEN reasons := array_append(reasons,'missing_'||field); END IF;
    END LOOP;
    IF p_before->>'latitude' IS NOT NULL AND p_before->>'longitude' IS NOT NULL
       AND p_after->>'latitude' IS NOT NULL AND p_after->>'longitude' IS NOT NULL
       AND NOT lifetime_private.invalid_facility(p_after) THEN
        SELECT movement_review_m INTO STRICT threshold FROM public.facility_change_settings WHERE singleton;
        IF extensions.ST_DistanceSphere(
            extensions.ST_SetSRID(extensions.ST_MakePoint((p_before->>'longitude')::float8,(p_before->>'latitude')::float8),4326),
            extensions.ST_SetSRID(extensions.ST_MakePoint((p_after->>'longitude')::float8,(p_after->>'latitude')::float8),4326)
        ) > threshold THEN reasons := array_append(reasons,'coordinate_movement'); END IF;
    END IF;
    IF p_before->>'address' IS NOT NULL AND p_before->>'address' IS DISTINCT FROM p_after->>'address' THEN reasons := array_append(reasons,'address_changed'); END IF;
    IF jsonb_array_length(p_before->'access_hours')>0 AND (
        p_before->'access_hours' IS DISTINCT FROM p_after->'access_hours'
        OR p_before->>'schedule_status' IS DISTINCT FROM p_after->>'schedule_status'
    ) THEN reasons := array_append(reasons,'hours_changed'); END IF;
    RETURN reasons;
END;
$$;

CREATE OR REPLACE FUNCTION lifetime_private.require_admin(p_actor uuid)
RETURNS void LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM auth.users WHERE id=p_actor AND raw_app_meta_data->>'role'='admin') THEN
        RAISE EXCEPTION 'Administrator required' USING ERRCODE='42501';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION lifetime_private.stage_change(p_record jsonb, p_request uuid, p_actor uuid DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SET search_path = '' AS $$
DECLARE rec jsonb; old jsonb; fid uuid; stamp timestamptz; reasons text[]; change_row public.facility_change_requests;
        previous public.facility_change_requests; state text; action text;
BEGIN
    rec := lifetime_private.normalize_facility(p_record);
    IF rec->>'facility_type' IS NULL OR rec->>'source_id' IS NULL THEN RAISE EXCEPTION 'Invalid identity' USING ERRCODE='22023'; END IF;
    -- Serializes imports/administrator submissions even before a facility exists.
    PERFORM pg_advisory_xact_lock(hashtextextended((rec->>'facility_type')||':'||(rec->>'source_id'),0));
    SELECT * INTO previous FROM public.facility_change_requests WHERE request_id=p_request;
    IF FOUND THEN
        IF previous.after_data IS DISTINCT FROM rec OR previous.submitted_by IS DISTINCT FROM p_actor THEN
            RAISE EXCEPTION 'Idempotency key reused' USING ERRCODE='40001'; END IF;
        RETURN jsonb_build_object('id',previous.id,'status',previous.status,'reasons',previous.reasons,'outcome','unchanged');
    END IF;
    SELECT id,updated_at INTO fid,stamp FROM public.facilities
        WHERE facility_type=rec->>'facility_type' AND source_id=rec->>'source_id' FOR UPDATE;
    PERFORM 1 FROM public.facility_access_hours WHERE facility_id=fid FOR UPDATE;
    old := lifetime_private.facility_snapshot(fid);
    IF old IS NOT DISTINCT FROM rec THEN
        IF p_actor IS NULL THEN RETURN jsonb_build_object('status','unchanged','outcome','unchanged'); END IF;
        INSERT INTO public.facility_change_requests(request_id,facility_id,before_data,after_data,base_updated_at,reasons,status,submitted_by)
            VALUES(p_request,fid,old,rec,stamp,'{}','unchanged',p_actor) RETURNING * INTO change_row;
        INSERT INTO public.facility_change_events(change_id,request_id,action,actor_id)
            VALUES(change_row.id,p_request,'proposed',p_actor);
        RETURN jsonb_build_object('id',change_row.id,'status','unchanged','reasons','[]'::jsonb,'outcome','unchanged');
    END IF;
    reasons := lifetime_private.change_reasons(old,rec);
    IF fid IS NULL AND cardinality(reasons)>0 THEN RAISE EXCEPTION 'Invalid new facility' USING ERRCODE='22023'; END IF;
    IF fid IS NOT NULL AND p_actor IS NULL THEN
        SELECT * INTO previous FROM public.facility_change_requests
        WHERE facility_id=fid AND status='pending' AND after_data=rec AND base_updated_at=stamp ORDER BY created_at LIMIT 1;
        IF FOUND THEN RETURN jsonb_build_object('id',previous.id,'status','pending','reasons',previous.reasons,'outcome','held'); END IF;
    END IF;
    state := CASE WHEN cardinality(reasons)>0 THEN 'pending' ELSE 'applied' END;
    action := CASE WHEN fid IS NULL THEN 'inserted' WHEN state='pending' THEN 'held' ELSE 'updated' END;
    IF state='applied' THEN
        PERFORM lifetime_private.upsert_facility_batch(jsonb_build_array(rec));
        SELECT id INTO fid FROM public.facilities WHERE facility_type=rec->>'facility_type' AND source_id=rec->>'source_id';
    END IF;
    INSERT INTO public.facility_change_requests(request_id,facility_id,before_data,after_data,base_updated_at,
        applied_updated_at,reasons,status,submitted_by)
    VALUES(p_request,fid,old,rec,stamp,CASE WHEN state='applied' THEN (SELECT updated_at FROM public.facilities WHERE id=fid) END,
           reasons,state,p_actor) RETURNING * INTO change_row;
    INSERT INTO public.facility_change_events(change_id,request_id,action,actor_id)
        VALUES(change_row.id,p_request,'proposed',p_actor);
    IF state='applied' THEN
        INSERT INTO public.facility_change_events(change_id,request_id,action,actor_id)
            VALUES(change_row.id,gen_random_uuid(),'applied',p_actor);
    END IF;
    RETURN jsonb_build_object('id',change_row.id,'status',state,'reasons',reasons,'outcome',action);
END;
$$;

CREATE OR REPLACE FUNCTION public.stage_facility_batch(p_records jsonb,p_request_id uuid DEFAULT NULL)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE rec jsonb; result jsonb; counts jsonb := '{"inserted":0,"updated":0,"held":0,"unchanged":0}'::jsonb; key text;
        previous public.facility_import_batches;
BEGIN
    IF jsonb_typeof(p_records) IS DISTINCT FROM 'array' OR jsonb_array_length(p_records)>1000 THEN
        RAISE EXCEPTION 'Invalid batch' USING ERRCODE='22023'; END IF;
    IF p_request_id IS NOT NULL THEN
        PERFORM pg_advisory_xact_lock(hashtextextended('batch:'||p_request_id::text,0));
        SELECT * INTO previous FROM public.facility_import_batches WHERE request_id=p_request_id;
        IF FOUND THEN
            IF previous.records IS DISTINCT FROM p_records THEN RAISE EXCEPTION 'Batch identity conflict' USING ERRCODE='40001'; END IF;
            RETURN previous.result;
        END IF;
    END IF;
    -- Stable ordering prevents two overlapping batches locking facilities in reverse order.
    FOR rec IN SELECT value FROM jsonb_array_elements(p_records)
        ORDER BY value->>'facility_type',value->>'source_id' LOOP
        result := lifetime_private.stage_change(rec,gen_random_uuid()); key := result->>'outcome';
        counts := jsonb_set(counts,ARRAY[key],to_jsonb((counts->>key)::integer+1));
    END LOOP;
    IF p_request_id IS NOT NULL THEN
        INSERT INTO public.facility_import_batches(request_id,records,result) VALUES(p_request_id,p_records,counts);
    END IF;
    RETURN counts;
END;
$$;

-- Retain the historical integer-returning entry point, now through the same guard.
CREATE OR REPLACE FUNCTION public.upsert_facility_batch(p_records jsonb)
RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    PERFORM public.stage_facility_batch(p_records);
    RETURN jsonb_array_length(p_records);
END;
$$;

CREATE OR REPLACE FUNCTION public.propose_facility_change(p_facility_id uuid,p_record jsonb,p_request_id uuid,p_actor_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE fid uuid;
BEGIN
    PERFORM lifetime_private.require_admin(p_actor_id);
    SELECT id INTO fid FROM public.facilities WHERE id=p_facility_id
      AND facility_type=p_record->>'facility_type' AND source_id=p_record->>'source_id';
    IF fid IS NULL THEN RAISE EXCEPTION 'Facility not found' USING ERRCODE='P0002'; END IF;
    RETURN lifetime_private.stage_change(p_record,p_request_id,p_actor_id);
END;
$$;

CREATE OR REPLACE FUNCTION public.decide_facility_change(p_change_id uuid,p_action text,p_request_id uuid,p_actor_id uuid,p_reason text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE change_row public.facility_change_requests; evt public.facility_change_events; stamp timestamptz; fid uuid; target jsonb; state text;
BEGIN
    PERFORM lifetime_private.require_admin(p_actor_id);
    IF p_action NOT IN ('approve','reject','restore') OR p_action IS NULL OR coalesce(length(trim(p_reason)),0) NOT BETWEEN 1 AND 500 THEN
        RAISE EXCEPTION 'Invalid decision' USING ERRCODE='22023'; END IF;
    -- Always facility then change: same order as stage_change and competing decisions.
    SELECT facility_id INTO fid FROM public.facility_change_requests WHERE id=p_change_id;
    IF fid IS NULL THEN RAISE EXCEPTION 'Change not found' USING ERRCODE='P0002'; END IF;
    SELECT updated_at INTO stamp FROM public.facilities WHERE id=fid FOR UPDATE;
    PERFORM 1 FROM public.facility_access_hours WHERE facility_id=fid FOR UPDATE;
    SELECT * INTO STRICT change_row FROM public.facility_change_requests WHERE id=p_change_id FOR UPDATE;
    SELECT * INTO evt FROM public.facility_change_events WHERE request_id=p_request_id;
    IF FOUND THEN
        IF evt.change_id<>p_change_id OR evt.action<>p_action OR evt.actor_id IS DISTINCT FROM p_actor_id OR evt.reason IS DISTINCT FROM p_reason THEN
            RAISE EXCEPTION 'Idempotency conflict' USING ERRCODE='40001'; END IF;
        RETURN jsonb_build_object('id',change_row.id,'status',change_row.status);
    END IF;
    IF p_action IN ('approve','reject') THEN
        IF change_row.status<>'pending' OR stamp IS DISTINCT FROM change_row.base_updated_at
           OR lifetime_private.facility_snapshot(fid) IS DISTINCT FROM change_row.before_data THEN
            RAISE EXCEPTION 'Stale or processed change' USING ERRCODE='40001'; END IF;
        target := change_row.after_data; state := CASE WHEN p_action='approve' THEN 'approved' ELSE 'rejected' END;
    ELSE
        IF change_row.status NOT IN ('approved','applied') OR change_row.before_data IS NULL
            OR stamp IS DISTINCT FROM change_row.applied_updated_at
            OR lifetime_private.facility_snapshot(fid) IS DISTINCT FROM change_row.after_data THEN
            RAISE EXCEPTION 'Restore conflict' USING ERRCODE='40001'; END IF;
        target := change_row.before_data; state := 'restored';
    END IF;
    IF p_action<>'reject' THEN
        IF lifetime_private.invalid_facility(target) THEN RAISE EXCEPTION 'Invalid candidate' USING ERRCODE='22023'; END IF;
        PERFORM lifetime_private.upsert_facility_batch(jsonb_build_array(target));
    END IF;
    UPDATE public.facility_change_requests SET status=state, reviewed_by=p_actor_id, reviewed_at=clock_timestamp(),
      applied_updated_at=CASE WHEN p_action='approve' THEN (SELECT updated_at FROM public.facilities WHERE id=fid) ELSE applied_updated_at END
      WHERE id=p_change_id;
    INSERT INTO public.facility_change_events(change_id,request_id,action,actor_id,reason)
      VALUES(p_change_id,p_request_id,p_action,p_actor_id,p_reason);
    RETURN jsonb_build_object('id',p_change_id,'status',state);
END;
$$;

CREATE OR REPLACE FUNCTION public.facility_change_history(p_facility_id uuid,p_actor_id uuid,p_limit integer DEFAULT 50)
RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = '' AS $$
BEGIN
    PERFORM lifetime_private.require_admin(p_actor_id);
    IF p_limit NOT BETWEEN 1 AND 100 OR p_limit IS NULL THEN RAISE EXCEPTION 'Invalid limit' USING ERRCODE='22023'; END IF;
    RETURN (SELECT coalesce(jsonb_agg(to_jsonb(c) || jsonb_build_object('events',(
        SELECT coalesce(jsonb_agg(to_jsonb(e) ORDER BY e.id),'[]'::jsonb) FROM public.facility_change_events e WHERE e.change_id=c.id
    )) ORDER BY c.created_at DESC,c.id),'[]'::jsonb)
    FROM (SELECT * FROM public.facility_change_requests WHERE facility_id=p_facility_id ORDER BY created_at DESC,id LIMIT p_limit) c);
END;
$$;

REVOKE ALL ON ALL FUNCTIONS IN SCHEMA lifetime_private FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.stage_facility_batch(jsonb,uuid), public.upsert_facility_batch(jsonb),
    public.propose_facility_change(uuid,jsonb,uuid,uuid), public.decide_facility_change(uuid,text,uuid,uuid,text),
    public.facility_change_history(uuid,uuid,integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.stage_facility_batch(jsonb,uuid), public.upsert_facility_batch(jsonb),
    public.propose_facility_change(uuid,jsonb,uuid,uuid), public.decide_facility_change(uuid,text,uuid,uuid,text),
    public.facility_change_history(uuid,uuid,integer) TO service_role;
COMMIT;
