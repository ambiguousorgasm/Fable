"""Dice service — logged, auditable randomness (CORE §3, §7.2).

No outcome a model claims is real unless it came from here. Every roll is
written to the event log as a `dice_roll` event through the mechanical
capability, so it cannot be faked by a direct append.

The RNG is injectable so rolls are deterministic under test.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .event_log import _MECHANICAL_CAPABILITY, EventLog
from .events import ROLL_VISIBILITY_LEVELS, Visibility


@dataclass(frozen=True)
class DiceResult:
    notation: str
    rolls: tuple[int, ...]
    total: int
    event_id: str


class DiceService:
    def __init__(self, log: EventLog, rng: random.Random | None = None) -> None:
        self._log = log
        self._rng = rng if rng is not None else random.Random()

    def roll(
        self,
        count: int,
        sides: int,
        *,
        author: str,
        audience: tuple[str, ...] | list[str] = (),
        reason: str = "",
        visibility: Visibility = "content",
        roll_visibility: str = "table",
    ) -> DiceResult:
        if count < 1 or sides < 2:
            raise ValueError("roll needs count >= 1 and sides >= 2")
        if roll_visibility not in ROLL_VISIBILITY_LEVELS:
            raise ValueError(
                f"roll_visibility must be one of {sorted(ROLL_VISIBILITY_LEVELS)}"
            )
        rolls = tuple(self._rng.randint(1, sides) for _ in range(count))
        total = sum(rolls)
        notation = f"{count}d{sides}"
        content = f"{notation} = {list(rolls)} = {total}"
        if reason:
            content += f" ({reason})"
        event = self._log.append(
            author=author,
            channel="dice",
            type="dice_roll",
            content=content,
            audience=audience,
            visibility=visibility,
            roll_visibility=roll_visibility,
            _capability=_MECHANICAL_CAPABILITY,
        )
        return DiceResult(notation=notation, rolls=rolls, total=total, event_id=event.id)
