"""
Groq LLM Provider implementation for KrishiVaani — Phase 7.2.
Integrates openai/gpt-oss-120b with secure authentication, timeouts,
structured exception handling, token usage tracking, and safe logging.
"""

import time
import json
import logging
from typing import Optional, Dict, Any, List
from groq import (
    Groq,
    APIError,
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
    InternalServerError,
)

from app.llm.config import LLMConfig, get_llm_config, mask_api_key
from app.llm.schemas import LLMResponseSchema
from app.llm.exceptions import (
    LLMProviderNotConfiguredError,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMProviderUnavailableError,
    LLMTimeoutError,
    LLMMalformedResponseError,
)

logger = logging.getLogger(__name__)


class GroqProvider:
    """
    Groq Cloud LLM provider wrapping openai/gpt-oss-120b.
    Implements secure credential management, JSON schema enforcement,
    and structured exception mapping.
    """

    def __init__(self, config: Optional[LLMConfig] = None, client: Optional[Groq] = None):
        self.config = config or get_llm_config()
        self.model_id = self.config.model_id
        
        if not self.config.api_key:
            logger.warning("GroqProvider initialized without GROQ_API_KEY. Live calls will fail.")
            self._client = client
        else:
            masked = mask_api_key(self.config.api_key)
            logger.info("Initializing GroqProvider for model '%s' with key %s", self.model_id, masked)
            self._client = client or Groq(
                api_key=self.config.api_key,
                timeout=self.config.timeout_seconds,
                max_retries=self.config.max_retries,
            )

    @property
    def client(self) -> Groq:
        if self._client is None:
            raise LLMProviderNotConfiguredError(
                message="GROQ_API_KEY is not configured. Cannot perform inference.",
                provider="groq"
            )
        return self._client

    def generate_completion(
        self,
        messages: List[Dict[str, str]],
        json_mode: bool = True,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
    ) -> LLMResponseSchema:
        """
        Execute chat completion against Groq API and parse response into LLMResponseSchema.
        
        Args:
            messages: List of chat messages (system, user, assistant).
            json_mode: Whether to enforce JSON object generation.
            max_tokens: Optional token limit override.
            temperature: Optional temperature override.
            
        Returns:
            Validated LLMResponseSchema.
            
        Raises:
            LLMProviderNotConfiguredError: If credentials are missing.
            LLMAuthenticationError: On HTTP 401/403.
            LLMRateLimitError: On HTTP 429.
            LLMTimeoutError: On request timeout.
            LLMProviderUnavailableError: On HTTP 5xx or connection loss.
            LLMMalformedResponseError: On unparseable or schema-violating output.
        """
        groq_client = self.client
        tokens_to_request = max_tokens or self.config.max_tokens
        temp_to_request = temperature if temperature is not None else self.config.temperature

        kwargs: Dict[str, Any] = {
            "model": self.model_id,
            "messages": messages,
            "temperature": temp_to_request,
            "max_tokens": tokens_to_request,
            "reasoning_effort": self.config.reasoning_effort,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        logger.debug(
            "Executing Groq chat completion (model=%s, json_mode=%s, max_tokens=%d)",
            self.model_id, json_mode, tokens_to_request
        )

        t0 = time.perf_counter()
        try:
            completion = groq_client.chat.completions.create(**kwargs)
            elapsed_ms = (time.perf_counter() - t0) * 1000
        except AuthenticationError as e:
            logger.error("Groq authentication failure: HTTP 401/403")
            raise LLMAuthenticationError(
                message=f"Groq API authentication failed: {e.message}",
                provider="groq",
                details={"error_type": "AuthenticationError"}
            ) from e
        except RateLimitError as e:
            logger.warning("Groq rate limit exceeded: HTTP 429")
            raise LLMRateLimitError(
                message=f"Groq API rate limit or quota exceeded: {e.message}",
                provider="groq",
                details={"error_type": "RateLimitError"}
            ) from e
        except APITimeoutError as e:
            logger.error("Groq request timed out after %.1fs", self.config.timeout_seconds)
            raise LLMTimeoutError(
                message=f"Groq API request timed out after {self.config.timeout_seconds}s",
                provider="groq",
                details={"timeout_seconds": self.config.timeout_seconds}
            ) from e
        except (APIConnectionError, InternalServerError) as e:
            logger.error("Groq provider service unavailable or connection failed: %s", str(e))
            raise LLMProviderUnavailableError(
                message=f"Groq API service unavailable: {str(e)}",
                provider="groq",
                details={"error_type": type(e).__name__}
            ) from e
        except APIError as e:
            logger.error("Groq API error (status=%s): %s", getattr(e, "status_code", "unknown"), str(e))
            raise LLMProviderUnavailableError(
                message=f"Groq API returned error: {str(e)}",
                provider="groq",
                details={"status_code": getattr(e, "status_code", None)}
            ) from e
        except Exception as e:
            logger.error("Unexpected error during Groq completion: %s", str(e))
            raise LLMProviderUnavailableError(
                message=f"Unexpected failure in Groq provider: {str(e)}",
                provider="groq",
            ) from e

        # Extract content and metadata
        try:
            choice = completion.choices[0]
            raw_text = choice.message.content or ""
            usage_obj = completion.usage
            usage_dict = {
                "prompt_tokens": usage_obj.prompt_tokens,
                "completion_tokens": usage_obj.completion_tokens,
                "total_tokens": usage_obj.total_tokens,
            } if usage_obj else {}
        except (IndexError, AttributeError) as e:
            raise LLMMalformedResponseError(
                message="Groq completion returned empty or missing choices",
                provider="groq",
            ) from e

        if not json_mode:
            # Fallback if non-JSON requested
            return LLMResponseSchema(
                intent="general_inquiry",
                language="English",
                required_information=[],
                supported_facts=[],
                unsupported_questions=[],
                abstain=False,
                response=raw_text,
                model_id=self.model_id,
                latency_ms=elapsed_ms,
                usage=usage_dict,
                safety_status="UNVERIFIED",
            )

        # Parse and validate JSON
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError as e:
            logger.error("Failed to decode JSON from Groq completion: %s", raw_text[:200])
            raise LLMMalformedResponseError(
                message=f"Groq returned malformed unparseable JSON: {str(e)}",
                provider="groq",
                details={"raw_content": raw_text[:300]}
            ) from e

        if not isinstance(data, dict):
            raise LLMMalformedResponseError(
                message="Groq returned JSON that is not an object",
                provider="groq",
                details={"data_type": type(data).__name__}
            )

        try:
            response_schema = LLMResponseSchema(
                intent=data.get("intent", "unclassified"),
                language=data.get("language", "Telugu"),
                required_information=data.get("required_information", []),
                supported_facts=data.get("supported_facts", []),
                unsupported_questions=data.get("unsupported_questions", []),
                abstain=bool(data.get("abstain", False)),
                response=data.get("response", ""),
                evidence_citations=data.get("evidence_citations", []),
                model_id=self.model_id,
                latency_ms=elapsed_ms,
                usage=usage_dict,
                safety_status="UNVERIFIED",
            )
            return response_schema
        except Exception as e:
            logger.error("Groq JSON object failed schema validation: %s", str(e))
            raise LLMMalformedResponseError(
                message=f"Groq response violated required schema: {str(e)}",
                provider="groq",
                details={"parsed_json": data}
            ) from e
