# Progress

Handoff doc for continuing this take-home. Read this first in a new chat, then `.cursor/rules/` in order (00 → 05).

## Phases completed

| Phase | Status | Notes |
|---|---|---|
| **1** Skeleton + DB | **DONE** | FastAPI app, JSON logs, envelope handlers, `/health`, Supabase schema + seed |
| **2** REST API + deploy | **DONE** | Validators, PatientService, CRUD `/patients`, Railway US East live, redeploy persistence confirmed |
| **3** LLM proxy + key pool | **NOT STARTED** | Next |
| **4** Vapi + first real call | NOT STARTED | |
| **5** Edge cases + prompt | NOT STARTED | |
| **6** Docs + cheap bonuses | NOT STARTED | |
| **7** Final check + submit | NOT STARTED | |

## Live URLs / IDs

- **API / Railway:** `https://carecloud-project.up.railway.app` (US East)
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
- Local checkpoint: **31/31** passed
- Railway checkpoint: `/health` 200 connected; list Jane/John; POST Casey Rivera 201; invalid POST 422; **redeploy confirmed** — Supabase rows still present (scenario 23)

### Seed / demo patients in DB (active)
- Jane Doe `5125550101`
- John Public `5125550199`
- Casey Rivera `5125550144` (created on Railway during Phase 2 check)
- Riley Nguyen was soft-deleted during local testing (should not appear in GET list)

## What's NOT built yet (do not start until Phase 3+)

- `POST /llm/chat/completions` streaming proxy
- Gemini key pool rotation / failover / spoken fallback
- `app/llm/prompt.py` system prompt
- Vapi webhook + tool dispatcher
- Dashboard, call_logs writes, appointments, pytest suite, README (Phases 5–6)

## Manual setup already done

- [x] Supabase US East project + `001_init.sql` + seed + RLS
- [x] Local `.env` (gitignored) with full vars; `APP_ENV=production` for Railway copy
- [x] Python `.venv` + deps (incl. `tzdata` on Windows)
- [x] GitHub repo pushed (`main` @ initial Phase 1–2 commit; update PROGRESS if committing again)
- [x] Railway from GitHub, US East, env vars pasted from `.env`, public URL live
- [ ] Vapi account / free US number (needed Phase 4)
- [ ] Gemini API keys from **separate** Google Cloud projects (needed Phase 3) — confirm current Flash-Lite / Flash model names in AI Studio; do not guess

## Conflicts / decisions already resolved (from Step 1)

- Duplicate phone lookup is **core for Phase 4** (DoD / scenario 12), even though labeled bonus — no UNIQUE on phone
- Dashboard / call transcript endpoint = bonus timing; `end-of-call-report` → call_logs needed for scenario 14 in Phase 5
- Do not create empty `appointment_service` / `call_log_service` until those features ship

## Next step: Phase 3

Follow [`.cursor/rules/05-build-plan.mdc`](.cursor/rules/05-build-plan.mdc) Phase 3 and [`.cursor/rules/02-tech-stack.mdc`](.cursor/rules/02-tech-stack.mdc) LLM proxy + key pool specs; voice details in [`.cursor/rules/03-voice-agent.mdc`](.cursor/rules/03-voice-agent.mdc).

Build:
1. `app/llm/key_pool.py` — rotation, cooldowns, masked keys in `/health`
2. `app/llm/gemini_client.py` — stream + failover + spoken fallback line
3. `app/llm/prompt.py` — section-commented system prompt (draft in 03)
4. `app/api/llm_proxy.py` — `POST /llm/chat/completions` (Vapi Custom LLM points at `https://carecloud-project.up.railway.app/llm`)

Before coding Phase 3, user must provide current Gemini model names and at least one (ideally 2–3) API keys in `.env` / Railway as `GEMINI_API_KEYS`.

Checkpoint: curl the proxy with an OpenAI-style chat request; tokens stream; forced 429 rotates keys.
