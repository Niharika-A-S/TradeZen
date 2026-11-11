"""Official google-genai SDK wrapper for TradeZen Chatbot."""
from dataclasses import dataclass, field
import logging
import random
import threading
import time
from typing import List, Optional, Union, Dict, Any

import numpy as np

from .config import cfg

logger = logging.getLogger(__name__)


@dataclass
class LLMResult:
    ok: bool
    text: Optional[str] = None
    vectors: Optional[List[List[float]]] = None
    error_kind: Optional[str] = None  # 'NO_KEY', 'CIRCUIT_OPEN', 'RATE_LIMIT', 'TIMEOUT', 'BLOCKED', 'EMPTY', 'NETWORK_ERROR'


class CircuitBreaker:
    """Thread-safe circuit breaker that trips after 3 consecutive failures for 60 seconds."""
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
                    # Half-open/recovered
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


class GeminiWrapper:
    """Thread-safe, resilient wrapper for the official google-genai SDK."""

    def __init__(self, config=cfg):
        self.config = config
        self._client = None
        self._client_lock = threading.Lock()
        self.circuit_breaker = CircuitBreaker(failure_threshold=3, recovery_time=60.0)
        # Custom mock hooks for tests
        self._fake_generate = None
        self._fake_embed = None

    def _get_client(self):
        """Lazily initialize and return the google.genai Client."""
        if not self.config.has_gemini_key:
            return None
        with self._client_lock:
            if self._client is None:
                try:
                    from google import genai
                    self._client = genai.Client(
                        api_key=self.config.GEMINI_API_KEY,
                        http_options={"timeout": self.config.LLM_TIMEOUT_SECONDS}
                    )
                except Exception as exc:
                    logger.warning("Failed to initialize google-genai Client: %s", exc)
                    return None
            return self._client

    def generate(
        self,
        system: Optional[str] = None,
        messages: Optional[List[Dict[str, str]]] = None,
        max_output_tokens: Optional[int] = 1000,
        temperature: Optional[float] = 0.2,
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

        if not self.circuit_breaker.allow_request():
            return LLMResult(ok=False, error_kind="CIRCUIT_OPEN")

        client = self._get_client()
        if client is None:
            return LLMResult(ok=False, error_kind="NO_KEY")

        from google.genai import types

        # Build contents from messages
        contents = []
        if messages:
            for m in messages:
                role = "user" if m.get("role") in ("user", "human") else "model"
                contents.append(types.Content(role=role, parts=[types.Part.from_text(text=m.get("content", ""))]))

        gen_config = types.GenerateContentConfig(
            system_instruction=system if system else None,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            http_options=types.HttpOptions(timeout=self.config.LLM_TIMEOUT_SECONDS * 1000)
        )

        max_retries = 2
        last_error_kind = "UNKNOWN"

        for attempt in range(max_retries + 1):
            try:
                response = client.models.generate_content(
                    model=self.config.GEMINI_CHAT_MODEL,
                    contents=contents,
                    config=gen_config
                )

                # Check for empty, blocked or truncated response
                if not response.candidates or len(response.candidates) == 0:
                    self.circuit_breaker.record_failure()
                    return LLMResult(ok=False, error_kind="EMPTY")

                candidate = response.candidates[0]
                finish_reason = getattr(candidate, "finish_reason", None)
                finish_str = str(finish_reason).upper() if finish_reason else ""
                if "SAFETY" in finish_str or "BLOCKED" in finish_str:
                    self.circuit_breaker.record_failure()
                    return LLMResult(ok=False, error_kind="BLOCKED")

                text = response.text
                if not text or not text.strip():
                    self.circuit_breaker.record_failure()
                    return LLMResult(ok=False, error_kind="EMPTY")

                self.circuit_breaker.record_success()
                return LLMResult(ok=True, text=text.strip())

            except Exception as exc:
                err_str = str(exc).lower()
                is_rate_limit = "429" in err_str or "resource_exhausted" in err_str
                is_server_error = "500" in err_str or "503" in err_str or "504" in err_str
                is_timeout = "timeout" in err_str or "timed out" in err_str

                if is_rate_limit:
                    last_error_kind = "RATE_LIMIT"
                elif is_timeout:
                    last_error_kind = "TIMEOUT"
                elif is_server_error:
                    last_error_kind = "SERVER_ERROR"
                else:
                    last_error_kind = "NETWORK_ERROR"

                logger.warning("Gemini generate call attempt %d failed: %s", attempt + 1, exc)

                if attempt < max_retries and (is_rate_limit or is_server_error or is_timeout):
                    backoff = (2 ** attempt) + random.uniform(0.1, 0.5)
                    time.sleep(backoff)
                    continue
                else:
                    self.circuit_breaker.record_failure()
                    return LLMResult(ok=False, error_kind=last_error_kind)

        self.circuit_breaker.record_failure()
        return LLMResult(ok=False, error_kind=last_error_kind)

    def embed(self, texts: List[str], kind: str = "document") -> LLMResult:
        """Generates L2-normalized embeddings for given texts. Never raises."""
        if not texts:
            return LLMResult(ok=True, vectors=[])

        if self._fake_embed is not None:
            return self._fake_embed(texts=texts, kind=kind)

        if not self.config.has_gemini_key:
            return LLMResult(ok=False, error_kind="NO_KEY")

        if not self.circuit_breaker.allow_request():
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

        # Batch embed with fallback to one-by-one
        batch_size = 16
        all_vectors = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_result = self._embed_batch_with_retry(client, model_name, batch, embed_config)
            if batch_result.ok and batch_result.vectors:
                all_vectors.extend(batch_result.vectors)
            else:
                # Fallback to one text per request
                logger.info("Batch embedding failed; falling back to 1 text per request")
                for single_text in batch:
                    single_res = self._embed_batch_with_retry(client, model_name, [single_text], embed_config)
                    if single_res.ok and single_res.vectors:
                        all_vectors.extend(single_res.vectors)
                    else:
                        self.circuit_breaker.record_failure()
                        return LLMResult(ok=False, error_kind=single_res.error_kind or "EMBED_FAILED")

        self.circuit_breaker.record_success()
        return LLMResult(ok=True, vectors=all_vectors)

    def _embed_batch_with_retry(self, client, model_name, texts_batch: List[str], embed_config) -> LLMResult:
        max_retries = 2
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
                    # Single response format check
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
                err_str = str(exc).lower()
                is_rate_limit = "429" in err_str or "resource_exhausted" in err_str
                is_server_error = "500" in err_str or "503" in err_str or "504" in err_str
                is_timeout = "timeout" in err_str or "timed out" in err_str

                if is_rate_limit:
                    last_error_kind = "RATE_LIMIT"
                elif is_timeout:
                    last_error_kind = "TIMEOUT"
                elif is_server_error:
                    last_error_kind = "SERVER_ERROR"
                else:
                    last_error_kind = "NETWORK_ERROR"

                if attempt < max_retries and (is_rate_limit or is_server_error or is_timeout):
                    backoff = (2 ** attempt) + random.uniform(0.1, 0.5)
                    time.sleep(backoff)
                    continue
                else:
                    return LLMResult(ok=False, error_kind=last_error_kind)

        return LLMResult(ok=False, error_kind=last_error_kind)


llm_client = GeminiWrapper()
