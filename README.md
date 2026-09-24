# CareCloud — Voice AI Patient Registration

Inbound phone agent that registers U.S. patients through natural conversation, then exposes the records over a REST API and a simple dashboard.

## Live demo

| | |
|---|---|
| **Phone** | `+1 (757) 908-7431` |
| **API base** | https://carecloud-project.up.railway.app |
| **Health** | https://carecloud-project.up.railway.app/health |
| **Dashboard** | https://carecloud-project.up.railway.app/dashboard |
| **OpenAPI** | https://carecloud-project.up.railway.app/docs |
| **Custom LLM (for Vapi)** | `https://carecloud-project.up.railway.app/llm` |
| **Webhook** | `https://carecloud-project.up.railway.app/vapi/webhook` |

Dial the number (or use Vapi **Talk** if you are outside the U.S.). Complete a registration, then check `GET /patients` or the dashboard.

## Architecture

```
Caller (phone / Vapi web call)
        |
        v
     Vapi (PSTN + STT + TTS + barge-in)
       |                         |
       | Custom LLM SSE          | tool-calls + end-of-call-report
       v                         v
 FastAPI on Railway (US East)
   POST /llm/chat/completions  --> Gemini key pool --> Gemini API
   POST /vapi/webhook          --> tool handlers --> PatientService / CallLogService
   /patients, /dashboard, /health
        |
        v
 Supabase Postgres (patients, call_logs, appointments)
```

Voice tools and the REST API share the same service layer. Validation is enforced server-side regardless of what the LLM says.

## Tech stack (and why)

| Layer | Choice | Why |
|---|---|---|
| Telephony / STT / TTS | Vapi | Free U.S. inbound number; turn-taking and barge-in so we focus on prompt + tools |
| LLM | Gemini via OpenAI-compatible endpoint | Free tier, tool calling, streaming |
| LLM access | Vapi Custom LLM → our FastAPI proxy | Own the prompt in code, rotate keys, log latency, spoken fallback |
| Backend | FastAPI + Python 3.12 | Async, Pydantic v2, auto `/docs` |
| Database | Supabase Postgres | Survives redeploys; real CHECK constraints |
| Hosting | Railway US East | Always-on; keeps Vapi ↔ app ↔ Gemini round-trips short |
| Dashboard | Jinja + vanilla JS at `/dashboard` | One deploy, no separate frontend |

## Setup

1. Create a Supabase project in **us-east-1**. Run [`supabase/migrations/001_init.sql`](supabase/migrations/001_init.sql) then [`supabase/seed.sql`](supabase/seed.sql). Use the **session pooler** connection string (`postgresql+asyncpg://…`).
2. Copy [`.env.example`](.env.example) to `.env` and fill in values (see below).
3. `python -m venv .venv` → activate → `pip install -r requirements.txt`
4. Run locally: `uvicorn app.main:app --reload --port 8000`
5. Deploy to Railway (US East). Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`. Health check: `/health`.
6. In Vapi: Custom LLM URL `https://<app>/llm`, server URL `https://<app>/vapi/webhook`, same `VAPI_SERVER_SECRET`. Attach a free U.S. number. Export/sync config lives in [`vapi/assistant.json`](vapi/assistant.json).

## Environment variables

See [`.env.example`](.env.example) for every variable with comments. Critical ones:

| Var | Purpose |
|---|---|
| `DATABASE_URL` | Supabase session pooler (`postgresql+asyncpg://`) |
| `GEMINI_API_KEYS` | Comma-separated keys from **different** GCP projects |
| `GEMINI_MODEL` / `GEMINI_FALLBACK_MODEL` | Primary + fallback Flash models |
| `VAPI_SERVER_SECRET` | Shared secret for `/llm` and `/vapi/webhook` |
| `CLINIC_NAME` / `CLINIC_TIMEZONE` | Injected into the system prompt; DOB “today” |
| `SIMULATE_DB_FAILURE` | Only honored when `APP_ENV=development` |

Key rotation is for **failover/resilience** (429 / 5xx / timeout), not quota evasion. Keys from one GCP project share quota, so use separate projects.

## API reference

All responses use `{ "data": ..., "error": null }` (or the inverse).

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | DB ping + masked Gemini pool |
| GET | `/patients` | Filters: `last_name`, `date_of_birth`, `phone_number` |
| GET | `/patients/{id}` | 404 if missing or soft-deleted |
| POST | `/patients` | 201 created |
| PUT | `/patients/{id}` | Partial update |
| DELETE | `/patients/{id}` | Soft delete (`deleted_at`) |
| GET | `/patients/{id}/calls` | Call transcripts linked to that patient |
| GET | `/dashboard` | HTML UI over the same APIs |
| POST | `/llm/chat/completions` | OpenAI-compatible SSE proxy for Vapi |
| POST | `/vapi/webhook` | Tools + end-of-call-report |

Invalid bodies → **422** with per-field `details`. Unknown / deleted ids → **404**.

## Prompt design

Canonical prompt lives in [`app/llm/prompt.py`](app/llm/prompt.py), section-commented (ROLE, CONTEXT, SPEAKING STYLE, FIELDS, VALIDATION, CORRECTIONS, RETURNING CALLER, CONFIRMATION, SAVING, APPOINTMENTS, LANGUAGE, BOUNDARIES, ENDING).

The LLM proxy **replaces** any system message from Vapi with a render that injects:

- clinic name
- today’s date in `CLINIC_TIMEZONE` (so future DOBs can be caught in-conversation)
- caller number / last-4 (or `unknown` for web calls)

Design goals: 1–2 sentence turns, full read-back before save (spell last name, digit-group phone/ZIP), field-specific re-prompts, start-over without hanging up, duplicate phone → offer update, Spanish switch on request, emergency → hang up and call 911.

## Voice tools

| Tool | When |
|---|---|
| `lookup_patient_by_phone` | As soon as a phone number is known |
| `register_patient` | Only after explicit confirmation |
| `update_patient` | Returning caller confirms changes |
| `endCall` | Vapi built-in, after “You’re all set” |

Successful register/update **links** `vapi_call_id` → `patient_id`. The end-of-call report upserts transcript/summary into `call_logs` (`incomplete` if hung up with no save, `completed` if linked).

## Testing

```bash
pytest -q
```

Covered today: validators (via existing suites), Gemini key pool rotation, LLM proxy auth/streaming helpers, Vapi webhook shapes (lookup/register/update/validation/DB failure), end-of-call → call_logs parsing, register → call link.

Manual reviewer scripts (happy path, info dump, corrections, bad DOB/phone/ZIP/state, start over, duplicate phone, hangup, DB failure, Spanish, API envelope) should be run against the live number before submission — see `.cursor/rules/01-evaluation-criteria.mdc`.

## Known limitations & trade-offs

- **Free Vapi number**: inbound U.S. only; outbound from free numbers is limited. Outside the U.S., use Vapi web call.
- **Gemini 3.x thinking**: cannot set `reasoning_effort=none`; we use `low` and drop the param if a model 400s.
- **Duplicate phones**: allowed in the schema (shared family phones). Dedup is conversational via `lookup_patient_by_phone`, not a UNIQUE constraint.
- **Appointments**: table exists; tools are not wired yet. Prompt offers booking only if those tools are present.
- **Spanish**: prompt switches language; Deepgram is still `language: en` until multilingual is enabled and re-tested.
- **Not HIPAA**: demo data only. No dashboard auth.
- **Railway auto-deploy**: confirm Source → auto-deploy on `main`; otherwise Redeploy after push.

## Next steps

- Live pass of reviewer scripts 1–18 on `+1 (757) 908-7431` and prompt tweaks from real transcripts
- Multilingual Deepgram + Spanish voice if claiming the language bonus
- Appointment slot tools (`get_available_slots` / `book_appointment`)
- Broader pytest coverage against a dedicated `TEST_DATABASE_URL`
- Optional sync script using `VAPI_API_KEY` to push `vapi/assistant.json`
