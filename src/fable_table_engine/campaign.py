"""Campaign package — validated campaign data loader (CORE §7.4; phase 17).

A campaign package is a JSON file that seeds the session with a prepared plot
graph (functions, hooks, fronts, factions, hidden nodes) and optional world
state (clocks). It is the authoritative input for the PlotManager; nothing in
the campaign package may appear in player or TM belief projections.

Loading:
    pkg = load_campaign("my_campaign.json")
    graph = pkg.to_plot_graph()      # populate PlotGraph
    pkg.seed_world(world)            # seed WorldState clocks

Cross-reference validation is performed at load time. Unknown function IDs in
hooks, unknown faction IDs in fronts, and unknown clock names in fronts are
all caught before the session starts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .plot_graph import (
    Faction,
    FixtureBinding,
    Front,
    FunctionNode,
    Hook,
    PlotGraph,
)


# --------------------------------------------------------------------------- #
# CampaignPackage                                                               #
# --------------------------------------------------------------------------- #

@dataclass
class CampaignPackage:
    """Validated, deserialized campaign data.

    Produced by `load_campaign` / `load_campaign_dict`. Immutable by convention
    — do not mutate after creation; use `to_plot_graph()` and `seed_world()` to
    produce live mutable objects.
    """

    title: str
    version: str
    description: str
    function_nodes: list[FunctionNode] = field(default_factory=list)
    hooks: list[Hook] = field(default_factory=list)
    fronts: list[Front] = field(default_factory=list)
    factions: list[Faction] = field(default_factory=list)
    hidden_nodes: list[FunctionNode] = field(default_factory=list)
    alternative_fixtures: dict[str, list[FixtureBinding]] = field(default_factory=dict)
    world_clocks: list[dict[str, Any]] = field(default_factory=list)
    lore_entries: list[dict[str, Any]] = field(default_factory=list)

    def lore_deck(self, gm_entity: str = "gm"):
        """Build a LoreDeck from this package's lore_entries (lazy import)."""
        from .lorebook import LoreDeck
        return LoreDeck.from_dicts(self.lore_entries, gm_entity=gm_entity)

    def to_plot_graph(self) -> PlotGraph:
        """Construct a populated in-memory PlotGraph from this package."""
        g = PlotGraph()
        for fn in self.function_nodes:
            g.add_function(fn)
        for hook in self.hooks:
            g.add_hook(hook)
        for front in self.fronts:
            g.add_front(front)
        for faction in self.factions:
            g.add_faction(faction)
        for node in self.hidden_nodes:
            g.add_hidden_node(node)
        for fn_id, alts in self.alternative_fixtures.items():
            g.set_alternatives(fn_id, alts)
        return g

    def seed_world(self, world: Any) -> None:
        """Add campaign-defined clocks to WorldState.

        The `name` key in each clock dict is used as the clock identifier;
        all other keys are stored as clock data passed to `WorldState.set_clock`.
        """
        for clock in self.world_clocks:
            name = clock["name"]
            data = {k: v for k, v in clock.items() if k != "name"}
            world.set_clock(name, data)


# --------------------------------------------------------------------------- #
# Public loaders                                                                #
# --------------------------------------------------------------------------- #

def load_campaign(path: str | Path) -> CampaignPackage:
    """Read and validate a campaign JSON file."""
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Cannot read campaign file {path!r}: {exc}") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Campaign file {path!r} is not valid JSON: {exc}") from exc
    return load_campaign_dict(data)


def load_campaign_dict(data: dict[str, Any]) -> CampaignPackage:
    """Validate and deserialize a campaign dict.

    Raises `ValueError` for any structural error or cross-reference violation.
    """
    if not isinstance(data, dict):
        raise ValueError("Campaign must be a JSON object")

    title = data.get("title")
    if not title or not isinstance(title, str):
        raise ValueError("Campaign requires a non-empty 'title' string")

    version = data.get("version")
    if not version or not isinstance(version, str):
        raise ValueError("Campaign requires a non-empty 'version' string")

    description = str(data.get("description", ""))

    # ---- function nodes ---------------------------------------------------- #
    function_nodes: list[FunctionNode] = []
    fn_ids: set[str] = set()
    for i, fn_data in enumerate(data.get("function_nodes", [])):
        fn_id = _req_str(fn_data, "id", f"function_nodes[{i}]")
        if fn_id in fn_ids:
            raise ValueError(f"Duplicate function_node id {fn_id!r}")
        fn_ids.add(fn_id)
        function_nodes.append(FunctionNode(
            id=fn_id,
            description=_req_str(fn_data, "description", f"function_nodes[{i}]"),
            required=bool(fn_data.get("required", True)),
        ))

    # ---- hidden nodes ------------------------------------------------------- #
    hidden_nodes: list[FunctionNode] = []
    hidden_ids: set[str] = set()
    for i, n_data in enumerate(data.get("hidden_nodes", [])):
        n_id = _req_str(n_data, "id", f"hidden_nodes[{i}]")
        if n_id in hidden_ids or n_id in fn_ids:
            raise ValueError(f"Duplicate hidden_node id {n_id!r}")
        hidden_ids.add(n_id)
        hidden_nodes.append(FunctionNode(
            id=n_id,
            description=_req_str(n_data, "description", f"hidden_nodes[{i}]"),
            required=bool(n_data.get("required", False)),
        ))

    # ---- factions ----------------------------------------------------------- #
    factions: list[Faction] = []
    faction_ids: set[str] = set()
    for i, fac_data in enumerate(data.get("factions", [])):
        fac_id = _req_str(fac_data, "id", f"factions[{i}]")
        if fac_id in faction_ids:
            raise ValueError(f"Duplicate faction id {fac_id!r}")
        faction_ids.add(fac_id)
        goals = fac_data.get("goals", [])
        if not isinstance(goals, list):
            raise ValueError(f"factions[{i}].goals must be a list")
        factions.append(Faction(
            id=fac_id,
            name=_req_str(fac_data, "name", f"factions[{i}]"),
            goals=[str(g) for g in goals],
            momentum=int(fac_data.get("momentum", 0)),
        ))

    # ---- world clocks ------------------------------------------------------- #
    world_clocks: list[dict[str, Any]] = []
    clock_names: set[str] = set()
    for i, c_data in enumerate(data.get("world_clocks", [])):
        if not isinstance(c_data, dict):
            raise ValueError(f"world_clocks[{i}] must be an object")
        name = _req_str(c_data, "name", f"world_clocks[{i}]")
        if name in clock_names:
            raise ValueError(f"Duplicate world_clock name {name!r}")
        clock_names.add(name)
        world_clocks.append(dict(c_data))

    # ---- hooks + alternatives ----------------------------------------------- #
    hooks: list[Hook] = []
    alternative_fixtures: dict[str, list[FixtureBinding]] = {}
    for i, h_data in enumerate(data.get("hooks", [])):
        if not isinstance(h_data, dict):
            raise ValueError(f"hooks[{i}] must be an object")
        fn_id = _req_str(h_data, "function_id", f"hooks[{i}]")
        if fn_id not in fn_ids:
            raise ValueError(
                f"hooks[{i}].function_id {fn_id!r} does not match any function_node"
            )
        b_data = h_data.get("binding")
        if not isinstance(b_data, dict):
            raise ValueError(f"hooks[{i}].binding must be an object")
        binding = FixtureBinding(
            function_id=_req_str(b_data, "function_id", f"hooks[{i}].binding"),
            fixture_entity_id=_req_str(
                b_data, "fixture_entity_id", f"hooks[{i}].binding"
            ),
            description=_req_str(b_data, "description", f"hooks[{i}].binding"),
        )
        preconditions = h_data.get("preconditions", [])
        if not isinstance(preconditions, list):
            raise ValueError(f"hooks[{i}].preconditions must be a list")
        hooks.append(Hook(
            function_id=fn_id,
            binding=binding,
            preconditions=[str(p) for p in preconditions],
            active=bool(h_data.get("active", True)),
        ))
        # Alternatives are embedded per hook in the campaign JSON.
        alts_raw = h_data.get("alternatives", [])
        if not isinstance(alts_raw, list):
            raise ValueError(f"hooks[{i}].alternatives must be a list")
        alts: list[FixtureBinding] = []
        for j, alt_data in enumerate(alts_raw):
            if not isinstance(alt_data, dict):
                raise ValueError(f"hooks[{i}].alternatives[{j}] must be an object")
            alts.append(FixtureBinding(
                function_id=_req_str(
                    alt_data, "function_id", f"hooks[{i}].alternatives[{j}]"
                ),
                fixture_entity_id=_req_str(
                    alt_data, "fixture_entity_id", f"hooks[{i}].alternatives[{j}]"
                ),
                description=_req_str(
                    alt_data, "description", f"hooks[{i}].alternatives[{j}]"
                ),
            ))
        if alts:
            alternative_fixtures[fn_id] = alts

    # ---- fronts ------------------------------------------------------------- #
    fronts: list[Front] = []
    front_ids: set[str] = set()
    for i, f_data in enumerate(data.get("fronts", [])):
        if not isinstance(f_data, dict):
            raise ValueError(f"fronts[{i}] must be an object")
        f_id = _req_str(f_data, "id", f"fronts[{i}]")
        if f_id in front_ids:
            raise ValueError(f"Duplicate front id {f_id!r}")
        front_ids.add(f_id)
        clock_name = _req_str(f_data, "clock_name", f"fronts[{i}]")
        if clock_names and clock_name not in clock_names:
            raise ValueError(
                f"fronts[{i}].clock_name {clock_name!r} does not match any world_clock"
            )
        faction_id = f_data.get("faction_id")
        if faction_id is not None:
            faction_id = str(faction_id)
            if faction_ids and faction_id not in faction_ids:
                raise ValueError(
                    f"fronts[{i}].faction_id {faction_id!r} does not match any faction"
                )
        fronts.append(Front(
            id=f_id,
            name=_req_str(f_data, "name", f"fronts[{i}]"),
            threat=_req_str(f_data, "threat", f"fronts[{i}]"),
            clock_name=clock_name,
            consequence_truth=_req_str(f_data, "consequence_truth", f"fronts[{i}]"),
            faction_id=faction_id,
        ))

    # ---- lore entries ------------------------------------------------------- #
    lore_entries: list[dict[str, Any]] = []
    entry_ids: set[str] = set()
    for i, le_data in enumerate(data.get("lore_entries", [])):
        if not isinstance(le_data, dict):
            raise ValueError(f"lore_entries[{i}] must be an object")
        le_id = _req_str(le_data, "entry_id", f"lore_entries[{i}]")
        if le_id in entry_ids:
            raise ValueError(f"Duplicate lore entry id {le_id!r}")
        entry_ids.add(le_id)
        _req_str(le_data, "title", f"lore_entries[{i}]")
        _req_str(le_data, "content", f"lore_entries[{i}]")
        audience_class = le_data.get("audience_class", "all")
        valid_classes = {"all", "gm_only"}
        if (
            audience_class not in valid_classes
            and not str(audience_class).startswith("player_")
        ):
            raise ValueError(
                f"lore_entries[{i}].audience_class {audience_class!r} must be "
                f"'all', 'gm_only', or 'player_{{id}}'"
            )
        lore_entries.append(dict(le_data))

    return CampaignPackage(
        title=title,
        version=version,
        description=description,
        function_nodes=function_nodes,
        hooks=hooks,
        fronts=fronts,
        factions=factions,
        hidden_nodes=hidden_nodes,
        alternative_fixtures=alternative_fixtures,
        world_clocks=world_clocks,
        lore_entries=lore_entries,
    )


# --------------------------------------------------------------------------- #
# Internal helpers                                                              #
# --------------------------------------------------------------------------- #

def _req_str(obj: Any, key: str, ctx: str) -> str:
    val = obj.get(key) if isinstance(obj, dict) else None
    if not val or not isinstance(val, str):
        raise ValueError(f"{ctx}.{key} must be a non-empty string")
    return val
