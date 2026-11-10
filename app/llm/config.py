"""
LLM Configuration for KrishiVaani — Phase 7.2.
Provides validated settings for Groq Cloud API and the approved reasoning model openai/gpt-oss-120b.
"""

import os
from typing import Optional
from pydantic import BaseModel, Field
from app.core.config import settings


def mask_api_key(key: Optional[str]) -> str:
    """Safely mask an API key for logs without leaking secret characters."""
    if not key:
        return "<NOT_SET>"
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


class LLMConfig(BaseModel):
    """Configuration parameters for LLM provider operations."""
    model_config = {"protected_namespaces": ()}

    model_id: str = Field(default="openai/gpt-oss-120b", description="Approved reasoning model ID")
    api_key: Optional[str] = Field(default=None, description="Groq Cloud API key")
    temperature: float = Field(default=0.1, description="Low temperature for deterministic factual reasoning")
    max_tokens: int = Field(default=1500, description="Tokens allocated for reasoning chain and structured output")
    timeout_seconds: float = Field(default=15.0, description="Request timeout in seconds")
    max_retries: int = Field(default=2, description="Maximum network retry attempts")

    @classmethod
    def from_settings(cls) -> "LLMConfig":
        """Load LLM configuration from application settings and environment."""
        key = settings.GROQ_API_KEY or os.getenv("GROQ_API_KEY")
        return cls(
            model_id=getattr(settings, "GROQ_MODEL_ID", "openai/gpt-oss-120b"),
            api_key=key,
            temperature=getattr(settings, "GROQ_TEMPERATURE", 0.1),
            max_tokens=getattr(settings, "GROQ_MAX_TOKENS", 1500),
            timeout_seconds=getattr(settings, "GROQ_REQUEST_TIMEOUT_SECONDS", 15.0),
        )


def get_llm_config() -> LLMConfig:
    """Retrieve default LLM configuration instance."""
    return LLMConfig.from_settings()
