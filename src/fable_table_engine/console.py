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
        return self._drain_new_events()

    def _drain_new_events(self) -> list[str]:
        """Return rendered lines for events not yet seen by this session."""
        store = self._assembler.belief_store(self._player_id)
        lines: list[str] = []
        for event in store.events:
            if event.id not in self._rendered_ids:
                self._rendered_ids.add(event.id)
                rendered = render_event(event)
                if rendered:
                    lines.append(rendered)
        return lines

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
