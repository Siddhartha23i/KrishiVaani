# KrishiVaani diagnostic report

**Inspection date:** 2026-11-10  
**Repository:** `Siddhartha23i/KrishiVaani`  
**Scope:** source, tests, README, seed/data filenames, and the bounded timing probe.  
**Safety:** I did not read `.env`, environment values, credentials, API keys, tokens, phone numbers, user IDs, raw database rows, or other personal data. Secret-like values are omitted. No application code, configuration, or tests were changed. The only new files are this report and [`scripts/diagnostics/time_voice_pipeline.py`](scripts/diagnostics/time_voice_pipeline.py).

> [!NOTE] Historical Document Notice (As of 2026-11-10)
> This document is a historical diagnostic report reflecting the repository state on November 10, 2026. It preserves the findings, measurements, and architectural observations made at that time (when Groq was tested alone and before the Stage 2 Telegram-only cleanup). It does not reflect the current production architecture established on November 12, 2026 (Telegram-only channel, Sarvam AI `sarvam-105b-conversations` as primary LLM, Groq `openai/gpt-oss-120b` as automatic fallback, and retired WhatsApp/Twilio integrations).

## Executive diagnosis

The reported failures are consistent with the architecture. A normal Telegram voice request is a long serial chain: Telegram download -> FFmpeg decode -> Gnani STT -> SQLite/profile work -> optional WeatherAPI/IMD calls -> SQLite evidence retrieval -> one large Groq JSON completion -> deterministic safety validation -> Gnani TTS -> FFmpeg Opus encode -> Telegram upload. Weather can add two or three network calls before Groq. TTS is performed twice on some Telegram paths: once inside the voice service, then again after a handler-side fallback or special-flow decision.

The code does **not** contain the suspected multi-pass LLM design. There is one Groq completion for a normal message; intent/entity extraction is deterministic keyword logic; safety is Python regex/entity logic; translation is not a separate pass. The quality problem is therefore mostly prompt rigidity, weak retrieval/query matching, conservative all-or-nothing fallback behavior, and unmeasured upstream latency—not a hidden chain of answer/rewrite/verification LLM calls.

The strongest demo-safe change is to reduce serial work and avoid avoidable second TTS calls, while making abstentions informative rather than generic. Do not weaken evidence or chemical-safety checks immediately before a public demo.

## 1. Architecture map

### Entry points and modules

* Telegram long polling is built by [`app/telegram/run.py:20-43`](app/telegram/run.py:20), using `python-telegram-bot`; text and voice handlers live in [`app/telegram/handlers.py:145-891`](app/telegram/handlers.py:145).
* OGG/Opus input is converted to 16 kHz mono PCM WAV by [`app/telegram/audio.py:15-62`](app/telegram/audio.py:15).
* Voice orchestration, Prisma STT, conversation processing, Timbre TTS, and stage timings are in [`app/voice/service.py:106-476`](app/voice/service.py:106).
* Text orchestration is [`app/conversation/service.py:90-328`](app/conversation/service.py:90). It resolves profile/session context, routes intent, optionally retrieves weather, retrieves approved SQLite evidence, invokes Groq, and returns a response.
* Deterministic intent routing is [`app/conversation/intent.py:236-304`](app/conversation/intent.py:236).
* Groq configuration/provider are [`app/llm/config.py:20-43`](app/llm/config.py:20) and [`app/llm/providers/groq_provider.py:35-218`](app/llm/providers/groq_provider.py:35).
* Prompt construction and the single completion are [`app/llm/service.py:101-190`](app/llm/service.py:101).
* Safety validation is [`app/llm/safety.py:76-350`](app/llm/safety.py:76).
* Approved evidence retrieval is [`app/llm/knowledge_adapter.py:98-327`](app/llm/knowledge_adapter.py:98).
* Weather orchestration is [`app/weather/services/weather_service.py:49-428`](app/weather/services/weather_service.py:49), with WeatherAPI and IMD adapters.
* SQLite schema and seed-copy behavior are [`app/db/database.py:9-421`](app/db/database.py:9).

### Text request flow

1. Telegram receives text; pure greetings bypass the orchestrator and LLM in [`app/telegram/handlers.py:107-122`](app/telegram/handlers.py:107).
2. The handler builds `ConversationRequest` with `te-IN`, Telegram channel, session location, and consent state ([`app/telegram/handlers.py:320-377`](app/telegram/handlers.py:320)).
3. Orchestrator normalizes language, identifies channel, resolves farmer/session context, and runs deterministic intent keywords ([`app/conversation/service.py:122-151`](app/conversation/service.py:122)).
4. Weather-warning questions take a dedicated IMD path; ordinary weather questions may call WeatherAPI current + 3-day forecast and optionally IMD warning ([`app/conversation/service.py:153-205`](app/conversation/service.py:153), [`app/conversation/service.py:355-716`](app/conversation/service.py:355)).
5. SQLite approved evidence is retrieved; only `verification_status = approved` is eligible ([`app/llm/knowledge_adapter.py:134-186`](app/llm/knowledge_adapter.py:134)).
6. One Groq JSON completion is made, then Python safety validation runs ([`app/llm/service.py:109-141`](app/llm/service.py:109)).
7. The handler sends the returned text ([`app/telegram/handlers.py:377-389`](app/telegram/handlers.py:377)).

### Voice request flow

1. Telegram downloads the remote file and times the download ([`app/telegram/handlers.py:531-544`](app/telegram/handlers.py:531)).
2. FFmpeg converts OGG/Opus to WAV ([`app/telegram/handlers.py:546-548`](app/telegram/handlers.py:546), [`app/telegram/audio.py:28-58`](app/telegram/audio.py:28)).
3. The voice service validates the WAV, calls Prisma STT, then calls the same orchestrator ([`app/voice/service.py:181-299`](app/voice/service.py:181)).
4. The orchestrator may perform WeatherAPI current and forecast **sequentially**, then IMD warning, then SQLite retrieval, Groq, and safety.
5. Voice service calls Timbre TTS on the final text ([`app/voice/service.py:348-394`](app/voice/service.py:348)).
6. Telegram converts returned WAV to OGG/Opus and uploads it ([`app/telegram/handlers.py:817-835`](app/telegram/handlers.py:817)).

### External calls and sequencing

| Call | Provider/module | Sequential or parallel | Notes |
|---|---|---|---|
| Telegram `get_file` + download | Telegram Bot API | Sequential, first network hop | Timed as `telegram_download_ms`. |
| OGG -> WAV | bundled FFmpeg | Sequential local CPU | 15 s subprocess timeout. |
| STT | Gnani Prisma v3.0 | Sequential | `te-IN`, agriculture topic, [`app/voice/service.py:205-216`](app/voice/service.py:205). |
| Current weather | WeatherAPI | Sequential | Consent-gated; cache exists in provider/service. |
| 3-day forecast | WeatherAPI | Sequential after current weather | Not parallelized with current weather. |
| Official warning | public IMD adapter | Sequential after WeatherAPI | Optional for ordinary weather; dedicated for warning queries. |
| Evidence | SQLite | Sequential | Aggregate status checks plus retrieval. |
| LLM | Groq `openai/gpt-oss-120b` by default | Sequential | One call; client retries are configured below. |
| Safety | Python | Sequential | In-process regex and field checks. |
| TTS | Gnani Timbre v2.5 / Kaveri | Sequential | `te-IN`, speed `0.95`, 48 kHz WAV. |
| WAV -> OGG | bundled FFmpeg | Sequential local CPU | Opus encode and playability validation. |
| Telegram upload | Telegram Bot API | Sequential, last network hop | `reply_voice`; no streaming. |

No application-level `asyncio.gather`/parallel provider calls were found in the inspected request path.

## 2. LLM calls per request

### Actual call inventory

| Purpose | Implementation | Model | Temperature | Max tokens | Timeout/retries | Input |
|---|---|---|---:|---:|---:|---|
| Answer generation plus structured intent/abstention fields | `LLMReasoningService.process_query` -> `GroqProvider.generate_completion` | `openai/gpt-oss-120b` default, configurable | `0.1` | `1500` | 15 s; Groq client `max_retries=2` | One system prompt plus one user message containing target language, optional farmer context, weather facts, up to 10 evidence items, and the question |
| Intent/entity extraction | No LLM call | N/A | N/A | N/A | N/A | Deterministic keyword matching and Telegram location extraction |
| Safety check | No LLM call | N/A | N/A | N/A | N/A | Python validator over request/output |
| Rewrite/translation/verification | No separate call | N/A | N/A | N/A | N/A | There is no post-generation LLM pass |

**LLM calls per normal voice message: one.** A pure greeting is zero. A weather-warning terminal path is zero. A handler-level location/consent flow can process a pending question in a later message, which is a second user request, not a second LLM call inside one normal request. Groq transport retries can make more than one HTTP attempt, but they are not additional logical LLM passes.

### Prompt contract

The exact prompt constants are [`BASE_SYSTEM_INSTRUCTION`](app/llm/service.py:32) and [`TELEGRAM_SYSTEM_INSTRUCTION`](app/llm/service.py:56). They contain no credentials or user data. The following is a verbatim excerpt of the stable contract (the Telegram variant adds the voice/Telugu rules shown in the source):

```text
You are KrishiVaani, an AI agricultural advisory assistant for farmers in Telangana.
Your primary mission is farmer safety, financial security, and strict evidence-grounded truth.

CORE ADVISORY RULES:
1. EVIDENCE GROUNDING: You must answer agricultural factual questions ONLY using the explicitly supplied approved evidence. Never invent, extrapolate, or generalize recommendations beyond what the evidence states.
2. MISSING PARAMETERS: If a farmer asks for crop, sowing, or management advice without necessary field parameters (such as specific mandal/village, season, soil condition, or water availability), DO NOT recommend a crop. Identify what is missing and ask concise clarifying questions.
3. PESTICIDES & FERTILIZERS: NEVER prescribe chemical pesticides, fungicides, or specific dosages without confirmed pest identification and approved evidence. Direct the farmer to consult the local Agricultural Officer (AO) or Krishi Vigyan Kendra (KVK).
4. WEATHER BOUNDARIES: When weather data is provided, distinguish between observed historical data and forecasts. Never claim soil moisture or irrigation need is known from rainfall amounts alone unless explicitly stated. Clearly distinguish between probabilistic forecasts and official IMD warnings. When answering purely meteorological weather questions where no agricultural database evidence was supplied, set "evidence_citations": [].
5. RESTRICTIONS: Preserve all geographical, crop, variety, and validity-period restrictions stated in the evidence.
6. SPOKEN VOICE OUTPUT: The "response" field must be natural, polite, and conversational for voice playback. Keep sentences short and clear. Avoid markdown formatting, tables, or asterisks. If responding in Telugu, use standard conversational Telugu.

OUTPUT FORMAT:
Return valid JSON only matching this schema:
{
  "intent": string,
  "language": string,
  "required_information": [string],
  "supported_facts": [string],
  "unsupported_questions": [string],
  "abstain": boolean,
  "evidence_citations": [string],
  "response": string
}
```

Telegram adds exact rules for conversational Telangana Telugu, polite ``, one primary follow-up question, no parentheses/markdown, and phonetic forms for units/acronyms. The full source is [`app/llm/service.py:56-94`](app/llm/service.py:56); it is a long prompt, not a hidden second pass.

The user message is formatted in [`app/llm/service.py:149-190`](app/llm/service.py:149): `TARGET LANGUAGE`, optional farmer context, weather facts marked `[OBSERVATION]` or `[FORECAST]`, evidence blocks with ID/source/district/validity/title/content, and `FARMER QUESTION`.

## 3. Guardrails and refusal paths

### Deterministic safety rules

`LLMSafetyValidator.validate` runs these checks in order ([`app/llm/safety.py:76-124`](app/llm/safety.py:76)):

1. Unknown evidence IDs in citations and `KNOW-*` text references: violation -> safe abstention.
2. Citation of a non-`APPROVED` item: violation -> safe abstention.
3. Citation of expired advisory: violation -> safe abstention.
4. District mismatch when all supplied evidence is for another district and the answer is not explicitly qualified: violation -> safe abstention.
5. Actionable crop phrases without any approved crop evidence: violation -> safe abstention.
6. Dosage regex and monitored chemical names not present in evidence: violation -> safe abstention.
7. Forecast-only crop recommendation: violation -> safe abstention.
8. Unsupported yield, financial, or monitored scheme claims: violation -> safe abstention.
9. Response exactly echoes the input question: violation -> safe abstention.

The exact monitored chemical set, dosage/yield/financial regexes, and English/Telugu action phrases are in [`app/llm/safety.py:25-70`](app/llm/safety.py:25). These are substring/regex checks, not semantic verification. Telugu dosages and Telugu numerals are not comprehensively covered by the English-oriented dosage regex; conversely, broad phrases such as `పంట వేసుకోవచ్చు` can reject benign conditional language.

### What happens when triggered

* Any validator violation replaces the model output with a refusal and sets `safety_status="REJECTED"` ([`app/llm/safety.py:288-340`](app/llm/safety.py:288)).
* Voice suppresses audio only for strict `REJECTED`; it returns text-only response metadata ([`app/voice/service.py:286-326`](app/voice/service.py:286)).
* Telegram can replace empty/English-looking abstentions with a fixed Telugu referral before TTS ([`app/telegram/handlers.py:423-431`](app/telegram/handlers.py:423)).
* The orchestrator also forces abstention for crop/pest/fertilizer/scheme intents when no approved items exist ([`app/conversation/service.py:276-289`](app/conversation/service.py:276)).
* Exact echo checks exist independently in the validator, orchestrator, voice service, and Telegram handler. The handler override asks for a location even when the echoed question may not be a location question ([`app/conversation/service.py:306-320`](app/conversation/service.py:306), [`app/voice/service.py:257-277`](app/voice/service.py:257)).
* Weather consent, missing location, conflicting location, provider failure, district confirmation, empty transcript, STT failure, TTS failure, and generic handler failure each have separate paths.

### Exact fallback texts

* Telegram abstention: **“దీని గురించి పూర్తిగా నిర్ధారించిన వివరాలు నా దగ్గర ప్రస్తుతం లేవు . మీ పొలం పరిస్థితికి తగ్గట్టు సరైన సలహా కోసం మీ మండల వ్యవసాయ అధికారిని గానీ, దగ్గర్లో ఉన్న కృషి విజ్ఞాన కేంద్రాన్ని గానీ అడగండి.”** ([`app/telegram/handlers.py:79-82`](app/telegram/handlers.py:79))
* LLM Telegram technical failure: **“సాంకేతిక సమస్య వల్ల ప్రస్తుతం సమాధానం ఇవ్వలేకపోతున్నాను . అత్యవసరమైతే మీ స్థానిక వ్యవసాయ అధికారిని అడగండి, లేదా కాసేపటి తర్వాత మళ్ళీ అడగండి.”** ([`app/llm/service.py:211-242`](app/llm/service.py:211))
* Validator Telegram rejection: the same generic evidence-referral text above ([`app/llm/safety.py:302-307`](app/llm/safety.py:302)).
* Missing Telegram location: **“మీ ఊరి వాతావరణ వివరాల కోసం, మీది ఏ మండలం లేదా జిల్లానో చెప్తారా ?”** ([`app/conversation/service.py:848-865`](app/conversation/service.py:848))
* Weather consent request: **“మీ ఊరి వాన, వాతావరణ వివరాలు చూడాలంటే, మీ ప్రాంతం పేరును బయటి వాతావరణ సేవతో పంచుకోవాల్సి ఉంటుంది. అందుకు మీకు ఓకే నా ? అవును అంటే సరే అని చెప్పండి.”** ([`app/conversation/service.py:775-804`](app/conversation/service.py:775))
* Weather provider failure: **“సాంకేతిక సమస్య వల్ల ప్రస్తుతం వాతావరణ రిపోర్ట్ అందడం లేదు . దయచేసి కాసేపటి తర్వాత అడగండి.”** ([`app/conversation/service.py:867-899`](app/conversation/service.py:867))
* Empty transcript: **“మీ సందేశం స్పష్టంగా వినిపించలేదు. దయచేసి మీ వ్యవసాయ సందేహాన్ని లేదా అడిగే విషయాన్ని మళ్ళీ స్పష్టంగా మాట్లాడండి.”** ([`app/voice/service.py:49-53`](app/voice/service.py:49))

### Trigger-rate honesty

There is no production denominator, trigger counter, or sampled corpus in the repository. Therefore no defensible fraction of normal questions can be reported. The likely high-trigger cases are: any crop/pest/fertilizer/scheme question with zero eligible evidence; any answer containing a dosage, yield, price, scheme, or crop recommendation not textually present in evidence; expired/pending evidence; and district-specific evidence queried without matching district. The actual fraction is **unknown**, not zero.

Rules most able to cut information or force generic replies: all nine validator failures, the zero-evidence intent gate, the English-looking fallback replacement, and exact-echo location overrides. No code intentionally truncates a response character-by-character, but these paths replace the whole answer.

## 4. Answer quality

### Retrieval and prompt grounding

SQLite records contain category, type, title, content, language, geography, crop/season fields, validity dates, review metadata, and verification state ([`app/db/database.py:132-185`](app/db/database.py:132)). The adapter first counts database statuses, then fails closed if there are zero approved records, and otherwise filters approved, current, geographically compatible records ([`app/llm/knowledge_adapter.py:134-186`](app/llm/knowledge_adapter.py:134), [`app/llm/knowledge_adapter.py:218-327`](app/llm/knowledge_adapter.py:218)). It returns at most 10 items by default.

The prompt passes evidence as full text blocks, not embeddings or a ranked semantic search result. Query/category matching is conservative and mostly metadata-based; the farmer question is not used as a robust full-text retrieval query. Evidence is not translated before prompting. Database content can be Telugu (`language_code` defaults to `te-IN`), English, or mixed; the model is simply instructed to answer in the target language.

When evidence is missing, the model sees `APPROVED AGRICULTURAL EVIDENCE: None provided.` and crop/pest/fertilizer/scheme intents are forced to abstention. Weather facts are explicitly labelled meteorological context and can be used without agricultural citations.

### Telugu generation and post-processing

The answer is generated directly by Groq in the requested language; there is no translation call. Telegram hardcodes `te-IN` for text and voice requests and forces detected voice language to Telugu ([`app/voice/service.py:232-235`](app/voice/service.py:232), [`app/telegram/handlers.py:321-337`](app/telegram/handlers.py:321)).

For Telegram Telugu TTS, post-processing strips tags/markdown, joins lines, inserts periods between unterminated lines, expands units, removes selected parenthetical acronyms, expands acronyms, and normalizes whitespace ([`app/voice/service.py:72-135`](app/voice/service.py:72)). It does not impose a response character limit or sentence-aware chunking. It can alter punctuation and pronunciation, but the inspected code has no direct sentence truncation. A provider-side Timbre input/output limit is not documented in this repository; the report cannot claim one without provider documentation.

### Likely root causes

* Inaccurate answers: retrieval is not question-semantic, evidence can be sparse or mismatched, and the model is asked to compress full evidence into a single answer without a fact-level entailment check.
* Unfriendly/incomplete answers: the Telegram prompt is over-prescriptive, asks for exactly one follow-up, bans common vocabulary, and a single safety violation discards all useful supported facts.
* Generic responses: fail-closed validator, zero-evidence intent gate, multiple exact-echo overrides, and fallback text replacement.
* Telugu awkwardness: direct generation under a very long English prompt, mixed Telugu/English evidence, forced vocabulary substitutions, no Telugu linguistic evaluation, and no response-length/chunk policy.
* Apparent cut-offs: no local truncation is visible; likely candidates are provider TTS limits, long unchunked text, Telegram/Opus handling, or upstream audio failure. Instrument actual output duration and provider response length before changing text logic.

## 5. Latency

### Measurement status

The throwaway probe is [`scripts/diagnostics/time_voice_pipeline.py`](scripts/diagnostics/time_voice_pipeline.py). It converts the same checked-in Telugu sample to OGG once, then performs exactly three runs with three Prisma calls and three Timbre calls maximum. It measures OGG->WAV, STT, orchestration plus Groq/safety, TTS, and WAV->OGG. It intentionally does not print transcript, answer, IDs, secrets, or exception text. Telegram download/upload are not exercised because no safe Telegram session fixture is available.

**Live result:** the probe made zero Gnani calls because its runner could not start: the execution sandbox denied local network access. No live stage timing is available from this inspection. Do not treat mocked tests or the user-reported CLI figure as production timing.

| Run | OGG->WAV | STT | Orchestration + Groq + safety | TTS | WAV->OGG | Status |
|---:|---:|---:|---:|---:|---:|---|
| 1 | not run | not run | not run | not run | not run | sandbox blocked start |
| 2 | not run | not run | not run | not run | not run | sandbox blocked start |
| 3 | not run | not run | not run | not run | not run | sandbox blocked start |

The application already emits stage telemetry including Telegram download/upload, conversion, Prisma, intent, location, WeatherAPI, IMD, Groq, Timbre, and total milliseconds ([`app/telegram/handlers.py:400-420`](app/telegram/handlers.py:400)). It does not persist metrics or aggregate percentiles, and it logs no guardrail-trigger counter.

### Likely latency ranking and fixes

1. **Gnani STT and TTS (high impact, low/medium effort):** keep clients warm, shorten answers, and avoid re-synthesizing text already synthesized.
2. **Groq plus any weather calls (high impact, medium effort):** skip LLM for deterministic warning/consent/greeting paths; cache weather; parallelize independent current/forecast fetches only after verifying provider limits.
3. **Telegram/network variability (medium/high impact, medium effort):** reuse HTTP connections and measure upload separately; no streaming exists.
4. **Large prompt/evidence (medium impact, low effort):** retrieve fewer, more relevant evidence items and cap content size.
5. **FFmpeg conversion (low/medium impact, low effort):** keep it, but measure it; avoid repeated WAV->OGG conversion.

Do not add another verification LLM pass to fix latency. It would worsen the serial path and generic fallback rate.

## 6. Telugu and voice quality

### Preparation and limits

* Input accepted extensions are `.m4a`, `.wav`, `.mp3`, `.ogg`, `.aac`, `.flac`; max size is 15 MB and max duration is 30 s ([`app/voice/validator.py:20-30`](app/voice/validator.py:20)).
* Telegram OGG is decoded to 16 kHz mono PCM; Timbre output is requested as 48 kHz linear PCM WAV, Kaveri voice, speed `0.95` ([`app/voice/service.py:457-475`](app/voice/service.py:457)).
* Numeric units are expanded for `°C`, `%`, `mm`, `cm`, `km/h`, `kg`, and `ml`; selected English abbreviations become Telugu phonetics.
* There is no sentence chunking, maximum TTS text length, provider-side limit check, or retry/chunk fallback in the application.
* The code supports Telugu, Hindi, and English normalization only ([`app/conversation/service.py:73-88`](app/conversation/service.py:73)); Kaveri is used regardless of normalized language in `_synthesize_speech`.

### Five available examples, with evidence limits

The repository has no production transcript/TTS log corpus. The examples below are **test fixtures**, not real farmer logs. “Final spoken text” is not captured by tests because mocked TTS returns bytes; where a deterministic normalization test exists, that output is described as prepared text, not audio.

| # | Question/transcript fixture | LLM text fixture | Final spoken text | Defect |
|---:|---|---|---|---|
| 1 | `వరి పంటలో యూరియా ఎరువు మోతాదు ఎంత?` | `వరి పంటకు ఎకరాకు 50 కిలోల యూరియా సిఫార్సు చేయబడింది.` | Not captured; mocked WAV only | Test bypasses live guardrail; cannot prove spoken correctness. |
| 2 | `పురుగుల మందులు కలపవచ్చా` | `వరిలో అగ్గితెగులు నివారణకు ట్రైసైక్లాజోల్ పిచికారీ చేయండి.` | Not captured | Fixture demonstrates that handler tests can pass unsafe-looking text when the orchestrator is mocked. |
| 3 | `నమస్కారం, పత్తి పంట గురించి చెప్పండి` | No live LLM text; STT fixture only | Not captured | Integration fixture checks transcript plumbing, not language quality. |
| 4 | `ఉరుములు పడినప్పుడు పొలంలో ఏమి చేయాలి` | No live LLM text in the inspected test excerpt | Not captured | Routing is tested as agricultural advice; no end-to-end Telugu audio assertion. |
| 5 | `నిజామాబాద్ వాతావరణం: ఉష్ణోగ్రత 28.8°C, వర్షం 12.5 mm, అవకాశం 85% — వివరాలు AO (AO) లేదా KVK ని అడగండి.` | Prepared-text fixture | `28.8 డిగ్రీల సెల్సియస్`, `12.5 మిల్లీమీటర్లు`, `85 శాతం`, `ఏఓ`, `కేవీకే` substitutions are asserted | Deterministic normalization changes text; no acoustic/pronunciation score or final audio inspection. |

The “cut off mid-sentence” symptom is therefore not reproducible from repository tests alone. Capture redacted `input_chars`, `output_chars`, provider status, WAV duration, OGG duration, and TTS error class for the next demo run.

## 7. Data and knowledge base

The schema supports crops, crop varieties/stages, seasons, soil, water conditions, state/district/mandal/village, validity dates, review cycles, sources, and verification audits ([`app/db/database.py:132-250`](app/db/database.py:132)). Runtime adapters cover:

* PJTAU agromet advisories and static agricultural references (`app/knowledge/pjtau/`).
* TGDPS daily weather/rainfall reports (`app/knowledge/tgdps/`).
* WeatherAPI current conditions and 1–3 day forecast.
* Public IMD district warnings, including Telangana district mappings and 5-day day/date handling ([`app/weather/providers/imd_public_warning_adapter.py:1-55`](app/weather/providers/imd_public_warning_adapter.py:1)).

Checked-in raw PDF filenames show PJTAU documents dated `2026-10-02` and `2026-11-04`, and a TGDPS report dated `2026-11-07`; filenames are evidence of bundled files, not proof that every item is approved or current. The live database aggregate was not printed because the safe execution path was blocked; do not infer item counts from this report.

Mapping is metadata/location based: a request gets a `KnowledgeRetrievalFilter`, then approved and current records are passed as full evidence blocks. Weather facts are passed separately and cannot alone authorize crop advice. Missing or expired evidence yields abstention, not a source search.

Important gaps: no visible market-price corpus, no broad scheme eligibility corpus, no semantic crop/pest retrieval, no evidence coverage report by farmer question, no freshness dashboard, and no automated check that all translated Telugu content preserves the source meaning.

## 8. Multi-language readiness

### Current support

Prisma is called with `language_code` from normalized `te-IN`, `hi-IN`, or `en-IN`; Timbre receives the same normalized language but always uses voice `"Kaveri"` ([`app/voice/service.py:205-216`](app/voice/service.py:205), [`app/voice/service.py:457-475`](app/voice/service.py:457)). The repository documents Prisma/Timbre product versions but does not contain an authoritative catalogue proving Kannada, Tamil, or Marathi support. Verify those four languages with Gnani documentation before promising them.

### Telugu hardcoding

* Default language and unknown-language fallback: [`app/conversation/service.py:73-88`](app/conversation/service.py:73).
* Telegram text/voice requests force `te-IN`: [`app/telegram/handlers.py:321-337`](app/telegram/handlers.py:321).
* Telugu greetings, consent, missing-location, weather-error, abstention, and error messages are hardcoded across [`app/telegram/handlers.py:67-92`](app/telegram/handlers.py:67) and [`app/conversation/service.py:775-899`](app/conversation/service.py:775).
* Telegram TTS preparation, Kaveri voice, Telugu unit/acronym substitutions: [`app/voice/service.py:72-135`](app/voice/service.py:72), [`app/voice/service.py:457-475`](app/voice/service.py:457).
* Intent keyword lists exist for Telugu, Hindi, and English only ([`app/conversation/intent.py:30-170`](app/conversation/intent.py:30)).
* Knowledge defaults to `te-IN`; evidence language is not selected per user ([`app/db/database.py:152-157`](app/db/database.py:152)).
* IMD has Telugu and Hindi hazard text, but no Kannada/Tamil/Marathi equivalents in the inspected adapter ([`app/weather/providers/imd_public_warning_adapter.py:74-145`](app/weather/providers/imd_public_warning_adapter.py:74)).

### Minimum design for Hindi, Kannada, Tamil, Marathi

1. Confirm Prisma/Timbre language codes and voice names/limits from provider docs; add a capability test per language.
2. Create one `LanguageConfig` registry containing code, display name, STT code, TTS voice/model, greeting, consent/location/weather/error/abstention fallbacks, prompt style, unit map, and intent keywords.
3. Pass selected language from Telegram/session instead of forcing `te-IN`; retain a safe default.
4. Move prompts to per-language templates with a shared evidence/safety contract.
5. Add keyword/heuristic coverage plus test cases for each language; do not rely on LLM intent classification unless latency is accepted.
6. Add language-aware evidence selection or a translation step with explicit provenance; never silently mix untranslated evidence.
7. Add audio fixtures and human review for pronunciation, numerals, units, code-mixed crop names, and sentence completeness.

Do not scatter four more copies of every fallback through handlers. One registry should drive text and voice paths.

## 9. Tests and observability

The suite is broad but mostly mocked. README lists dedicated suites for Telegram, voice, LLM/safety, weather/IMD, knowledge ingestion, and review workflows ([`README.md:395-410`](README.md:395)). `tests/test_llm_service.py` explicitly uses mocked Groq completions and covers malformed JSON, citations, expiration, geography, unsupported numbers/chemicals, provider failures, and safe abstention. `tests/test_voice_pipeline.py` mocks STT/TTS and has a conditional live smoke test for the checked-in sample. `tests/test_telegram_integration.py` mocks Telegram, audio conversion, and voice service.

Real/external coverage is limited to optional live smoke tests and selected IMD live-read tests; mocked tests do not measure network latency, provider throttling, audio quality, or real Telugu grammar. There is no golden corpus with human labels for accuracy/friendliness/completeness.

Observability present:

* Per-request latency dictionaries in conversation and voice responses.
* Structured privacy-conscious Telegram stage log with total and component milliseconds.
* Groq usage metadata is parsed, but no durable metrics sink or percentile aggregation is visible.
* Validator logs violation count and violation strings, but there is no metric/counter, sampled rate, rule ID taxonomy, or dashboard.
* Transcript length is logged, but transcript content is not logged in the Telegram handler.

## 10. What is wrong with this architecture

Bluntly: it is over-engineered in policy surface and under-engineered in product feedback. There are several phases of consent/session/weather/knowledge/safety behavior, but no evaluation loop that tells the team which answer failed and why. The same echo/fallback concept is implemented in four layers. The system has a single huge prompt plus brittle regex checks, so one unsupported phrase can discard an otherwise useful answer. That is defense-in-depth only on paper; in user experience it is repeated refusal behavior.

The serial weather path is wasteful: current weather, forecast, and IMD warning are fetched sequentially before Groq, even though warning and forecast data can often be independent. The voice service synthesizes a response, then the Telegram handler may synthesize again for special flows or when it distrusts the response. HTTP clients are not consistently persistent: WeatherAPI creates a transient `httpx.Client` when no client is injected ([`app/weather/providers/weatherapi_provider.py:84-97`](app/weather/providers/weatherapi_provider.py:84)).

The evidence model is safer than an ungrounded chatbot but not a good retrieval system. “Approved” is treated as a binary gate, while relevance, contradiction, completeness, and language quality are not scored. A generic referral is safer than a hallucination but does not answer farmers’ questions. The system also claims multilingual readiness while the Telegram product path is Telugu-only and the voice registry is not truly per-language.

Technical debt includes duplicated fallback text, duplicated echo guards, mixed WhatsApp/Telegram abstractions, unbounded prompt evidence text, absent production metrics, hardcoded channel language, and tests that can pass unsafe text because dependencies are mocked. I disagree with adding more LLM safety passes: deterministic policy should be simpler and observable, while answer quality needs retrieval and evaluation.

### Top 10 problems, ranked by user impact

1. Generic/refusal output after any safety violation hides supported facts.
2. Retrieval is metadata/full-text-block based rather than question-semantic and relevance-ranked.
3. Telegram forces Telugu and Kaveri regardless of user language selection.
4. Long serial latency with weather, Groq, TTS, and Telegram network hops.
5. No sentence chunking or provider-limit handling for TTS.
6. No production accuracy/grammar/completeness evaluation set.
7. Multiple duplicated echo/fallback overrides can return the wrong clarification.
8. Weather forecast/current/IMD calls are sequential and can add several network delays.
9. Test fixtures overstate safety/voice confidence because STT/TTS/Telegram/Groq are mocked.
10. No durable metrics for guardrail triggers, provider failures, latency percentiles, or truncated audio.

### Fix plan

**Next three hours, lowest risk / highest gain**

1. Run the bounded timing probe and inspect the existing telemetry for one real demo path.
2. Fix duplicate TTS only: ensure a response synthesized by `VoicePipelineService` is reused by Telegram unless conversion/upload actually fails.
3. Cap the LLM answer contract to a short spoken answer at the prompt boundary, then add sentence-aware chunking only if the probe proves a provider-length issue.
4. Make refusal output preserve safe supported facts where possible; keep chemical/dosage refusal intact.
5. Add a small redacted evaluation table of 10 likely demo questions with expected intent, source, answer language, and “must not say” constraints.
6. Cache weather for the demo window and avoid IMD enrichment for non-warning questions unless it is required by the answer.

**Defer**

* Hindi/Kannada/Tamil/Marathi expansion, broad prompt refactoring, new model experiments, semantic retrieval, and provider migration.
* Parallel weather calls until provider cache/consent/error semantics are tested.
* Any redesign of the database review workflow.

**Do not touch before the demo**

* Do not remove approved-evidence gating, consent checks, chemical dosage checks, expiry checks, or IMD warning provenance.
* Do not change the database schema or seed data.
* Do not add a second LLM verifier or translate through another LLM.
* Do not change audio codec/sample rates without listening tests.
* Do not expose transcripts, user locations, credentials, or raw provider errors in logs.

## 11. Other reviewer-critical risks and known bugs

* The user-reported 9–10 s Telegram time and 4.5 s CLI time are not independently verified here. They measure different paths: Telegram adds download/upload and OGG conversion.
* `VoicePipelineService` estimates output duration from byte count as if all output were 48 kHz, 16-bit mono ([`app/voice/service.py:250-251`](app/voice/service.py:250)); this can be wrong if the provider returns another format.
* `_reply_voice_telugu` can send placeholder bytes `b"OggS_fallback_audio"` after conversion failure ([`app/telegram/handlers.py:468-482`](app/telegram/handlers.py:468), so the Telegram API may reject them or the user may receive a failed voice path.
* Broad exception handlers in Telegram preserve polling availability but can hide root cause from the user and reduce diagnostic precision ([`app/telegram/handlers.py:863-891`](app/telegram/handlers.py:863)).
* The validator’s dosage comparison checks the regex match against evidence text literally; harmless formatting differences can reject valid evidence.
* The validator’s geographic rule checks whether the farmer district appears in the set of evidence districts, which is conservative but can reject statewide evidence with incomplete metadata.
* The prompt asks for JSON and voice prose simultaneously; malformed JSON becomes a generic technical refusal.
* WeatherAPI’s provider documentation in code says current/forecast data is a nearby numerical grid estimate, not a farm station measurement. The product must not imply field-level precision.
* Public IMD HTML parsing is a dependency on a portal format; stale/unparseable data correctly abstains, but that path is not a substitute for an official authenticated API.
* The repository has uncommitted changes in core application and Telegram test files at inspection time. Any external review must first establish whether those changes are intended demo fixes.
* The checked-in `data/` and `data_seed/` databases should be treated as potentially containing user-related records; this report intentionally provides no row-level output.

## Appendix A — key source excerpts (trimmed)

The source of truth is linked above. The following short excerpts are deliberately limited to diagnostic lines rather than copying long prompts or secret-bearing configuration.

```python
# app/llm/service.py
raw_response = self.provider.generate_completion(messages=messages, json_mode=True)
validated_response = self.validator.validate(request, raw_response)
```

```python
# app/voice/service.py
stt_result = self.stt_client.transcribe(
    str(path_obj), language_code=target_lang, model="prisma-v3.0",
    format="transcribe", topic="Telangana farming and agriculture",
)
audio_bytes = self.tts_client.synthesize(
    text=spoken_text, voice="Kaveri", model="timbre-v2.5",
    language=target_lang, speed=0.95,
    audio_config=AudioConfig(container="wav", encoding="linear_pcm", sample_rate=48000),
)
```

```python
# app/llm/safety.py
if violations:
    return cls._create_safe_abstention(request, output, violations)
```

## Appendix B — timing probe contract

[`scripts/diagnostics/time_voice_pipeline.py`](scripts/diagnostics/time_voice_pipeline.py) is intentionally throwaway and bounded:

* same checked-in sample for all three runs;
* one local sample conversion;
* exactly three STT calls and three TTS calls maximum;
* no transcript, response, secret, identifier, or exception text printed;
* temporary WAV/OGG files removed before exit;
* Telegram network download/upload is not measured.
