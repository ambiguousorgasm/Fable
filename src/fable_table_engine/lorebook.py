"""Lorebook / world-info injection system (Phase 22; D-043).

LoreEntry:    one background entry — title, content, keyword triggers, audience class.
LoreDeck:     a collection of entries with audience-filtered access.
LoreAssembler: keyword-match retrieval against a POV's entitled belief projection.

Audience classes (assigned at authoring time):
  ``"all"``         — visible to every POV.
  ``"gm_only"``     — visible only to the GM entity.
  ``"player_{id}"`` — visible only to the named player entity.

Keyword matching is performed against the POV's entitled belief projection
(event text + committed fact labels) — never against raw event content outside
the POV's authorized view. This is the key audience-safety invariant from D-043
constraint 4: a GM-only event whose text contains a keyword cannot trigger
lorebook injection into a non-GM context.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .context import BeliefStore


# --------------------------------------------------------------------------- #
# LoreEntry                                                                     #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class LoreEntry:
    """One lorebook entry.

    Background/setting context only — never current-state authority. Event log,
    world state, canon ledger, and the disposition graph override lorebook
    entries on any conflict (D-043 constraint 1).
    """

    entry_id: str
    title: str
    content: str
    keywords: tuple[str, ...]
    audience_class: str = "all"

    def audience_permits(self, pov: str, gm_entity: str = "gm") -> bool:
        """Return True if this entry is visible to ``pov``."""
        if self.audience_class == "all":
            return True
        if self.audience_class == "gm_only":
            return pov == gm_entity
        if self.audience_class.startswith("player_"):
            return pov == self.audience_class[len("player_"):]
        return False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LoreEntry:
        return cls(
            entry_id=data["entry_id"],
            title=data["title"],
            content=data["content"],
            keywords=tuple(data.get("keywords", [])),
            audience_class=data.get("audience_class", "all"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "title": self.title,
            "content": self.content,
            "keywords": list(self.keywords),
            "audience_class": self.audience_class,
        }


# --------------------------------------------------------------------------- #
# LoreDeck                                                                      #
# --------------------------------------------------------------------------- #

class LoreDeck:
    """A collection of LoreEntry objects with audience-filtered access.

    Mutable at construction time (``add``); treat as read-only during a session.
    """

    def __init__(
        self,
        entries: list[LoreEntry] | None = None,
        gm_entity: str = "gm",
    ) -> None:
        self._entries: list[LoreEntry] = list(entries or [])
        self._gm = gm_entity

    @property
    def all_entries(self) -> list[LoreEntry]:
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def add(self, entry: LoreEntry) -> None:
        self._entries.append(entry)

    def entries_for(self, pov: str) -> list[LoreEntry]:
        """Return entries the given POV is entitled to see (audience gate)."""
        return [e for e in self._entries if e.audience_permits(pov, self._gm)]

    @classmethod
    def from_dicts(
        cls,
        data: list[dict[str, Any]],
        gm_entity: str = "gm",
    ) -> LoreDeck:
        """Deserialize from a list of raw dicts (campaign JSON ``lore_entries``)."""
        return cls(
            entries=[LoreEntry.from_dict(d) for d in data],
            gm_entity=gm_entity,
        )


# --------------------------------------------------------------------------- #
# LoreAssembler                                                                 #
# --------------------------------------------------------------------------- #

class LoreAssembler:
    """Matches lorebook entries against a POV's entitled belief projection.

    Audience class gate fires before any keyword matching: only entries the
    requesting POV is entitled to see are ever considered. Keyword search runs
    against the POV's entitled corpus (event text + fact labels) — not against
    global event content or any data outside the POV's authorized view.

    ``max_entries`` bounds the injected set to the configured window
    (``lorebook_injection_window`` in settings). First-match ordering preserves
    deck authoring order.
    """

    def __init__(
        self,
        deck: LoreDeck,
        max_entries: int = 5,
    ) -> None:
        self._deck = deck
        self._max_entries = max_entries

    @property
    def deck(self) -> LoreDeck:
        return self._deck

    @property
    def max_entries(self) -> int:
        return self._max_entries

    def _search_corpus(self, store: BeliefStore) -> str:
        """Build the text corpus to search from the POV's entitled projection.

        Concatenates:
        - Event content text (from entitled ``store.events``)
        - Committed fact labels (subject, predicate, value from ``store.beliefs``)

        Only includes what the POV is entitled to see at content level.
        """
        parts: list[str] = []
        for e in store.events:
            if e.content:
                parts.append(e.content.lower())
        for (subject, predicate), belief in store.beliefs.items():
            parts.append(f"{subject} {predicate} {belief.value}".lower())
        return " ".join(parts)

    def matching(self, store: BeliefStore, pov: str) -> list[LoreEntry]:
        """Return lore entries triggered for this POV.

        Audience class gate fires first. Then keyword match against the
        entitled corpus only. Returns at most ``max_entries`` entries in deck
        order.
        """
        corpus = self._search_corpus(store)
        visible = self._deck.entries_for(pov)
        matched: list[LoreEntry] = []
        for entry in visible:
            if any(kw.lower() in corpus for kw in entry.keywords):
                matched.append(entry)
                if len(matched) >= self._max_entries:
                    break
        return matched

    def lore_context_block(self, entries: list[LoreEntry]) -> str:
        """Format matched entries into a prompt-ready background block.

        Returns empty string when no entries matched.
        """
        if not entries:
            return ""
        parts = ["[Background lore]"]
        for e in entries:
            parts.append(f"## {e.title}\n{e.content}")
        return "\n\n".join(parts)
