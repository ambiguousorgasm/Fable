"""Provider gateway + isolated telemetry (Phase 14; D-017, D-022).

ModelGateway is the single controlled seam for all model calls. Every call
site (AdjudicatorGM, NarratorGM, CharacterAgent, Auditor) routes through it.
TelemetrySink records operational data (latency, tokens, cost) completely
outside fictional state — never in the event log, belief stores, or canon.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import anthropic

# Per-token pricing in USD.
# Source: Anthropic pricing cached 2026-06-04 via claude-api skill.
# cache_read ≈ 0.1× input; cache_write (5-min TTL) ≈ 1.25× input.
_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input":       3.00 / 1_000_000,
        "output":     15.00 / 1_000_000,
        "cache_read":  0.30 / 1_000_000,
        "cache_write": 3.75 / 1_000_000,
    },
    "claude-haiku-4-5": {
        "input":       1.00 / 1_000_000,
        "output":      5.00 / 1_000_000,
        "cache_read":  0.10 / 1_000_000,
        "cache_write": 1.25 / 1_000_000,
    },
    "claude-haiku-4-5-20251001": {
        "input":       1.00 / 1_000_000,
        "output":      5.00 / 1_000_000,
        "cache_read":  0.10 / 1_000_000,
        "cache_write": 1.25 / 1_000_000,
    },
    "claude-opus-4-8": {
        "input":       5.00 / 1_000_000,
        "output":     25.00 / 1_000_000,
        "cache_read":  0.50 / 1_000_000,
        "cache_write": 6.25 / 1_000_000,
    },
}


def _cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
) -> float:
    prices = _PRICING.get(model, _PRICING["claude-sonnet-4-6"])
    return (
        input_tokens * prices["input"]
        + output_tokens * prices["output"]
        + cache_read_tokens * prices["cache_read"]
        + cache_write_tokens * prices["cache_write"]
    )


@dataclass
class CallRecord:
    """Telemetry for one model call. Never enters fictional state (D-022)."""

    role: str
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    cost_usd: float
    latency_ms: float


class TelemetrySink:
    """In-process telemetry store. Zero coupling to fictional state (D-022).

    `records` is append-only. `summary()` returns totals and per-role
    breakdowns. Never referenced by EventLog, CommitPipeline, or
    ContextAssembler.
    """

    def __init__(self) -> None:
        self.records: list[CallRecord] = []

    def record(self, r: CallRecord) -> None:
        self.records.append(r)

    def summary(self) -> dict[str, Any]:
        if not self.records:
            return {
                "total_cost_usd": 0.0,
                "total_calls": 0,
                "avg_latency_ms": 0.0,
                "by_role": {},
            }
        total_cost = sum(r.cost_usd for r in self.records)
        avg_latency = sum(r.latency_ms for r in self.records) / len(self.records)
        by_role: dict[str, dict[str, Any]] = {}
        for r in self.records:
            slot = by_role.setdefault(r.role, {
                "calls": 0,
                "cost_usd": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
            })
            slot["calls"] += 1
            slot["cost_usd"] += r.cost_usd
            slot["input_tokens"] += r.input_tokens
            slot["output_tokens"] += r.output_tokens
        return {
            "total_cost_usd": total_cost,
            "total_calls": len(self.records),
            "avg_latency_ms": avg_latency,
            "by_role": by_role,
        }


class ModelCallError(Exception):
    """Raised by ModelGateway.call() after all retries are exhausted."""

    def __init__(self, role: str, attempts: int, last_error: Exception) -> None:
        self.role = role
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(
            f"Model call failed for role {role!r} after {attempts} attempt(s): {last_error}"
        )


# Transient errors worth retrying.
_RETRYABLE = (anthropic.APITimeoutError, anthropic.APIConnectionError)


class ModelGateway:
    """Single controlled seam for all model calls (Phase 14; D-017, D-022).

    Wraps an ``anthropic.Anthropic`` client (or any duck-typed mock). All GM,
    narrator, character-agent, and auditor calls route through ``call()``.
    Records operational telemetry to TelemetrySink — never to fictional state.

    ``timeout_secs`` is forwarded to the SDK as the per-call wall-clock limit.
    ``max_retries`` controls how many additional attempts follow the first
    failure on transient errors (APITimeoutError, APIConnectionError). Each retry
    waits ``0.5 * 2^attempt`` seconds (0.5 s, 1.0 s, …). Non-transient errors
    (4xx, auth, etc.) propagate immediately without retry.

    Raises ModelCallError after all attempts fail.

    Usage::

        gw = ModelGateway(client)
        response = gw.call("adjudicator", model="claude-sonnet-4-6", ...)
    """

    def __init__(
        self,
        client: anthropic.Anthropic,
        sink: TelemetrySink | None = None,
        timeout_secs: float | None = 60.0,
        max_retries: int = 1,
    ) -> None:
        self._client = client
        self.sink = sink or TelemetrySink()
        self.timeout_secs = timeout_secs
        self.max_retries = max_retries

    def call(self, role: str, **kwargs: Any) -> anthropic.types.Message:
        """Call ``client.messages.create`` with timeout and retry; record telemetry."""
        if self.timeout_secs is not None:
            kwargs.setdefault("timeout", self.timeout_secs)

        model = str(kwargs.get("model", ""))
        last_error: Exception | None = None

        for attempt in range(1 + self.max_retries):
            t0 = time.monotonic()
            try:
                response = self._client.messages.create(**kwargs)
            except _RETRYABLE as exc:
                last_error = exc
                latency_ms = (time.monotonic() - t0) * 1000.0
                self.sink.record(CallRecord(
                    role=role, model=model,
                    input_tokens=0, output_tokens=0,
                    cache_read_tokens=0, cache_write_tokens=0,
                    cost_usd=0.0, latency_ms=latency_ms,
                ))
                if attempt < self.max_retries:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise ModelCallError(role, attempt + 1, last_error) from last_error

            latency_ms = (time.monotonic() - t0) * 1000.0
            usage = getattr(response, "usage", None)
            if usage is not None:
                input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
                output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
                cache_read_tokens = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
                cache_write_tokens = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
            else:
                input_tokens = output_tokens = cache_read_tokens = cache_write_tokens = 0

            self.sink.record(CallRecord(
                role=role, model=model,
                input_tokens=input_tokens, output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens, cache_write_tokens=cache_write_tokens,
                cost_usd=_cost_usd(
                    model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens
                ),
                latency_ms=latency_ms,
            ))
            return response

        # Unreachable; loop above either returns or raises.
        raise ModelCallError(role, 1 + self.max_retries, last_error)  # type: ignore[arg-type]
