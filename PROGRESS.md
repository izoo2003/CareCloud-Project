# Progress

Handoff doc for continuing this take-home. Read this first in a new chat, then `.cursor/rules/` in order (00 → 05).

## Phases completed

| Phase | Status | Notes |
|---|---|---|
| **1** Skeleton + DB | **DONE** | FastAPI app, JSON logs, envelope handlers, `/health`, Supabase schema + seed |
| **2** REST API + deploy | **DONE** | Validators, PatientService, CRUD `/patients`, Railway US East live, redeploy persistence confirmed |
| **3** LLM proxy + key pool | **DONE** | Streaming `/llm/chat/completions`, key rotation, spoken fallback; local + Railway verified |
| **4** Vapi + first real call | **BACKEND LIVE** | Webhook + tools on Railway. Free number attached. Live happy-path call still to confirm (Phase 7) |
| **5** Edge cases + prompt | **CODE DONE** | call_logs upsert + patient link + `GET /patients/{id}/calls`. Live scripts 1–16 still pending your phone/web test |
| **6** Docs + cheap bonuses | **DONE** | README + `/dashboard` + call_logs/dashboard tests |
| **7** Final check + submit | **YOUR TURN** | One clean end-to-end call, verify API/dashboard, submit |

## Live URLs / IDs

- **Phone:** `+1 (757) 908-7431`
- **API / Railway:** `https://carecloud-project.up.railway.app` (US East)
- **Dashboard:** `https://carecloud-project.up.railway.app/dashboard`
- **Custom LLM URL for Vapi:** `https://carecloud-project.up.railway.app/llm`
- **Webhook:** `https://carecloud-project.up.railway.app/vapi/webhook`
- **GitHub:** `https://github.com/izoo2003/CareCloud-Project` (branch `main`)
- **Supabase:** project `CareCloud-Project`, ref `ozkflnaxsbxgfyzqiexw`, region `us-east-1`

## What's working

### Phase 5
- [`app/services/call_log_service.py`](app/services/call_log_service.py): `link_patient`, `upsert_from_report`, `list_for_patient`
- Adapter [`parse_end_of_call_report`](app/telephony/vapi_adapter.py); webhook persists transcripts
- Register/update tools link `vapi_call_id` → `patient_id`
- `GET /patients/{id}/calls`
- Prompt: appointments disabled until tools ship (no inventing tool names)

### Phase 6
- README with phone, API URL, architecture, env vars, prompt design, limitations, Next Steps
- `GET /dashboard` — patient table, last-name filter, detail + call transcripts (vanilla JS)

## Seed / demo patients in DB (active)

- Jane Doe `5125550101`
- John Public `5125550199`
- Casey Rivera `5125550144`
- Taylor Brooks `5125550177`

## Next step: Phase 7 (you do this)

1. Redeploy Railway if auto-deploy did not pick up the latest push.
2. Web call or dial `+1 (757) 908-7431` — happy path registration.
3. Confirm row on `GET /patients` and on `/dashboard`.
4. Second call with same phone → duplicate detection offer.
5. Hang up mid-call → no patient row; `call_logs` status `incomplete`.
6. Submit repo URL, phone number, API base URL, testing notes.
