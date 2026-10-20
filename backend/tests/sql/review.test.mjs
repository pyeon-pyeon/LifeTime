// Local PostgreSQL-WASM tests. Never connects to Supabase or reads .env.
// PostGIS storage helpers are replaced by text points and spherical math here;
// production PostGIS and simultaneous independent DB sessions require staging QA.
import { test, before, beforeEach, afterEach, after } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { randomUUID } from 'node:crypto';

const modulePath = process.env.PGLITE_MODULE || resolve('.venv/sql-check/node_modules/@electric-sql/pglite/dist/index.js');
const { PGlite } = await import(pathToFileURL(modulePath).href);
let db, fid;
const admin = '00000000-0000-0000-0000-000000000001';
const member = '00000000-0000-0000-0000-000000000002';
const hours = Array.from({length:7}, (_,i)=>({weekday:i+1,opens_at:'09:00',closes_at:'18:00',ends_next_day:false,is_24_hours:false}));
const base = ()=>({facility_type:'aed',source_id:'SYNTHETIC-SQL-ONLY',name:'Fixture',address:'Fixture address',
    latitude:37.5,longitude:127,schedule_status:'known',access_hours:structuredClone(hours)});
const query = async (sql, params=[]) => (await db.query(sql,params)).rows;
const value = async (sql, params=[]) => (await query(sql,params))[0].result;
const stage = record => value('SELECT public.stage_facility_batch($1::jsonb) AS result',[JSON.stringify([record])]);
const propose = (record, actor=admin, request=randomUUID()) => value(
    'SELECT public.propose_facility_change($1,$2::jsonb,$3,$4) AS result',[fid,JSON.stringify(record),request,actor]);
const decide = (id, action, request=randomUUID(), actor=admin) => value(
    'SELECT public.decide_facility_change($1,$2,$3,$4,$5) AS result',[id,action,request,actor,'Fixture review']);
const snapshot = () => value('SELECT lifetime_private.facility_snapshot($1) AS result',[fid]);
async function expectError(callback, code) {
    await db.exec('SAVEPOINT expected_error');
    let caught;
    try { await callback(); } catch(error) { caught=error; }
    await db.exec('ROLLBACK TO SAVEPOINT expected_error');
    await db.exec('RELEASE SAVEPOINT expected_error');
    assert.ok(caught,'Expected database rejection');
    assert.equal(caught.code,code);
}

before(async ()=>{
    db = new PGlite();
    await db.exec(`
        CREATE ROLE anon; CREATE ROLE authenticated; CREATE ROLE service_role BYPASSRLS;
        CREATE SCHEMA auth;
        CREATE TABLE auth.users(id uuid PRIMARY KEY,raw_app_meta_data jsonb);
        CREATE SCHEMA extensions;
        CREATE DOMAIN extensions.geography AS text;
        CREATE FUNCTION extensions.ST_MakePoint(float8,float8) RETURNS text LANGUAGE sql IMMUTABLE
          AS $$ SELECT $1::text || ',' || $2::text $$;
        CREATE FUNCTION extensions.ST_SetSRID(text,integer) RETURNS text LANGUAGE sql IMMUTABLE AS $$ SELECT $1 $$;
        CREATE FUNCTION extensions.ST_DistanceSphere(text,text) RETURNS float8 LANGUAGE sql IMMUTABLE AS $$
          SELECT 6371008.8*2*asin(least(1.0,sqrt(
            power(sin(radians(split_part($2,',',2)::float8-split_part($1,',',2)::float8)/2),2)
            +cos(radians(split_part($1,',',2)::float8))*cos(radians(split_part($2,',',2)::float8))
            *power(sin(radians(split_part($2,',',1)::float8-split_part($1,',',1)::float8)/2),2)))) $$;
    `);
    const original = await readFile('supabase/migrations/20261020130000_facilities_schema.sql','utf8');
    const tables = original.slice(original.indexOf('CREATE TABLE IF NOT EXISTS public.facilities'),original.indexOf('CREATE INDEX IF NOT EXISTS'))
        .replaceAll('extensions.geography(Point, 4326)','extensions.geography');
    const trigger = original.slice(original.indexOf('CREATE OR REPLACE FUNCTION public.set_facility_location_and_updated_at'),
        original.indexOf('ALTER TABLE public.facilities ENABLE ROW LEVEL SECURITY'));
    const importer = original.slice(original.indexOf('CREATE OR REPLACE FUNCTION public.upsert_facility_batch'),
        original.indexOf('CREATE OR REPLACE FUNCTION public.get_aed_import_stats'));
    await db.exec(tables+trigger+importer);
    const migration = await readFile('supabase/migrations/20261021010000_facility_change_review.sql','utf8');
    await db.exec(migration);
    // Check reapplication does not relocate the guarded wrapper over its helper.
    await db.exec(migration);
});
beforeEach(async ()=>{
    await db.exec('BEGIN');
    await db.query('INSERT INTO auth.users VALUES ($1,$2::jsonb),($3,$4::jsonb)',
        [admin,JSON.stringify({role:'admin'}),member,JSON.stringify({role:'member'})]);
    assert.equal((await stage(base())).inserted,1);
    fid=(await query('SELECT id FROM public.facilities'))[0].id;
});
afterEach(async ()=>{ await db.exec('ROLLBACK'); });
after(async ()=>{ await db.close(); });

test('normal changes apply atomically and exact repeats are unchanged',async ()=>{
    const next={...base(),name:'Updated fixture',latitude:37.50001};
    assert.equal((await stage(next)).updated,1);
    assert.equal((await snapshot()).name,'Updated fixture');
    assert.equal((await stage(next)).unchanged,1);
});
test('coordinate anomalies are held and original data is retained',async ()=>{
    const original=await snapshot();
    const next={...base(),latitude:38};
    assert.equal((await stage(next)).held,1);
    assert.deepEqual(await snapshot(),original);
    const [pending]=await query("SELECT * FROM public.facility_change_requests WHERE status='pending'");
    assert.ok(pending.reasons.includes('coordinate_movement'));
    assert.equal((await stage(next)).held,1);
    assert.equal((await query("SELECT count(*)::int AS n FROM public.facility_change_requests WHERE status='pending'"))[0].n,1);
});
test('hours deletion and missing required data are held',async ()=>{
    const change=await propose({...base(),address:null,access_hours:[],schedule_status:'unknown'});
    assert.equal(change.status,'pending');
    assert.ok(change.reasons.includes('missing_address'));
    assert.ok(change.reasons.includes('hours_changed'));
    assert.equal((await snapshot()).access_hours.length,7);
});
test('administrator approval applies reviewed coordinates',async ()=>{
    const change=await propose({...base(),latitude:38});
    assert.equal((await decide(change.id,'approve')).status,'approved');
    assert.equal((await snapshot()).latitude,38);
});
test('non-administrator is denied by database even with server RPC',async ()=>{
    const change=await propose({...base(),latitude:38});
    await expectError(()=>decide(change.id,'approve',randomUUID(),member),'42501');
    assert.equal((await snapshot()).latitude,37.5);
});
test('rejection preserves the last good data',async ()=>{
    const original=await snapshot();
    const change=await propose({...base(),latitude:38});
    assert.equal((await decide(change.id,'reject')).status,'rejected');
    assert.deepEqual(await snapshot(),original);
});
test('approved changes restore exact prior data and preserve all events',async ()=>{
    const original=await snapshot();
    const change=await propose({...base(),latitude:38,access_hours:[],schedule_status:'unknown'});
    await decide(change.id,'approve');
    assert.equal((await snapshot()).access_hours.length,0);
    assert.equal((await decide(change.id,'restore')).status,'restored');
    assert.deepEqual(await snapshot(),original);
    const history=await value('SELECT public.facility_change_history($1,$2,50) AS result',[fid,admin]);
    const row=history.find(r=>r.id===change.id);
    assert.deepEqual(row.events.map(e=>e.action),['proposed','approve','restore']);
    assert.equal(row.before_data.latitude,37.5);
    assert.equal(row.after_data.latitude,38);
});
test('duplicate decisions are idempotent; a different request cannot approve twice',async ()=>{
    const change=await propose({...base(),latitude:38}); const key=randomUUID();
    await decide(change.id,'approve',key);
    await decide(change.id,'approve',key);
    assert.equal((await query("SELECT count(*)::int AS n FROM public.facility_change_events WHERE action='approve'"))[0].n,1);
    await expectError(()=>decide(change.id,'approve'),'40001');
});
test('stale candidate cannot overwrite newer normal changes',async ()=>{
    const change=await propose({...base(),latitude:38});
    await stage({...base(),name:'Newer fixture'});
    await expectError(()=>decide(change.id,'approve'),'40001');
    assert.equal((await snapshot()).name,'Newer fixture');
});
test('competing candidates cannot both approve on the same base version',async ()=>{
    const a=await propose({...base(),latitude:38});
    const b=await propose({...base(),longitude:128});
    await decide(a.id,'approve');
    await expectError(()=>decide(b.id,'approve'),'40001');
    assert.equal((await snapshot()).longitude,127);
});
test('restore cannot overwrite a later accepted update',async ()=>{
    const change=await propose({...base(),latitude:38}); await decide(change.id,'approve');
    await stage({...base(),latitude:38,name:'Later fixture'});
    await expectError(()=>decide(change.id,'restore'),'40001');
    assert.equal((await snapshot()).name,'Later fixture');
});
test('out-of-band schedule changes cannot evade conflict checks using an unchanged parent timestamp',async ()=>{
    const change=await propose({...base(),latitude:38});
    await db.query("UPDATE public.facility_access_hours SET opens_at=TIME '10:00' WHERE facility_id=$1 AND weekday=1",[fid]);
    await expectError(()=>decide(change.id,'approve'),'40001');
    assert.equal((await snapshot()).access_hours[0].opens_at,'10:00:00');
});
test('restore also detects out-of-band schedule changes',async ()=>{
    const change=await propose({...base(),latitude:38});await decide(change.id,'approve');
    await db.query("UPDATE public.facility_access_hours SET opens_at=TIME '10:00' WHERE facility_id=$1 AND weekday=1",[fid]);
    await expectError(()=>decide(change.id,'restore'),'40001');
});
test('invalid hours are recorded but cannot be approved',async ()=>{
    const bad=base();bad.access_hours[0].closes_at='08:00';
    const change=await propose(bad);
    assert.ok(change.reasons.includes('invalid_record'));
    await expectError(()=>decide(change.id,'approve'),'22023');
    assert.equal((await snapshot()).access_hours[0].closes_at,'18:00:00');
});
test('request identifiers cannot be reused for a different candidate',async ()=>{
    const key=randomUUID();await propose({...base(),latitude:38},admin,key);
    await expectError(()=>propose({...base(),latitude:39},admin,key),'40001');
});
test('unchanged administrator requests also reserve their idempotency identifiers',async ()=>{
    const key=randomUUID();assert.equal((await propose(base(),admin,key)).status,'unchanged');
    await expectError(()=>propose({...base(),latitude:38},admin,key),'40001');
});
test('batch retry returns original inserted counts without duplicate audit events',async ()=>{
    const key=randomUUID(), records=JSON.stringify([{...base(),source_id:'NEW-BATCH-FIXTURE'}]);
    const first=await value('SELECT public.stage_facility_batch($1::jsonb,$2) AS result',[records,key]);
    const second=await value('SELECT public.stage_facility_batch($1::jsonb,$2) AS result',[records,key]);
    assert.deepEqual(second,first);assert.equal(first.inserted,1);
    assert.equal((await query("SELECT count(*)::int AS n FROM public.facility_change_requests WHERE after_data->>'source_id'='NEW-BATCH-FIXTURE'"))[0].n,1);
    await expectError(()=>value('SELECT public.stage_facility_batch($1::jsonb,$2) AS result',[JSON.stringify([base()]),key]),'40001');
});
test('historical importer entry point uses the same safety gate',async ()=>{
    assert.equal(await value('SELECT public.upsert_facility_batch($1::jsonb) AS result',
        [JSON.stringify([{...base(),latitude:38}])]),1);
    assert.equal((await snapshot()).latitude,37.5);
});
test('client roles cannot execute moderation RPCs or read audit tables',async ()=>{
    for (const role of ['anon','authenticated']) {
        assert.equal(await value("SELECT has_function_privilege($1,'public.decide_facility_change(uuid,text,uuid,uuid,text)','EXECUTE') AS result",[role]),false);
        assert.equal(await value("SELECT has_table_privilege($1,'public.facility_change_requests','SELECT') AS result",[role]),false);
    }
    assert.equal(await value("SELECT has_function_privilege('service_role','public.decide_facility_change(uuid,text,uuid,uuid,text)','EXECUTE') AS result"),true);
    await expectError(async ()=>{
        await db.exec('SET LOCAL ROLE service_role');
        await db.query('SELECT lifetime_private.upsert_facility_batch($1::jsonb)',['[]']);
    },'42501');
});
test('a failed multi-record batch rolls back earlier records in that batch',async ()=>{
    await expectError(()=>value('SELECT public.stage_facility_batch($1::jsonb) AS result',[JSON.stringify([
        {...base(),name:'Should roll back'}, {...base(),source_id:'ZZ-INVALID',latitude:999}
    ])]),'22023');
    assert.equal((await snapshot()).name,'Fixture');
});
