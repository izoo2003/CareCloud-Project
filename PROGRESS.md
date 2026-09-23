# Progress

## Phases completed

- **Phase 1 (skeleton + DB)** — passed against Supabase `CareCloud-Project` (us-east-1).
- **Phase 2 (REST API)** — local checkpoint **PASSED** (31/31). Railway deploy is **your next step**.

## What's working

- `GET /health` → 200, database connected.
- Validators + `PatientCreate` / `PatientUpdate` / `PatientOut` (normalize then validate).
- `PatientService` shared layer: create / get / list / update / soft_delete / find_active_by_phone.
- REST: `GET/POST/PUT/DELETE /patients` with `{data, error}` envelope.
- Local checks: 201 create, 422 per-field (future DOB, short phone, bad ZIP, Ontario), 400 bad UUID / empty PUT / bad filter / malformed JSON, 404 unknown + deleted, partial PUT, soft delete hidden from list.

## What's broken / not built yet

- Not on Railway yet (you deploy).
- No LLM proxy or Gemini key pool (Phase 3).
- No Vapi webhook or tools (Phase 4).

## Manual setup already done

- **Supabase:** schema + seed. Riley Nguyen test row was created then soft-deleted during the local checkpoint.
- **Local `.env`:** session pooler `DATABASE_URL` (gitignored).
- **Python venv:** `.venv` including `tzdata` (needed on Windows for `America/New_York`).

## Next step (you): deploy to Railway

1. Push this repo to GitHub. Do **not** commit `.env`.
2. Railway → New Project → Deploy from GitHub → pick this repo.
3. Region: **US East**.
4. Start command (if not using the Dockerfile):  
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`  
   Health check path: `/health`
5. Variables → set:

```
APP_ENV=production
LOG_LEVEL=INFO
DATABASE_URL=postgresql+asyncpg://postgres.ozkflnaxsbxgfyzqiexw:<URL-ENCODED-PASSWORD>@aws-0-us-east-1.pooler.supabase.com:5432/postgres
CLINIC_NAME=Maple Grove Family Health
CLINIC_TIMEZONE=America/New_York
```

Use the same `DATABASE_URL` as local `.env` (password already encoded as `%40...`). Gemini/Vapi can stay empty.

6. Paste the public URL here when it is live.

## Railway checkpoint (replace BASE)

```bash
curl -s https://BASE/health
curl -s https://BASE/patients
curl -s -X POST https://BASE/patients -H "Content-Type: application/json" -d "{\"first_name\":\"Casey\",\"last_name\":\"Rivera\",\"date_of_birth\":\"06/01/1990\",\"sex\":\"Male\",\"phone_number\":\"5125550144\",\"address_line_1\":\"10 Pine St\",\"city\":\"Austin\",\"state\":\"TX\",\"zip_code\":\"78701\"}"
curl -s -X POST https://BASE/patients -H "Content-Type: application/json" -d "{\"first_name\":\"X\",\"last_name\":\"Y\",\"date_of_birth\":\"01/05/2031\",\"sex\":\"Male\",\"phone_number\":\"5125550133\",\"address_line_1\":\"1 A St\",\"city\":\"Austin\",\"state\":\"Ontario\",\"zip_code\":\"1234\"}"
```

Expect: health 200; list includes Jane/John; POST valid → 201; second POST → 422 with `details` for dob/state/zip. Then **Redeploy** and `GET /patients` — earlier rows must still be there.

No Phase 3 until Railway CRUD + redeploy is confirmed.
