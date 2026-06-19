"""Phase 22 tests — D-043 lorebook / world-info injection.

Covers: LoreEntry (audience_permits, from_dict, to_dict), LoreDeck
(entries_for audience gate, from_dicts), LoreAssembler (keyword matching,
audience-safe corpus, max_entries, lore_context_block), ContextAssembler
lore_for() integration, CampaignPackage lore_entries parsing and lore_deck(),
and the key security invariant: a gm_only entry is never visible in a player
context regardless of keyword match.
"""
from __future__ import annotations

import pytest

from fable_table_engine import (
    ContextAssembler,
    EventLog,
    LoreAssembler,
    LoreDeck,
    LoreEntry,
    load_campaign_dict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry(
    entry_id: str = "e1",
    title: str = "The Guild",
    content: str = "A secret thieves guild operates in the city.",
    keywords: tuple[str, ...] = ("guild", "thieves"),
    audience_class: str = "all",
) -> LoreEntry:
    return LoreEntry(
        entry_id=entry_id,
        title=title,
        content=content,
        keywords=keywords,
        audience_class=audience_class,
    )


def _store_with_events(log: EventLog, pov: str, texts: list[str]):
    for text in texts:
        log.append(author="gm", channel="public", type="narration",
                   content=text, audience=(pov, "gm"))
    return ContextAssembler(log).belief_store(pov)


# ---------------------------------------------------------------------------
# LoreEntry
# ---------------------------------------------------------------------------

class TestLoreEntry:
    def test_all_visible_to_anyone(self):
        e = _entry(audience_class="all")
        assert e.audience_permits("hero") is True
        assert e.audience_permits("gm") is True
        assert e.audience_permits("npc") is True

    def test_gm_only_visible_to_gm(self):
        e = _entry(audience_class="gm_only")
        assert e.audience_permits("gm") is True
        assert e.audience_permits("hero") is False
        assert e.audience_permits("player_hero") is False

    def test_gm_only_custom_gm_entity(self):
        e = _entry(audience_class="gm_only")
        assert e.audience_permits("dungeon_master", gm_entity="dungeon_master") is True
        assert e.audience_permits("hero", gm_entity="dungeon_master") is False

    def test_player_scoped_entry(self):
        e = _entry(audience_class="player_hero")
        assert e.audience_permits("hero") is True
        assert e.audience_permits("mira") is False
        assert e.audience_permits("gm") is False

    def test_unknown_audience_class_denies_all(self):
        e = _entry(audience_class="mystery_class")
        assert e.audience_permits("gm") is False
        assert e.audience_permits("hero") is False

    def test_from_dict_round_trip(self):
        e = _entry(entry_id="e99", keywords=("dragon", "mountain"))
        d = e.to_dict()
        restored = LoreEntry.from_dict(d)
        assert restored == e

    def test_keywords_stored_as_tuple(self):
        e = _entry(keywords=("dragon", "mountain"))
        assert isinstance(e.keywords, tuple)

    def test_frozen(self):
        e = _entry()
        with pytest.raises((AttributeError, TypeError)):
            e.audience_class = "all"  # type: ignore[misc]

    def test_to_dict_keywords_as_list(self):
        e = _entry(keywords=("a", "b"))
        d = e.to_dict()
        assert isinstance(d["keywords"], list)


# ---------------------------------------------------------------------------
# LoreDeck
# ---------------------------------------------------------------------------

class TestLoreDeck:
    def test_empty_deck(self):
        deck = LoreDeck()
        assert len(deck) == 0
        assert deck.entries_for("gm") == []

    def test_entries_for_all(self):
        deck = LoreDeck(entries=[_entry(audience_class="all")])
        assert len(deck.entries_for("hero")) == 1
        assert len(deck.entries_for("gm")) == 1

    def test_entries_for_gm_only(self):
        deck = LoreDeck(entries=[_entry(audience_class="gm_only")])
        assert len(deck.entries_for("gm")) == 1
        assert len(deck.entries_for("hero")) == 0

    def test_entries_for_player_scoped(self):
        deck = LoreDeck(entries=[
            _entry(entry_id="e1", audience_class="player_hero"),
            _entry(entry_id="e2", audience_class="player_mira"),
        ])
        assert len(deck.entries_for("hero")) == 1
        assert len(deck.entries_for("mira")) == 1
        assert deck.entries_for("villain") == []

    def test_mixed_audience_filtering(self):
        deck = LoreDeck(entries=[
            _entry(entry_id="e1", audience_class="all"),
            _entry(entry_id="e2", audience_class="gm_only"),
            _entry(entry_id="e3", audience_class="player_hero"),
        ])
        gm_entries = deck.entries_for("gm")
        hero_entries = deck.entries_for("hero")
        assert len(gm_entries) == 2   # all + gm_only
        assert len(hero_entries) == 2  # all + player_hero

    def test_add_entry(self):
        deck = LoreDeck()
        deck.add(_entry())
        assert len(deck) == 1

    def test_all_entries_returns_copy(self):
        e = _entry()
        deck = LoreDeck(entries=[e])
        lst = deck.all_entries
        lst.clear()
        assert len(deck) == 1

    def test_from_dicts(self):
        data = [
            {"entry_id": "e1", "title": "T1", "content": "C1",
             "keywords": ["dragon"], "audience_class": "all"},
            {"entry_id": "e2", "title": "T2", "content": "C2",
             "keywords": ["guild"], "audience_class": "gm_only"},
        ]
        deck = LoreDeck.from_dicts(data, gm_entity="gm")
        assert len(deck) == 2
        assert len(deck.entries_for("gm")) == 2
        assert len(deck.entries_for("hero")) == 1

    def test_from_dicts_custom_gm(self):
        data = [{"entry_id": "e1", "title": "T", "content": "C",
                 "keywords": [], "audience_class": "gm_only"}]
        deck = LoreDeck.from_dicts(data, gm_entity="narrator")
        assert len(deck.entries_for("narrator")) == 1
        assert len(deck.entries_for("gm")) == 0


# ---------------------------------------------------------------------------
# LoreAssembler — keyword matching
# ---------------------------------------------------------------------------

class TestLoreAssemblerMatching:
    def test_keyword_in_event_text_triggers(self):
        log = EventLog()
        store = _store_with_events(log, "hero", ["The guild controls the docks."])
        deck = LoreDeck(entries=[_entry(keywords=("guild",))])
        asm = LoreAssembler(deck)
        matched = asm.matching(store, pov="hero")
        assert len(matched) == 1
        assert matched[0].entry_id == "e1"

    def test_keyword_missing_no_match(self):
        log = EventLog()
        store = _store_with_events(log, "hero", ["The tavern is quiet tonight."])
        deck = LoreDeck(entries=[_entry(keywords=("dragon",))])
        asm = LoreAssembler(deck)
        assert asm.matching(store, pov="hero") == []

    def test_keyword_matching_is_case_insensitive(self):
        log = EventLog()
        store = _store_with_events(log, "hero", ["The GUILD sends an agent."])
        deck = LoreDeck(entries=[_entry(keywords=("guild",))])
        asm = LoreAssembler(deck)
        assert len(asm.matching(store, pov="hero")) == 1

    def test_any_keyword_triggers(self):
        log = EventLog()
        store = _store_with_events(log, "hero", ["A dragon stirs in the north."])
        deck = LoreDeck(entries=[_entry(keywords=("dragon", "guild"))])
        asm = LoreAssembler(deck)
        assert len(asm.matching(store, pov="hero")) == 1

    def test_multiple_entries_matched(self):
        log = EventLog()
        store = _store_with_events(log, "hero", ["A dragon attacked the guild."])
        deck = LoreDeck(entries=[
            _entry(entry_id="dragon", title="Dragon", content="...", keywords=("dragon",)),
            _entry(entry_id="guild", title="Guild", content="...", keywords=("guild",)),
        ])
        asm = LoreAssembler(deck)
        matched = asm.matching(store, pov="hero")
        assert len(matched) == 2

    def test_max_entries_limits_results(self):
        log = EventLog()
        store = _store_with_events(log, "hero", ["dragon guild magic rune sword"])
        entries = [
            _entry(entry_id=f"e{i}", title=f"T{i}", content=f"C{i}",
                   keywords=(kw,))
            for i, kw in enumerate(["dragon", "guild", "magic", "rune", "sword"])
        ]
        deck = LoreDeck(entries=entries)
        asm = LoreAssembler(deck, max_entries=3)
        matched = asm.matching(store, pov="hero")
        assert len(matched) == 3

    def test_empty_event_log_no_match(self):
        log = EventLog()
        store = ContextAssembler(log).belief_store("hero")
        deck = LoreDeck(entries=[_entry(keywords=("dragon",))])
        asm = LoreAssembler(deck)
        assert asm.matching(store, pov="hero") == []

    def test_keyword_in_committed_fact_labels(self):
        from fable_table_engine import CommitPipeline, Commitment
        log = EventLog()
        pipeline = CommitPipeline(log)
        pipeline.commit(
            author="gm",
            channel="public",
            content="The dragon lair has been discovered.",
            audience=("hero", "gm"),
            commitments=[
                Commitment(subject="dragon_lair", predicate="location", value="mountain peak")
            ],
        )
        store = ContextAssembler(log).belief_store("hero")
        deck = LoreDeck(entries=[_entry(keywords=("dragon_lair",))])
        asm = LoreAssembler(deck)
        matched = asm.matching(store, pov="hero")
        assert len(matched) == 1


# ---------------------------------------------------------------------------
# SECURITY INVARIANT: gm_only never injected into player context
# ---------------------------------------------------------------------------

class TestLoreAudienceSecurity:
    def test_gm_only_entry_never_in_player_context(self):
        """Core D-043 security invariant: gm_only entry blocked even when keyword matches.

        Scenario: 'shadow_guild' appears in a GM-only narration event AND in a
        gm_only lorebook entry. The hero was never in the audience of the event,
        so the keyword never enters the hero's entitled corpus. Even if it did
        appear somehow, the audience gate must block the entry.
        """
        log = EventLog()
        # GM-only event — hero is NOT in audience
        log.append(
            author="gm", channel="system", type="narration",
            content="The shadow_guild has infiltrated the castle.",
            audience=("gm",),
        )
        # Hero event — no mention of shadow_guild
        log.append(
            author="hero", channel="public", type="speech",
            content="I walk into the market.",
            audience=("hero", "gm"),
        )

        gm_only_entry = LoreEntry(
            entry_id="guild_secret",
            title="Shadow Guild",
            content="The shadow guild controls the underworld.",
            keywords=("shadow_guild",),
            audience_class="gm_only",
        )
        deck = LoreDeck(entries=[gm_only_entry])
        asm = LoreAssembler(deck)

        hero_store = ContextAssembler(log).belief_store("hero")
        matched = asm.matching(hero_store, pov="hero")
        assert matched == [], (
            "gm_only lorebook entry must never appear in hero context"
        )

    def test_gm_only_entry_visible_to_gm(self):
        log = EventLog()
        log.append(
            author="gm", channel="system", type="narration",
            content="The shadow_guild strikes tonight.",
            audience=("gm",),
        )
        gm_only_entry = LoreEntry(
            entry_id="guild_secret",
            title="Shadow Guild",
            content="The shadow guild controls the underworld.",
            keywords=("shadow_guild",),
            audience_class="gm_only",
        )
        deck = LoreDeck(entries=[gm_only_entry])
        asm = LoreAssembler(deck)
        gm_store = ContextAssembler(log).belief_store("gm")
        matched = asm.matching(gm_store, pov="gm")
        assert len(matched) == 1

    def test_player_scoped_entry_not_visible_to_other_players(self):
        log = EventLog()
        log.append(
            author="gm", channel="public", type="narration",
            content="You see the dragon.",
            audience=("hero", "mira", "gm"),
        )
        entry = LoreEntry(
            entry_id="hero_secret",
            title="Hero Backstory",
            content="Hero's dark secret.",
            keywords=("dragon",),
            audience_class="player_hero",
        )
        deck = LoreDeck(entries=[entry])
        asm = LoreAssembler(deck)

        hero_store = ContextAssembler(log).belief_store("hero")
        mira_store = ContextAssembler(log).belief_store("mira")

        assert len(asm.matching(hero_store, pov="hero")) == 1
        assert asm.matching(mira_store, pov="mira") == []

    def test_gm_only_corpus_keyword_does_not_leak_to_player(self):
        """D-043 constraint 4: even if the same keyword appears in the player's
        corpus, a gm_only entry must not be injected because the audience gate
        fires before keyword matching."""
        log = EventLog()
        # Both GM and hero see "dragon" in their events
        log.append(
            author="gm", channel="public", type="narration",
            content="A dragon appears.",
            audience=("hero", "gm"),
        )
        gm_only_entry = LoreEntry(
            entry_id="dragon_lore",
            title="Dragon Lore",
            content="Ancient dragon secrets.",
            keywords=("dragon",),
            audience_class="gm_only",
        )
        deck = LoreDeck(entries=[gm_only_entry])
        asm = LoreAssembler(deck)

        hero_store = ContextAssembler(log).belief_store("hero")
        # hero sees "dragon" in their corpus but audience class denies them
        matched = asm.matching(hero_store, pov="hero")
        assert matched == [], "audience gate must fire before keyword match"


# ---------------------------------------------------------------------------
# LoreAssembler — lore_context_block
# ---------------------------------------------------------------------------

class TestLoreContextBlock:
    def test_empty_list_returns_empty_string(self):
        asm = LoreAssembler(LoreDeck())
        assert asm.lore_context_block([]) == ""

    def test_entries_formatted_with_header(self):
        e = _entry(title="Dragon History", content="Dragons once ruled all.")
        asm = LoreAssembler(LoreDeck())
        block = asm.lore_context_block([e])
        assert "[Background lore]" in block
        assert "Dragon History" in block
        assert "Dragons once ruled all." in block

    def test_multiple_entries(self):
        entries = [
            _entry(entry_id="e1", title="T1", content="C1"),
            _entry(entry_id="e2", title="T2", content="C2"),
        ]
        asm = LoreAssembler(LoreDeck())
        block = asm.lore_context_block(entries)
        assert "T1" in block
        assert "T2" in block
        assert "C1" in block
        assert "C2" in block


# ---------------------------------------------------------------------------
# ContextAssembler.lore_for integration
# ---------------------------------------------------------------------------

class TestContextAssemblerLoreFor:
    def test_no_lore_assembler_returns_empty(self):
        log = EventLog()
        log.append(author="gm", channel="public", type="narration",
                   content="A dragon stirs.", audience=("hero", "gm"))
        assembler = ContextAssembler(log)
        store = assembler.belief_store("hero")
        result = assembler.lore_for(store, "hero")
        assert result == []

    def test_with_lore_assembler_returns_matches(self):
        log = EventLog()
        log.append(author="gm", channel="public", type="narration",
                   content="A dragon stirs.", audience=("hero", "gm"))
        deck = LoreDeck(entries=[_entry(keywords=("dragon",))])
        lore_asm = LoreAssembler(deck)
        assembler = ContextAssembler(log, lore_assembler=lore_asm)
        store = assembler.belief_store("hero")
        result = assembler.lore_for(store, "hero")
        assert len(result) == 1

    def test_lore_assembler_property(self):
        log = EventLog()
        lore_asm = LoreAssembler(LoreDeck())
        assembler = ContextAssembler(log, lore_assembler=lore_asm)
        assert assembler.lore_assembler is lore_asm

    def test_lore_assembler_none_by_default(self):
        log = EventLog()
        assembler = ContextAssembler(log)
        assert assembler.lore_assembler is None

    def test_audience_gate_enforced_through_context_assembler(self):
        log = EventLog()
        log.append(author="gm", channel="public", type="narration",
                   content="The dragon flies overhead.",
                   audience=("hero", "gm"))
        gm_only_entry = LoreEntry(
            entry_id="secret", title="Dragon Secret",
            content="Hidden lore.", keywords=("dragon",),
            audience_class="gm_only",
        )
        deck = LoreDeck(entries=[gm_only_entry])
        lore_asm = LoreAssembler(deck)
        assembler = ContextAssembler(log, lore_assembler=lore_asm)
        hero_store = assembler.belief_store("hero")
        result = assembler.lore_for(hero_store, "hero")
        assert result == []


# ---------------------------------------------------------------------------
# CampaignPackage — lore_entries parsing
# ---------------------------------------------------------------------------

class TestCampaignPackageLore:
    def _base_campaign(self) -> dict:
        return {
            "title": "Test Campaign",
            "version": "1.0",
            "description": "For testing.",
        }

    def test_no_lore_entries_defaults_empty(self):
        pkg = load_campaign_dict(self._base_campaign())
        assert pkg.lore_entries == []

    def test_lore_entries_parsed(self):
        data = self._base_campaign()
        data["lore_entries"] = [
            {"entry_id": "e1", "title": "T1", "content": "C1",
             "keywords": ["dragon"], "audience_class": "all"},
        ]
        pkg = load_campaign_dict(data)
        assert len(pkg.lore_entries) == 1
        assert pkg.lore_entries[0]["entry_id"] == "e1"

    def test_duplicate_lore_entry_id_raises(self):
        data = self._base_campaign()
        data["lore_entries"] = [
            {"entry_id": "e1", "title": "T1", "content": "C1", "keywords": []},
            {"entry_id": "e1", "title": "T2", "content": "C2", "keywords": []},
        ]
        with pytest.raises(ValueError, match="Duplicate lore entry id"):
            load_campaign_dict(data)

    def test_invalid_audience_class_raises(self):
        data = self._base_campaign()
        data["lore_entries"] = [
            {"entry_id": "e1", "title": "T", "content": "C",
             "keywords": [], "audience_class": "bad_value"},
        ]
        with pytest.raises(ValueError, match="audience_class"):
            load_campaign_dict(data)

    def test_valid_player_scoped_audience_class(self):
        data = self._base_campaign()
        data["lore_entries"] = [
            {"entry_id": "e1", "title": "T", "content": "C",
             "keywords": [], "audience_class": "player_hero"},
        ]
        pkg = load_campaign_dict(data)
        assert len(pkg.lore_entries) == 1

    def test_lore_deck_from_package(self):
        data = self._base_campaign()
        data["lore_entries"] = [
            {"entry_id": "e1", "title": "T", "content": "C",
             "keywords": ["dragon"], "audience_class": "all"},
        ]
        pkg = load_campaign_dict(data)
        deck = pkg.lore_deck()
        assert len(deck) == 1

    def test_lore_deck_gm_only_filtered(self):
        data = self._base_campaign()
        data["lore_entries"] = [
            {"entry_id": "e1", "title": "T", "content": "C",
             "keywords": [], "audience_class": "gm_only"},
        ]
        pkg = load_campaign_dict(data)
        deck = pkg.lore_deck()
        assert len(deck.entries_for("hero")) == 0
        assert len(deck.entries_for("gm")) == 1
