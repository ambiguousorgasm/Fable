"""Auditor — beat-loop integrity layer (CORE §3; phase 8).

Two hooks wired into BeatRunner.run (D-018, D-019):
  Pre-commit  — deterministic consistency check before CommitPipeline.commit.
  Post-narration (step 7) — structural + semantic check before log write.

Failure tiers (D-018):
  CRITICAL     → abort the beat; narration not written to the log.
  NON_CRITICAL → retry; on exhaustion, degrade and log a warning; play continues.
  ADVISORY     → log to GM audience only; play continues.

Semantic auditing (D-019):
  On by default; advisory unless confidence >= HIGH_CONFIDENCE_THRESHOLD and
  the contradiction threatens a *revealed* canon fact not set via an override.
  Disable via Auditor(semantic=False) or by omitting a gateway.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import anthropic

from .access import Fact
from .events import Commitment
from .provider import ModelGateway


HIGH_CONFIDENCE_THRESHOLD = 0.9


class AuditTier(str, Enum):
    CRITICAL = "critical"
    NON_CRITICAL = "non_critical"
    ADVISORY = "advisory"


@dataclass(frozen=True)
class AuditFlag:
    tier: AuditTier
    category: str
    description: str


@dataclass
class AuditResult:
    passed: bool
    flags: list[AuditFlag] = field(default_factory=list)

    @property
    def any_blocking(self) -> bool:
        return any(f.tier == AuditTier.CRITICAL for f in self.flags)


# --------------------------------------------------------------------------- #
# Semantic check tool                                                           #
# --------------------------------------------------------------------------- #

_SEMANTIC_TOOL: dict[str, Any] = {
    "name": "report_consistency",
    "description": (
        "Report semantic contradictions between narrator prose and committed canon facts. "
        "Only flag genuine contradictions where the narration implies a different value "
        "from what the canon says. Do not flag facts that are simply unmentioned."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "contradictions": {
                "type": "array",
                "description": "Contradictions found. Empty list if none.",
                "items": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string"},
                        "predicate": {"type": "string"},
                        "committed_value": {"type": "string"},
                        "narrated_value": {"type": "string"},
                        "confidence": {
                            "type": "number",
                            "description": "0.0–1.0 certainty that this is a real contradiction.",
                        },
                    },
                    "required": [
                        "subject", "predicate",
                        "committed_value", "narrated_value", "confidence",
                    ],
                },
            },
        },
        "required": ["contradictions"],
    },
}

_SEMANTIC_SYSTEM = (
    "You are a semantic consistency auditor for a tabletop RPG. "
    "Detect contradictions between narrator prose and committed world facts. "
    "Be conservative: only flag genuine contradictions, not missing details or new information. "
    "Call report_consistency exactly once."
)


# --------------------------------------------------------------------------- #
# Auditor                                                                       #
# --------------------------------------------------------------------------- #

class Auditor:
    """Live integrity layer for the FABLE beat loop.

    Deterministic checks always run. Semantic checks require a client and are
    enabled by default (disable with semantic=False). All results are returned
    as AuditResult — no exceptions are raised to the caller.
    """

    def __init__(
        self,
        gateway: ModelGateway | None = None,
        model: str = "claude-haiku-4-5-20251001",
        semantic: bool = True,
        max_retries: int = 2,
    ) -> None:
        self._gateway = gateway
        self._model = model
        self._semantic = semantic and (gateway is not None)
        self._max_retries = max_retries

    # --- Pre-commit hook ------------------------------------------------

    def check_commitments(
        self,
        commitments: list[Commitment],
        canon: dict[tuple[str, str], Fact],
        *,
        is_override: bool = False,
    ) -> AuditResult:
        """Deterministic pre-commit check (D-018 pre-commit hook).

        Passes immediately if is_override=True: a logged override is intentional
        fiat and is never a bug (D-008). Otherwise checks each revealed
        commitment against the canon ledger for contradictions (CRITICAL).
        Hidden commitments are not yet part of the immutable boundary and are
        not checked — revising hidden facts is the plot-manager's job.
        """
        if is_override:
            return AuditResult(passed=True)

        flags: list[AuditFlag] = []
        for c in commitments:
            if not c.revealed:
                continue
            existing = canon.get((c.subject, c.predicate))
            if existing is not None and existing.value != c.value:
                flags.append(AuditFlag(
                    tier=AuditTier.CRITICAL,
                    category="canon_contradiction",
                    description=(
                        f"{c.subject}.{c.predicate}: proposed {c.value!r} but "
                        f"canon holds {existing.value!r} (event {existing.event_id})"
                    ),
                ))

        return AuditResult(passed=not flags, flags=flags)

    # --- Post-narration hook (step 7) -----------------------------------

    def check_narration(
        self,
        narration: str,
        actor: str,
        action: str,
        canon: dict[tuple[str, str], Fact],
    ) -> AuditResult:
        """Structural + optional semantic check on narrator output (D-018/D-019).

        Structural check (always): empty prose is CRITICAL.
        Semantic check (if self._semantic and canon is non-empty): model call
        with retry; failure degrades to NON_CRITICAL so play is never blocked
        by a model API error.
        """
        flags: list[AuditFlag] = []

        if not narration.strip():
            flags.append(AuditFlag(
                tier=AuditTier.CRITICAL,
                category="structural",
                description="Narrator returned empty narration.",
            ))
            return AuditResult(passed=False, flags=flags)

        if self._semantic and canon:
            semantic_flags = self._semantic_check_with_retry(narration, actor, action, canon)
            flags.extend(semantic_flags)

        blocking = any(f.tier == AuditTier.CRITICAL for f in flags)
        return AuditResult(passed=not blocking, flags=flags)

    # --- Semantic check (private) ---------------------------------------

    def _semantic_check_with_retry(
        self,
        narration: str,
        actor: str,
        action: str,
        canon: dict[tuple[str, str], Fact],
    ) -> list[AuditFlag]:
        last_exc: Exception | None = None
        for _ in range(self._max_retries + 1):
            try:
                return self._run_semantic_check(narration, actor, action, canon)
            except Exception as exc:
                last_exc = exc

        return [AuditFlag(
            tier=AuditTier.NON_CRITICAL,
            category="model_failure",
            description=(
                f"Semantic check unavailable after {self._max_retries + 1} attempt(s): "
                f"{last_exc!s:.80}"
            ),
        )]

    def _run_semantic_check(
        self,
        narration: str,
        actor: str,
        action: str,
        canon: dict[tuple[str, str], Fact],
    ) -> list[AuditFlag]:
        revealed = [f for f in canon.values() if f.revealed][:20]
        facts_text = "\n".join(
            f"  {f.subject}.{f.predicate} = {f.value!r}" for f in revealed
        ) or "  (none)"

        user_message = (
            f"Committed canon facts:\n{facts_text}\n\n"
            f"Actor: {actor}\n"
            f"Action: {action}\n\n"
            f"Narration:\n{narration}\n\n"
            "Call report_consistency with any contradictions you find."
        )

        response = self._gateway.call(  # type: ignore[union-attr]
            "auditor",
            model=self._model,
            max_tokens=256,
            system=_SEMANTIC_SYSTEM,
            messages=[{"role": "user", "content": user_message}],
            tools=[_SEMANTIC_TOOL],
            tool_choice={"type": "tool", "name": "report_consistency"},
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == "report_consistency":
                return self._flags_from_contradictions(
                    block.input.get("contradictions", []), canon
                )

        raise RuntimeError(
            "semantic audit: report_consistency tool call not found in model response"
        )

    def _flags_from_contradictions(
        self,
        contradictions: list[dict],
        canon: dict[tuple[str, str], Fact],
    ) -> list[AuditFlag]:
        """Apply D-019 escalation rule to model-reported contradictions.

        Escalate to CRITICAL when:
          - confidence >= HIGH_CONFIDENCE_THRESHOLD, AND
          - the threatened fact is revealed in canon, AND
          - it was not already set via a logged override (override IS the
            transition that explains the value change — D-008/D-019).
        """
        flags: list[AuditFlag] = []
        for c in contradictions:
            confidence = float(c.get("confidence", 0.0))
            subject = str(c.get("subject", ""))
            predicate = str(c.get("predicate", ""))
            existing = canon.get((subject, predicate))

            if (
                confidence >= HIGH_CONFIDENCE_THRESHOLD
                and existing is not None
                and existing.revealed
                and not existing.via_override
            ):
                tier = AuditTier.CRITICAL
            else:
                tier = AuditTier.ADVISORY

            flags.append(AuditFlag(
                tier=tier,
                category="semantic",
                description=(
                    f"{subject}.{predicate}: canon={c.get('committed_value')!r}, "
                    f"narrated={c.get('narrated_value')!r} "
                    f"(confidence={confidence:.2f})"
                ),
            ))
        return flags
