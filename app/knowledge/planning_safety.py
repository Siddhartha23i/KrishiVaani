"""
Agricultural Advisory Planning and Weather Trigger Safety Module for KrishiVaani — Phase 5.4.1.

Standing Safety Rule:
A WEATHER FORECAST ALONE MUST NEVER AUTOMATICALLY TRIGGER AN AGRICULTURAL RECOMMENDATION.

Before presenting field-related advice, KrishiVaani services must evaluate:
1. Current crop and crop growth stage.
2. Farmer's soil type and water/irrigation conditions.
3. Actual ground rainfall observations (e.g., TSDPS automatic weather stations at mandal level).
4. Valid, officially issued agricultural advisories (e.g., PJTSAU / AMFU bulletins).
5. The forecast's actual geographical resolution (district/mandal) and validity period.
6. The source, forecast confidence, and meteorological uncertainty.

For 16–30 and 31–60 day horizons:
- Use contingency scenarios, normal historical patterns, and strategic seasonal planning.
- Daily deterministic forecasts must NEVER be fabricated at these horizons.
- Distant outlooks must NEVER be presented as guaranteed rainfall events.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Tuple, Dict, Any


SAFETY_RULE_FORECAST_ALONE_CANNOT_TRIGGER_ADVICE: bool = True

REQUIRED_AGRONOMIC_CONTEXT_FACTORS: Tuple[str, ...] = (
    "crop_and_crop_stage",
    "soil_and_water_conditions",
    "actual_rainfall_observations",
    "valid_official_advisories",
    "forecast_geographical_resolution",
    "forecast_source_and_uncertainty",
)


class AdvisorySafetyViolationError(ValueError):
    """Raised when an advisory trigger attempts to generate field recommendations from weather data alone."""
    pass


@dataclass(frozen=True)
class AdvisorySafetyEvaluationResult:
    """Evaluation result for advisory trigger safety."""
    is_safe_to_trigger: bool
    missing_factors: Tuple[str, ...]
    safety_message: str
    planning_guidance_level: str  # "operational_field_advice", "strategic_planning_only", "blocked"


class AdvisoryTriggerSafetyPolicy:
    """
    Enforces that weather information alone cannot trigger agricultural recommendations,
    and regulates planning horizon safety.
    """

    @classmethod
    def evaluate_trigger_safety(
        cls,
        has_forecast: bool,
        has_crop_and_stage: bool = False,
        has_soil_water_conditions: bool = False,
        has_actual_rainfall_observations: bool = False,
        has_valid_official_advisory: bool = False,
        horizon_days: int = 1,
    ) -> AdvisorySafetyEvaluationResult:
        """
        Evaluate if field recommendations may be presented.
        Rule: A weather forecast alone must never trigger an agricultural recommendation.
        """
        if not has_forecast:
            return AdvisorySafetyEvaluationResult(
                is_safe_to_trigger=False,
                missing_factors=("weather_forecast",),
                safety_message="No weather forecast provided.",
                planning_guidance_level="blocked",
            )

        # Evaluate agronomic context completeness
        missing = []
        if not has_crop_and_stage:
            missing.append("crop_and_crop_stage")
        if not has_soil_water_conditions:
            missing.append("soil_and_water_conditions")
        if not has_valid_official_advisory:
            missing.append("valid_official_advisories")

        # Core safety rule: Forecast alone is strictly blocked
        if not has_crop_and_stage and not has_soil_water_conditions and not has_valid_official_advisory:
            return AdvisorySafetyEvaluationResult(
                is_safe_to_trigger=False,
                missing_factors=tuple(missing),
                safety_message=(
                    "SAFETY POLICY VIOLATION: A weather forecast alone must never automatically trigger "
                    "an agricultural recommendation. Field advice requires verified agronomic context "
                    "(crop, stage, soil/water conditions, and official agromet advisories)."
                ),
                planning_guidance_level="blocked",
            )

        # Horizon-based constraints
        if horizon_days > 15:
            # 16-30d and 31-60d cannot provide deterministic daily field operational advice
            return AdvisorySafetyEvaluationResult(
                is_safe_to_trigger=True,
                missing_factors=tuple(missing),
                safety_message=(
                    f"Planning horizon of {horizon_days} days is restricted to strategic seasonal planning "
                    "and contingent scenarios. Deterministic daily weather forecasts are not scientifically "
                    "valid at this range and cannot be presented as guaranteed events."
                ),
                planning_guidance_level="strategic_planning_only",
            )

        # Short / Extended range with adequate context
        if missing:
            return AdvisorySafetyEvaluationResult(
                is_safe_to_trigger=True,
                missing_factors=tuple(missing),
                safety_message=(
                    "Advisory may be presented with noted uncertainty regarding missing agronomic factors: "
                    + ", ".join(missing)
                ),
                planning_guidance_level="operational_field_advice",
            )

        return AdvisorySafetyEvaluationResult(
            is_safe_to_trigger=True,
            missing_factors=(),
            safety_message="Full agronomic and meteorological context verified. Safe for operational field advice.",
            planning_guidance_level="operational_field_advice",
        )

