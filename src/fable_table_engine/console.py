"""Human-seat adapter and text playtest console (Phase 15).

`parse_proposal` converts raw player text into a channel-tagged `Proposal`.
`render_event` formats one entitled event as a display line.
`PlaytestSession` wraps `BeatRunner` with a clean per-player interface:
  - parse → run → render, always reading only the player's entitled stream
  - `export_transcript` / `export_transcript_json` for review and replay

Architecture invariants kept here:
  - The client never computes audiences, rules, effects, or hidden state.
  - All computation stays in the engine; this module is presentation and
    proposal plumbing only.
  - `export_transcript_json` includes only events the player is entitled to
    (derived from `assembler.belief_store(player_id)`, not the raw log).
"""

from __future__ import annotations

import re as _re
from typing import Any

from .beat import BeatRunner
from .character_agent import Proposal
from .context import ContextAssembler
from .events import ProjectedEvent


# --------------------------------------------------------------------------- #
# Proposal parser                                                               #
# --------------------------------------------------------------------------- #

def parse_proposal(text: str, agent: str) -> Proposal:
    """Convert player text to a channel-tagged ``Proposal``.

    Syntax::

        whisper <target>: <intent>   → channel="whisper", target=target
        /ooc <intent>                → channel="ooc"
        <anything else>              → channel="public"

    Raises ``ValueError`` for an empty action, a whisper without a colon, or a
    whisper with an empty target or intent.
    """
    stripped = text.strip()

    # OOC: /ooc prefix
    if stripped.startswith("/ooc"):
        rest = stripped[4:].strip()
        return Proposal(agent=agent, intent=rest or "(out of character)", channel="ooc")

    # Whisper: "whisper <target>: <intent>"
    if stripped.lower().startswith("whisper "):
        rest = stripped[8:].strip()  # after "whisper "
        if ":" not in rest:
            raise ValueError(
                f"Malformed whisper — expected 'whisper <target>: <intent>', got: {text!r}"
            )
        target_part, _, intent_part = rest.partition(":")
        target = target_part.strip()
        intent = intent_part.strip()
        if not target:
            raise ValueError(f"Whisper requires a target entity id: {text!r}")
        if not intent:
            raise ValueError(f"Whisper requires a non-empty intent: {text!r}")
        return Proposal(agent=agent, intent=intent, channel="whisper", target=target)

    # Public: everything else
    if not stripped:
        raise ValueError("Player input must not be empty")
    return Proposal(agent=agent, intent=stripped, channel="public")


# --------------------------------------------------------------------------- #
# Event renderer                                                                #
# --------------------------------------------------------------------------- #

# D-032: player-facing epistemic certainty labels. Backend-emitted; client never
# computes these from prose or inference.
EPISTEMIC_LABELS: dict[str, str] = {
    "fact":        "Confirmed",
    "claim":       "Claimed",
    "observation": "Observed",
    "theory":      "Suspected",
}


def epistemic_label(epistemic_type: str | None, *, superseded: bool = False) -> str:
    """Return the player-facing certainty label for an epistemic_type (D-032).

    When ``superseded`` is True (i.e. the event carries a D-031 superseded_by
    value), the label is ``"Corrected/Superseded"`` regardless of type.
    ``"Unknown"`` is reserved for GM-annotated Case File template slots that
    have no evidence yet; it is not inferred from the absence of a commitment.
    """
    if superseded:
        return "Corrected/Superseded"
    return EPISTEMIC_LABELS.get(epistemic_type or "", "Unknown")


def _commitment_labels(event: ProjectedEvent) -> str:
    """Return a bracketed label string for any commitments on this event, or ''."""
    if not event.commitments:
        return ""
    superseded = bool(event.superseded_by)
    parts = []
    for c in event.commitments:
        label = epistemic_label(c.epistemic_type, superseded=superseded)
        parts.append(f"[{label}: {c.subject}.{c.predicate}={c.value}]")
    return " " + " ".join(parts)


def render_event(event: ProjectedEvent) -> str | None:
    """Format one entitled event as a display string, or ``None`` to skip.

    Only event types meaningful to the player are rendered; GM-internal types
    (audit, system, effect_applied) are silent from the player's perspective.

    Superseded events (D-031): events whose id appears in the derived_from of a
    correction or retcon event carry superseded_by set by project_for(). They are
    still rendered — not omitted — but prefixed with [superseded] so the player
    can see the original and the correction together in the transcript.

    Commitment labels (D-032): events with non-empty commitments append bracketed
    epistemic labels so the player can see what was established and how certain it
    is. The client never computes this — it comes from the backend commitment type.
    """
    prefix = "[superseded] " if event.superseded_by else ""

    labels = _commitment_labels(event)

    if event.type == "correction":
        return f"[correction] {event.content}{labels}" if event.content else None
    if event.type == "retcon":
        return f"[retcon] {event.content}{labels}" if event.content else None
    if event.type == "narration":
        return f"{prefix}{event.content}{labels}" if event.content else None
    if event.type == "ooc":
        return f"{prefix}[OOC] {event.author}: {event.content}{labels}" if event.content else None
    if event.type == "dice_roll":
        # D-029: gm_only rolls must not reach the client render path.
        if event.roll_visibility == "gm_only":
            return None
        return f"{prefix}[roll] {event.content}{labels}" if event.content else None
    if event.type == "resolution":
        return f"{prefix}[outcome] {event.content}{labels}" if event.content else None
    if event.type == "front_advance":
        return f"{prefix}[event] {event.content}{labels}" if event.content else None
    if event.type == "action_lifecycle":
        return None
    return None


# --------------------------------------------------------------------------- #
# Structured JSON event renderer (for browser GUI)                              #
# --------------------------------------------------------------------------- #

def _parse_dice_content(content: str) -> dict:
    """Parse '3d6 = [3, 5, 2] = 10 (reason)' into a dict of dice fields."""
    m = _re.search(r'(\d+)d(\d+)\s*=\s*\[([^\]]+)\]\s*=\s*(\d+)(?:\s*\(([^)]*)\))?', content)
    if not m:
        return {}
    rolled = [int(x.strip()) for x in m.group(3).split(",") if x.strip().lstrip("-").isdigit()]
    reason = m.group(5) or ""
    skill_m = _re.match(r'([A-Za-z][A-Za-z\s]*?)\s+vs\s+TN', reason)
    tn_m = _re.search(r'vs\s+TN\s+(\d+)', reason)
    return {
        "pool": int(m.group(1)),
        "rolled": rolled,
        "total": int(m.group(4)),
        "skill": skill_m.group(1).strip() if skill_m else "check",
        "tn_hint": int(tn_m.group(1)) if tn_m else None,
    }


def _parse_resolution_content(content: str) -> dict:
    """Parse 'actor: 3d6+N = T vs TN M -> margin X -> Band' into a dict."""
    m = _re.search(
        r'3d6\+(\d+)\s*=\s*(\d+)\s*vs\s*TN\s*(\d+)\s*->\s*margin\s*([+-]?\d+)\s*->\s*(\w+)',
        content,
    )
    if not m:
        return {}
    return {
        "rating": int(m.group(1)),
        "total": int(m.group(2)),
        "tn": int(m.group(3)),
        "margin": int(m.group(4)),
        "band": m.group(5).lower(),
    }


def _combine_dice_events(events: list[dict]) -> list[dict]:
    """Merge consecutive _dice_partial + _resolution pairs into a single dice event.

    The browser GUI shows one dice card per roll. The backend emits two events
    (dice_roll for the die faces, resolution for skill/TN/band). This function
    folds them into the shape DiceLine expects: {kind, rolled, pool, skill,
    rating, tn, result}. Orphans fall back to system text.
    """
    result: list[dict] = []
    i = 0
    while i < len(events):
        ev = events[i]
        if ev.get("_kind") == "_dice_partial" and i + 1 < len(events):
            nxt = events[i + 1]
            if nxt.get("_kind") == "_resolution":
                result.append({
                    "kind": "dice",
                    "rolled": ev.get("rolled", []),
                    "pool": ev.get("pool", 3),
                    "skill": nxt.get("skill_name") or ev.get("skill", "check"),
                    "rating": nxt.get("rating", 0),
                    "tn": nxt.get("tn") or ev.get("tn_hint") or 10,
                    "result": nxt.get("band", "cost"),
                    "total": nxt.get("total", ev.get("total", 0)),
                })
                i += 2
                continue
        # Orphan dice partial: show raw text
        if ev.get("_kind") == "_dice_partial":
            result.append({"kind": "system", "text": ev.get("raw", "")})
        # Orphan resolution (no preceding dice): show inline
        elif ev.get("_kind") == "_resolution":
            result.append({"kind": "system", "text": ev.get("raw", "")})
        else:
            result.append(ev)
        i += 1
    return result


def render_event_json(event: ProjectedEvent) -> dict | None:
    """Format one entitled event as a JSON-safe dict for the browser GUI client.

    Returns None for events that should not reach the frontend. Uses internal
    ``_kind`` tags for dice pairing (consumed by ``_combine_dice_events``
    before being sent to the client).

    Sender kinds understood by the GUI: gm, ally, npc, system, dice.
    """
    if event.type == "narration" and event.content:
        kind = "gm" if event.author in ("gm", "GM") else "ally"
        d: dict = {"kind": kind, "text": event.content}
        if kind == "ally":
            d["who"] = event.author
        if event.superseded_by:
            d["superseded"] = True
        return d
    if event.type == "ooc" and event.content:
        return {"kind": "system", "text": f"[OOC] {event.author}: {event.content}"}
    if event.type == "correction" and event.content:
        return {"kind": "system", "text": f"[correction] {event.content}"}
    if event.type == "retcon" and event.content:
        return {"kind": "system", "text": f"[retcon] {event.content}"}
    if event.type == "dice_roll" and event.content:
        if event.roll_visibility == "gm_only":
            return None
        parsed = _parse_dice_content(event.content)
        return {"_kind": "_dice_partial", "raw": event.content, **parsed}
    if event.type == "resolution" and event.content:
        if event.roll_visibility == "gm_only":
            return None
        parsed = _parse_resolution_content(event.content)
        # Carry the skill name from "actor: 3d6+N..." prefix
        actor_m = _re.match(r'^([^:]+):\s*', event.content)
        return {"_kind": "_resolution", "raw": event.content,
                "skill_name": actor_m.group(1).strip() if actor_m else None, **parsed}
    if event.type == "front_advance" and event.content:
        return {"kind": "system", "text": event.content}
    return None


# --------------------------------------------------------------------------- #
# PlaytestSession                                                               #
# --------------------------------------------------------------------------- #

class PlaytestSession:
    """Human-seat adapter for a single player in a text playtest session.

    Wraps ``BeatRunner`` so the human player:
      1. Types raw text → ``parse_proposal`` converts it to a ``Proposal``.
      2. ``step`` runs the player's beat and returns only player-entitled lines.
      3. ``export_transcript`` / ``export_transcript_json`` serialize the full
         entitled event stream for review or replay.

    ``step`` tracks which events have already been returned so each call yields
    only what is new since the previous call. ``player_view`` and the export
    methods always return the complete entitled history.

    Only the player's ``BeliefStore`` (``assembler.belief_store(player_id)``)
    is ever read here — never the raw log, world state, or GM context.
    """

    def __init__(
        self,
        runner: BeatRunner,
        assembler: ContextAssembler,
        player_id: str,
    ) -> None:
        self._runner = runner
        self._assembler = assembler
        self._player_id = player_id
        self._rendered_ids: set[str] = set()

    @property
    def player_id(self) -> str:
        return self._player_id

    def parse_proposal(self, text: str) -> Proposal:
        """Convert raw player text to a ``Proposal`` (delegates to module-level helper)."""
        return parse_proposal(text, self._player_id)

    def step(self, player_input: str) -> list[str]:
        """Parse ``player_input``, run the player's beat, return new entitled lines.

        Each call to ``step`` returns only the events that were added since the
        previous call — not the entire history. Use ``player_view`` or
        ``export_transcript`` for the full history.
        """
        proposal = self.parse_proposal(player_input)
        self._runner.run(
            actor=self._player_id,
            action=proposal.intent,
            channel=proposal.channel,
            target=proposal.target,
        )
        return [r for e in self._collect_new_events() if (r := render_event(e))]

    def step_both(self, player_input: str) -> tuple[list[str], list[dict]]:
        """Run the beat and return ``(text_lines, gui_events)`` in one call.

        ``text_lines`` matches what ``step()`` would return. ``gui_events`` is a
        list of typed dicts ready for the browser GUI's ``applyEvent()`` handler.
        Dice/resolution pairs are folded into a single dice event.
        """
        proposal = self.parse_proposal(player_input)
        self._runner.run(
            actor=self._player_id,
            action=proposal.intent,
            channel=proposal.channel,
            target=proposal.target,
        )
        new_events = self._collect_new_events()
        lines = [r for e in new_events if (r := render_event(e))]
        raw_json = [d for e in new_events if (d := render_event_json(e)) is not None]
        return lines, _combine_dice_events(raw_json)

    def history_json(self) -> list[dict]:
        """Full entitled event stream as typed GUI dicts (for session resume)."""
        store = self._assembler.belief_store(self._player_id)
        raw = [d for e in store.events if (d := render_event_json(e)) is not None]
        return _combine_dice_events(raw)

    def _collect_new_events(self) -> list[ProjectedEvent]:
        """Return entitled events not yet seen and mark them as rendered."""
        store = self._assembler.belief_store(self._player_id)
        new_events: list[ProjectedEvent] = []
        for event in store.events:
            if event.id not in self._rendered_ids:
                self._rendered_ids.add(event.id)
                new_events.append(event)
        return new_events

    def _drain_new_events(self) -> list[str]:
        """Return rendered lines for events not yet seen by this session."""
        return [r for e in self._collect_new_events() if (r := render_event(e))]

    def player_view(self) -> list[str]:
        """All rendered lines from the player's current entitled belief store."""
        store = self._assembler.belief_store(self._player_id)
        return [r for e in store.events for r in [render_event(e)] if r]

    def export_transcript(self) -> str:
        """Full entitled event stream as a text transcript (newline-separated)."""
        return "\n\n".join(self.player_view())

    def export_transcript_json(self) -> list[dict[str, Any]]:
        """Full entitled event stream as a list of serializable dicts.

        Includes only events the player is entitled to — never raw log events
        the player was not in the audience of.
        """
        store = self._assembler.belief_store(self._player_id)
        return [
            {
                "id": e.id,
                "sequence": e.sequence,
                "timestamp": e.timestamp,
                "type": e.type,
                "author": e.author,
                "channel": e.channel,
                "content": e.content,
            }
            for e in store.events
        ]
