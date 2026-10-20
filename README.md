# LifeTime backend starter

Backend-only starter. No real public facility data, Supabase credentials, or walking-route keys are included.

## Team integration contract

Follow [팀 연결 규칙](docs/integration-contract.md) for facility types, field names, units, timezone handling, missing values, permissions, location privacy, development data, and the three agreed API routes.

## Core backend development

The recommendation API now combines Supabase AED schedules with a replaceable walking provider. Set server-only `TMAP_API_KEY` for the TMAP adapter; missing keys return 503. Tests inject fixed mock routes and never estimate walking time from straight-line distance. Holiday/temporary-closure information is absent from the current schema, so opening hours alone do not establish `available`: an unknown closure calendar returns `unknown`. End times are exclusive and all arrival decisions use Asia/Seoul.

Before enabling guarded imports or administrator operations, review and separately approve `supabase/migrations/20261021010000_facility_change_review.sql`, then apply it **after** the two existing migrations. It adds change requests, append-only-to-client audit events, import retry receipts, and review settings. It moves the existing atomic import function into a private schema and preserves the public entry point behind the guard. It also changes update timestamps to monotonically increasing clock timestamps for conflict detection. This migration has **not** been applied to Supabase by Codex.

The importer uses the new guarded batch RPC and reports inserted/updated/held/unchanged separately. Suspicious coordinate/address/schedule changes retain the published facility until reviewed; held records prevent the CLI from reporting a complete import. The default 500m review threshold is an initial example in `facility_change_settings`, to be reviewed for operation. Applying this SQL requires owner permissions and changes server write behavior; take a backup and compare any pre-existing same-named objects before application. Existing service-role credentials remain trusted server credentials with direct base-table access and must never reach clients.

Administrator endpoints require a Supabase Auth bearer token. `auth.get_user` verifies it and only server-managed `app_metadata.role=admin` is accepted; editable user metadata is ignored. The DB also checks the actor's current `auth.users.raw_app_meta_data`. There is no administrator bypass token or public role-provisioning endpoint. Provision administrators through the existing trusted Supabase administration process.

- `POST /api/admin/facilities/{id}/changes`: `{ "request_id": "UUID", "record": { ...complete existing facility fields and access_hours... } }`. Identity cannot change. Suspicious valid candidates stay pending; semantically invalid candidates cannot be approved.
- `POST /api/admin/facility-changes/{id}/approve`, `/reject`, `/restore`: `{ "request_id": "UUID", "reason": "review reason" }`. Use a new request ID per distinct action and the same ID for a retry. Stale versions or conflicting/repeated decisions return 409.
- `GET /api/admin/facilities/{id}/history?limit=50`: administrator-only candidate snapshots and audit events. A restore requires the currently published version to match the reviewed version; it never deletes a newly inserted facility or overwrites later updates.

Run Python tests from `backend`: `..\.venv\Scripts\python.exe -m pytest tests -q`.
Optional isolated SQL tests from the repository root (no `.env` or network used by the tests):

```powershell
npm.cmd install --prefix .venv/sql-check @electric-sql/pglite@0.5.10
node --test backend/tests/sql/review.test.mjs
```

The SQL tests execute the real review migration in PostgreSQL WASM with test-only geographic storage helpers. They verify approval, rejection, restore, audit history, stale competing versions, retry receipts and access grants. Full PostGIS behavior, independent simultaneous sessions, real Supabase administrator tokens and the external walking service still require staging verification after approval. They are not reported as production verification.

## Windows PowerShell

If the GitHub repository is empty, initialize main on GitHub with a README first. Then:

```powershell
git clone https://github.com/pyeon-pyeon/LifeTime.git
cd LifeTime
git switch main
git pull origin main
git switch -c feat/backend-db-security
```

Copy the `backend`, `docs` and `.gitignore` files from this starter into the cloned repository root, then:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs`. In a second terminal, run `python -m pytest -q` in `backend` with the virtual environment active.

Do not commit `.env`, API secrets, or `.venv`. Before push, review `git status`, then `git add backend docs .gitignore README.md`, commit, and `git push -u origin feat/backend-db-security`.
