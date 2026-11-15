# Agricultural Safety Guardrails & Knowledge Management

KrishiVaani employs a defense-in-depth architecture to ensure agricultural advice is evidence-grounded, geographically applicable, and safe for smallholder farmers.

---

## 1. The 9-Rule Deterministic Safety Gate

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

---

## 2. Human Review & Approval Lifecycle

The lifecycle of agricultural knowledge is governed by [`ReviewService`](../app/knowledge/review_service.py) through a strict three-state machine:

```
[ Ingested PDF ] ──> pending_verification ──(Technical Reviewer)──> verified ──(Agricultural Expert)──> approved
                                                                       │
                                                                       └──(Rejection / Clarification)──> rejected
```

1. **`pending_verification`**: Raw extracted text and tables ingested from PJTSAU agromet bulletins or TGDPS weather reports. Not eligible for retrieval.
2. **`verified`**: Technical review completed by a technical reviewer or system administrator. Verifies PDF accessibility, source URL provenance, OCR fidelity, and metadata schema.
3. **`approved`**: Agronomic sign-off completed strictly by an authorized `agricultural_expert` or `agronomist`. Validates pesticide active ingredients, spray ratios, soil suitability, and seasonal applicability.

### Why `verified` Items Are Excluded from Retrieval
In [`ApprovedKnowledgeAdapter`](../app/llm/knowledge_adapter.py), database queries strictly enforce `WHERE LOWER(verification_status) = 'approved'`. Technical verification confirms only document structure and OCR syntax. An OCR misread (such as confusing `2.5 ml/L` with `25 ml/L` or mixing up active ingredients) can cause crop devastation, environmental poisoning, or financial collapse. Grounding is therefore restricted to expert-approved advisories.

---

## 3. Current Seed Database Audit (`data_seed/krishivaani.db`)

An inspection of the checked-in seed database reveals:

| Status | Count | Notes |
| :--- | :--- | :--- |
| **`verified`** | 50 | Ingested PJTSAU advisories verified technically, awaiting expert agronomic sign-off. |
| **`approved`** | 1 | Advisory `ki_pjtau_f2742207_7` (Thunderstorm forecast for standing crops, valid `2026-11-04` to `2026-11-08`). |
| **Approved & Currently Valid** | **0** | As of today, the single approved advisory is expired. |

**Farmer Impact Today**: Because 0 approved and active crop advisories exist in the seed database today, consequential questions regarding crop chemicals, pests, or fertilizer schedules cleanly trigger safe deterministic abstention. Farmers receive a polite spoken Telugu referral advising them to consult their local Mandal Agricultural Officer (AO) or nearest Krishi Vigyan Kendra (KVK).

---

## 4. Tiered Advisory Policy

To balance safety with everyday usefulness, KrishiVaani implements a three-tier policy:

- **Tier 1 (General Agricultural Concepts)**: Educational queries (e.g., *"What is drip irrigation?"*, *"How does the monsoon form?"*) are answered from general model knowledge in concise conversational sentences without requiring local farm parameters.
- **Tier 2 (Live Weather & Forecasts)**: Meteorological observations and IMD rainfall warnings are derived strictly from live provider data and official bulletins with explicit consent gating.
- **Tier 3 (Consequential Farm Actions)**: Chemical spray recommendations, fertilizer formulas, seed varieties, and government scheme disbursements strictly require valid, expert-approved evidence; otherwise, the system abstains.

