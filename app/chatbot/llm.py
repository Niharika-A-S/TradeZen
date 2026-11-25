"""Official google-genai SDK wrapper for TradeZen Chatbot.

Key design contracts
--------------------
* Model discovery: if GEMINI_CHAT_MODEL is unset (or empty), discover a usable
  generateContent model at runtime, preferring names containing 'flash'.
* Fallback chain: on model_not_found (404 / NOT_FOUND), try
  GEMINI_CHAT_MODEL_FALLBACKS then discovered models in order.
  The first working model is remembered in-process.
* Circuit breaker: counts ONLY transport errors, 429, and 5xx.
  4xx (including 404), SERIAL_ERROR, EMPTY, BLOCKED, our own bugs
  — none of these trip the breaker.
  Per-flow so a broken prompt type does not block plain chat.
  Half-open after LLM_BREAKER_RECOVERY_SECONDS (monotonic clock).
  Closes immediately on the first success.
* Safe JSON: Decimal, datetime, UUID, numpy — all handled without crashing.
* Never raises to callers. Never logs message text, trade values, or keys.
"""
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, date
import json
import logging
import random
import socket
import ssl
import threading
import time
from typing import List, Optional, Dict, Any, Tuple
import uuid

import numpy as np

from .config import cfg

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Safe JSON Serializer
# ---------------------------------------------------------------------------

class SafeJSONEncoder(json.JSONEncoder):
    """Safe JSON encoder: Decimal, datetime, date, UUID, numpy — no TypeError."""
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
    """Serializes arbitrary facts/dicts to JSON without throwing TypeError."""
    kwargs.setdefault("ensure_ascii", False)
    kwargs.setdefault("cls", SafeJSONEncoder)
    try:
        return json.dumps(obj, **kwargs)
    except Exception as exc:
        logger.warning("safe_json_dumps fallback triggered: %s", exc)
        return json.dumps(str(obj))


# ---------------------------------------------------------------------------
# LLM Result
# ---------------------------------------------------------------------------

@dataclass
class LLMResult:
    ok: bool
    text: Optional[str] = None
    vectors: Optional[List[List[float]]] = None
    # error_kind values:
    #   NO_KEY, CIRCUIT_OPEN, RATE_LIMIT, TIMEOUT, BLOCKED, EMPTY,
    #   CONNECT_ERROR, DNS_ERROR, TLS_ERROR, CLIENT_ERROR_NNN,
    #   SERVER_ERROR_5XX, SERIAL_ERROR, UNKNOWN_ERROR:<classname>,
    #   MODEL_NOT_FOUND  — never NETWORK_ERROR for unrecognised exceptions
    error_kind: Optional[str] = None
    model_used: Optional[str] = None  # actual model name that produced this result


# ---------------------------------------------------------------------------
# Circuit Breaker — counts only transport / 5xx / 429 failures
# ---------------------------------------------------------------------------

#: error_kinds that trip the circuit breaker
_BREAKER_KINDS = frozenset({"RATE_LIMIT", "TIMEOUT", "SERVER_ERROR_5XX", "CONNECT_ERROR",
                             "DNS_ERROR", "TLS_ERROR"})


class CircuitBreaker:
    """Thread-safe per-flow circuit breaker.

    Only transport, 429, and 5xx errors count.
    4xx (404, 400 …), SERIAL_ERROR, EMPTY, BLOCKED, our own bugs:
    these do NOT increment the failure counter.
    Half-open after recovery_time (monotonic).
    Closes on the first success.
    """
    def __init__(self, failure_threshold: int = 3, recovery_time: float = 45.0):
        self.failure_threshold = failure_threshold
        self.recovery_time = recovery_time
        self.consecutive_failures = 0
        self.last_failure_time = 0.0
        self._lock = threading.Lock()

    def allow_request(self, current_time: Optional[float] = None) -> bool:
        now = current_time if current_time is not None else time.monotonic()
        with self._lock:
            if self.consecutive_failures >= self.failure_threshold:
                if now - self.last_failure_time > self.recovery_time:
                    # Half-open: allow one trial request, reset counter
                    self.consecutive_failures = 0
                    return True
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            self.consecutive_failures = 0

    def record_failure(self, error_kind: str = "SERVER_ERROR_5XX", current_time: Optional[float] = None) -> None:
        """Only count kinds that belong to _BREAKER_KINDS."""
        if error_kind not in _BREAKER_KINDS:
            return
        now = current_time if current_time is not None else time.monotonic()
        with self._lock:
            self.consecutive_failures += 1
            self.last_failure_time = now

    @property
    def state(self) -> str:
        with self._lock:
            if self.consecutive_failures >= self.failure_threshold:
                if time.monotonic() - self.last_failure_time > self.recovery_time:
                    return "half-open"
                return "open"
            return "closed"


# ---------------------------------------------------------------------------
# Exception → error_kind classifier
# ---------------------------------------------------------------------------

def _classify_exception(exc: Exception) -> str:
    """Classify an LLM-call exception into a human-readable error_kind string.

    Rules
    -----
    - Type-based checks first (precise).
    - HTTP status code extracted from google-genai ClientError / ServerError
      attributes when available.
    - String scanning ONLY as a last resort for 404 / 429 / 5xx codes.
    - Unknown exceptions → UNKNOWN_ERROR:<ClassName> — never NETWORK_ERROR.
    """
    # serialisation errors (must be checked before anything else)
    if isinstance(exc, (TypeError, ValueError)):
        return "SERIAL_ERROR"

    # timeouts
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "TIMEOUT"

    # TLS / SSL
    if isinstance(exc, ssl.SSLError):
        return "TLS_ERROR"

    # DNS
    if isinstance(exc, socket.gaierror):
        return "DNS_ERROR"

    # connection refused / reset / aborted
    if isinstance(exc, ConnectionError):
        return "CONNECT_ERROR"
    if isinstance(exc, OSError) and getattr(exc, "errno", None) in (
        111,    # ECONNREFUSED (Linux)
        10061,  # WSAECONNREFUSED (Windows)
        10013,  # WSAEACCES (Windows)
    ):
        return "CONNECT_ERROR"

    # google-genai SDK: try HTTP status from exception attributes
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status is not None:
        try:
            status = int(status)
        except (TypeError, ValueError):
            status = None
    if status is not None:
        if status == 429:
            return "RATE_LIMIT"
        if status == 404:
            return "MODEL_NOT_FOUND"
        if 400 <= status < 500:
            return f"CLIENT_ERROR_{status}"
        if 500 <= status < 600:
            return "SERVER_ERROR_5XX"

    # string fallback for SDKs that embed status only in the message
    err_str = str(exc).lower()
    if "429" in err_str or "resource_exhausted" in err_str:
        return "RATE_LIMIT"
    if "404" in err_str or "not found" in err_str or "model_not_found" in err_str:
        return "MODEL_NOT_FOUND"
    if "timeout" in err_str or "timed out" in err_str:
        return "TIMEOUT"
    for code in ("500", "502", "503", "504"):
        if code in err_str:
            return "SERVER_ERROR_5XX"

    # httpx / urllib3 class name hints
    cls_name = type(exc).__name__
    cls_qual = type(exc).__qualname__
    if "Timeout" in cls_name:
        return "TIMEOUT"
    if "Connect" in cls_name:
        return "CONNECT_ERROR"

    return f"UNKNOWN_ERROR:{cls_qual}"


def _is_model_not_found(error_kind: str) -> bool:
    return error_kind == "MODEL_NOT_FOUND"


# ---------------------------------------------------------------------------
# Model discovery and validation (cached, timeout-guarded)
# ---------------------------------------------------------------------------

_MODEL_CACHE_LOCK = threading.Lock()
_MODEL_CACHE: Dict[str, Any] = {
    "usable_generate": None,   # list[str] of discovered generateContent model names
    "chat_model_status": None, # 'ok' | 'not_found' | 'unreachable' | 'unknown'
    "embed_model_status": None,
    "working_chat_model": None,
    "last_checked": 0.0,
    "cache_ttl": 300.0,        # re-check every 5 minutes at most
}


def _list_usable_generate_models(client, timeout: int = 10) -> List[str]:
    """Return model names that support generateContent, preferring 'flash' ones.
    Returns empty list on any error. Never raises."""
    try:
        models = client.models.list()
        names: List[str] = []
        for m in models:
            name = getattr(m, "name", "") or ""
            # Strip 'models/' prefix if present
            if name.startswith("models/"):
                name = name[len("models/"):]
            supported = getattr(m, "supported_generation_methods", []) or []
            if "generateContent" in supported and name:
                names.append(name)
        # Sort: 'flash' first, then others
        names.sort(key=lambda n: (0 if "flash" in n.lower() else 1, n))
        return names
    except Exception as exc:
        logger.debug("Model list failed: %s", type(exc).__name__)
        return []


def _probe_model_status(client, model_name: str, timeout: int = 8) -> str:
    """Test whether a model is reachable. Returns 'ok', 'not_found', 'unreachable', 'unknown'."""
    if not model_name:
        return "unknown"
    try:
        from google.genai import types as gtypes
        client.models.generate_content(
            model=model_name,
            contents=[gtypes.Content(role="user", parts=[gtypes.Part.from_text(text="hi")])],
            config=gtypes.GenerateContentConfig(
                max_output_tokens=4,
                http_options=gtypes.HttpOptions(timeout=timeout * 1000),
            ),
        )
        return "ok"
    except Exception as exc:
        kind = _classify_exception(exc)
        if kind == "MODEL_NOT_FOUND":
            return "not_found"
        if kind in ("TIMEOUT", "CONNECT_ERROR", "DNS_ERROR", "TLS_ERROR"):
            return "unreachable"
        return "unknown"


def refresh_model_cache(client) -> None:
    """Refresh the model discovery cache. Called at startup and by health endpoint."""
    now = time.monotonic()
    with _MODEL_CACHE_LOCK:
        last = _MODEL_CACHE["last_checked"]
        ttl = _MODEL_CACHE["cache_ttl"]
    if now - last < ttl:
        return  # still fresh

    usable = _list_usable_generate_models(client)
    chat_status = _probe_model_status(client, _MODEL_CACHE.get("working_chat_model") or "")
    embed_status = "unknown"  # probed separately; embedding errors are logged separately

    with _MODEL_CACHE_LOCK:
        _MODEL_CACHE["usable_generate"] = usable
        _MODEL_CACHE["chat_model_status"] = chat_status
        _MODEL_CACHE["embed_model_status"] = embed_status
        _MODEL_CACHE["last_checked"] = time.monotonic()


def get_working_chat_model(config, client) -> Optional[str]:
    """Return the first working chat model (from cache or by probing).

    Priority:
    1. Already found working model in this process.
    2. GEMINI_CHAT_MODEL env var (probe it).
    3. GEMINI_CHAT_MODEL_FALLBACKS list (probe each).
    4. Discovered models (probe each flash-first).
    Returns None if nothing works.
    """
    with _MODEL_CACHE_LOCK:
        cached = _MODEL_CACHE["working_chat_model"]
    if cached:
        return cached

    # Build the candidate list
    primary = (config.GEMINI_CHAT_MODEL or "").strip()
    fallbacks_raw = (config.GEMINI_CHAT_MODEL_FALLBACKS or "").strip()
    fallbacks = [m.strip() for m in fallbacks_raw.split(",") if m.strip()] if fallbacks_raw else []

    # Discovered models (refresh if needed)
    with _MODEL_CACHE_LOCK:
        discovered = list(_MODEL_CACHE.get("usable_generate") or [])
    if not discovered:
        discovered = _list_usable_generate_models(client)
        with _MODEL_CACHE_LOCK:
            _MODEL_CACHE["usable_generate"] = discovered

    # Candidates: primary → fallbacks → discovered (excluding already tried)
    candidates: List[str] = []
    if primary:
        candidates.append(primary)
    for f in fallbacks:
        if f not in candidates:
            candidates.append(f)
    for d in discovered:
        if d not in candidates:
            candidates.append(d)

    for model in candidates:
        status = _probe_model_status(client, model)
        logger.info("Model probe: model=%s status=%s", model, status)
        if status == "ok":
            with _MODEL_CACHE_LOCK:
                _MODEL_CACHE["working_chat_model"] = model
                _MODEL_CACHE["chat_model_status"] = "ok"
            return model

    logger.warning("No working chat model found from %d candidates", len(candidates))
    with _MODEL_CACHE_LOCK:
        _MODEL_CACHE["chat_model_status"] = "not_found"
    return None


def get_model_health_status(config, client) -> Dict[str, Any]:
    """Return model status dict for the health endpoint. Never raises."""
    try:
        refresh_model_cache(client)
        with _MODEL_CACHE_LOCK:
            chat_status = _MODEL_CACHE.get("chat_model_status") or "unknown"
            embed_status = _MODEL_CACHE.get("embed_model_status") or "unknown"
            working = _MODEL_CACHE.get("working_chat_model")
            discovered = list(_MODEL_CACHE.get("usable_generate") or [])

        chat_model = working or config.GEMINI_CHAT_MODEL or "unset"
        embed_model = config.GEMINI_EMBED_MODEL or "unset"

        return {
            "chat_model": chat_model,
            "chat_model_status": chat_status,
            "embed_model": embed_model,
            "embed_model_status": embed_status,
            "discovered_usable_models": discovered,
        }
    except Exception as exc:
        logger.debug("get_model_health_status failed: %s", type(exc).__name__)
        return {
            "chat_model": "unknown",
            "chat_model_status": "unknown",
            "embed_model": "unknown",
            "embed_model_status": "unknown",
            "discovered_usable_models": [],
        }


# ---------------------------------------------------------------------------
# GeminiWrapper
# ---------------------------------------------------------------------------

class GeminiWrapper:
    """Thread-safe, resilient wrapper for the official google-genai SDK.

    Model selection:
    - Calls get_working_chat_model() on the first generate() call.
    - On MODEL_NOT_FOUND, invalidates the working model and retries the
      fallback chain once per request (without counting against the breaker).
    Circuit breaker:
    - Counts only RATE_LIMIT, TIMEOUT, SERVER_ERROR_5XX, CONNECT_ERROR,
      DNS_ERROR, TLS_ERROR.
    - 4xx (MODEL_NOT_FOUND, CLIENT_ERROR_NNN), SERIAL_ERROR, EMPTY, BLOCKED:
      not counted.
    """

    def __init__(self, config=cfg):
        self.config = config
        self._client = None
        self._client_lock = threading.Lock()
        recovery = getattr(config, "LLM_BREAKER_RECOVERY_SECONDS", 45.0)
        # Per-flow circuit breakers so a failure in one flow does not block others
        self._breakers: Dict[str, CircuitBreaker] = {
            "general": CircuitBreaker(failure_threshold=3, recovery_time=recovery),
            "personalised": CircuitBreaker(failure_threshold=3, recovery_time=recovery),
        }
        self.circuit_breaker = self._breakers["general"]  # backward-compat alias
        # Custom mock hooks for tests
        self._fake_generate = None
        self._fake_embed = None

    def get_circuit_breaker(self, flow: str = "general") -> CircuitBreaker:
        return self._breakers.get(flow, self._breakers["general"])

    def _get_client(self):
        """Lazily initialize and return the google.genai Client. Never raises."""
        if not self.config.has_gemini_key:
            return None
        with self._client_lock:
            if self._client is None:
                try:
                    from google import genai
                    timeout_val = getattr(self.config, "LLM_TIMEOUT_SECONDS", 20)
                    self._client = genai.Client(
                        api_key=self.config.GEMINI_API_KEY,
                        http_options={"timeout": timeout_val},
                    )
                except Exception as exc:
                    logger.warning("Failed to initialize google-genai Client: %s", type(exc).__name__)
                    return None
            return self._client

    def _resolve_chat_model(self, client) -> Optional[str]:
        """Return the working chat model, discovering if needed."""
        return get_working_chat_model(self.config, client)

    def _invalidate_working_model(self) -> None:
        """Clear the cached working model so discovery retries on next call."""
        with _MODEL_CACHE_LOCK:
            _MODEL_CACHE["working_chat_model"] = None
            _MODEL_CACHE["chat_model_status"] = "not_found"

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
                return self._fake_generate(
                    system=system, messages=messages,
                    max_output_tokens=max_output_tokens, temperature=temperature,
                )
            except Exception as exc:
                logger.warning("Fake generate threw: %s", type(exc).__name__)
                return LLMResult(ok=False, error_kind="EXCEPTION")

        if not self.config.has_gemini_key:
            return LLMResult(ok=False, error_kind="NO_KEY")

        breaker = self.get_circuit_breaker(flow)
        if not breaker.allow_request():
            logger.warning(
                "Gemini circuit breaker OPEN — flow=%s failures=%d",
                flow, breaker.consecutive_failures,
            )
            return LLMResult(ok=False, error_kind="CIRCUIT_OPEN")

        client = self._get_client()
        if client is None:
            return LLMResult(ok=False, error_kind="NO_KEY")

        from google.genai import types

        # Build contents: validate roles, merge consecutive same-role turns,
        # drop empty turns and old boilerplate refusals.
        raw_messages = messages or []
        contents = []
        for m in raw_messages:
            role = "user" if m.get("role") in ("user", "human") else "model"
            content_text = (m.get("content") or "").strip()
            if not content_text:
                continue
            if "I am an educational trading coach" in content_text and "SEBI registration" in content_text:
                continue
            if "Limited mode" in content_text and len(content_text) < 100:
                continue
            if role == "model" and len(content_text) > 1500:
                content_text = content_text[:1500] + "..."
            if contents and contents[-1].role == role:
                prev_text = contents[-1].parts[0].text if contents[-1].parts else ""
                contents[-1] = types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=prev_text + "\n" + content_text)],
                )
            else:
                contents.append(
                    types.Content(role=role, parts=[types.Part.from_text(text=content_text)])
                )

        if not contents:
            return LLMResult(ok=False, error_kind="EMPTY_PROMPT")

        prompt_chars = sum(len(c.parts[0].text) for c in contents if c.parts)
        if system:
            prompt_chars += len(system)

        if timeout is None:
            if flow == "personalised":
                timeout = getattr(self.config, "LLM_TIMEOUT_PERSONALISED_SECONDS", 30)
            else:
                timeout = getattr(self.config, "LLM_TIMEOUT_SECONDS", 20)

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
            "http_options": types.HttpOptions(timeout=timeout * 1000),
        }
        if thinking_cfg is not None:
            gen_config_kwargs["thinking_config"] = thinking_cfg
        try:
            gen_config = types.GenerateContentConfig(**gen_config_kwargs)
        except Exception:
            gen_config_kwargs.pop("thinking_config", None)
            gen_config = types.GenerateContentConfig(**gen_config_kwargs)

        # Resolve the working model (discovers / probes if needed)
        model_name = self._resolve_chat_model(client)
        if not model_name:
            return LLMResult(ok=False, error_kind="MODEL_NOT_FOUND")

        t_start = time.monotonic()

        # At most 1 retry for transport errors; model-not-found does its own
        # fallback chain (tries next model) without retry and without breaker count.
        max_retries = 1
        last_error_kind = "UNKNOWN"

        for attempt in range(max_retries + 1):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=gen_config,
                )

                elapsed_ms = int((time.monotonic() - t_start) * 1000)

                if not response.candidates or len(response.candidates) == 0:
                    # Empty output: not a breaker event
                    return LLMResult(ok=False, error_kind="EMPTY", model_used=model_name)

                candidate = response.candidates[0]
                finish_reason = getattr(candidate, "finish_reason", None)
                finish_str = str(finish_reason).upper() if finish_reason else ""
                if "SAFETY" in finish_str or "BLOCKED" in finish_str:
                    # Safety block: not a breaker event
                    return LLMResult(ok=False, error_kind="BLOCKED", model_used=model_name)

                text = response.text
                if not text or not text.strip():
                    return LLMResult(ok=False, error_kind="EMPTY", model_used=model_name)

                breaker.record_success()
                logger.debug(
                    "Gemini OK — model=%s flow=%s prompt_chars=%d elapsed_ms=%d",
                    model_name, flow, prompt_chars, elapsed_ms,
                )
                return LLMResult(ok=True, text=text.strip(), model_used=model_name)

            except Exception as exc:
                elapsed_ms = int((time.monotonic() - t_start) * 1000)
                last_error_kind = _classify_exception(exc)

                logger.warning(
                    "Gemini generate attempt %d/%d failed — model=%s flow=%s "
                    "error_kind=%s prompt_chars=%d elapsed_ms=%d",
                    attempt + 1, max_retries + 1,
                    model_name, flow, last_error_kind, prompt_chars, elapsed_ms,
                )

                if _is_model_not_found(last_error_kind):
                    # Invalidate cached model, try fallback chain once — no retry loop
                    self._invalidate_working_model()
                    next_model = self._resolve_chat_model(client)
                    if next_model and next_model != model_name:
                        model_name = next_model
                        # Try once with next model (do not loop back through retry)
                        try:
                            response2 = client.models.generate_content(
                                model=model_name,
                                contents=contents,
                                config=gen_config,
                            )
                            elapsed_ms2 = int((time.monotonic() - t_start) * 1000)
                            text2 = getattr(response2, "text", None)
                            if text2 and text2.strip():
                                breaker.record_success()
                                logger.info(
                                    "Gemini fallback OK — model=%s flow=%s elapsed_ms=%d",
                                    model_name, flow, elapsed_ms2,
                                )
                                return LLMResult(ok=True, text=text2.strip(), model_used=model_name)
                        except Exception as exc2:
                            fallback_kind = _classify_exception(exc2)
                            logger.warning(
                                "Gemini fallback failed — model=%s error_kind=%s",
                                model_name, fallback_kind,
                            )
                            # Only count breaker-worthy errors from fallback
                            breaker.record_failure(fallback_kind)
                            return LLMResult(ok=False, error_kind=fallback_kind, model_used=model_name)
                    # No fallback found
                    return LLMResult(ok=False, error_kind="MODEL_NOT_FOUND", model_used=None)

                is_retryable = last_error_kind in _BREAKER_KINDS
                if attempt < max_retries and is_retryable:
                    backoff = (2 ** attempt) + random.uniform(0.1, 0.4)
                    time.sleep(backoff)
                    continue
                else:
                    # Count against breaker only for transport / 5xx / 429
                    breaker.record_failure(last_error_kind)
                    return LLMResult(ok=False, error_kind=last_error_kind, model_used=model_name)

        breaker.record_failure(last_error_kind)
        return LLMResult(ok=False, error_kind=last_error_kind, model_used=model_name)

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
            http_options=types.HttpOptions(timeout=self.config.LLM_TIMEOUT_SECONDS * 1000),
        )

        batch_size = 16
        all_vectors: List[List[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i: i + batch_size]
            batch_result = self._embed_batch_with_retry(client, model_name, batch, embed_config)
            if batch_result.ok and batch_result.vectors:
                all_vectors.extend(batch_result.vectors)
            else:
                logger.info("Batch embedding failed; falling back to 1 text per request")
                for single_text in batch:
                    single_res = self._embed_batch_with_retry(
                        client, model_name, [single_text], embed_config
                    )
                    if single_res.ok and single_res.vectors:
                        all_vectors.extend(single_res.vectors)
                    else:
                        breaker.record_failure(single_res.error_kind or "EMBED_FAILED")
                        return LLMResult(ok=False, error_kind=single_res.error_kind or "EMBED_FAILED")

        breaker.record_success()
        return LLMResult(ok=True, vectors=all_vectors)

    def _embed_batch_with_retry(
        self, client, model_name: str, texts_batch: List[str], embed_config
    ) -> LLMResult:
        max_retries = 1
        last_error_kind = "UNKNOWN"

        for attempt in range(max_retries + 1):
            try:
                response = client.models.embed_content(
                    model=model_name,
                    contents=texts_batch,
                    config=embed_config,
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
                is_retryable = last_error_kind in _BREAKER_KINDS

                if attempt < max_retries and is_retryable:
                    backoff = (2 ** attempt) + random.uniform(0.1, 0.4)
                    time.sleep(backoff)
                    continue
                else:
                    return LLMResult(ok=False, error_kind=last_error_kind)

        return LLMResult(ok=False, error_kind=last_error_kind)


llm_client = GeminiWrapper()
