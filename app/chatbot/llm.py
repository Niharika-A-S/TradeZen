"""Official google-genai SDK wrapper for TradeZen Chatbot with safe JSON serialization and resiliency."""
from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime, date
import json
import logging
import os
import random
import socket
import ssl
import threading
import time
from typing import List, Optional, Union, Dict, Any
import uuid

import numpy as np

from .config import cfg

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Safe JSON Serializer for Database Facts & Profile Data
# ---------------------------------------------------------------------------

class SafeJSONEncoder(json.JSONEncoder):
    """Safe JSON encoder handling Decimal, datetime, date, UUID, numpy types."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            f = float(obj)
            return int(f) if f.is_integer() else f
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
        if isinstance(obj, uuid.UUID):
            return str(obj)
        module = getattr(type(obj), "__module__", "")
        if "numpy" in module:
            if isinstance(obj, np.floating):
                f = float(obj)
                return int(f) if f.is_integer() else f
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
        if hasattr(obj, "isoformat"):
            return obj.isoformat()
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)


def safe_json_dumps(obj: Any, **kwargs) -> str:
    """Serializes arbitrary facts/dicts to JSON without throwing TypeError on DB types."""
    kwargs.setdefault("ensure_ascii", False)
    kwargs.setdefault("cls", SafeJSONEncoder)
    try:
        return json.dumps(obj, **kwargs)
    except Exception as exc:
        logger.warning("safe_json_dumps fallback triggered: %s", exc)
        return json.dumps(str(obj))


# ---------------------------------------------------------------------------
# LLM Data Structures & Circuit Breaker
# ---------------------------------------------------------------------------

@dataclass
class LLMResult:
    ok: bool
    text: Optional[str] = None
    vectors: Optional[List[List[float]]] = None
    error_kind: Optional[str] = None  # 'NO_KEY', 'CIRCUIT_OPEN', 'RATE_LIMIT', 'TIMEOUT', 'BLOCKED', 'EMPTY',
    # 'CONNECT_ERROR', 'DNS_ERROR', 'TLS_ERROR', 'CLIENT_ERROR_4XX', 'SERVER_ERROR_5XX',
    # 'SERIAL_ERROR', 'UNKNOWN_ERROR:<classname>'  — never 'NETWORK_ERROR' for unrecognised exceptions


class CircuitBreaker:
    """Thread-safe circuit breaker that trips after consecutive failures, self-recovering half-open."""
    def __init__(self, failure_threshold: int = 3, recovery_time: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_time = recovery_time
        self.consecutive_failures = 0
        self.last_failure_time = 0.0
        self._lock = threading.Lock()

    def allow_request(self, current_time: Optional[float] = None) -> bool:
        now = current_time if current_time is not None else time.time()
        with self._lock:
            if self.consecutive_failures >= self.failure_threshold:
                if now - self.last_failure_time > self.recovery_time:
                    # Half-open: allow a trial request and reset counter
                    self.consecutive_failures = 0
                    return True
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            self.consecutive_failures = 0

    def record_failure(self, current_time: Optional[float] = None) -> None:
        now = current_time if current_time is not None else time.time()
        with self._lock:
            self.consecutive_failures += 1
            self.last_failure_time = now

    @property
    def state(self) -> str:
        with self._lock:
            if self.consecutive_failures >= self.failure_threshold:
                if time.time() - self.last_failure_time > self.recovery_time:
                    return "half-open"
                return "open"
            return "closed"


# ---------------------------------------------------------------------------
# Exception → error_kind classifier  (type-based, never string-scanning)
# ---------------------------------------------------------------------------

def _classify_exception(exc: Exception) -> str:
    """Classify an LLM-call exception into a human-readable error_kind string.

    Rules
    -----
    - Type-based checks first (precise).
    - HTTP status code extracted from google-genai ClientError / ServerError
      attributes when available.
    - String scanning ONLY as a last resort for 429 / 5xx codes that some SDK
      wrappers embed in the message without exposing a status attribute.
    - Unknown exceptions → ``UNKNOWN_ERROR:<ClassName>`` — never ``NETWORK_ERROR``.
    """
    # --- serialisation errors (must be checked before anything else) --------
    if isinstance(exc, (TypeError, ValueError)):
        return "SERIAL_ERROR"

    # --- timeouts -----------------------------------------------------------
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "TIMEOUT"

    # --- TLS / SSL ----------------------------------------------------------
    if isinstance(exc, ssl.SSLError):
        return "TLS_ERROR"

    # --- DNS ----------------------------------------------------------------
    if isinstance(exc, socket.gaierror):
        return "DNS_ERROR"

    # --- connection refused / reset / aborted etc. --------------------------
    if isinstance(exc, ConnectionError):                     # includes ConnectionRefusedError, ConnectionResetError
        return "CONNECT_ERROR"
    if isinstance(exc, OSError) and getattr(exc, "errno", None) in (
        111,    # ECONNREFUSED (Linux)
        10061,  # WSAECONNREFUSED (Windows)
        10013,  # WSAEACCES (Windows)
    ):
        return "CONNECT_ERROR"

    # --- google-genai SDK exceptions ----------------------------------------
    # Try extracting HTTP status from the exception object (google.genai wraps
    # HTTP errors in its own exception types with a `status_code` or `code` attr).
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status is not None:
        try:
            status = int(status)
        except (TypeError, ValueError):
            status = None
    if status is not None:
        if status == 429:
            return "RATE_LIMIT"
        if 400 <= status < 500:
            return f"CLIENT_ERROR_{status}"
        if 500 <= status < 600:
            return "SERVER_ERROR_5XX"

    # --- string fallback for SDKs that embed status only in the message -----
    err_str = str(exc).lower()
    if "429" in err_str or "resource_exhausted" in err_str:
        return "RATE_LIMIT"
    if "timeout" in err_str or "timed out" in err_str:
        return "TIMEOUT"
    for code in ("500", "502", "503", "504"):
        if code in err_str:
            return "SERVER_ERROR_5XX"

    # --- httpx / urllib3 specific types (import-safe) -----------------------
    cls_name = type(exc).__name__
    cls_qual = type(exc).__qualname__
    if "Timeout" in cls_name:
        return "TIMEOUT"
    if "Connect" in cls_name:
        return "CONNECT_ERROR"

    # --- truly unknown ------------------------------------------------------
    return f"UNKNOWN_ERROR:{cls_qual}"


# ---------------------------------------------------------------------------
# GeminiWrapper
# ---------------------------------------------------------------------------

class GeminiWrapper:
    """Thread-safe, resilient wrapper for the official google-genai SDK."""

    def __init__(self, config=cfg):
        self.config = config
        self._client = None
        self._client_lock = threading.Lock()
        # Per-flow circuit breakers so a failure in one flow does not block others
        self._breakers: Dict[str, CircuitBreaker] = {
            "general": CircuitBreaker(failure_threshold=3, recovery_time=60.0),
            "personalised": CircuitBreaker(failure_threshold=3, recovery_time=60.0),
        }
        self.circuit_breaker = self._breakers["general"]  # backward-compat alias
        # Custom mock hooks for tests
        self._fake_generate = None
        self._fake_embed = None

    def get_circuit_breaker(self, flow: str = "general") -> CircuitBreaker:
        return self._breakers.get(flow, self._breakers["general"])

    def _get_client(self):
        """Lazily initialize and return the google.genai Client."""
        if not self.config.has_gemini_key:
            return None
        with self._client_lock:
            if self._client is None:
                try:
                    from google import genai
                    # Read timeout from config
                    timeout_val = getattr(self.config, "LLM_TIMEOUT_SECONDS", 20)
                    self._client = genai.Client(
                        api_key=self.config.GEMINI_API_KEY,
                        http_options={"timeout": timeout_val}
                    )
                except Exception as exc:
                    logger.warning("Failed to initialize google-genai Client: %s", exc)
                    return None
            return self._client

    def generate(
        self,
        system: Optional[str] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        max_output_tokens: Optional[int] = 1500,
        temperature: Optional[float] = 0.2,
        flow: str = "general",
        timeout: Optional[int] = None,
    ) -> LLMResult:
        """Generates chat completion text. Never raises exceptions to caller."""
        if self._fake_generate is not None:
            try:
                return self._fake_generate(system=system, messages=messages, max_output_tokens=max_output_tokens, temperature=temperature)
            except Exception as exc:
                logger.warning("Fake generate threw exception: %s", exc)
                return LLMResult(ok=False, error_kind="EXCEPTION")

        if not self.config.has_gemini_key:
            return LLMResult(ok=False, error_kind="NO_KEY")

        breaker = self.get_circuit_breaker(flow)
        if not breaker.allow_request():
            logger.warning(
                "Gemini circuit breaker OPEN for flow=%s — model=%s failures=%d",
                flow,
                self.config.GEMINI_CHAT_MODEL,
                breaker.consecutive_failures,
            )
            return LLMResult(ok=False, error_kind="CIRCUIT_OPEN")

        client = self._get_client()
        if client is None:
            return LLMResult(ok=False, error_kind="NO_KEY")

        from google.genai import types

        # Build contents: validate roles ('user', 'model'), merge consecutive same-role turns,
        # drop empty turns and drop turns containing old refusal or limited mode badges
        raw_messages = messages or []
        contents = []
        for m in raw_messages:
            role = "user" if m.get("role") in ("user", "human") else "model"
            content_text = (m.get("content") or "").strip()
            if not content_text:
                continue
            # Drop saved refusal or degraded notice boilerplate from history sent to model
            if "I am an educational trading coach" in content_text and "SEBI registration" in content_text:
                continue
            if "Limited mode" in content_text and len(content_text) < 100:
                continue

            # Trim overly long earlier assistant replies to save context
            if role == "model" and len(content_text) > 1500:
                content_text = content_text[:1500] + "..."

            if contents and contents[-1].role == role:
                prev_text = contents[-1].parts[0].text if contents[-1].parts else ""
                contents[-1] = types.Content(role=role, parts=[types.Part.from_text(text=prev_text + "\n" + content_text)])
            else:
                contents.append(types.Content(role=role, parts=[types.Part.from_text(text=content_text)]))

        if not contents:
            return LLMResult(ok=False, error_kind="EMPTY_PROMPT")

        prompt_chars = sum(len(c.parts[0].text) for c in contents if c.parts)
        if system:
            prompt_chars += len(system)

        # Timeout selection: per-call override or flow-specific default
        if timeout is None:
            if flow == "personalised":
                timeout = getattr(self.config, "LLM_TIMEOUT_PERSONALISED_SECONDS", 30)
            else:
                timeout = getattr(self.config, "LLM_TIMEOUT_SECONDS", 20)

        # Build GenerateContentConfig with thinking budget (disabled by default to prevent token exhaustion)
        thinking_budget = getattr(self.config, "LLM_THINKING_BUDGET", 0)
        thinking_cfg = None
        try:
            thinking_cfg = types.ThinkingConfig(thinking_budget=thinking_budget)
        except Exception:
            pass

        gen_config_kwargs: Dict[str, Any] = {
            "system_instruction": system if system else None,
            "max_output_tokens": max_output_tokens or 1500,
            "temperature": temperature,
            "http_options": types.HttpOptions(timeout=timeout * 1000)
        }
        if thinking_cfg is not None:
            gen_config_kwargs["thinking_config"] = thinking_cfg

        try:
            gen_config = types.GenerateContentConfig(**gen_config_kwargs)
        except Exception:
            # Fallback without thinking_config if unsupported
            gen_config_kwargs.pop("thinking_config", None)
            gen_config = types.GenerateContentConfig(**gen_config_kwargs)

        # At most 1 retry (total 2 attempts) only for rate-limit, 5xx, or network timeout
        max_retries = 1
        last_error_kind = "UNKNOWN"
        t_start = time.monotonic()

        for attempt in range(max_retries + 1):
            try:
                response = client.models.generate_content(
                    model=self.config.GEMINI_CHAT_MODEL,
                    contents=contents,
                    config=gen_config
                )

                elapsed_ms = int((time.monotonic() - t_start) * 1000)

                if not response.candidates or len(response.candidates) == 0:
                    breaker.record_failure()
                    return LLMResult(ok=False, error_kind="EMPTY")

                candidate = response.candidates[0]
                finish_reason = getattr(candidate, "finish_reason", None)
                finish_str = str(finish_reason).upper() if finish_reason else ""
                if "SAFETY" in finish_str or "BLOCKED" in finish_str:
                    breaker.record_failure()
                    return LLMResult(ok=False, error_kind="BLOCKED")

                text = response.text
                if not text or not text.strip():
                    breaker.record_failure()
                    return LLMResult(ok=False, error_kind="EMPTY")

                breaker.record_success()
                logger.debug(
                    "Gemini generate OK — model=%s flow=%s prompt_chars=%d elapsed_ms=%d",
                    self.config.GEMINI_CHAT_MODEL, flow, prompt_chars, elapsed_ms,
                )
                return LLMResult(ok=True, text=text.strip())

            except Exception as exc:
                last_error_kind = _classify_exception(exc)
                is_retryable = last_error_kind in ("RATE_LIMIT", "TIMEOUT", "SERVER_ERROR_5XX", "CONNECT_ERROR")

                elapsed_ms = int((time.monotonic() - t_start) * 1000)
                logger.warning(
                    "Gemini generate attempt %d/%d failed — model=%s flow=%s error_kind=%s prompt_chars=%d elapsed_ms=%d",
                    attempt + 1, max_retries + 1,
                    self.config.GEMINI_CHAT_MODEL, flow, last_error_kind, prompt_chars, elapsed_ms,
                )

                if attempt < max_retries and is_retryable:
                    backoff = (2 ** attempt) + random.uniform(0.1, 0.4)
                    time.sleep(backoff)
                    continue
                else:
                    breaker.record_failure()
                    return LLMResult(ok=False, error_kind=last_error_kind)

        breaker.record_failure()
        return LLMResult(ok=False, error_kind=last_error_kind)

    def embed(self, texts: List[str], kind: str = "document") -> LLMResult:
        """Generates L2-normalized embeddings for given texts. Never raises."""
        if not texts:
            return LLMResult(ok=True, vectors=[])

        if self._fake_embed is not None:
            return self._fake_embed(texts=texts, kind=kind)

        if not self.config.has_gemini_key:
            return LLMResult(ok=False, error_kind="NO_KEY")

        breaker = self.get_circuit_breaker("general")
        if not breaker.allow_request():
            return LLMResult(ok=False, error_kind="CIRCUIT_OPEN")

        client = self._get_client()
        if client is None:
            return LLMResult(ok=False, error_kind="NO_KEY")

        from google.genai import types

        model_name = self.config.GEMINI_EMBED_MODEL
        use_task_types = "embedding-2" not in model_name.lower()

        task_type = None
        if use_task_types:
            task_type = "RETRIEVAL_QUERY" if kind == "query" else "RETRIEVAL_DOCUMENT"

        embed_config = types.EmbedContentConfig(
            output_dimensionality=self.config.EMBED_DIMENSIONS,
            task_type=task_type,
            http_options=types.HttpOptions(timeout=self.config.LLM_TIMEOUT_SECONDS * 1000)
        )

        batch_size = 16
        all_vectors = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_result = self._embed_batch_with_retry(client, model_name, batch, embed_config)
            if batch_result.ok and batch_result.vectors:
                all_vectors.extend(batch_result.vectors)
            else:
                logger.info("Batch embedding failed; falling back to 1 text per request")
                for single_text in batch:
                    single_res = self._embed_batch_with_retry(client, model_name, [single_text], embed_config)
                    if single_res.ok and single_res.vectors:
                        all_vectors.extend(single_res.vectors)
                    else:
                        breaker.record_failure()
                        return LLMResult(ok=False, error_kind=single_res.error_kind or "EMBED_FAILED")

        breaker.record_success()
        return LLMResult(ok=True, vectors=all_vectors)

    def _embed_batch_with_retry(self, client, model_name, texts_batch: List[str], embed_config) -> LLMResult:
        max_retries = 1
        last_error_kind = "UNKNOWN"

        for attempt in range(max_retries + 1):
            try:
                response = client.models.embed_content(
                    model=model_name,
                    contents=texts_batch,
                    config=embed_config
                )

                raw_embeddings = getattr(response, "embeddings", None)
                if not raw_embeddings:
                    embedding_obj = getattr(response, "embedding", None)
                    if embedding_obj:
                        raw_embeddings = [embedding_obj]

                if not raw_embeddings:
                    return LLMResult(ok=False, error_kind="EMPTY")

                vectors: List[List[float]] = []
                for emb in raw_embeddings:
                    vals = getattr(emb, "values", None)
                    if vals is None and isinstance(emb, list):
                        vals = emb
                    if vals:
                        vec = np.array(vals, dtype=np.float32)
                        norm = np.linalg.norm(vec)
                        if norm > 0:
                            vec = vec / norm
                        vectors.append(vec.tolist())

                if len(vectors) != len(texts_batch):
                    return LLMResult(ok=False, error_kind="EMBED_COUNT_MISMATCH")

                return LLMResult(ok=True, vectors=vectors)

            except Exception as exc:
                last_error_kind = _classify_exception(exc)
                is_retryable = last_error_kind in ("RATE_LIMIT", "TIMEOUT", "SERVER_ERROR_5XX", "CONNECT_ERROR")

                if attempt < max_retries and is_retryable:
                    backoff = (2 ** attempt) + random.uniform(0.1, 0.4)
                    time.sleep(backoff)
                    continue
                else:
                    return LLMResult(ok=False, error_kind=last_error_kind)

        return LLMResult(ok=False, error_kind=last_error_kind)


llm_client = GeminiWrapper()
