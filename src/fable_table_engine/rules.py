"""Rules engine — minimal interface (CORE §3, §7.2; `FABLE_Engine_Schema_v6.md` §5).

Phase 1 implements only the irreducible mechanical core needed to hold the
determinism boundary: a single check that rolls 3d6 + Skill vs TN through the
dice service, computes the margin, reads the FABLE result band, and logs a
cold `resolution` event linked to its dice event. It is the *adjudicator* half
of the cold/warm split — it reads the outcome, it does not narrate it.

Deliberately NOT here yet (later phases): Exposure, Effect, Trade, the Ledger,
Clocks/Fronts, Stress/Scars, Edge. See `FABLE_Engine_Schema_v6.md` and the roadmap.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .dice import DiceService
from .event_log import _MECHANICAL_CAPABILITY, EventLog


class Band(str, Enum):
    """FABLE result bands by margin (`FABLE_Engine_Schema_v6.md` §5)."""

    TRIUMPH = "Triumph"
    SUCCESS = "Success"
    COST = "Cost"
    SETBACK = "Setback"


def band_for_margin(margin: int) -> Band:
    if margin >= 3:
        return Band.TRIUMPH
    if margin >= 0:
        return Band.SUCCESS
    if margin >= -2:
        return Band.COST
    return Band.SETBACK


@dataclass(frozen=True)
class CheckResult:
    actor: str
    skill: int
    tn: int
    roll_total: int
    margin: int
    band: Band
    dice_event_id: str
    resolution_event_id: str


class RulesEngine:
    def __init__(self, log: EventLog, dice: DiceService) -> None:
        self._log = log
        self._dice = dice

    def resolve_check(
        self,
        *,
        actor: str,
        skill: int,
        tn: int,
        audience: tuple[str, ...] | list[str] = (),
        reason: str = "",
        roll_visibility: str = "table",
    ) -> CheckResult:
        """Resolve one 3d6 + Skill vs TN check and log the cold result.

        The roll comes from the dice service (the only source of real
        randomness); the resolution event is written through the mechanical
        capability and linked to the dice event via `derived_from`, so its
        provenance is auditable.

        `roll_visibility` tags both the dice_roll and resolution events (D-029).
        `gm_only` rolls must use a GM-only audience; that is the caller's
        responsibility — resolve_check enforces the tag, not the audience.
        """
        roll = self._dice.roll(
            3, 6, author=actor, audience=audience,
            reason=reason or f"check vs TN {tn}",
            roll_visibility=roll_visibility,
        )
        roll_total = roll.total + skill
        margin = roll_total - tn
        band = band_for_margin(margin)
        content = (
            f"{actor}: 3d6+{skill} = {roll_total} vs TN {tn} "
            f"-> margin {margin:+d} -> {band.value}"
        )
        resolution = self._log.append(
            author="rules-engine",
            channel="system",
            type="resolution",
            content=content,
            audience=audience,
            visibility="content",
            derived_from=(roll.event_id,),
            roll_visibility=roll_visibility,
            _capability=_MECHANICAL_CAPABILITY,
        )
        return CheckResult(
            actor=actor,
            skill=skill,
            tn=tn,
            roll_total=roll_total,
            margin=margin,
            band=band,
            dice_event_id=roll.event_id,
            resolution_event_id=resolution.id,
        )
