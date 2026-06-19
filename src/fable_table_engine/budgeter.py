"""Context budget management (Phase 22; D-042).

ContextBudgeter enforces per-role token/event limits at context-assembly time.
Correct data flow: belief store → ContextBudgeter → prompt strings → ModelGateway.

TokenEstimator uses a fast char-count proxy as the primary gate; calls the
`count_tokens` API only when the proxy estimate is near the per-role cap
(hybrid approach from D-042 option C).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .settings import SettingsManager


@dataclass(frozen=True)
class ContextBudgetPolicy:
    """Per-role budget configuration."""

    max_tokens: int
    event_window: int
    required_sections: tuple[str, ...] = ()
    summarize_older: bool = False


@dataclass(frozen=True)
class BudgetCheckResult:
    """Result of a budget-fit check for one assembled prompt."""

    role: str
    token_estimate: int
    cap: int
    fits: bool

    @property
    def over_by(self) -> int:
        return max(0, self.token_estimate - self.cap)


class TokenEstimator:
    """Hybrid token estimator: fast proxy + optional API preflight.

    Proxy: ``len(text) // CHARS_PER_TOKEN`` — no network call, O(1).
    Preflight: if the proxy reaches ``PREFLIGHT_THRESHOLD × cap``, call
    ``client.messages.count_tokens`` for an accurate count. Falls back to the
    proxy on any exception so the call path never blocks on estimator failure.
    """

    CHARS_PER_TOKEN: int = 4
    PREFLIGHT_THRESHOLD: float = 0.80

    def __init__(self, client: Any = None) -> None:
        self._client = client

    def estimate(self, text: str) -> int:
        """Fast char-count proxy. Returns at least 1."""
        return max(1, len(text) // self.CHARS_PER_TOKEN)

    def count(self, text: str, model: str, cap: int) -> int:
        """Return token count, calling API only when proxy is near cap."""
        proxy = self.estimate(text)
        if self._client is None or proxy < int(cap * self.PREFLIGHT_THRESHOLD):
            return proxy
        try:
            result = self._client.messages.count_tokens(
                model=model,
                messages=[{"role": "user", "content": text}],
            )
            return int(result.input_tokens)
        except Exception:
            return proxy


# Per-role budget policies (D-042 table).
_DEFAULT_POLICIES: dict[str, ContextBudgetPolicy] = {
    "gm_adjudicator":    ContextBudgetPolicy(max_tokens=40_000, event_window=20),
    "gm_narrator":       ContextBudgetPolicy(max_tokens=20_000, event_window=8),
    "character_agent":   ContextBudgetPolicy(max_tokens=12_000, event_window=12),
    "social_interpreter": ContextBudgetPolicy(max_tokens=8_000, event_window=6),
    "auditor":           ContextBudgetPolicy(max_tokens=16_000, event_window=10),
    "plot_manager":      ContextBudgetPolicy(max_tokens=24_000, event_window=15),
}

# Fallback for unrecognised roles.
_FALLBACK_POLICY = _DEFAULT_POLICIES["gm_adjudicator"]


class ContextBudgeter:
    """Applies per-role budget policies at context-assembly time.

    Instantiate once per session (or via ``from_settings``). BeatRunner holds
    one instance and uses ``event_window(role)`` when slicing events for each
    model call.

    Example::

        budgeter = ContextBudgeter()
        limit = budgeter.event_window("gm_adjudicator")  # 20
        gm_events = _events_summary(store, limit=limit)
    """

    DEFAULT_POLICIES: dict[str, ContextBudgetPolicy] = _DEFAULT_POLICIES

    def __init__(
        self,
        policies: dict[str, ContextBudgetPolicy] | None = None,
        estimator: TokenEstimator | None = None,
    ) -> None:
        self._policies: dict[str, ContextBudgetPolicy] = {
            **self.DEFAULT_POLICIES,
            **(policies or {}),
        }
        self._estimator = estimator or TokenEstimator()

    # ------------------------------------------------------------------
    # Policy access
    # ------------------------------------------------------------------

    def policy(self, role: str) -> ContextBudgetPolicy:
        """Return the policy for ``role``, falling back to the adjudicator policy."""
        return self._policies.get(role, _FALLBACK_POLICY)

    def event_window(self, role: str) -> int:
        return self.policy(role).event_window

    # ------------------------------------------------------------------
    # Event trimming
    # ------------------------------------------------------------------

    def trim_events(self, events: list, role: str) -> list:
        """Return the most-recent ``event_window(role)`` events."""
        window = self.event_window(role)
        return events[-window:] if len(events) > window else list(events)

    # ------------------------------------------------------------------
    # Quality checks
    # ------------------------------------------------------------------

    def check_sections(self, sections: dict[str, str], role: str) -> list[str]:
        """Return required section keys that are empty or absent after assembly."""
        required = self.policy(role).required_sections
        return [k for k in required if not sections.get(k, "").strip()]

    def check_budget(
        self,
        text: str,
        role: str,
        model: str | None = None,
    ) -> BudgetCheckResult:
        """Estimate assembled text size against the role's token cap."""
        pol = self.policy(role)
        count = self._estimator.count(text, model or "claude-opus-4-8", pol.max_tokens)
        return BudgetCheckResult(
            role=role,
            token_estimate=count,
            cap=pol.max_tokens,
            fits=count <= pol.max_tokens,
        )

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_settings(
        cls,
        settings: SettingsManager,
        campaign_id: str | None = None,
        estimator: TokenEstimator | None = None,
    ) -> ContextBudgeter:
        """Build from SettingsManager, overriding defaults with user/campaign values.

        Reads ``{role}_max_tokens`` and ``{role}_event_window`` for each role;
        falls back to DEFAULT_POLICIES on missing or non-integer values.
        """
        def _int(key: str, default: int) -> int:
            try:
                raw = settings.get(key, campaign_id=campaign_id)
                return int(raw) if raw else default
            except (ValueError, KeyError, TypeError):
                return default

        policies: dict[str, ContextBudgetPolicy] = {}
        for role_key, default_pol in cls.DEFAULT_POLICIES.items():
            mt = _int(f"{role_key}_max_tokens", default_pol.max_tokens)
            ew = _int(f"{role_key}_event_window", default_pol.event_window)
            policies[role_key] = ContextBudgetPolicy(
                max_tokens=mt,
                event_window=ew,
                required_sections=default_pol.required_sections,
                summarize_older=default_pol.summarize_older,
            )
        return cls(policies=policies, estimator=estimator)
