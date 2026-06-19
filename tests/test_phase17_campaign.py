"""Phase 17: Campaign Package and Plot-Graph Core.

Tests the following acceptance contracts:
  1.  load_campaign_dict rejects missing 'title'.
  2.  load_campaign_dict rejects missing 'version'.
  3.  load_campaign_dict rejects a hook whose function_id is unknown.
  4.  load_campaign_dict rejects a front whose clock_name is unknown (when clocks are declared).
  5.  load_campaign_dict rejects a front whose faction_id is unknown (when factions are declared).
  6.  load_campaign_dict rejects duplicate function_node ids.
  7.  load_campaign_dict rejects duplicate world_clock names.
  8.  A minimal campaign (title + version only) loads without error.
  9.  to_plot_graph() produces function_nodes, hooks, fronts, factions, hidden_nodes.
  10. Alternatives embedded in hook JSON appear in PlotGraph.alternative_fixtures.
  11. seed_world() calls world.set_clock for each world_clock entry.
  12. load_campaign() reads a JSON file from disk.
  13. load_campaign() raises ValueError on missing file.
  14. load_campaign() raises ValueError on invalid JSON.
  15. SQLitePlotGraph starts empty on a fresh DB.
  16. add_function / add_hook / add_front / add_faction survive a close/reopen.
  17. add_hidden_node survives a close/reopen.
  18. set_alternatives survives a close/reopen.
  19. update_hook_binding is persisted; rebinding survives reopen.
  20. SQLitePlotGraph.update_hook_binding is a no-op for unknown function_id.
  21. Mutation inside a failed transaction is rolled back in memory.
  22. Mutation inside a failed transaction is absent after reopen.
  23. attach_campaign creates a SQLitePlotGraph and wires rollback into log.
  24. attach_campaign seeds an empty graph from campaign on first open.
  25. attach_campaign does NOT overwrite a pre-existing graph on reopen.
  26. PlotManager.accept_rebinding routes through update_hook_binding and persists.
  27. PlotManager events carry gm+plot_manager audience — never appear in player belief store.
  28. Front clock validation skips when world_clocks is absent (pure plot-graph campaign).
  29. Faction cross-reference skips when factions list is empty.
  30. CampaignPackage description defaults to empty string.
"""

import json
import sqlite3
import pytest

from fable_table_engine import (
    CampaignPackage,
    CommitPipeline,
    Commitment,
    ContextAssembler,
    Entity,
    EventLog,
    Faction,
    FixtureBinding,
    Front,
    FunctionNode,
    Hook,
    PlotGraph,
    PlotManager,
    SQLitePlotGraph,
    SQLiteWorldState,
    WorldState,
    attach_campaign,
    load_campaign,
    load_campaign_dict,
    open_session,
)


# --------------------------------------------------------------------------- #
# Minimal valid campaign dict                                                  #
# --------------------------------------------------------------------------- #

def _minimal() -> dict:
    return {"version": "1.0", "title": "Test Campaign"}


def _full() -> dict:
    """A campaign with one of each element and cross-references that are valid."""
    return {
        "version": "1.0",
        "title": "The Salt Lantern",
        "description": "A mystery campaign.",
        "function_nodes": [
            {"id": "fn-001", "description": "The party learns of the conspiracy.", "required": True},
            {"id": "fn-002", "description": "A way into the vault exists.", "required": False},
        ],
        "hidden_nodes": [
            {"id": "hn-001", "description": "A secret smuggler route.", "required": False},
        ],
        "factions": [
            {"id": "faction-cult", "name": "The Hidden Cult", "goals": ["hide the truth"], "momentum": 0},
        ],
        "world_clocks": [
            {"name": "cult_clock", "current": 0, "max": 6, "trigger_types": ["beat"], "active": True},
        ],
        "hooks": [
            {
                "function_id": "fn-001",
                "binding": {
                    "function_id": "fn-001",
                    "fixture_entity_id": "innkeeper",
                    "description": "The innkeeper knows the rumor.",
                },
                "preconditions": ["innkeeper"],
                "active": True,
                "alternatives": [
                    {
                        "function_id": "fn-001",
                        "fixture_entity_id": "merchant",
                        "description": "The merchant can reveal it instead.",
                    }
                ],
            },
        ],
        "fronts": [
            {
                "id": "front-001",
                "name": "The Cult's Rise",
                "threat": "The cult gains power.",
                "clock_name": "cult_clock",
                "consequence_truth": "The cult controls the harbor.",
                "faction_id": "faction-cult",
            }
        ],
    }


# --------------------------------------------------------------------------- #
# 1–8: Validation                                                               #
# --------------------------------------------------------------------------- #

class TestCampaignValidation:

    def test_missing_title_raises(self):  # 1
        with pytest.raises(ValueError, match="title"):
            load_campaign_dict({"version": "1.0"})

    def test_missing_version_raises(self):  # 2
        with pytest.raises(ValueError, match="version"):
            load_campaign_dict({"title": "T"})

    def test_hook_unknown_function_id_raises(self):  # 3
        data = _minimal()
        data["function_nodes"] = [{"id": "fn-A", "description": "foo"}]
        data["hooks"] = [
            {
                "function_id": "fn-UNKNOWN",
                "binding": {"function_id": "fn-UNKNOWN", "fixture_entity_id": "x", "description": "y"},
            }
        ]
        with pytest.raises(ValueError, match="function_id"):
            load_campaign_dict(data)

    def test_front_unknown_clock_raises(self):  # 4
        data = _minimal()
        data["world_clocks"] = [{"name": "clock-A"}]
        data["fronts"] = [
            {
                "id": "f1", "name": "Front", "threat": "T",
                "clock_name": "NONEXISTENT",
                "consequence_truth": "C",
            }
        ]
        with pytest.raises(ValueError, match="clock_name"):
            load_campaign_dict(data)

    def test_front_unknown_faction_raises(self):  # 5
        data = _minimal()
        data["factions"] = [{"id": "fac-A", "name": "Fac A"}]
        data["world_clocks"] = [{"name": "ck"}]
        data["fronts"] = [
            {
                "id": "f1", "name": "F", "threat": "T",
                "clock_name": "ck",
                "consequence_truth": "C",
                "faction_id": "NONEXISTENT",
            }
        ]
        with pytest.raises(ValueError, match="faction_id"):
            load_campaign_dict(data)

    def test_duplicate_function_node_id_raises(self):  # 6
        data = _minimal()
        data["function_nodes"] = [
            {"id": "fn-dup", "description": "a"},
            {"id": "fn-dup", "description": "b"},
        ]
        with pytest.raises(ValueError, match="Duplicate function_node"):
            load_campaign_dict(data)

    def test_duplicate_clock_name_raises(self):  # 7
        data = _minimal()
        data["world_clocks"] = [{"name": "same"}, {"name": "same"}]
        with pytest.raises(ValueError, match="Duplicate world_clock"):
            load_campaign_dict(data)

    def test_minimal_loads_without_error(self):  # 8
        pkg = load_campaign_dict(_minimal())
        assert pkg.title == "Test Campaign"
        assert pkg.version == "1.0"


# --------------------------------------------------------------------------- #
# 9–14: CampaignPackage structure and file I/O                                 #
# --------------------------------------------------------------------------- #

class TestCampaignPackageContent:

    def test_to_plot_graph_structure(self):  # 9
        pkg = load_campaign_dict(_full())
        g = pkg.to_plot_graph()
        assert "fn-001" in g.function_nodes
        assert "fn-002" in g.function_nodes
        assert len(g.hooks) == 1
        assert g.hooks[0].function_id == "fn-001"
        assert len(g.fronts) == 1
        assert g.fronts[0].id == "front-001"
        assert len(g.factions) == 1
        assert g.factions[0].id == "faction-cult"
        assert len(g.hidden_nodes) == 1
        assert g.hidden_nodes[0].id == "hn-001"

    def test_alternatives_in_plot_graph(self):  # 10
        pkg = load_campaign_dict(_full())
        g = pkg.to_plot_graph()
        assert "fn-001" in g.alternative_fixtures
        alts = g.alternative_fixtures["fn-001"]
        assert len(alts) == 1
        assert alts[0].fixture_entity_id == "merchant"

    def test_seed_world_adds_clocks(self):  # 11
        pkg = load_campaign_dict(_full())
        world = WorldState()
        pkg.seed_world(world)
        assert "cult_clock" in world.clocks
        assert world.clocks["cult_clock"]["max"] == 6

    def test_load_campaign_from_file(self, tmp_path):  # 12
        path = tmp_path / "campaign.json"
        path.write_text(json.dumps(_full()), encoding="utf-8")
        pkg = load_campaign(path)
        assert pkg.title == "The Salt Lantern"

    def test_load_campaign_missing_file_raises(self, tmp_path):  # 13
        with pytest.raises(ValueError, match="Cannot read"):
            load_campaign(tmp_path / "nonexistent.json")

    def test_load_campaign_invalid_json_raises(self, tmp_path):  # 14
        path = tmp_path / "bad.json"
        path.write_text("{broken", encoding="utf-8")
        with pytest.raises(ValueError, match="not valid JSON"):
            load_campaign(path)

    def test_description_defaults_to_empty(self):  # 30
        pkg = load_campaign_dict(_minimal())
        assert pkg.description == ""

    def test_front_clock_validation_skips_without_world_clocks(self):  # 28
        data = _minimal()
        data["function_nodes"] = []
        data["fronts"] = [
            {
                "id": "f1", "name": "F", "threat": "T",
                "clock_name": "any_clock",
                "consequence_truth": "C",
            }
        ]
        # No world_clocks key → no cross-reference check → should load fine
        pkg = load_campaign_dict(data)
        assert pkg.fronts[0].clock_name == "any_clock"

    def test_faction_cross_reference_skips_without_factions(self):  # 29
        data = _minimal()
        data["world_clocks"] = [{"name": "ck"}]
        data["fronts"] = [
            {
                "id": "f1", "name": "F", "threat": "T",
                "clock_name": "ck",
                "consequence_truth": "C",
                "faction_id": "any_faction",
            }
        ]
        # No factions key → no cross-reference check → should load fine
        pkg = load_campaign_dict(data)
        assert pkg.fronts[0].faction_id == "any_faction"


# --------------------------------------------------------------------------- #
# 15–22: SQLitePlotGraph persistence and rollback                              #
# --------------------------------------------------------------------------- #

def _make_graph(tmp_path) -> SQLitePlotGraph:
    conn = sqlite3.connect(str(tmp_path / "graph.db"))
    return SQLitePlotGraph(conn)


class TestSQLitePlotGraph:

    def test_starts_empty_on_fresh_db(self, tmp_path):  # 15
        g = _make_graph(tmp_path)
        assert not g.function_nodes
        assert not g.hooks
        assert not g.fronts
        assert not g.factions
        assert not g.hidden_nodes

    def test_function_nodes_survive_restart(self, tmp_path):  # 16
        db = tmp_path / "graph.db"
        conn1 = sqlite3.connect(str(db))
        g1 = SQLitePlotGraph(conn1)
        g1.add_function(FunctionNode(id="fn-a", description="A function"))
        g1.add_front(Front(id="front-a", name="F", threat="T",
                           clock_name="ck", consequence_truth="C"))
        g1.add_faction(Faction(id="fac-a", name="Faction A"))
        conn1.close()

        conn2 = sqlite3.connect(str(db))
        g2 = SQLitePlotGraph(conn2)
        assert "fn-a" in g2.function_nodes
        assert len(g2.fronts) == 1
        assert g2.fronts[0].id == "front-a"
        assert len(g2.factions) == 1
        conn2.close()

    def test_hooks_survive_restart(self, tmp_path):  # 16 cont.
        db = tmp_path / "hook.db"
        conn1 = sqlite3.connect(str(db))
        g1 = SQLitePlotGraph(conn1)
        g1.add_function(FunctionNode(id="fn-x", description="X"))
        binding = FixtureBinding(function_id="fn-x", fixture_entity_id="npc", description="d")
        g1.add_hook(Hook(function_id="fn-x", binding=binding))
        conn1.close()

        conn2 = sqlite3.connect(str(db))
        g2 = SQLitePlotGraph(conn2)
        assert len(g2.hooks) == 1
        assert g2.hooks[0].function_id == "fn-x"
        assert g2.hooks[0].binding.fixture_entity_id == "npc"
        conn2.close()

    def test_hidden_node_survives_restart(self, tmp_path):  # 17
        db = tmp_path / "hidden.db"
        conn1 = sqlite3.connect(str(db))
        g1 = SQLitePlotGraph(conn1)
        g1.add_hidden_node(FunctionNode(id="hn-1", description="Hidden"))
        conn1.close()

        conn2 = sqlite3.connect(str(db))
        g2 = SQLitePlotGraph(conn2)
        assert len(g2.hidden_nodes) == 1
        assert g2.hidden_nodes[0].id == "hn-1"
        conn2.close()

    def test_alternatives_survive_restart(self, tmp_path):  # 18
        db = tmp_path / "alt.db"
        conn1 = sqlite3.connect(str(db))
        g1 = SQLitePlotGraph(conn1)
        g1.add_function(FunctionNode(id="fn-y", description="Y"))
        g1.set_alternatives("fn-y", [
            FixtureBinding(function_id="fn-y", fixture_entity_id="backup", description="b"),
        ])
        conn1.close()

        conn2 = sqlite3.connect(str(db))
        g2 = SQLitePlotGraph(conn2)
        assert "fn-y" in g2.alternative_fixtures
        assert g2.alternative_fixtures["fn-y"][0].fixture_entity_id == "backup"
        conn2.close()

    def test_update_hook_binding_persists(self, tmp_path):  # 19
        db = tmp_path / "rebind.db"
        conn1 = sqlite3.connect(str(db))
        g1 = SQLitePlotGraph(conn1)
        g1.add_function(FunctionNode(id="fn-z", description="Z"))
        original = FixtureBinding(function_id="fn-z", fixture_entity_id="npc1", description="d1")
        g1.add_hook(Hook(function_id="fn-z", binding=original))
        new_binding = FixtureBinding(function_id="fn-z", fixture_entity_id="npc2", description="d2")
        g1.update_hook_binding("fn-z", new_binding)
        conn1.close()

        conn2 = sqlite3.connect(str(db))
        g2 = SQLitePlotGraph(conn2)
        assert g2.hooks[0].binding.fixture_entity_id == "npc2"
        conn2.close()

    def test_update_hook_binding_unknown_id_is_noop(self, tmp_path):  # 20
        g = _make_graph(tmp_path)
        # Should not raise; graph stays empty.
        g.update_hook_binding("nonexistent", FixtureBinding("x", "y", "z"))
        assert not g.hooks

    def test_rollback_removes_mutation_from_memory(self, tmp_path):  # 21
        log, world, _ = open_session(tmp_path / "session.db")
        graph = attach_campaign(log)
        graph.add_function(FunctionNode(id="fn-persist", description="Persists"))
        log.close()

        log2, _, _ = open_session(tmp_path / "session.db")
        graph2 = attach_campaign(log2)
        assert "fn-persist" in graph2.function_nodes
        try:
            with log2.transaction():
                graph2.add_function(FunctionNode(id="fn-phantom", description="Gone"))
                assert "fn-phantom" in graph2.function_nodes
                raise RuntimeError("forced rollback")
        except RuntimeError:
            pass
        assert "fn-phantom" not in graph2.function_nodes
        assert "fn-persist" in graph2.function_nodes
        log2.close()

    def test_rollback_absent_after_reopen(self, tmp_path):  # 22
        log, _, _ = open_session(tmp_path / "session.db")
        graph = attach_campaign(log)
        try:
            with log.transaction():
                graph.add_function(FunctionNode(id="fn-ghost", description="Ghost"))
                raise RuntimeError("rollback")
        except RuntimeError:
            pass
        log.close()

        log2, _, _ = open_session(tmp_path / "session.db")
        graph2 = attach_campaign(log2)
        assert "fn-ghost" not in graph2.function_nodes
        log2.close()


# --------------------------------------------------------------------------- #
# 23–26: attach_campaign integration                                           #
# --------------------------------------------------------------------------- #

class TestAttachCampaign:

    def test_attach_creates_graph_and_wires_rollback(self, tmp_path):  # 23
        log, _, _ = open_session(tmp_path / "session.db")
        graph = attach_campaign(log)
        assert isinstance(graph, SQLitePlotGraph)
        assert log._plot_graph_ref is graph
        log.close()

    def test_attach_seeds_empty_graph_from_campaign(self, tmp_path):  # 24
        pkg = load_campaign_dict(_full())
        log, _, _ = open_session(tmp_path / "session.db")
        graph = attach_campaign(log, campaign=pkg)
        assert "fn-001" in graph.function_nodes
        assert len(graph.hooks) == 1
        assert len(graph.fronts) == 1
        assert len(graph.factions) == 1
        assert len(graph.hidden_nodes) == 1
        log.close()

    def test_attach_does_not_overwrite_existing_graph(self, tmp_path):  # 25
        db = tmp_path / "session.db"
        pkg = load_campaign_dict(_full())

        # First open: seed
        log, _, _ = open_session(db)
        graph = attach_campaign(log, campaign=pkg)
        graph.add_function(FunctionNode(id="fn-extra", description="Added at runtime"))
        log.close()

        # Second open: pass a different campaign; graph should be unchanged
        other_pkg = load_campaign_dict({"version": "1.0", "title": "Other", "function_nodes": []})
        log2, _, _ = open_session(db)
        graph2 = attach_campaign(log2, campaign=other_pkg)
        assert "fn-001" in graph2.function_nodes     # from original campaign
        assert "fn-extra" in graph2.function_nodes   # runtime addition persisted
        log2.close()

    def test_plot_manager_accept_rebinding_persists(self, tmp_path):  # 26
        pkg = load_campaign_dict(_full())
        db = tmp_path / "session.db"
        log, world, _ = open_session(db)
        graph = attach_campaign(log, campaign=pkg)
        pipeline = CommitPipeline(log)
        pm = PlotManager(graph, pipeline, log)
        hook = graph.hooks[0]
        new_binding = FixtureBinding(
            function_id="fn-001",
            fixture_entity_id="merchant",
            description="Merchant replaces innkeeper.",
        )
        pm.accept_rebinding(hook, new_binding)
        assert graph.hooks[0].binding.fixture_entity_id == "merchant"
        log.close()

        # Verify it persisted
        log2, _, _ = open_session(db)
        graph2 = attach_campaign(log2)
        assert graph2.hooks[0].binding.fixture_entity_id == "merchant"
        log2.close()


# --------------------------------------------------------------------------- #
# 27: PlotManager events never leak to player belief store                     #
# --------------------------------------------------------------------------- #

class TestPlotGraphHiddenFromPlayer:

    def test_plot_revision_not_in_player_belief_store(self, tmp_path):  # 27
        """PlotManager events carry gm+plot_manager audience — player never sees them."""
        pkg = load_campaign_dict(_full())
        log, world, _ = open_session(tmp_path / "session.db")
        graph = attach_campaign(log, campaign=pkg)
        pipeline = CommitPipeline(log)
        pm = PlotManager(graph, pipeline, log, gm_entity="gm", plot_manager_entity="pm")

        # Commit the innkeeper as destroyed — triggers fixture health check
        world.add_entity(Entity(id="innkeeper", kind="npc", name="Innkeeper"))
        pipeline.commit(
            author="gm",
            channel="public",
            content="The innkeeper was slain.",
            audience=("player",),
            commitments=[Commitment(
                subject="innkeeper",
                predicate="condition",
                value="dead",
                revealed=True,
            )],
        )

        # PlotManager proposes a rebinding — emits plot_revision event
        issues = pm.check_fixture_health()
        assert issues, "Should detect innkeeper as blocked"
        pm.propose_rebinding(issues[0])

        # Player belief store should contain only the declaration, not the plot_revision
        assembler = ContextAssembler(log)
        store = assembler.belief_store("player")
        types_seen = {e.type for e in store.events}
        assert "plot_revision" not in types_seen
        assert "declaration" in types_seen
        log.close()
