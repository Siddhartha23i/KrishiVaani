"""Sarvam chat-completions provider for KrishiVaani."""

import json
import logging
import time
import math
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.llm.exceptions import (
    LLMAuthenticationError,
    LLMMalformedResponseError,
    LLMProviderNotConfiguredError,
    LLMProviderUnavailableError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from app.llm.schemas import LLMResponseSchema

logger = logging.getLogger(__name__)


class SarvamProvider:
    """Persistent HTTP client for Sarvam's OpenAI-compatible chat endpoint."""

    ENDPOINT = "https://api.sarvam.ai/v1/chat/completions"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
        max_tokens: Optional[int] = None,
        client: Optional[httpx.Client] = None,
    ):
        self.api_key = api_key if api_key is not None else settings.SARVAM_API_KEY
        self.model_id = model_id or getattr(settings, "SARVAM_MODEL", "sarvam-105b-conversations")
        self.max_tokens = max_tokens or getattr(settings, "SARVAM_MAX_TOKENS", 900)
        self.length_retry_multiplier = getattr(settings, "SARVAM_LENGTH_RETRY_MULTIPLIER", 1.5)
        self._client = client or httpx.Client(timeout=12.0)

    @property
    def client(self) -> httpx.Client:
        if not self.api_key:
            raise LLMProviderNotConfiguredError(
                message="SARVAM_API_KEY is not configured. Cannot perform inference.",
                provider="sarvam",
            )
        return self._client

    def generate_completion(
        self,
        messages: List[Dict[str, str]],
        json_mode: bool = True,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        _length_retry_attempt: bool = False,
    ) -> LLMResponseSchema:
        tokens_to_request = max_tokens or self.max_tokens
        temp_to_request = temperature if temperature is not None else 0.2
        payload: Dict[str, Any] = {
            "model": self.model_id,
            "messages": messages,
            "temperature": temp_to_request,
            "max_tokens": tokens_to_request,
            "reasoning_effort": None,
        }
        if json_mode:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "krishivaani_response",
                    "strict": True,
                    "schema": LLMResponseSchema.model_json_schema(),
                },
            }

        headers = {
            "api-subscription-key": self.api_key or "",
            "Content-Type": "application/json",
        }
        started = time.perf_counter()
        response: Optional[httpx.Response] = None
        for attempt in range(2):
            try:
                response = self.client.post(self.ENDPOINT, headers=headers, json=payload)
                if response.status_code in (408, 429) or response.status_code >= 500:
                    if attempt == 0:
                        continue
                break
            except httpx.TimeoutException as exc:
                if attempt == 0:
                    continue
                raise LLMTimeoutError(
                    message="Sarvam request timed out after 12.0s",
                    provider="sarvam",
                    details={"timeout_seconds": 12.0},
                ) from exc
            except httpx.RequestError as exc:
                if attempt == 0:
                    continue
                raise LLMProviderUnavailableError(
                    message="Sarvam provider connection failed.",
                    provider="sarvam",
                    details={"error_type": type(exc).__name__},
                ) from exc

        if response is None:
            raise LLMProviderUnavailableError(
                message="Sarvam provider returned no response.",
                provider="sarvam",
            )
        self._raise_for_status(response)

        try:
            body = response.json()
            choice = body["choices"][0]
            message = choice["message"]
            raw_text = message.get("content") or ""
            finish_reason = choice.get("finish_reason")
            usage = body.get("usage") or {}
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMMalformedResponseError(
                message="Sarvam returned an invalid completion response.",
                provider="sarvam",
            ) from exc

        logger.info(
            "Sarvam token usage: prompt=%s completion=%s total=%s",
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            usage.get("total_tokens"),
        )
        if not raw_text or finish_reason == "length":
            if finish_reason == "length" and not _length_retry_attempt:
                return self.generate_completion(
                    messages=messages,
                    json_mode=json_mode,
                    max_tokens=max(
                        tokens_to_request + 1,
                        math.ceil(tokens_to_request * self.length_retry_multiplier),
                    ),
                    temperature=temperature,
                    _length_retry_attempt=True,
                )
            raise LLMMalformedResponseError(
                message="Sarvam returned empty or truncated completion content.",
                provider="sarvam",
            )
        if not json_mode:
            return LLMResponseSchema(
                intent="general_inquiry",
                language="English",
                response=raw_text,
                abstain=False,
                model_id=self.model_id,
                latency_ms=(time.perf_counter() - started) * 1000,
                usage=self._usage_dict(usage),
                safety_status="UNVERIFIED",
            )

        try:
            data = json.loads(raw_text)
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
                latency_ms=(time.perf_counter() - started) * 1000,
                usage=self._usage_dict(usage),
                safety_status="UNVERIFIED",
            )
            return response_schema
        except (ValueError, TypeError, AttributeError) as exc:
            raise LLMMalformedResponseError(
                message="Sarvam returned malformed or schema-invalid JSON.",
                provider="sarvam",
            ) from exc

    @staticmethod
    def _usage_dict(usage: Dict[str, Any]) -> Dict[str, int]:
        return {
            key: int(usage[key])
            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            if usage.get(key) is not None
        }

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        if status in (401, 403):
            raise LLMAuthenticationError(
                message="Sarvam authentication failed.",
                provider="sarvam",
                details={"http_status": status},
            )
        if status == 429:
            raise LLMRateLimitError(
                message="Sarvam rate limit exceeded.",
                provider="sarvam",
                details={"http_status": status},
            )
        if status in (408, 504):
            raise LLMTimeoutError(
                message="Sarvam request timed out.",
                provider="sarvam",
                details={"http_status": status},
            )
        if status >= 500:
            raise LLMProviderUnavailableError(
                message="Sarvam service is unavailable.",
                provider="sarvam",
                details={"http_status": status},
            )
        if status >= 400:
            raise LLMProviderUnavailableError(
                message="Sarvam request failed.",
                provider="sarvam",
                details={"http_status": status},
            )
