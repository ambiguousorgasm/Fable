"""Plot graph — campaign structure for runtime management (CORE §7.4; phase 9).

The plot graph is the GM's private model of the campaign's living structure:
narrative functions (what the story needs), their current fixture bindings
(which entity delivers each need), active fronts (off-screen threats with
clocks), factions (standing forces), and hidden nodes (prepared-but-unrevealed
material). It is never exposed to player or TM belief projections.

Ownership (D-016): the PlotManager is the sole authoritative writer. Other
agents propose revisions through it; nothing writes the graph directly.

Scope (D-020): the graph is authored or AI-assisted during campaign setup.
Autonomous generation of a complete campaign graph from scratch is out of scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# --------------------------------------------------------------------------- #
# Core graph types                                                               #
# --------------------------------------------------------------------------- #

@dataclass
class FunctionNode:
    """An abstract narrative need the plot must fulfill — fixture-independent.

    Examples: "the party learns of the conspiracy," "a way into the vault exists."
    The function stays constant even when the fixture delivering it changes.
    """

    id: str
    description: str
    required: bool = True


@dataclass
class FixtureBinding:
    """The current delivery mechanism for a function node.

    Maps a function to the specific entity (NPC, location, item) that currently
    delivers it. If the fixture is destroyed or blocked, the PlotManager searches
    for an alternative binding.
    """

    function_id: str
    fixture_entity_id: str
    description: str


@dataclass
class Hook:
    """A live narrative function with its current fixture and preconditions.

    Preconditions are entity IDs that must be alive/available for this hook
    to be in play. An inactive hook is not monitored for fixture health.
    """

    function_id: str
    binding: FixtureBinding
    preconditions: list[str] = field(default_factory=list)
    active: bool = True


@dataclass
class Front:
    """An off-screen threat tracked by a world clock (CORE §7.4).

    When `clock_name` fills, `consequence_truth` becomes a committed canvas fact
    (via WorldSimulator → PlotManager's front-fire response). Optional
    `faction_id` links the front to a standing force.
    """

    id: str
    name: str
    threat: str
    clock_name: str
    consequence_truth: str
    faction_id: str | None = None


@dataclass
class Faction:
    """A standing force with goals and momentum in the campaign world."""

    id: str
    name: str
    goals: list[str] = field(default_factory=list)
    momentum: int = 0


# --------------------------------------------------------------------------- #
# PlotGraph                                                                     #
# --------------------------------------------------------------------------- #

@dataclass
class PlotGraph:
    """The campaign's living plot structure — GM-private, PlotManager-owned.

    `alternative_fixtures` maps function_id → ordered list of backup
    FixtureBindings to try when the active fixture is blocked.
    `hidden_nodes` are prepared-but-unrevealed function nodes; the PlotManager
    may promote them to active hooks when interest signals warrant it.
    """

    function_nodes: dict[str, FunctionNode] = field(default_factory=dict)
    hooks: list[Hook] = field(default_factory=list)
    fronts: list[Front] = field(default_factory=list)
    factions: list[Faction] = field(default_factory=list)
    hidden_nodes: list[FunctionNode] = field(default_factory=list)
    alternative_fixtures: dict[str, list[FixtureBinding]] = field(default_factory=dict)

    def add_function(self, node: FunctionNode) -> None:
        self.function_nodes[node.id] = node

    def add_hook(self, hook: Hook) -> None:
        self.hooks.append(hook)

    def add_front(self, front: Front) -> None:
        self.fronts.append(front)

    def add_faction(self, faction: Faction) -> None:
        self.factions.append(faction)

    def set_alternatives(
        self, function_id: str, alternatives: list[FixtureBinding]
    ) -> None:
        self.alternative_fixtures[function_id] = alternatives

    def add_hidden_node(self, node: FunctionNode) -> None:
        self.hidden_nodes.append(node)

    def update_hook_binding(
        self, function_id: str, new_binding: FixtureBinding
    ) -> None:
        """Replace the active binding for the given function. No-op if not found."""
        for hook in self.hooks:
            if hook.function_id == function_id:
                hook.binding = new_binding
                return

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict (for persistence)."""
        return {
            "function_nodes": {
                id_: {"id": fn.id, "description": fn.description, "required": fn.required}
                for id_, fn in self.function_nodes.items()
            },
            "hooks": [
                {
                    "function_id": h.function_id,
                    "binding": {
                        "function_id": h.binding.function_id,
                        "fixture_entity_id": h.binding.fixture_entity_id,
                        "description": h.binding.description,
                    },
                    "preconditions": list(h.preconditions),
                    "active": h.active,
                }
                for h in self.hooks
            ],
            "fronts": [
                {
                    "id": f.id,
                    "name": f.name,
                    "threat": f.threat,
                    "clock_name": f.clock_name,
                    "consequence_truth": f.consequence_truth,
                    "faction_id": f.faction_id,
                }
                for f in self.fronts
            ],
            "factions": [
                {
                    "id": fac.id,
                    "name": fac.name,
                    "goals": list(fac.goals),
                    "momentum": fac.momentum,
                }
                for fac in self.factions
            ],
            "hidden_nodes": [
                {"id": n.id, "description": n.description, "required": n.required}
                for n in self.hidden_nodes
            ],
            "alternative_fixtures": {
                fn_id: [
                    {
                        "function_id": b.function_id,
                        "fixture_entity_id": b.fixture_entity_id,
                        "description": b.description,
                    }
                    for b in bindings
                ]
                for fn_id, bindings in self.alternative_fixtures.items()
            },
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PlotGraph":
        """Deserialize from a dict produced by `to_dict()`."""
        g = cls()
        for id_, fn_data in d.get("function_nodes", {}).items():
            g.function_nodes[id_] = FunctionNode(
                id=fn_data["id"],
                description=fn_data["description"],
                required=fn_data.get("required", True),
            )
        for h_data in d.get("hooks", []):
            b = h_data["binding"]
            g.hooks.append(Hook(
                function_id=h_data["function_id"],
                binding=FixtureBinding(
                    function_id=b["function_id"],
                    fixture_entity_id=b["fixture_entity_id"],
                    description=b["description"],
                ),
                preconditions=list(h_data.get("preconditions", [])),
                active=h_data.get("active", True),
            ))
        for f_data in d.get("fronts", []):
            g.fronts.append(Front(
                id=f_data["id"],
                name=f_data["name"],
                threat=f_data["threat"],
                clock_name=f_data["clock_name"],
                consequence_truth=f_data["consequence_truth"],
                faction_id=f_data.get("faction_id"),
            ))
        for fac_data in d.get("factions", []):
            g.factions.append(Faction(
                id=fac_data["id"],
                name=fac_data["name"],
                goals=list(fac_data.get("goals", [])),
                momentum=fac_data.get("momentum", 0),
            ))
        for n_data in d.get("hidden_nodes", []):
            g.hidden_nodes.append(FunctionNode(
                id=n_data["id"],
                description=n_data["description"],
                required=n_data.get("required", False),
            ))
        for fn_id, bindings_data in d.get("alternative_fixtures", {}).items():
            g.alternative_fixtures[fn_id] = [
                FixtureBinding(
                    function_id=b["function_id"],
                    fixture_entity_id=b["fixture_entity_id"],
                    description=b["description"],
                )
                for b in bindings_data
            ]
        return g

    def front_for_clock(self, clock_name: str) -> Front | None:
        """Return the front that owns a given clock, if any."""
        for front in self.fronts:
            if front.clock_name == clock_name:
                return front
        return None


# --------------------------------------------------------------------------- #
# InterestSignalAccumulator                                                     #
# --------------------------------------------------------------------------- #

@dataclass
class InterestSignal:
    """A weighted signal indicating player or fictional attention on a subject."""

    subject: str
    category: str
    weight: float
    causal_event_id: str = ""


class InterestSignalAccumulator:
    """Accumulates weighted interest signals per subject/thread.

    Sources: player queries (D-003), repeated fictional attention, distance
    queries, failed fixture checks, and beat events. The PlotManager reads
    these to decide which unplanned threads warrant promotion into standing
    structure.
    """

    PROMOTION_THRESHOLD: float = 5.0

    def __init__(self) -> None:
        self._signals: list[InterestSignal] = []

    def emit(
        self,
        subject: str,
        category: str,
        weight: float,
        causal_event_id: str = "",
    ) -> None:
        self._signals.append(
            InterestSignal(
                subject=subject,
                category=category,
                weight=weight,
                causal_event_id=causal_event_id,
            )
        )

    def total_weight(self, subject: str) -> float:
        return sum(s.weight for s in self._signals if s.subject == subject)

    def top_subjects(self, n: int = 5) -> list[tuple[str, float]]:
        totals: dict[str, float] = {}
        for s in self._signals:
            totals[s.subject] = totals.get(s.subject, 0.0) + s.weight
        return sorted(totals.items(), key=lambda x: x[1], reverse=True)[:n]

    def promotion_candidates(self) -> list[str]:
        """Subjects whose total weight exceeds the promotion threshold."""
        return [
            subject
            for subject, weight in self.top_subjects(n=len(self._signals))
            if weight >= self.PROMOTION_THRESHOLD
        ]

    def signals_for(self, subject: str) -> list[InterestSignal]:
        return [s for s in self._signals if s.subject == subject]

    @property
    def all_signals(self) -> list[InterestSignal]:
        return list(self._signals)
