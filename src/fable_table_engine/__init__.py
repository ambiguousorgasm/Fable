"""FABLE Table Engine — AI-facilitated tabletop RPG table engine.

Public surface through phase 3 (deterministic core + event log, access/commit
boundary, perception model). Read CLAUDE.md and the CORE blueprint
(FABLE_Table_Engine_Blueprint.md) before adding modules.
"""

from .access import (
    OVERRIDE_TYPE,
    CanonConflictError,
    CommitPipeline,
    Conflict,
    Fact,
    canon_ledger,
    committed_facts,
)
from .context import Belief, BeliefStore, ContextAssembler
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
from .perception import (
    MAY_HAVE_PERCEIVED,
    PERCEPTION_AUTHOR,
    Scene,
    Stimulus,
    derive_overhears,
    perceivers,
    perception_map,
    perceptible_entities,
)
from .rules import Band, CheckResult, RulesEngine, band_for_margin
from .world_state import Entity, WorldState

__version__ = "0.1.0"

__all__ = [
    "Band",
    "Belief",
    "BeliefStore",
    "CHANNELS",
    "CanonConflictError",
    "CheckResult",
    "CommitPipeline",
    "Commitment",
    "Conflict",
    "ContextAssembler",
    "DeterminismBoundaryError",
    "DiceResult",
    "DiceService",
    "Entity",
    "Event",
    "EventLog",
    "Fact",
    "MAY_HAVE_PERCEIVED",
    "MECHANICAL_TYPES",
    "OVERRIDE_TYPE",
    "PERCEPTION_AUTHOR",
    "ProjectedEvent",
    "RulesEngine",
    "Scene",
    "Stimulus",
    "VISIBILITY_LEVELS",
    "WorldState",
    "band_for_margin",
    "canon_ledger",
    "committed_facts",
    "derive_overhears",
    "perceivers",
    "perception_map",
    "perceptible_entities",
    "__version__",
]
