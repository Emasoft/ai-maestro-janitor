"""OpenRouter-backed ``JevClient`` (TRDD-541CBN36 card 2 — not upstream, added here).

Mirrors ``jevctx.jev.HttpJevClient`` field-for-field: the request/response payload
shapes (``state``/``questions``/``answers``) are identical between TypeSafe's own
endpoint and OpenRouter's (confirmed in
reports/compaction-replacement/20260922_205137+0200-jev-compaction-study.md §I) — only
the transport/identity layer differs: URL, model id (OpenRouter's ``~namespace/`` form),
and the API key source. A live probe
(reports/compaction-replacement/20260922_210008+0200-jev-proposal-measurements.md §M1)
confirmed the exact shape: ``POST https://openrouter.ai/api/alpha/decisions``, body
``{model, state, questions}``, response ``{model, answers, usage:{input_tokens,
output_tokens,cost}, id, provider}`` — HTTP 200 in ~0.41s. The extra response fields
(``model``, ``id``, ``provider``) are simply never read, which is how "tolerate" works
for a dict-shaped payload — no special-casing needed.

Reuses ``RetryPolicy``/``RateLimiter``/``check_request_budget``/``parse_answer`` from
``jev.py`` unchanged: none of those are TypeSafe-specific (§I of the study). Also reuses
``jev.py``'s private ``_to_jsonable``/``_error_detail``/``_parse_retry_after`` helpers
rather than re-implementing them — they are transport-shape helpers with no TypeSafe
awareness either, and duplicating them would be two copies of the same bug surface to
fix in step. ``usage.cost`` (USD) is the one field ``HttpJevClient`` does not capture;
``OpenRouterUsage`` below extends ``Usage`` with it.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from jevctx.jev import (
    RateLimiter,
    RetryPolicy,
    Usage,
    _detail_from_last_error,
    _error_detail,
    _parse_retry_after,
    _to_jsonable,
    check_request_budget,
)
from jevctx.types import (
    RATE_LIMIT_RPM,
    Answer,
    JevAuthError,
    JevError,
    JevUnavailableError,
    JevValidationError,
    Question,
    State,
    parse_answer,
)

__all__ = [
    "API_KEY_ENV", "DEFAULT_BASE_URL", "DEFAULT_MODEL", "JevBlockedError",
    "OpenRouterJevClient", "OpenRouterUsage",
]

# TRDD-1ETALGDG (2026-09-23): a real-transcript 403 against typesafe.ai (the backend
# OpenRouter proxies Jev to) turned out to be a Cloudflare EDGE block -- an HTML "Attention
# Required"/"Sorry, you have been blocked" page, forwarded through OpenRouter verbatim --
# not a real OpenRouter account/key rejection (which is always JSON). The two look identical
# at the HTTP-status level (both 403) but mean opposite things: an edge block is provoked by
# THIS one request's content/volume and is worth retrying with a smaller/different request
# (jev_compaction.py::score_items splits the batch); a real OpenRouter 403 is an account/key
# state no retry or split fixes, so it stays JevAuthError. When set, JEV_DEBUG_LOG appends one
# JSON line per 403 response (status/cf-ray/content-type/a sha256 of the body -- never the
# body itself) for the bisection this card's investigation needed; unset by default, so a
# normal run never pays for it.
_DEBUG_LOG_ENV = "JEV_DEBUG_LOG"

DEFAULT_BASE_URL = "https://openrouter.ai/api/alpha"
DEFAULT_MODEL = "~typesafe/jev-latest"
# The provider's own env var name, never inferred from which keys happen to exist
# (PRRD-adjacent spec requirement, card 2 bullet 3) — this is the ONE name every
# error message and every doc must use so a missing-key failure is greppable.
API_KEY_ENV = "OPENROUTER_API_KEY"


@dataclass
class OpenRouterUsage(Usage):
    """``Usage`` plus the one field OpenRouter's response adds: ``usage.cost`` (USD).

    ``Usage.record()`` takes no ``cost`` kwarg, so this overrides it rather than
    calling ``super().record()`` — the parent's lock is inherited (dataclass fields
    carry over on subclassing) and reused here, not duplicated, so a request update
    is still atomic across both the token counters and the new cost total.
    """

    cost: float = 0.0

    def record(self, *, input_tokens: int = 0, output_tokens: int = 0, cost: float = 0.0) -> None:
        with self._lock:
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            self.requests += 1
            self.cost += cost


class JevBlockedError(JevError):
    """A 403 from a Cloudflare edge in front of the Jev backend, not a real OpenRouter
    error (TRDD-1ETALGDG). Kept distinct from ``JevAuthError`` (a real 402/403 JSON
    response — an account/key state, no retry fixes it) because an edge block is provoked
    by THIS one request's own content or volume, scoped to the batch that tripped it —
    ``jev_compaction.py::score_items`` catches it and splits the batch instead of treating
    it as an outright auth failure; ``jev_compact.py``'s probe-stamp classifier gives it its
    own ``kind="blocked"`` (non-declining, like auth/budget/invalid — never evidence the
    whole endpoint is down).

    ``cf_ray``/``body_sha256`` mirror ``JevUnavailableError``'s ``status``/``cause`` pattern
    (types.py, commit 40cc06d1 follow-up): public attributes with safe defaults, carrying
    the block response's own Cloudflare trace id and a hash of its body (never the body
    itself — it may contain the transcript content that tripped the block) for whoever
    reads the stamp/finding.
    """

    def __init__(
        self, message: str = "", *, cf_ray: str | None = None, body_sha256: str = "",
    ) -> None:
        super().__init__(message)
        self.cf_ray = cf_ray
        self.body_sha256 = body_sha256


def _is_cloudflare_block(response: httpx.Response) -> bool:
    """True iff a 403 ``response`` looks like a Cloudflare edge block rather than a genuine
    OpenRouter JSON error (TRDD-1ETALGDG). Two independent signals, either is enough: (1) the
    body is HTML carrying Cloudflare's own block-page wording — "Attention Required" / "you
    have been blocked" are the exact phrases this card's real-transcript capture recorded
    (reports/compaction-replacement/20260923_211019+0200-*.md); or (2) a ``cf-ray`` response
    header (Cloudflare's own per-request trace id, stamped on every edge-terminated response)
    on a body that is NOT valid JSON — a genuine OpenRouter error always returns JSON, so a
    non-JSON body already means the edge intercepted the request before OpenRouter's own
    error handler ever saw it.
    """
    if "cf-ray" in response.headers:
        try:
            response.json()
        except ValueError:
            return True
    text_lower = response.text.lower()
    return "attention required" in text_lower or "you have been blocked" in text_lower


def _log_403_debug(response: httpx.Response) -> None:
    """Append one diagnostic JSON line to ``$JEV_DEBUG_LOG`` for every 403 response — the
    step-1 bisection instrumentation this card's investigation needed (status, cf-ray,
    content-type, a sha256 of the body — never the body itself, which may carry the
    transcript content that tripped the block). A no-op when the env var is unset (default),
    and best-effort when set: a log-write failure must never fail the actual request.
    """
    path = os.environ.get(_DEBUG_LOG_ENV)
    if not path:
        return
    record = {
        "ts": time.time(),
        "status": response.status_code,
        "cf_ray": response.headers.get("cf-ray"),
        "content_type": response.headers.get("content-type"),
        "body_sha256": hashlib.sha256(response.content).hexdigest(),
        "body_len": len(response.content),
    }
    try:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass


class OpenRouterJevClient:
    """``JevClient`` over OpenRouter's ``/decisions`` endpoint.

    Structurally identical to ``HttpJevClient`` (jev.py:284-430) — same retry/rate-limit/
    budget/concurrency guards, same request-building and response-parsing logic — with
    the transport layer swapped for OpenRouter's URL, model id, and key source. Kept as a
    sibling class rather than a subclass of ``HttpJevClient`` because that class hardcodes
    its own endpoint construction (``f"{base_url}/systemone"``, __init__.py:284) with no
    seam to override; duplicating the ~40-line ``ask()``/``_parse_response()`` pair here
    is smaller and clearer than threading an override point through code we don't own.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 15.0,
        max_retries: int = 3,
        max_concurrency: int = 16,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
    ) -> None:
        key = api_key or os.environ.get(API_KEY_ENV)
        if not key:
            raise JevAuthError(f"no OpenRouter API key: pass api_key=, or set the {API_KEY_ENV} env var")
        self._model = model
        self._timeout = timeout
        self._sleep = sleep
        self._retry_policy = RetryPolicy(max_retries=max_retries, rng=rng)
        self._concurrency = threading.Semaphore(max_concurrency)
        self._rate_limiter = RateLimiter(RATE_LIMIT_RPM, 60.0, sleep=sleep)
        self.usage = OpenRouterUsage()
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {key}"},
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OpenRouterJevClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        self.close()

    @property
    def endpoint(self) -> str:
        return f"{str(self._client.base_url).rstrip('/')}/decisions"

    @property
    def model(self) -> str:
        return self._model

    def ask(self, state: State, questions: Mapping[str, Question]) -> dict[str, Answer]:
        check_request_budget(state, questions)
        body: dict[str, Any] = {
            "model": self._model,
            "state": _to_jsonable(state),
            "questions": {key: question.to_payload() for key, question in questions.items()},
        }

        last_error: Exception | None = None
        with self._concurrency:
            for attempt in range(self._retry_policy.max_retries + 1):
                is_last_attempt = attempt == self._retry_policy.max_retries
                self._rate_limiter.acquire()
                try:
                    response = self._client.post("/decisions", json=body)
                except httpx.TransportError as exc:
                    last_error = exc
                    if is_last_attempt:
                        break
                    self._sleep(self._retry_policy.delay(attempt))
                    continue

                if response.status_code == 200:
                    return self._parse_response(response, questions)
                if response.status_code == 401:
                    raise JevAuthError(_error_detail(response))
                # 402 = insufficient credits; 403 = forbidden (bad key permissions, a
                # guardrail block, or a moderation flag) -- OpenRouter's own error
                # reference (openrouter.ai/docs/api-reference/errors). Neither is a
                # malformed request (the 422 branch below) nor a Jev outage: both are
                # non-retryable and need a human to act (top up credits, fix key
                # permissions/guardrail config) or are specific to this request's
                # content. JevAuthError is the one error kind jev_compact stamps
                # human-facing and non-declining ("auth"); the catch-all
                # JevValidationError below instead becomes kind="invalid" -- also
                # non-declining, scoped to this one request (TRDD-RAEGS1D5 corrected the
                # stale claim here that it became a declining "unavailable" stamp).
                #
                # TRDD-1ETALGDG: a 403 gets ONE extra check first -- a Cloudflare edge
                # block (HTML "Attention Required"/"you have been blocked", or a cf-ray
                # header on a non-JSON body) is NOT a real OpenRouter 403 (see
                # `_is_cloudflare_block`'s docstring); it raises the distinct
                # `JevBlockedError` instead, so `score_items` retries by splitting the
                # batch rather than treating it as an unfixable account/key rejection.
                # 402 never gets this check -- "insufficient credits" has no Cloudflare
                # edge-block shape to confuse it with.
                if response.status_code == 403:
                    _log_403_debug(response)
                    if _is_cloudflare_block(response):
                        raise JevBlockedError(
                            f"Jev (OpenRouter) request blocked by an edge firewall (403): "
                            f"{_error_detail(response)[:200]}",
                            cf_ray=response.headers.get("cf-ray"),
                            body_sha256=hashlib.sha256(response.content).hexdigest(),
                        )
                if response.status_code in (402, 403):
                    raise JevAuthError(f"Jev (OpenRouter) returned {response.status_code}: {_error_detail(response)}")
                if response.status_code == 422:
                    raise JevValidationError(_error_detail(response))
                # 408 = "Your request timed out" (OpenRouter's own error reference) -- retryable
                # the same as a 429/5xx, NOT the generic "bad request" bucket below (TRDD-RAEGS1D5,
                # owner decision 2026-09-23: "retry accordingly for 5 minutes before falling back
                # to llm-ext"). Before this fix a 408 raised JevValidationError on the FIRST
                # attempt, with no retry at all -- exactly the outage shape the owner's 5-minute
                # retry budget is supposed to ride out.
                if response.status_code == 408 or response.status_code == 429 or response.status_code >= 500:
                    retry_after = self._retry_after_seconds(response)
                    last_error = JevUnavailableError(
                        f"Jev (OpenRouter) returned {response.status_code}: {_error_detail(response)}",
                        status=response.status_code, cause=f"HTTP {response.status_code}",
                        retry_after=retry_after,
                    )
                    if is_last_attempt:
                        break
                    self._sleep(self._retry_policy.delay(attempt, retry_after=retry_after))
                    continue
                # Any other 4xx (400/404/413/422/...): the request is bad in some way retrying
                # cannot fix -- raises JevValidationError, which jev_compact.py's
                # `_stamp_kind_for_error` stamps `kind="invalid"` (TRDD-RAEGS1D5): scoped to THIS
                # request, never a machine-wide outage, so it must not decline a later attempt the
                # way the exhausted-retries JevUnavailableError above correctly does.
                raise JevValidationError(f"Jev (OpenRouter) returned {response.status_code}: {_error_detail(response)}")

        status, cause, retry_after = _detail_from_last_error(last_error)
        raise JevUnavailableError(
            f"Jev (OpenRouter) request failed after {self._retry_policy.max_retries + 1} attempt(s)",
            status=status, cause=cause, retry_after=retry_after,
        ) from last_error

    def _retry_after_seconds(self, response: httpx.Response) -> float | None:
        header = response.headers.get("retry-after")
        if header is None:
            return None
        seconds = _parse_retry_after(header)
        if seconds is None:
            return None
        return min(seconds, self._timeout)

    def _parse_response(self, response: httpx.Response, questions: Mapping[str, Question]) -> dict[str, Answer]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise JevValidationError(f"Jev (OpenRouter) response was not valid JSON: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise JevValidationError("Jev (OpenRouter) response body must be a JSON object")
        raw_answers = payload.get("answers")
        if not isinstance(raw_answers, Mapping):
            raise JevValidationError("Jev (OpenRouter) response is missing an 'answers' object")

        answers: dict[str, Answer] = {}
        for key in questions:
            if key not in raw_answers:
                raise JevValidationError(f"Jev (OpenRouter) response is missing an answer for {key!r}")
            answers[key] = parse_answer(raw_answers[key])

        # `model`, `id`, `provider` (per §M1's live probe) are read by nobody here — that
        # IS how "tolerate the extra fields" works for a dict payload: absence of a
        # `.get()` call for a key is absence of a dependency on it.
        usage = payload.get("usage")
        usage_map = usage if isinstance(usage, Mapping) else {}
        self.usage.record(
            input_tokens=int(usage_map.get("input_tokens", 0) or 0),
            output_tokens=int(usage_map.get("output_tokens", 0) or 0),
            cost=float(usage_map.get("cost", 0.0) or 0.0),
        )
        return answers
