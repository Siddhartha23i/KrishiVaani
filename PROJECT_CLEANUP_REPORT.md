# KrishiVaani — Stage 2 Cleanup Report: Telegram-Only Architecture with Sarvam Primary & Groq Fallback

**Date:** 2026-11-12
**Branch:** `telegram-only-cleanup`
**Execution Status:** Working tree intentionally uncommitted. No commit created, no push executed, zero changes deployed.
**Core Architecture:** Telegram Bot (User Channel) + Gnani Prisma v3.0 (STT) + Sarvam AI `sarvam-105b-conversations` (Primary LLM) + Groq `openai/gpt-oss-120b` (Automatic Fallback LLM) + Gnani Timbre v2.5 Kaveri (TTS) + SQLite + Railway.

---

## 1. Files Deleted (30 Tracked Files in Git + 4 Directories)

The following 30 tracked files and 4 directories were removed after verifying zero runtime dependencies:

### A. WhatsApp Integration Packages & Routes (9 Deleted)
1. `app/whatsapp/__init__.py`
2. `app/whatsapp/audio_converter.py` (Migrated to `app/telegram/audio.py` prior to deletion)
3. `app/whatsapp/client.py`
4. `app/whatsapp/event_repository.py`
5. `app/whatsapp/exceptions.py`
6. `app/whatsapp/schemas.py`
7. `app/whatsapp/security.py`
8. `app/whatsapp/service.py`
9. `app/api/routes/whatsapp.py`

### B. Twilio WhatsApp Integration Packages & Routes (10 Deleted)
10. `app/twilio/__init__.py`
11. `app/twilio/client.py`
12. `app/twilio/event_repository.py`
13. `app/twilio/exceptions.py`
14. `app/twilio/media_manager.py`
15. `app/twilio/schemas.py`
16. `app/twilio/security.py`
17. `app/twilio/service.py`
18. `app/api/routes/twilio.py`
19. `scripts/diagnose_twilio_outbound.py`

### C. WhatsApp & Twilio Test Modules (2 Deleted)
20. `tests/test_whatsapp_integration.py` (26 tests retired)
21. `tests/test_twilio_integration.py` (43 tests retired)

### D. Obsolete Node.js OpenWA Prototype (4 Deleted)
22. `package.json`
23. `package-lock.json`
24. `wa.config.js`
25. `voice-echo.js`

### E. Retired Website Asset (1 Deleted)
26. `site/assets/icons/whatsapp.svg` (Unreferenced icon)

### F. Exploratory Benchmark Scripts & JSON Results (4 Deleted)
27. `gemini_llm_test.py`
28. `gemini_models_eval.py`
29. `gemini_eval_results.json`
30. `gemini_eval_results_7_1_3.json`

*(Note: Untracked filesystem scratch cleanups included root audio files `pipeline-reply.wav` and `telugu-response.wav`, plus obsolete cache `telangana-farmer-whatsapp.data.json`, bringing total filesystem deletions to 33 files, with exactly 30 tracked by Git).*

### G. Directories Deleted
- `app/whatsapp/`
- `app/twilio/`
- `node_modules/` (17,409 files, reclaiming **364.94 MB**)
- `.open-wa/` (browser session token cache)

---

## 2. Files Modified (26 Files: 21 Non-Test + 5 Test)

### A. Modified Non-Test Files (21 Files)
| File | Modifications Made |
|---|---|
| `.env.example` | Removed WhatsApp and Twilio credential templates. Clarified that Sarvam AI is primary and Groq is automatic fallback. |
| `LLM_AB_RESULTS.md` | Updated model benchmark references to reflect Groq `openai/gpt-oss-120b` fallback role alongside Sarvam primary. |
| `PROJECT_AUDIT_REPORT.md` | Cleaned trailing whitespace; updated knowledge base descriptions to accurate technical breakdown. |
| `PROJECT_STATE_REPORT.md` | Updated architecture context to reflect current Telegram-only runtime state. |
| `README.md` | Removed WhatsApp/Twilio standby entries from Scope & Limitations and Future Roadmap. |
| `app/api/router.py` | Removed `whatsapp` and `twilio` router imports and sub-router registrations. Kept `health`, `farmers`, `knowledge`, `weather`, and `voice`. |
| `app/conversation/intent.py` | Isolated Telegram-specific conversational intent handling; removed legacy channel branching. |
| `app/conversation/service.py` | Preserved dialogue orchestrator and safe location consent handling; decoupled legacy WhatsApp branching. |
| `app/core/config.py` | Removed all Meta WhatsApp Cloud API and Twilio settings and properties. Updated application description to voice-first Telegram assistant. Retained all Sarvam, Groq, and Telegram settings. |
| `app/llm/safety.py` | Standardized citation parsing and deterministic agricultural safety checks across all provider outputs. |
| `app/llm/service.py` | Implemented strict Sarvam primary execution with automated fallback to Groq `openai/gpt-oss-120b` only on qualifying provider errors. Ensured safety rejections never trigger Groq. |
| `app/telegram/audio.py` | Added `convert_wav_bytes_to_ogg_opus()`, `convert_wav_to_ogg_opus()`, and `validate_audio_playability()`. Preserved exact FFmpeg parameters (mono, 24k bitrate, libopus, playability validation, safe temp file cleanup). Cleaned EOF newline. |
| `app/telegram/handlers.py` | Updated audio import from `app.whatsapp.audio_converter` to `app.telegram.audio`. |
| `app/voice/service.py` | Preserved Gnani Prisma v3.0 STT and Gnani Timbre v2.5 Kaveri TTS; decoupled legacy channel branches. |
| `docker-entrypoint.sh` | Removed legacy `mkdir -p /app/data/twilio_media`. Retained SQLite seed initialization and PDF directory setup. |
| `railway_deployment_guide.md` | Removed Twilio media storage volume reference; updated container launch commands. |
| `requirements.txt` | Removed `twilio==9.13.0`. Preserved `groq==0.37.1` and all core dependencies. |
| `scripts/diagnostics/compare_llm_providers.py` | Updated comparison diagnostic script for Sarvam primary and Groq fallback evaluation. |
| `scripts/diagnostics/live_policy_check.py` | Updated policy verification script for Telegram-only response formatting. |
| `site/README.md` | Removed WhatsApp icon reference and coming-soon note. |
| `site/index.html` | Removed disabled WhatsApp button; removed WhatsApp coming soon status tag; updated Step 04 pipeline text to specify Sarvam AI primary and Groq automatic fallback. |

### B. Modified Test Files (5 Files)
| File | Modifications Made |
|---|---|
| `tests/test_conversation_orchestration.py` | Verified conversation orchestration operates seamlessly without WhatsApp/Twilio routers. |
| `tests/test_llm_service.py` | Added `TestSarvamPrimaryGroqFallback` suite (6 tests) verifying Sarvam priority, Groq fallback trigger on failure, Groq safety validation, rate-limit fallback, and localized safe abstention. (Expanded from 17 to 23 tests). |
| `tests/test_telegram_integration.py` | Added `TestTelegramAudioConversion` suite (3 tests) testing WAV to OGG Opus encoding, OGG Opus to WAV decoding, round-trip fidelity, and temp file cleanup. (Expanded from 55 to 58 tests). |
| `tests/test_telegram_memory.py` | Verified conversation memory and HMAC integrity in Telegram standalone environment. |
| `tests/test_tiered_policy.py` | Ensured tiered policy enforcement operates identically without legacy channel flags. |

---

## 3. Files Retained & Justification

| File / Component | Purpose & Justification |
|---|---|
| `app/telegram/*` | Core user interface. Long-polling runner, message/voice handlers, session management, and HMAC memory store. |
| `app/llm/providers/groq_provider.py` | **MANDATORY FALLBACK PROVIDER.** Required for automated fallback when Sarvam experiences timeouts, rate limits, or server outages. |
| `app/llm/providers/sarvam_provider.py` | **MANDATORY PRIMARY PROVIDER.** Executes reasoning using `sarvam-105b-conversations` for all incoming queries. |
| `app/knowledge/*` | Ingestion, schemas, and retrieval adapter for university research bulletins and weather reports. |
| `data/krishivaani.db` & `data_seed/krishivaani.db` | Persistent SQLite knowledge base with 51 knowledge records (50 verified seasonal advisories and 1 approved permanent reference) and university research stations. |
| `app/weather/*` | WeatherAPI integration, IMD district warnings, 30-minute consent caching, and location extraction. |
| `site/*` | Independent marketing and user onboarding static website deployed to Netlify. |

---

## 4. Shared Audio Migration Details

`app/telegram/audio.py` previously contained only Telegram session logic. It now hosts the complete, verified audio conversion pipeline:
- `convert_wav_bytes_to_ogg_opus(wav_bytes, duration_seconds=None)`: Converts 16kHz WAV from Gnani Timbre TTS into compliant Telegram voice notes using system FFmpeg (`-c:a libopus -b:a 24k -ar 16000 -ac 1`).
- `convert_ogg_opus_to_wav(ogg_bytes)`: Converts incoming farmer Telegram voice notes (`audio/ogg`) into 16kHz 16-bit mono WAV for Gnani Prisma STT inference.
- `validate_audio_playability(ogg_bytes)`: Validates that generated audio contains valid Ogg Opus page headers (`OggS`) and readable audio streams before Telegram dispatch.

---

## 5. Confirmation that Telegram Voice Handling Still Works

Telegram voice handling remains fully functional and verified:
1. `tests/test_telegram_integration.py::TestTelegramAudioConversion::test_convert_wav_bytes_to_ogg_opus`: **PASSED**
2. `tests/test_telegram_integration.py::TestTelegramAudioConversion::test_convert_ogg_opus_to_wav`: **PASSED**
3. `tests/test_telegram_integration.py::TestTelegramAudioConversion::test_audio_cleanup_after_conversion`: **PASSED**
4. `tests/test_telegram_integration.py::TestPart1HumanFriendlyConversations`: **100% PASSED** (6 passed in 5.24s).

---

## 6. Confirmation: Sarvam is Primary & Groq is Fallback

The LLM orchestration pipeline in `app/llm/service.py` enforces the following contract:
1. **Primary Invocation:** Sarvam AI receives every request first via `SarvamProvider.generate_completion()`.
2. **Fallback Gating:** Groq `openai/gpt-oss-120b` is invoked **strictly** upon caught provider failures (`LLMTimeoutError`, `LLMProviderUnavailableError`, `LLMRateLimitError`, `LLMMalformedResponseError`, `LLMAuthenticationError`).
3. **Safety Isolation:** If Sarvam successfully returns a response that fails deterministic agricultural safety checks (e.g. missing evidence citations, unsupported chemical dosage, or expired validity), the response is rejected immediately and localized safety fallback is returned. **Groq fallback is NEVER triggered on agricultural safety rejections.**
4. **Unified Safety Validation:** Responses from both Sarvam and Groq are parsed through identical JSON schemas, stripped of markdown wrappers, validated against active evidence citations, and styled via `normalize_response_style()`.
5. **Both-Provider Failure:** If both Sarvam and Groq fail, the orchestrator returns a localized safe fallback referring the farmer to their local agricultural officer or nearest KVK.

---

## 7. Test Results for Sarvam and Groq Fallback

All 6 tests in `TestSarvamPrimaryGroqFallback` (`tests/test_llm_service.py`) execute and pass cleanly:

```
tests/test_llm_service.py::TestSarvamPrimaryGroqFallback::test_sarvam_success_does_not_call_groq PASSED [95%]
tests/test_llm_service.py::TestSarvamPrimaryGroqFallback::test_sarvam_rate_limit_calls_groq_fallback_once PASSED [91%]
tests/test_llm_service.py::TestSarvamPrimaryGroqFallback::test_sarvam_timeout_calls_groq_fallback_once PASSED [100%]
tests/test_llm_service.py::TestSarvamPrimaryGroqFallback::test_safety_rejection_from_sarvam_does_not_trigger_groq_fallback PASSED [86%]
tests/test_llm_service.py::TestSarvamPrimaryGroqFallback::test_groq_response_passes_through_safety_validator PASSED [82%]
tests/test_llm_service.py::TestSarvamPrimaryGroqFallback::test_both_providers_fail_returns_localized_safe_fallback PASSED [78%]
```

---

## 8. Pytest Test Collection and Failure Analysis

### Exact Test Collection Breakdown
- **Stage 1 Baseline Collection:** **512 tests** across 22 test files.
- **Retired WhatsApp/Twilio Tests:** **-69 tests** (43 from `tests/test_twilio_integration.py` + 26 from `tests/test_whatsapp_integration.py`).
- **Added Integration Tests:** **+9 tests** (6 in `tests/test_llm_service.py` for fallback + 3 in `tests/test_telegram_integration.py` for audio conversion).
- **Stage 2 Collection:** **452 tests** across 20 test files ($512 - 69 + 9 = 452$).

### Pytest Execution Summary
- **429 Passed**
- **23 Failed** (identical to Stage 1 baseline)
- **79 Subtests Passed**

### Clear Distinction: Pre-Existing Test Fixture Failures vs. Architecture Health
The 23 test failures are **not** application bugs or cleanup regressions. They are pre-existing SQLite test fixture harness collisions in two modules:
1. `tests/test_knowledge_adapter.py` (17 failures): Unit tests insert a mock record (e.g. `KNOW-ADIL-001`) and assert `result.total_eligible == 1`. However, the test harness opens `data/krishivaani.db`, which already contains active pre-seeded records matching the same query parameters, resulting in assertion mismatches (`2 != 1` or `1 != 0`).
2. `tests/test_tgdps_ingestion.py` (6 failures): Ingestion tests assert that newly ingested items have status `'pending_verification'`. In Phase 8.7, all pre-seeded records were permanently promoted to `'verified'` in the volume database, causing `AssertionError: 'verified' != 'pending_verification'`.

All production Telegram pipeline tests, speech processing tests, and LLM orchestration tests pass at 100%.

---

## 9. Confirmation of WhatsApp/Twilio Code Removal

Exhaustive text and AST scans confirm:
- Active imports of `whatsapp` or `twilio` in `app/`: **0**
- Active imports of `whatsapp` or `twilio` in `tests/`: **0**
- Active routes mounted in `app/api/router.py`: **0** (Only `health`, `farmers`, `knowledge`, `weather`, and `voice` remain)
- WhatsApp CTAs or assets on website (`site/index.html`): **0**

---

## 10. Remaining Legacy References and Reasons

The few remaining occurrences of `whatsapp` and `twilio` are inert and documented below:
1. **Database Schema DDL (`app/db/database.py:331, 354`):** `CREATE TABLE IF NOT EXISTS whatsapp_events` and `twilio_events` remain in `init_db()` to preserve backward compatibility with existing SQLite files. No code reads from or writes to these tables.
2. **Channel Docstrings & Schema Annotations (`app/conversation/schemas.py`, `app/llm/schemas.py`, `app/voice/schemas.py`):** Field descriptions document historical channel inputs (`'telegram', 'whatsapp', 'twilio'`).
3. **Channel-Isolation Tests (`tests/test_telegram_integration.py`):** Regression tests verify that requests without `channel="telegram"` maintain baseline system prompts without leaking Telegram conversational honorific rules.

---

## 11. Dependencies Removed and Retained (`requirements.txt`)

### Retained Core Dependencies
- `fastapi==0.115.6`, `uvicorn==0.34.0`, `pydantic==2.10.4`, `pydantic-settings==2.7.0`
- `python-telegram-bot==21.10`
- `httpx==0.28.1`, `requests==2.32.3`
- `groq==0.37.1` (Retained: Mandatory fallback provider)
- `imageio-ffmpeg==0.6.0` (Retained: FFmpeg wrapper)
- `sqlite-vec==0.1.6` (Retained: Vector search extension)
- `gnani-vachana==0.9.0` (Retained: STT & TTS client SDK)

### Removed Dependencies
- `twilio==9.13.0` (Removed: No longer required)

---

## 12. Database Files Preserved

In strict adherence to project safety requirements:
- `data/krishivaani.db`: Untouched and preserved (`PRAGMA integrity_check = ok`).
- `data_seed/krishivaani.db`: Untouched and preserved (`PRAGMA integrity_check = ok`).
- All 4 approved PJTSAU PDFs and 2 approved TGDPS PDFs: Untouched and preserved.
- **Knowledge Records Breakdown:** Exactly **51 knowledge records** preserved in both databases:
  - **50 verified seasonal advisories** (expired on November 8, 2026, as documented).
  - **1 approved permanent reference** (`ki_pjtau_f2742207_7`: Thunderstorm and lightning safety).
- **User Privacy & Consent State:** Exactly **1 live user consent record** on volume (`weather_provider_sharing_consent = 1`), with zero personal account identifiers or farmer personal data stored or exposed. Seed database contains 0 consent records.
- **Farmer Records:** Exactly **0 rows** in the `farmers` table (zero unintended registrations).
- SQLite tables `whatsapp_events` and `twilio_events`: Preserved without schema mutation.

---

## 13. Remaining Cleanup Recommendations (Post-Stage 2)

1. **SQLite Legacy Table Cleanup:** After creating a verified volume snapshot, execute an isolated migration script to drop the empty `whatsapp_events` and unused `twilio_events` tables from `data/krishivaani.db` and `data_seed/krishivaani.db`.
2. **Agricultural Knowledge Season Refresh:** The 50 seasonal advisory records with `applicable_until = '2026-11-08'` should be updated with current university bulletins (Kharif/Rabi 2026–2027) via `app/knowledge/pjtau/cli.py`.
3. **Test Fixture Database Isolation:** Update `tests/test_knowledge_adapter.py` and `tests/test_tgdps_ingestion.py` to use in-memory SQLite fixtures (`:memory:`) rather than connecting to the pre-seeded `data/krishivaani.db`, resolving the 23 test fixture count assertion failures.

---

## 14. Git Branch and Git Status

- **Current Branch:** `telegram-only-cleanup` (branched locally from `main`).
- **Working Tree State:** Intentionally uncommitted.
- **Git File Counts:**
  - **Modified non-test files:** **21**
  - **Modified test files:** **5**
  - **Deleted tracked files:** **30**
  - **Untracked files:** **1** (`PROJECT_CLEANUP_REPORT.md`)
- **Git Safety Guarantees:**
  - **No commit** has been created.
  - **No push** has happened.
  - **No deployment** has happened.
  - All application changes remain safely in the uncommitted working tree on `telegram-only-cleanup`.
  - **No secrets or credentials** were detected in the Git diff.

---

## 15. Railway Variable Changes Required Manually

Please review your **Railway Dashboard → Project → Service → Variables** tab and delete the following obsolete environment variables:

| Variable to Remove from Railway | Reason |
|---|---|
| `WHATSAPP_PHONE_NUMBER_ID` | WhatsApp channel retired |
| `WHATSAPP_ACCESS_TOKEN` | WhatsApp channel retired |
| `WHATSAPP_BUSINESS_ACCOUNT_ID` | WhatsApp channel retired |
| `WHATSAPP_APP_SECRET` | WhatsApp channel retired |
| `WHATSAPP_WEBHOOK_VERIFY_TOKEN` | WhatsApp channel retired |
| `META_WHATSAPP_ACCESS_TOKEN` | WhatsApp legacy alias retired |
| `META_PHONE_NUMBER_ID` | WhatsApp legacy alias retired |
| `META_APP_SECRET` | WhatsApp legacy alias retired |
| `TWILIO_ACCOUNT_SID` | Twilio sandbox retired |
| `TWILIO_AUTH_TOKEN` | Twilio sandbox retired |
| `TWILIO_WHATSAPP_FROM` | Twilio sandbox retired |
| `TWILIO_WEBHOOK_PUBLIC_BASE_URL` | Twilio sandbox retired |
| `TWILIO_ENABLED` | Twilio sandbox retired |

**DO NOT REMOVE:** `GROQ_API_KEY`, `GROQ_MODEL_ID`, or `GROQ_REASONING_EFFORT`. They are required for the automated fallback.

---

*Report updated and verified.*
