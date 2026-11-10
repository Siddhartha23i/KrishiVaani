"""
Text Conversation Orchestration Service for KrishiVaani — Phase 7.5.

Orchestrates end-to-end dialogue between farmers and KrishiVaani:
1. Resolves farmer profile context and validates consent.
2. Performs multilingual intent classification and routing.
3. Conditionally fetches weather observations/forecasts strictly with explicit sharing consent.
4. Retrieves currently valid, explicitly approved agricultural evidence from SQLite.
5. Invokes the Groq LLM reasoning service with strict evidence boundaries.
6. Enforces deterministic safety validation on final output text.
7. Produces voice-ready responses with complete latency and provenance metadata.

STRICT SAFETY GUARANTEES:
- Only explicitly approved knowledge items are supplied to the LLM.
- Zero approved records in the database results in safe abstention for agricultural recommendations.
- Weather data alone never triggers crop, irrigation, or chemical guidance.
- WeatherAPI is never invoked without verified weather_provider_sharing_consent.
- Zero database records are created or mutated during conversation processing.
"""

import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from datetime import date

from app.core.config import settings
from app.models.farmer import FarmerModel
from app.services.farmer_service import FarmerService
from app.weather.services.weather_service import WeatherService
from app.weather.disclaimers import get_weather_disclaimer
from app.weather.exceptions import (
    WeatherLocationSharingConsentRequiredError,
    LocationNotFoundError,
    LocationDistrictMismatchError,
    ForecastDaysLimitExceededError,
)
from app.llm.knowledge_adapter import (
    ApprovedKnowledgeAdapter,
    KnowledgeRetrievalFilter,
    EvidenceRetrievalResult,
)
from app.llm.service import LLMReasoningService
from app.llm.schemas import (
    LLMReasoningRequest,
    LLMResponseSchema,
    FarmerContextSchema,
    ApprovedEvidenceItem,
    WeatherFactItem,
)
from app.conversation.schemas import (
    ConversationRequest,
    ConversationResponse,
    LocationInput,
    WeatherMetadata,
    GuestWeatherConsentEvent,
)
from app.conversation.intent import (
    classify_intent,
    is_weather_query,
    is_weather_warning_query,
    is_lightning_safety_query,
    INTENT_WEATHER_INQUIRY,
    INTENT_CROP_RECOMMENDATION,
    INTENT_PEST_DISEASE_INQUIRY,
    INTENT_FERTILIZER_GUIDANCE,
    INTENT_GOVERNMENT_SCHEME,
    INTENT_AGRICULTURAL_ADVICE,
    INTENT_GENERAL_CONVERSATION,
)

logger = logging.getLogger(__name__)


def normalize_language(lang_input: Optional[str]) -> Tuple[str, str]:
    """
    Normalize language input into (standard_code, prompt_language_name).
    Returns: ('te-IN', 'Telugu'), ('hi-IN', 'Hindi'), or ('en-IN', 'English').
    """
    if not lang_input:
        return "te-IN", "Telugu"

    clean = lang_input.strip().lower()
    if clean.startswith("te") or "telugu" in clean:
        return "te-IN", "Telugu"
    elif clean.startswith("hi") or "hindi" in clean:
        return "hi-IN", "Hindi"
    elif clean.startswith("en") or "english" in clean:
        return "en-IN", "English"

    # Default to Telugu for Telangana farmers
    return "te-IN", "Telugu"


class ConversationOrchestrator:
    """
    Central orchestration service for KrishiVaani conversational interactions.
    Coordinates farmer context, weather retrieval, approved knowledge access,
    Groq LLM reasoning, and safety guardrails.
    """

    def __init__(
        self,
        farmer_service: Optional[FarmerService] = None,
        weather_service: Optional[WeatherService] = None,
        knowledge_adapter: Optional[ApprovedKnowledgeAdapter] = None,
        llm_service: Optional[LLMReasoningService] = None,
        db_path: Optional[Path] = None,
    ):
        self.db_path = db_path or settings.DATABASE_PATH
        self.farmer_service = farmer_service or FarmerService(db_path=self.db_path)
        self.weather_service = weather_service or WeatherService(farmer_service=self.farmer_service, db_path=self.db_path)
        self.knowledge_adapter = knowledge_adapter or ApprovedKnowledgeAdapter(db_path=self.db_path)
        self.llm_service = llm_service or LLMReasoningService()

    def process_message(self, request: ConversationRequest) -> ConversationResponse:
        """
        Process a text message from a farmer through the end-to-end orchestration pipeline.
        Never mutates the database.
        """
        start_total = time.perf_counter()
        latencies: Dict[str, float] = {}

        # 1. Normalize Language
        lang_code, prompt_lang = normalize_language(request.language)
        is_telegram = (getattr(request, "channel", None) == "telegram") or (bool(request.farmer_id) and request.farmer_id.startswith("tg_"))
        channel = "telegram" if is_telegram else (getattr(request, "channel", None) or "default")

        # 2. Farmer Context Resolution
        t0 = time.perf_counter()
        farmer_model, resolved_context, has_weather_consent = self._resolve_farmer_context(request)
        latencies["farmer_lookup_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        # 3. Intent Classification
        t0 = time.perf_counter()
        detected_intent = classify_intent(request.question)
        is_warning_q = is_weather_warning_query(request.question)
        # Phase 8.9: Lightning/thunderstorm safety questions must NOT be routed through
        # the weather forecast pipeline. They ask for precaution advice (which is served
        # by the approved PJTAU static_reference record) and do not need WeatherAPI data,
        # weather-provider consent, or location.
        is_lightning_safety = is_lightning_safety_query(request.question)
        needs_weather = (
            not is_lightning_safety
            and (is_weather_query(request.question) or (detected_intent == INTENT_WEATHER_INQUIRY) or is_warning_q)
        )
        latencies["intent_classification_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        # 3.1 Dedicated IMD District Weather Warning Flow (Phase 7.8)
        if is_warning_q:
            district = resolved_context.district if resolved_context else None
            if not district:
                # District not confirmed - strictly ask farmer to confirm district
                latencies["weather_retrieval_ms"] = 0.0
                latencies["safety_validation_ms"] = None
                latencies["safety_validation_status"] = "NOT_RUN"
                latencies["total_ms"] = round((time.perf_counter() - start_total) * 1000, 2)
                resp = self._create_district_confirmation_required_response(lang_code, channel=channel)
                resp.latency_breakdown_ms = latencies
                return resp

            t_w = time.perf_counter()
            warning_rec = self.weather_service.get_imd_district_warning(district, day="Day_1")
            formatted_text = self.weather_service.format_imd_warning_for_farmer(
                district, day="Day_1", language=prompt_lang
            )
            latencies["weather_retrieval_ms"] = round((time.perf_counter() - t_w) * 1000, 2)
            latencies["safety_validation_ms"] = 0.0
            latencies["safety_validation_status"] = "PASSED" if warning_rec.has_data else "ABSTAINED"
            latencies["total_ms"] = round((time.perf_counter() - start_total) * 1000, 2)

            meta = WeatherMetadata(
                source_name="India Meteorological Department (IMD)",
                source_url=warning_rec.source_url,
                retrieved_at=warning_rec.retrieved_at,
                issued_at=warning_rec.issue_date,
                is_grid_estimate=False,
                station_name="Meteorological Centre Hyderabad",
                freshness_status="CURRENT" if not warning_rec.is_stale else "STALE",
                disclaimer="Data provided by India Meteorological Department (IMD), Ministry of Earth Sciences, Government of India. This is district-level weather information only and not farm-specific guidance.",
                disclaimer_language=lang_code,
            )

            is_abst = not warning_rec.has_data
            return ConversationResponse(
                intent=INTENT_WEATHER_INQUIRY,
                language=lang_code,
                response_text=formatted_text,
                is_abstention=is_abst,
                evidence_citations=[],
                weather_metadata=meta,
                safety_status="PASSED" if not is_abst else "ABSTAINED",
                safety_validation_status="PASSED" if not is_abst else "ABSTAINED",
                safety_reason=None if not is_abst else "IMD_DATA_UNAVAILABLE",
                latency_breakdown_ms=latencies,
            )

        # 4. Weather Routing & Data Retrieval
        t0 = time.perf_counter()
        weather_facts: List[WeatherFactItem] = []
        weather_meta: Optional[WeatherMetadata] = None

        if needs_weather:
            weather_res = self._handle_weather_routing(
                request=request,
                farmer=farmer_model,
                resolved_context=resolved_context,
                has_consent=has_weather_consent,
                lang_code=lang_code,
                channel=channel,
            )
            latencies["weather_retrieval_ms"] = round((time.perf_counter() - t0) * 1000, 2)

            # If weather handling returned a terminal abstention (e.g. consent or location missing)
            if weather_res.get("terminal_response") is not None:
                latencies["safety_validation_ms"] = None
                latencies["safety_validation_status"] = "NOT_RUN"
                latencies["total_ms"] = round((time.perf_counter() - start_total) * 1000, 2)
                resp = weather_res["terminal_response"]
                resp.latency_breakdown_ms = latencies
                return resp

            weather_facts = weather_res.get("facts", [])
            weather_meta = weather_res.get("metadata")
        else:
            latencies["weather_retrieval_ms"] = 0.0

        # 5. Approved Knowledge Retrieval (Phase 7.3)
        t0 = time.perf_counter()
        retrieval_filter = KnowledgeRetrievalFilter(
            farmer_district=resolved_context.district if resolved_context else None,
            farmer_mandal=resolved_context.mandal if resolved_context else None,
            farmer_village=resolved_context.village if resolved_context else None,
            crop_name=resolved_context.crop_name if resolved_context else None,
            as_of_date=request.as_of_date,
        )
        evidence_result: EvidenceRetrievalResult = self.knowledge_adapter.retrieve_approved_evidence(retrieval_filter)
        approved_items = evidence_result.items
        latencies["knowledge_retrieval_ms"] = round((time.perf_counter() - t0) * 1000, 2)

        # 6. Groq LLM Reasoning Service Execution (Phase 7.2)
        t0 = time.perf_counter()

        llm_question = request.question
        if weather_facts and not approved_items:
            llm_question += " (Note: Weather facts are meteorological context. Set evidence_citations to [])."

        llm_request = LLMReasoningRequest(
            farmer_question=llm_question,
            language=prompt_lang,
            farmer_context=resolved_context,
            approved_evidence=approved_items,
            weather_facts=weather_facts,
            as_of_date=request.as_of_date,
            channel=channel,
        )
        llm_response: LLMResponseSchema = self.llm_service.process_query(llm_request)
        total_llm_ms = (time.perf_counter() - t0) * 1000
        val_ms = llm_response.validation_latency_ms if llm_response.validation_latency_ms is not None else 0.0
        latencies["llm_inference_ms"] = round(max(0.0, total_llm_ms - val_ms), 2)

        # 7. Post-Processing & Safety Gate
        valid_evidence_ids = {ev.evidence_id for ev in approved_items}
        filtered_citations = [cid for cid in llm_response.evidence_citations if cid in valid_evidence_ids]

        is_abstention = (
            llm_response.abstain
            or llm_response.safety_status in ("ABSTAINED", "REJECTED")
            or (len(approved_items) == 0 and detected_intent in (
                INTENT_CROP_RECOMMENDATION,
                INTENT_PEST_DISEASE_INQUIRY,
                INTENT_FERTILIZER_GUIDANCE,
                INTENT_GOVERNMENT_SCHEME,
            ))
        )

        safety_status = llm_response.safety_status
        if safety_status == "UNVERIFIED":
            safety_status = "ABSTAINED" if is_abstention else "PASSED"

        safety_reason = None
        if llm_response.safety_violations:
            safety_reason = "; ".join(llm_response.safety_violations)
        elif is_abstention and evidence_result.abstention_reason:
            safety_reason = evidence_result.abstention_reason

        # Synchronous validation latency measured via time.perf_counter_ns()
        latencies["safety_validation_ms"] = llm_response.validation_latency_ms
        latencies["safety_validation_status"] = safety_status
        latencies["total_ms"] = round((time.perf_counter() - start_total) * 1000, 2)

        # Defense-in-depth guardrail: Assistant response must never echo the user question
        q_clean = request.question.strip().strip(" !?,.:;~`'\"|•\t\n\r\u0964\u0965").lower()
        resp_clean = (llm_response.response or "").strip().strip(" !?,.:;~`'\"|•\t\n\r\u0964\u0965").lower()
        if resp_clean and resp_clean == q_clean:
            logger.warning("ConversationOrchestrator detected response echoing question. Overriding with safe clarification.")
            if needs_weather or detected_intent == INTENT_WEATHER_INQUIRY:
                resp = self._create_conflicting_location_clarification(lang_code, channel=channel)
                resp.latency_breakdown_ms = latencies
                return resp
            else:
                resp = self._create_location_required_abstention(lang_code, detected_intent=detected_intent, channel=channel)
                resp.latency_breakdown_ms = latencies
                return resp

        return ConversationResponse(
            intent=detected_intent or llm_response.intent,
            language=lang_code,
            response_text=llm_response.response,
            is_abstention=is_abstention,
            evidence_citations=filtered_citations,
            weather_metadata=weather_meta,
            safety_status=safety_status,
            safety_validation_status=safety_status,
            safety_reason=safety_reason,
            latency_breakdown_ms=latencies,
        )

    def _resolve_farmer_context(
        self, request: ConversationRequest
    ) -> Tuple[Optional[FarmerModel], Optional[FarmerContextSchema], bool]:
        """
        Safely resolve farmer profile and context without database mutation.
        Enforces strict consent provenance (Phase 7.5.1):
        - Registered farmer: requires recorded affirmative flag AND audit metadata (timestamp & disclosure version).
        - Guest: requires explicit, affirmative GuestWeatherConsentEvent with disclosure version & timestamp.
        - Untrusted boolean or GPS location sharing alone NEVER establishes consent.
        Returns: (farmer_model, resolved_context, has_weather_consent)
        """
        farmer: Optional[FarmerModel] = None
        has_consent = False

        # 1. Lookup stored farmer if farmer_id provided
        if request.farmer_id:
            try:
                farmer = self.farmer_service.get_farmer_by_id(request.farmer_id)
                if farmer:
                    is_flag_set = bool(getattr(farmer, "weather_provider_sharing_consent", False))
                    has_ts = bool(getattr(farmer, "weather_provider_sharing_consent_at", None))
                    has_version = bool(getattr(farmer, "weather_provider_disclosure_version", None))
                    # Stored farmer consent is trusted ONLY when affirmative flag AND audit metadata exist
                    if is_flag_set and has_ts and has_version:
                        has_consent = True
                        logger.info("Weather consent verified from stored profile '%s' (v%s).",
                                    farmer.farmer_id, farmer.weather_provider_disclosure_version)
                    else:
                        has_consent = False
                        logger.info("Stored farmer profile '%s' lacks verified weather sharing consent/metadata.", request.farmer_id)
                else:
                    logger.warning("Farmer profile '%s' not found; proceeding safely as unverified guest.", request.farmer_id)
            except Exception as e:
                logger.error("Safe handling: Error querying farmer profile '%s': %s", request.farmer_id, str(e))
                farmer = None

        # 2. Consent provenance for guest (Phase 7.5.1 Policy)
        # Plain untrusted boolean in LocationInput or ConversationRequest is REJECTED
        # Sharing WhatsApp GPS location alone NEVER implies consent to transmit to WeatherAPI
        if not has_consent and request.guest_consent:
            gc = request.guest_consent
            if (
                gc.consent_given is True
                and gc.disclosure_version and gc.disclosure_version.strip()
                and gc.consent_timestamp and gc.consent_timestamp.strip()
                and gc.channel and gc.channel.strip()
            ):
                has_consent = True
                logger.info("Guest weather sharing consent verified via explicit session event (v%s, channel=%s).",
                            gc.disclosure_version, gc.channel)
            else:
                logger.warning("Guest consent event rejected: missing affirmative flag, disclosure version, or timestamp.")

        # 3. Assemble FarmerContextSchema
        district = None
        mandal = None
        village = None
        preferred_lang = "Telugu"

        if farmer:
            district = farmer.district_name
            mandal = farmer.mandal_name
            village = farmer.village_name
            if farmer.preferred_language:
                _, prompt_lang = normalize_language(farmer.preferred_language)
                preferred_lang = prompt_lang

        # Request location overrides or supplements stored profile
        if request.location:
            loc = request.location
            if loc.district:
                district = loc.district
            if loc.mandal:
                mandal = loc.mandal
            if loc.village:
                village = loc.village

        # Extract location entities directly from question text if not provided in request location
        if not district or not village or not mandal:
            from app.telegram.session import extract_location_from_text
            qv, qm, qd, qp = extract_location_from_text(request.question)
            district = district or qd
            mandal = mandal or qm
            village = village or qv

        # Request context supplements stored profile
        crop_name = None
        soil_type = None
        water_source = None
        land_size = None

        if request.farmer_context:
            fc = request.farmer_context
            district = fc.district or district
            mandal = fc.mandal or mandal
            village = fc.village or village
            crop_name = fc.crop_name
            soil_type = fc.soil_type
            water_source = fc.water_source
            land_size = fc.land_size_acres
            if fc.preferred_language:
                preferred_lang = fc.preferred_language

        resolved_context = FarmerContextSchema(
            state="Telangana",
            district=district,
            mandal=mandal,
            village=village,
            crop_name=crop_name,
            soil_type=soil_type,
            water_source=water_source,
            land_size_acres=land_size,
            preferred_language=preferred_lang,
        )

        return farmer, resolved_context, has_consent

    def _handle_weather_routing(
        self,
        request: ConversationRequest,
        farmer: Optional[FarmerModel],
        resolved_context: Optional[FarmerContextSchema],
        has_consent: bool,
        lang_code: str,
        channel: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Handle meteorological query routing with strict privacy consent and location gates.
        Returns dict with keys: 'facts', 'metadata', and optional 'terminal_response'.
        """
        # RULE 1: Consent check
        if not has_consent:
            logger.info("Weather routing blocked: explicit weather_provider_sharing_consent is missing.")
            return {
                "terminal_response": self._create_consent_required_abstention(lang_code, detected_intent=INTENT_WEATHER_INQUIRY)
            }

        # RULE 1.5: Conflicting or ambiguous location check (do not silently pick an arbitrary location)
        from app.telegram.session import has_conflicting_locations

        has_confirmed_loc = bool(
            request.location and request.location.location_confirmed and (
                request.location.district or request.location.mandal or request.location.village
            )
        )
        if not has_confirmed_loc and has_conflicting_locations(request.question):
            logger.info("Weather routing blocked: Conflicting or ambiguous location references in question.")
            return {
                "terminal_response": self._create_conflicting_location_clarification(lang_code, channel=channel)
            }

        # RULE 2: Location check
        district = resolved_context.district if resolved_context else None
        mandal = resolved_context.mandal if resolved_context else None
        village = resolved_context.village if resolved_context else None
        has_coords = (
            farmer is not None
            and farmer.latitude is not None
            and farmer.longitude is not None
        ) or (
            request.location is not None
            and request.location.latitude is not None
            and request.location.longitude is not None
        )

        if not district and not village and not has_coords:
            logger.info("Weather routing blocked: insufficient location parameters provided.")
            return {
                "terminal_response": self._create_location_required_abstention(lang_code, detected_intent=INTENT_WEATHER_INQUIRY, channel=channel)
            }

        # RULE 3: Retrieve Weather via WeatherService or WeatherAPIProvider
        try:
            facts: List[WeatherFactItem] = []
            meta: Optional[WeatherMetadata] = None

            # Path A: Using stored farmer profile ID
            if farmer and farmer.farmer_id:
                curr_weather = self.weather_service.get_current_weather(farmer.farmer_id)
                forecast_weather = self.weather_service.get_forecast(farmer.farmer_id, days=3)

                # Format current conditions observation
                loc_name = getattr(curr_weather.location, "location_name", None) or district or "Telangana"
                obs_summary = (
                    f"WeatherAPI model/grid estimate for {loc_name}: "
                    f"Temperature {curr_weather.temperature_c}°C, Condition: {curr_weather.condition_text or 'Clear'}, "
                    f"Recent precipitation: {curr_weather.precipitation_mm or 0.0} mm, Humidity: {curr_weather.humidity_percent or 'N/A'}%. "
                    f"(Notice: This represents a nearby numerical model grid estimate, not an on-farm weather station measurement)."
                )
                facts.append(
                    WeatherFactItem(
                        district=district,
                        observation_time=curr_weather.issued_at or curr_weather.retrieved_at,
                        is_forecast=False,
                        temperature_c=curr_weather.temperature_c,
                        observed_rainfall_mm=curr_weather.observed_rainfall_mm,
                        summary=obs_summary,
                    )
                )

                # Format 3-day forecast
                day_summaries = []
                for d in forecast_weather.forecast_days:
                    day_summaries.append(
                        f"{d.date}: Rain {d.total_precipitation_mm} mm, Chance of rain {d.chance_of_rain_percent}% "
                        f"({d.condition_text or 'N/A'}, Max {d.max_temp_c}°C / Min {d.min_temp_c}°C)"
                    )
                fc_summary = (
                    f"WeatherAPI short-range 3-day forecast for {loc_name}: "
                    f"{'; '.join(day_summaries)}. (Probabilistic numerical model forecast)."
                )
                facts.append(
                    WeatherFactItem(
                        district=district,
                        observation_time=forecast_weather.issued_at or forecast_weather.retrieved_at,
                        is_forecast=True,
                        forecast_days=3,
                        forecast_rainfall_mm=sum(d.total_precipitation_mm for d in forecast_weather.forecast_days),
                        summary=fc_summary,
                    )
                )

                # Optional official IMD warning context (Phase 7.8) - fresh warnings only
                if district:
                    try:
                        imd_rec = self.weather_service.get_imd_district_warning(district, day="Day_1")
                        if imd_rec.has_data and not imd_rec.is_stale:
                            facts.append(
                                WeatherFactItem(
                                    district=district,
                                    observation_time=imd_rec.retrieved_at,
                                    is_forecast=True,
                                    forecast_days=1,
                                    forecast_rainfall_mm=None,
                                    summary=f"Official IMD District Warning for {district}: {imd_rec.warning_text} ({imd_rec.severity_color_name}). Source: India Meteorological Department (IMD).",
                                )
                            )
                    except Exception as exc:
                        logger.warning("Could not append IMD warning context for %s: %s", district, exc)

                meta = WeatherMetadata(
                    source_name=curr_weather.source_name,
                    source_url=curr_weather.source_url,
                    retrieved_at=curr_weather.retrieved_at,
                    issued_at=curr_weather.issued_at,
                    is_grid_estimate=True,
                    station_name=None,
                    freshness_status=curr_weather.freshness_status.value if hasattr(curr_weather.freshness_status, "value") else "CURRENT",
                    disclaimer=get_weather_disclaimer(lang_code),
                    disclaimer_language=lang_code,
                )

                return {"facts": facts, "metadata": meta}

            # Path B: Using caller-provided confirmed location (no stored profile ID)
            else:
                loc_input = request.location
                lat = loc_input.latitude if loc_input else None
                lon = loc_input.longitude if loc_input else None

                parts = [p for p in [village, mandal, district, "Telangana, India"] if p]
                query_str = f"{lat:.6f},{lon:.6f}" if (lat and lon) else ", ".join(parts)

                try:
                    curr_weather = self.weather_service.weatherapi_provider.get_current_weather(
                        query=query_str, lat=lat, lon=lon, language=lang_code
                    )
                    forecast_weather = self.weather_service.weatherapi_provider.get_forecast(
                        query=query_str, days=3, lat=lat, lon=lon, language=lang_code
                    )
                except LocationNotFoundError:
                    # If detailed village/mandal query fails on WeatherAPI, fallback to district
                    if district and query_str != f"{district}, Telangana, India":
                        fallback_query = f"{district}, Telangana, India"
                        logger.info("WeatherAPI location not found for '%s'; falling back to district '%s'", query_str, fallback_query)
                        curr_weather = self.weather_service.weatherapi_provider.get_current_weather(
                            query=fallback_query, language=lang_code
                        )
                        forecast_weather = self.weather_service.weatherapi_provider.get_forecast(
                            query=fallback_query, days=3, language=lang_code
                        )
                    else:
                        raise

                loc_name = getattr(curr_weather.location, "location_name", None) or district or "Telangana"
                obs_summary = (
                    f"WeatherAPI model/grid estimate for {loc_name}: "
                    f"Temperature {curr_weather.temperature_c}°C, Condition: {curr_weather.condition_text or 'Clear'}, "
                    f"Precipitation: {curr_weather.precipitation_mm or 0.0} mm. (Nearby numerical model grid estimate)."
                )
                facts.append(
                    WeatherFactItem(
                        district=district,
                        observation_time=curr_weather.issued_at or curr_weather.retrieved_at,
                        is_forecast=False,
                        temperature_c=curr_weather.temperature_c,
                        summary=obs_summary,
                    )
                )

                day_summaries = []
                for d in forecast_weather.forecast_days:
                    day_summaries.append(
                        f"{d.date}: Rain {d.total_precipitation_mm} mm, Chance of rain {d.chance_of_rain_percent}% "
                        f"({d.condition_text or 'N/A'}, Max {d.max_temp_c}°C / Min {d.min_temp_c}°C)"
                    )
                fc_summary = (
                    f"WeatherAPI 3-day forecast for {loc_name}: {'; '.join(day_summaries)}. (Probabilistic numerical model forecast)."
                )
                facts.append(
                    WeatherFactItem(
                        district=district,
                        observation_time=forecast_weather.issued_at or forecast_weather.retrieved_at,
                        is_forecast=True,
                        forecast_days=3,
                        forecast_rainfall_mm=sum(d.total_precipitation_mm for d in forecast_weather.forecast_days),
                        summary=fc_summary,
                    )
                )

                # Optional official IMD warning context (Phase 7.8) - fresh warnings only
                if district:
                    try:
                        imd_rec = self.weather_service.get_imd_district_warning(district, day="Day_1")
                        if imd_rec.has_data and not imd_rec.is_stale:
                            facts.append(
                                WeatherFactItem(
                                    district=district,
                                    observation_time=imd_rec.retrieved_at,
                                    is_forecast=True,
                                    forecast_days=1,
                                    forecast_rainfall_mm=None,
                                    summary=f"Official IMD District Warning for {district}: {imd_rec.warning_text} ({imd_rec.severity_color_name}). Source: India Meteorological Department (IMD).",
                                )
                            )
                    except Exception as exc:
                        logger.warning("Could not append IMD warning context for %s: %s", district, exc)

                meta = WeatherMetadata(
                    source_name=curr_weather.source_name,
                    source_url=curr_weather.source_url,
                    retrieved_at=curr_weather.retrieved_at,
                    issued_at=curr_weather.issued_at,
                    is_grid_estimate=True,
                    disclaimer=get_weather_disclaimer(lang_code),
                    disclaimer_language=lang_code,
                )

                return {"facts": facts, "metadata": meta}

        except WeatherLocationSharingConsentRequiredError:
            return {
                "terminal_response": self._create_consent_required_abstention(lang_code, detected_intent=INTENT_WEATHER_INQUIRY)
            }
        except (LocationNotFoundError, LocationDistrictMismatchError) as e:
            logger.warning("Weather location mismatch: %s", str(e))
            return {
                "terminal_response": self._create_location_required_abstention(lang_code, detected_intent=INTENT_WEATHER_INQUIRY, channel=channel)
            }
        except Exception as e:
            logger.error("Weather service query error: %s", str(e))
            return {
                "terminal_response": self._create_weather_service_error_abstention(lang_code, str(e), channel=channel)
            }

    def _create_consent_required_abstention(self, lang_code: str, detected_intent: str) -> ConversationResponse:
        """Create safe abstention when weather location sharing consent is absent."""
        if lang_code.startswith("te"):
            msg = (
                "వాతావరణ సమాచారం పొందడానికి మీ స్థాన వివరాలను వాతావరణ ప్రొవైడర్‌తో పంచుకోవడానికి "
                "మీ సమ్మతి అవసరం. దయచేసి వాతావరణ సేవలను పొందడానికి సమ్మతిని తెలపండి."
            )
        elif lang_code.startswith("hi"):
            msg = (
                "मौसम की जानकारी प्राप्त करने के लिए मौसम प्रदाता के साथ स्थान साझा करने की आपकी सहमति आवश्यक है। "
                "कृपया मौसम सेवाओं के लिए सहमति प्रदान करें।"
            )
        else:
            msg = (
                "To access weather information, your explicit consent to share your location with "
                "third-party weather providers is required under data privacy policy. Please provide consent to enable weather updates."
            )

        return ConversationResponse(
            intent=detected_intent,
            language=lang_code,
            response_text=msg,
            is_abstention=True,
            evidence_citations=[],
            weather_metadata=None,
            safety_status="ABSTAINED",
            safety_validation_status="NOT_RUN",
            safety_reason="WEATHER_LOCATION_SHARING_CONSENT_REQUIRED",
            latency_breakdown_ms={
                "safety_validation_ms": None,
                "safety_validation_status": "NOT_RUN",
            },
        )

    def _create_conflicting_location_clarification(
        self, lang_code: str, channel: Optional[str] = None
    ) -> ConversationResponse:
        """Create safe clarification guidance when conflicting or ambiguous location parameters are provided."""
        if lang_code.startswith("te"):
            msg = "మీరు వేర్వేరు ప్రాంతాల పేర్లు చెప్పారు అండి. మీకు ఏ ఊరు లేదా మండలం వాతావరణ వివరాలు కావాలో స్పష్టంగా చెప్తారా?"
        elif lang_code.startswith("hi"):
            msg = "आपने अलग-अलग स्थानों के नाम बताए हैं। कृपया स्पष्ट करें कि आपको किस गांव या मंडल के मौसम की जानकारी चाहिए।"
        else:
            msg = "You mentioned multiple different locations. Please clarify which village or mandal in Telangana you need weather details for."

        return ConversationResponse(
            intent=INTENT_WEATHER_INQUIRY,
            language=lang_code,
            response_text=msg,
            is_abstention=True,
            evidence_citations=[],
            weather_metadata=None,
            safety_status="ABSTAINED",
            safety_validation_status="NOT_RUN",
            safety_reason="LOCATION_PARAMETERS_REQUIRED",
            latency_breakdown_ms={
                "safety_validation_ms": None,
                "safety_validation_status": "NOT_RUN",
            },
        )

    def _create_location_required_abstention(
        self, lang_code: str, detected_intent: str, channel: Optional[str] = None
    ) -> ConversationResponse:
        """Create safe abstention when location is missing or ambiguous."""
        if lang_code.startswith("te"):
            if channel == "telegram":
                msg = "మీ ఊరి వాతావరణ వివరాల కోసం, మీది ఏ మండలం లేదా జిల్లానో చెప్తారా అండి?"
            else:
                msg = "వాతావరణ సమాచారం తెలుసుకోవడానికి దయచేసి మీ జిల్లా లేదా మండల పేరును తెలపండి."
        elif lang_code.startswith("hi"):
            msg = "मौसम की जानकारी के लिए कृपया अपने जिले या मंडल का नाम बताएं।"
        else:
            msg = "Please specify your district or mandal in Telangana to check localized weather conditions."

        return ConversationResponse(
            intent=detected_intent,
            language=lang_code,
            response_text=msg,
            is_abstention=True,
            evidence_citations=[],
            weather_metadata=None,
            safety_status="ABSTAINED",
            safety_validation_status="NOT_RUN",
            safety_reason="LOCATION_PARAMETERS_REQUIRED",
            latency_breakdown_ms={
                "safety_validation_ms": None,
                "safety_validation_status": "NOT_RUN",
            },
        )

    def _create_weather_service_error_abstention(
        self, lang_code: str, error_detail: str, channel: Optional[str] = None
    ) -> ConversationResponse:
        """Create safe fallback when weather provider fails."""
        if lang_code.startswith("te"):
            if channel == "telegram":
                msg = "సాంకేతిక సమస్య వల్ల ప్రస్తుతం వాతావరణ రిపోర్ట్ అందడం లేదు అండి. దయచేసి కాసేపటి తర్వాత అడగండి."
            else:
                msg = "సాంకేతిక సమస్య కారణంగా ప్రస్తుతం వాతావరణ సమాచారం అందుబాటులో లేదు. దయచేసి కాసేపటి తర్వాత ప్రయత్నించండి."
        elif lang_code.startswith("hi"):
            msg = "तकनीकी समस्या के कारण वर्तमान में मौसम की जानकारी उपलब्ध नहीं है। कृपया कुछ समय बाद पुनः प्रयास करें।"
        else:
            msg = "Weather information is temporarily unavailable due to a service error. Please try again shortly."

        return ConversationResponse(
            intent=INTENT_WEATHER_INQUIRY,
            language=lang_code,
            response_text=msg,
            is_abstention=True,
            evidence_citations=[],
            weather_metadata=None,
            safety_status="ABSTAINED",
            safety_validation_status="NOT_RUN",
            safety_reason=f"WEATHER_PROVIDER_FAILURE: {error_detail}",
            latency_breakdown_ms={
                "safety_validation_ms": None,
                "safety_validation_status": "NOT_RUN",
            },
        )

    def _create_district_confirmation_required_response(
        self, lang_code: str, channel: Optional[str] = None
    ) -> ConversationResponse:
        """Create safe guidance asking the farmer to confirm their Telangana district for IMD warnings."""
        if lang_code.startswith("te"):
            if channel == "telegram":
                msg = "వాతావరణ హెచ్చరికలు తెలుసుకోవడానికి, మీది తెలంగాణలో ఏ జిల్లానో చెప్తారా అండి?"
            else:
                msg = "అధికారిక IMD వాతావరణ హెచ్చరికలను తనిఖీ చేయడానికి దయచేసి తెలంగాణలోని మీ జిల్లాను తెలియజేయండి."
        elif lang_code.startswith("hi"):
            msg = "आधिकारिक IMD मौसम चेतावनियों की जांच के लिए कृपया तेलंगाना में अपने जिले की पुष्टि करें।"
        else:
            msg = "Please confirm your district in Telangana to check official IMD district weather warnings."

        return ConversationResponse(
            intent=INTENT_WEATHER_INQUIRY,
            language=lang_code,
            response_text=msg,
            is_abstention=True,
            evidence_citations=[],
            weather_metadata=None,
            safety_status="ABSTAINED",
            safety_validation_status="NOT_RUN",
            safety_reason="DISTRICT_CONFIRMATION_REQUIRED",
            latency_breakdown_ms={
                "safety_validation_ms": None,
                "safety_validation_status": "NOT_RUN",
            },
        )
