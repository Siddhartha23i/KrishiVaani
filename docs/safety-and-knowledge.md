# Agricultural Safety Guardrails & Knowledge Management

KrishiVaani employs a defense-in-depth architecture to ensure agricultural advice is evidence-grounded, geographically applicable, and safe for smallholder farmers across India, with verified, expert-reviewed depth for Telangana first.

---

## 1. Geographic Coverage & Multilingual Architecture

KrishiVaani operates across India with a multilingual conversational pipeline supporting 10 Indian languages: Telugu (`te-IN`), Hindi (`hi-IN`), English (`en-IN`), Kannada (`kn-IN`), Tamil (`ta-IN`), Marathi (`mr-IN`), Malayalam (`ml-IN`), Punjabi (`pa-IN`), Bengali (`bn-IN`), and Gujarati (`gu-IN`).

### Modality per Language
- **Speech Recognition (STT)**: Accepts spoken voice notes in all 10 languages via Gnani Prisma v3.0 using an `"Indian agriculture"` domain topic hint.
- **Voice Synthesis (TTS)**: **Telugu-only** (`te-IN`) using the Kaveri voice via Gnani Timbre v2.5 (`settings.TTS_VOICE_MAP = {"te-IN": "Kaveri"}`). All non-Telugu queries receive localized text responses.
- **Onboarding**: `/start` sends an English welcome message; language is detected dynamically from user speech or text (there is no `/language` command).

### Regional Coverage Matrix

| Region | Supported Languages | Capabilities & Guardrails |
| :--- | :--- | :--- |
| **Telangana Farmers** | Any of 10 languages | Full LLM conversational guidance, general explanations, live WeatherAPI forecasts, IMD district warnings, and answers grounded in the Telangana verified knowledge base. |
| **Farmers in Other States** | Any of 10 languages | LLM general guidance, general explanations, live weather forecasts (with consent), and structured referrals to the **Kisan Call Centre (1800-180-1551)**, state agriculture departments, KVKs, and IMD agromet advisories. Consequential chemical, dosage, crop, or scheme prescriptions are strictly withheld. |

*In progress: grounded, guardrailed data for other states.*

---

## 2. Three-Tier Grounding Architecture

Dialogue routing in [`ConversationOrchestrator`](../app/conversation/service.py) and reasoning in [`LLMReasoningService`](../app/llm/service.py) enforce strict tiered boundaries:

- **Tier 1 (General Knowledge & Explanations)**:
  - Answers educational queries (e.g. *"What is drip irrigation?"*, *"What is El Niño?"*, *"How does the monsoon form?"*) from general LLM knowledge.
  - Formatted in 2–4 concise spoken sentences without requiring farm-specific parameters or local bulletins.
  - Exempt from the 0-evidence auto-abstention check.
- **Tier 2 (Live Meteorological Data)**:
  - Fetches current conditions, 3-day forecasts, and IMD district rainfall alerts.
  - Strictly gated by affirmative user consent for third-party weather sharing.
  - Distinguishes observed weather from probabilistic forecasts; weather alone never triggers chemical or irrigation advice.
- **Tier 3 (Consequential Farm Actions)**:
  - Crop recommendations, pest/disease management, chemical pesticide/fungicide choices, dosage amounts, fertilizer schedules, and government schemes.
  - **Strict Evidence Requirement**: Consequential guidance strictly requires valid, active, and expert-approved evidence matching the farmer's state and district. Without eligible approved evidence, the system abstains fail-closed.

---

## 3. Telangana Knowledge Base & Ingestion Tools

Telangana agricultural data is sourced from:
1. **Professor Jayashankar Telangana Agricultural University (PJTSAU)** agromet advisory bulletins.
2. **Telangana State Development Planning Society (TGDPS)** daily weather reports.
3. **India Meteorological Department (IMD)** Meteorological Centre Hyderabad public warnings.

### Ingestion Pipeline
- **Discovery & Extraction**: Handled by [`PJTAUSourceAdapter`](../app/knowledge/pjtau/adapter.py) and [`PJTAUBulletinExtractor`](../app/knowledge/pjtau/extractor.py) using PyMuPDF and pdfplumber.
- **Manual CLI Operations**: Ingestion tools run manually via terminal commands:
  - `python -m app.knowledge.pjtau.cli`: Discovers and extracts PJTSAU bulletins.
  - `python -m app.knowledge.tgdps.cli`: Ingests TGDPS daily weather reports.
  - `python -m app.knowledge.review_cli`: Administrative CLI for reviewing and transitioning records.
  - **No automated schedule**: Ingestion does not run on a background daemon or cron job.

---

## 4. Human Review & Approval Lifecycle

Governed by [`ReviewService`](../app/knowledge/review_service.py) through a strict three-state machine:

```
[ Ingested PDF ] ──> pending_verification ──(Technical Reviewer)──> verified ──(Agricultural Expert)──> approved
                                                                       │
                                                                       └──(Rejection / Clarification)──> rejected
```

1. **`pending_verification`**: Raw extracted text and tables. Ineligible for retrieval.
2. **`verified`**: Technical review verifying document URL, schema formatting, and OCR fidelity.
3. **`approved`**: Agronomic validation strictly by an authorized `agricultural_expert` or `agronomist`. Verifies pesticide active ingredients, spray ratios, soil suitability, and seasonal applicability.

### Why `verified` Items Are Excluded from Retrieval
In [`ApprovedKnowledgeAdapter`](../app/llm/knowledge_adapter.py), database queries strictly enforce `WHERE LOWER(verification_status) = 'approved'`. Technical verification confirms only document structure and OCR syntax. An OCR misread (such as confusing `2.5 ml/L` with `25 ml/L` or mixing up active ingredients) can cause crop devastation, environmental poisoning, or financial collapse. Grounding is therefore restricted to expert-approved advisories.

---

## 5. Seed Database Audit (`data_seed/krishivaani.db`)

A read-only audit of the checked-in seed database confirms:

| Status | Count | Verified By | Notes |
| :--- | :--- | :--- | :--- |
| **`verified`** | 50 | `technical_reviewer:developer` | PJTSAU bulletins verified technically for schema and extraction; awaiting agronomic sign-off. Not reviewed by agricultural officers. |
| **`approved`** | 1 | `agricultural_expert:agricultural_officer` | Advisory `ki_pjtau_f2742207_7` (Thunderstorm forecast for standing crops, valid `2026-11-04` to `2026-11-08`). |
| **Approved & Currently Valid** | **0** | — | The single approved advisory expired on `2026-11-08`. |

**Farmer Impact Today**: Because 0 approved and active crop advisories exist in the seed database today, consequential questions regarding crop chemicals, pests, or fertilizer schedules cleanly trigger safe deterministic abstention. Farmers receive a polite spoken Telugu referral advising them to consult their local Mandal Agricultural Officer (AO) or nearest Krishi Vigyan Kendra (KVK).

---

## 6. The 9-Rule Deterministic Safety Gate

Every LLM completion is evaluated synchronously in Python by [`LLMSafetyValidator`](../app/llm/safety.py) before text is forwarded to speech synthesis. If any check fails, the completion is rejected, fail-closed abstention is activated, and a localized referral is spoken:

| Rule | Enforcement Method | Protection Provided |
| :--- | :--- | :--- |
| **1. Unknown Evidence References** | `_check_unknown_evidence_references` | Flags citations not in the explicitly supplied retrieval context. |
| **2. Source Approval Status** | `_check_source_approval_status` | Enforces that cited evidence items hold `approved` verification status. |
| **3. Advisory Expiration** | `_check_advisory_expiration` | Rejects advisories where `applicable_until < request_date`. |
| **4. Geographic Applicability** | `_check_geographic_applicability` | Validates that state, district, or mandal matches the farmer's location. |
| **5. Unsupported Crop Advice** | `_check_unsupported_crop_recommendations` | Blocks crop selection guidance made without grounded evidence. |
| **6. Prohibited Chemical Dosages** | `_check_unsupported_chemical_dosages` | Strictly prevents prescribing ungrounded chemical pesticides, fungicides, or dosages. |
| **7. Forecast-Alone Crop Advice** | `_check_forecast_alone_crop_advice` | Prevents inferring irrigation or soil suitability solely from rainfall forecasts. |
| **8. Unsupported Numbers & Schemes** | `_check_unsupported_numbers_and_schemes` | Flags hallucinated yield numbers, subsidy amounts, or financial promises. |
| **9. Echoed Input Question** | `_check_echoed_input_question` | Prevents the model from repeating the farmer's question back as advice. |
