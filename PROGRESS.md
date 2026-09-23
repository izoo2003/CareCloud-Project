# Progress

Handoff doc for continuing this take-home. Read this first in a new chat, then `.cursor/rules/` in order (00 → 05).

## Phases completed

| Phase | Status | Notes |
|---|---|---|
| **1** Skeleton + DB | **DONE** | FastAPI app, JSON logs, envelope handlers, `/health`, Supabase schema + seed |
| **2** REST API + deploy | **DONE** | Validators, PatientService, CRUD `/patients`, Railway US East live, redeploy persistence confirmed |
| **3** LLM proxy + key pool | **DONE** | Streaming `/llm/chat/completions`, key rotation, spoken fallback, prompt renderer |
| **4** Vapi + first real call | NOT STARTED | Next |
| **5** Edge cases + prompt | NOT STARTED | |
| **6** Docs + cheap bonuses | NOT STARTED | |
| **7** Final check + submit | NOT STARTED | |

## Live URLs / IDs

- **API / Railway:** `https://carecloud-project.up.railway.app` (US East)
- **Custom LLM URL for Vapi:** `https://carecloud-project.up.railway.app/llm` (Vapi appends `/chat/completions`)
- **GitHub:** `https://github.com/izoo2003/CareCloud-Project` (branch `main`)
- **Supabase:** project `CareCloud-Project`, ref `ozkflnaxsbxgfyzqiexw`, region `us-east-1`
- **DB:** session pooler `aws-0-us-east-1.pooler.supabase.com:5432` via `postgresql+asyncpg://` in `.env` (gitignored) and Railway Variables

## What's working

### Phase 1
- App factory [`app/main.py`](app/main.py): lifespan, request-id middleware, envelope exception handlers
- Config [`app/config.py`](app/config.py), JSON logging [`app/core/logging.py`](app/core/logging.py)
- Domain errors [`app/core/errors.py`](app/core/errors.py), envelope [`app/schemas/envelope.py`](app/schemas/envelope.py)
- Async DB session [`app/db/session.py`](app/db/session.py) (port 6543 → `statement_cache_size=0`)
- Models [`app/db/models.py`](app/db/models.py): patients, appointments, call_logs
- SQL: [`supabase/migrations/001_init.sql`](supabase/migrations/001_init.sql) + [`supabase/seed.sql`](supabase/seed.sql)
- `GET /health` → `{ data: { status, database, gemini }, error }` — 503 if DB down
- Dockerfile, `.env.example`, `.gitignore`, `ruff.toml`

### Phase 2
- Validators [`app/core/validators.py`](app/core/validators.py) (names, DOB, sex, phone NANP, state names→codes, ZIP+4, email, etc.)
- Schemas [`app/schemas/patient.py`](app/schemas/patient.py): Create / Update / Out (`MM/DD/YYYY`, timestamps with `Z`)
- Service [`app/services/patient_service.py`](app/services/patient_service.py): create, get, list, update, soft_delete, find_active_by_phone (for Phase 4 tools)
- Routes [`app/api/patients.py`](app/api/patients.py): GET list/filters, GET by id, POST 201, PUT partial, DELETE soft
- Shared service rule: REST and future voice tools use the same layer
- Railway checkpoint: `/health` 200 connected; list Jane/John; POST Casey Rivera 201; invalid POST 422; **redeploy confirmed** — Supabase rows still present (scenario 23)

### Phase 3
- Key pool [`app/llm/key_pool.py`](app/llm/key_pool.py): LRU acquire, 429 cooldown (Retry-After or 60s), 5xx/timeout 10s, 401/403 disable, masked `/health`
- Prompt [`app/llm/prompt.py`](app/llm/prompt.py): section-commented canonical prompt; renders clinic, today (clinic TZ), caller / last-4
- Client [`app/llm/gemini_client.py`](app/llm/gemini_client.py): OpenAI-compatible Gemini stream + JSON; retries only before first chunk; fallback model; spoken fallback line; fills missing tool_call `id`/`index`
- Proxy [`app/api/llm_proxy.py`](app/api/llm_proxy.py): `POST /llm/chat/completions` — Bearer or `x-vapi-secret`; whitelist; replace system message; SSE default
- Models: primary `gemini-3.5-flash-lite`, fallback `gemini-3.8-flash`, `GEMINI_REASONING_EFFORT=low` (Gemini 3 cannot use `none`)
- Local checkpoint: **16/16** unit tests; local curl streamed tokens + `[DONE]`; `llm_request` log had `key_index`, `ttft_ms`, `outcome=success`; forced 429 rotation covered by test
- `/health` gemini object now includes `available`, `cooling_down`, `disabled` (keys still masked)

### Seed / demo patients in DB (active)
- Jane Doe `5125550101`
- John Public `5125550199`
- Casey Rivera `5125550144` (created on Railway during Phase 2 check)
- Riley Nguyen was soft-deleted during local testing (should not appear in GET list)

## What's NOT built yet (do not start until Phase 4+)

- Vapi assistant + free US number
- `/vapi/webhook` tool dispatcher (`lookup_patient_by_phone`, `register_patient`, `update_patient`)
- Dashboard, call_logs writes, appointments, full pytest suite, README (Phases 5–6)

## Manual setup already done

- [x] Supabase US East project + `001_init.sql` + seed + RLS
- [x] Local `.env` (gitignored) with Gemini key, model names, and `VAPI_SERVER_SECRET`
- [x] Python `.venv` + deps (incl. `tzdata` on Windows)
- [x] GitHub repo pushed (`main`)
- [x] Railway from GitHub, US East, public URL live
- [x] Gemini key + `gemini-3.5-flash-lite` / `gemini-3.8-flash` confirmed locally
- [ ] Copy Phase 3 vars to Railway if not already set: `GEMINI_API_KEYS`, `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL`, `GEMINI_REASONING_EFFORT=low`, `VAPI_SERVER_SECRET` (same value as local `.env`)
- [ ] Vapi account / free US number (needed Phase 4)

## Conflicts / decisions already resolved (from Step 1)

- Duplicate phone lookup is **core for Phase 4** (DoD / scenario 12), even though labeled bonus — no UNIQUE on phone
- Dashboard / call transcript endpoint = bonus timing; `end-of-call-report` → call_logs needed for scenario 14 in Phase 5
- Do not create empty `appointment_service` / `call_log_service` until those features ship
- Gemini 3.x cannot disable thinking; use `reasoning_effort=low` and drop the param if a model 400s

## Next step: Phase 4

Follow [`.cursor/rules/05-build-plan.mdc`](.cursor/rules/05-build-plan.mdc) Phase 4 and [`.cursor/rules/03-voice-agent.mdc`](.cursor/rules/03-voice-agent.mdc).

1. Confirm Railway `/health` shows gemini `configured: true` and curl `https://carecloud-project.up.railway.app/llm/chat/completions` streams
2. Create Vapi assistant: Custom LLM URL `https://carecloud-project.up.railway.app/llm`, same server secret, tools + first message
3. `POST /vapi/webhook` dispatcher: lookup, register, update
4. Web call AND phone call complete a registration; row appears in `GET /patients`
