"""FABLE Table Engine — AI-facilitated tabletop RPG table engine.

Phase 1 (deterministic core + event log) public surface. Read CLAUDE.md and the
CORE blueprint (FABLE_Table_Engine_Blueprint.md) before adding modules.
"""

from .dice import DiceResult, DiceService
from .event_log import EventLog
from .events import (
    CHANNELS,
    MECHANICAL_TYPES,
    VISIBILITY_LEVELS,
    Commitment,
    DeterminismBoundaryError,
    Event,
    ProjectedEvent,
)
from .rules import Band, CheckResult, RulesEngine, band_for_margin
from .world_state import Entity, WorldState

__version__ = "0.1.0"

__all__ = [
    "Band",
    "CHANNELS",
    "CheckResult",
    "Commitment",
    "DeterminismBoundaryError",
    "DiceResult",
    "DiceService",
    "Entity",
    "Event",
    "EventLog",
    "MECHANICAL_TYPES",
    "ProjectedEvent",
    "RulesEngine",
    "VISIBILITY_LEVELS",
    "WorldState",
    "band_for_margin",
    "__version__",
]
