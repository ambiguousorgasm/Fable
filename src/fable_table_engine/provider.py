"""Provider gateway + isolated telemetry (Phase 14 + Phase 22; D-017, D-022).

ModelGateway is the single controlled seam for all model calls. Every call
site (AdjudicatorGM, NarratorGM, CharacterAgent, Auditor) routes through it.
TelemetrySink records operational data (latency, tokens, cost) completely
outside fictional state — never in the event log, belief stores, or canon.

Phase 22 additions (D-017):
- ProviderAdapter ABC: formal abstraction over provider-specific APIs.
- AnthropicAdapter: wraps the Anthropic SDK client.
- ToolOutputError: raised when a model returns a malformed tool-call response.
- ModelGateway now accepts ProviderAdapter (or raw client for backward compat)
  and an optional SettingsManager for per-role model resolution.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

import anthropic

if TYPE_CHECKING:
    from .settings import SettingsManager

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


class CostCeilingStatus(str, Enum):
    """Session-level cost ceiling check result (D-042).

    OK      — cumulative cost is below 80 % of the ceiling.
    WARNING — cumulative cost is ≥ 80 % and < 100 % of the ceiling.
    EXCEEDED — cumulative cost has reached or passed the ceiling.

    When ceiling is None, always returns OK.
    """

    OK = "ok"
    WARNING = "warning"
    EXCEEDED = "exceeded"


class TelemetrySink:
    """In-process telemetry store. Zero coupling to fictional state (D-022).

    ``records`` is append-only. ``summary()`` returns totals and per-role
    breakdowns. Never referenced by EventLog, CommitPipeline, or
    ContextAssembler.

    Phase 22 (D-042): accepts an optional ``cost_ceiling_usd``. Call
    ``ceiling_status()`` to check whether the session has approached or
    exceeded the configured budget. Default policy is advisory-only — the
    engine checks status and surfaces a warning; a hard cutoff requires the
    caller to act on EXCEEDED.
    """

    _WARNING_FRACTION: float = 0.80

    def __init__(self, cost_ceiling_usd: float | None = None) -> None:
        self.records: list[CallRecord] = []
        self.cost_ceiling_usd = cost_ceiling_usd

    def total_cost_usd(self) -> float:
        return sum(r.cost_usd for r in self.records)

    def ceiling_status(self) -> CostCeilingStatus:
        if self.cost_ceiling_usd is None:
            return CostCeilingStatus.OK
        total = self.total_cost_usd()
        if total >= self.cost_ceiling_usd:
            return CostCeilingStatus.EXCEEDED
        if total >= self.cost_ceiling_usd * self._WARNING_FRACTION:
            return CostCeilingStatus.WARNING
        return CostCeilingStatus.OK

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


class ToolOutputError(Exception):
    """Raised when a model returns a malformed or absent tool-call response.

    Distinct from ModelCallError (network / timeout). Signals that the API call
    succeeded but the response content did not match the expected tool schema
    after all normalization retry attempts.
    """

    def __init__(self, role: str, attempts: int, reason: str) -> None:
        self.role = role
        self.attempts = attempts
        self.reason = reason
        super().__init__(
            f"Tool output malformed for role {role!r} after {attempts} "
            f"attempt(s): {reason}"
        )


# ------------------------------------------------------------------
# ProviderAdapter
# ------------------------------------------------------------------

class ProviderAdapter(ABC):
    """Abstraction over a specific model provider's API.

    Phase 22 introduces this interface to allow future non-Anthropic providers.
    The only supported implementation for now is AnthropicAdapter.

    Implementations must be stateless with respect to model calls — the same
    adapter instance may be reused across concurrent (or sequential) calls.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name (e.g., ``'anthropic'``)."""

    @abstractmethod
    def call(self, role: str, model: str, **kwargs: Any) -> Any:
        """Make one model call and return the raw provider response.

        ``role`` is forwarded for logging/debugging; it must not influence
        the call itself (callers set it; adapters should not branch on it).
        ``model`` must be the fully-qualified model ID string.
        All remaining ``kwargs`` are provider-specific (messages, tools, etc.).
        """


class AnthropicAdapter(ProviderAdapter):
    """Anthropic SDK adapter.

    Wraps ``anthropic.Anthropic`` (or any duck-typed mock) and forwards calls
    to ``client.messages.create(model=model, **kwargs)``.
    """

    def __init__(self, client: anthropic.Anthropic) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "anthropic"

    def call(self, role: str, model: str, **kwargs: Any) -> Any:
        return self._client.messages.create(model=model, **kwargs)


# Maps gateway role strings to SettingsManager keys.
# Roles not in this map fall back to f"{role}_model" as the settings key.
_ROLE_TO_SETTINGS_KEY: dict[str, str] = {
    "adjudicator": "gm_adjudicator_model",
    "narrator": "gm_narrator_model",
    "character_agent": "character_agent_default_model",
    "campaign_compiler": "campaign_compiler_model",
}

_FALLBACK_MODEL = "claude-opus-4-8"

# Transient errors worth retrying.
_RETRYABLE = (anthropic.APITimeoutError, anthropic.APIConnectionError)


class ModelGateway:
    """Single controlled seam for all model calls (Phase 14 + 22; D-017, D-022).

    Phase 22: accepts a ``ProviderAdapter`` (or a raw Anthropic client for
    backward compatibility — wrapped automatically in ``AnthropicAdapter``).
    Accepts an optional ``SettingsManager`` for per-role model resolution.

    Model resolution for each call (highest priority first):
    1. ``SettingsManager.get(settings_key)`` for the role, if settings configured.
    2. ``model=`` kwarg from the call site (legacy / test usage).
    3. ``SettingsRegistry.DEFAULTS.get(settings_key, _FALLBACK_MODEL)``.

    All GM, narrator, character-agent, and auditor calls route through
    ``call()``. Records operational telemetry to TelemetrySink — never to
    fictional state.

    ``timeout_secs`` is forwarded to the SDK as the per-call wall-clock limit.
    ``max_retries`` controls how many additional attempts follow the first
    failure on transient errors. Each retry waits ``0.5 * 2^attempt`` seconds.
    Non-transient errors propagate immediately. Raises ModelCallError after all
    attempts fail.

    Usage::

        gw = ModelGateway(client)                       # backward compat
        gw = ModelGateway(AnthropicAdapter(client))     # Phase 22 style
        gw = ModelGateway(client, settings=settings_mgr)  # per-role routing
        response = gw.call("adjudicator", model="claude-opus-4-8", ...)
    """

    def __init__(
        self,
        client_or_adapter: anthropic.Anthropic | ProviderAdapter,
        sink: TelemetrySink | None = None,
        timeout_secs: float | None = 60.0,
        max_retries: int = 1,
        settings: SettingsManager | None = None,
    ) -> None:
        if isinstance(client_or_adapter, ProviderAdapter):
            self._adapter = client_or_adapter
            self._client = getattr(client_or_adapter, "_client", None)
        else:
            self._adapter = AnthropicAdapter(client_or_adapter)
            self._client = client_or_adapter
        self.sink = sink or TelemetrySink()
        self.timeout_secs = timeout_secs
        self.max_retries = max_retries
        self._settings = settings

    def _resolve_model(self, role: str, kwargs: dict[str, Any]) -> str:
        """Return the model ID to use for this call.

        Checks settings first; falls back to call-site kwarg; then registry default.
        """
        settings_key = _ROLE_TO_SETTINGS_KEY.get(role, f"{role}_model")
        if self._settings is not None:
            value = self._settings.get(settings_key)
            if value:
                return value
        kwarg_model = str(kwargs.get("model", ""))
        if kwarg_model:
            return kwarg_model
        from .settings import SettingsRegistry
        return SettingsRegistry.DEFAULTS.get(settings_key, _FALLBACK_MODEL)

    def call(self, role: str, **kwargs: Any) -> Any:
        """Make a model call via the adapter; record telemetry; retry on transient errors.

        ``model=`` in kwargs is used as a fallback when no settings override
        exists for the role. The resolved model is always passed to the adapter
        (it is NOT left in kwargs).
        """
        if self.timeout_secs is not None:
            kwargs.setdefault("timeout", self.timeout_secs)

        model = self._resolve_model(role, kwargs)
        kwargs.pop("model", None)  # adapter sets model; don't double-pass

        last_error: Exception | None = None

        for attempt in range(1 + self.max_retries):
            t0 = time.monotonic()
            try:
                response = self._adapter.call(role, model, **kwargs)
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
