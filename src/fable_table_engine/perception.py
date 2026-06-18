"""Perception model — who *could* have sensed an event (CORE §6, §7.1; phase 3).

The load-bearing wall for secrets and differential information. It answers one
deterministic question: given a stimulus originating somewhere in the zone
graph, which entities could perceive it? That set is what event audiences and
overhears are computed from — secrecy is enforced here, by who-could-sense,
never by asking a model to pretend it didn't hear (CORE principle 4).

It operates over the fiction-positional zone graph (D-002): zones + relational
position Truths, never coordinates. Topology and presence live in `WorldState`;
the volatile sensory conditions (lighting now, which doorways are open) live in
the `Scene` here, the registered Scene/perception state. The model itself owns
no state — it is a pure read over `Scene` + `WorldState` + the `Stimulus`.

Modalities and propagation (deliberately a thin first cut, to be stress-tested):

  * auditory, by volume —
      - whisper: stays in the origin zone, and reaches only entities *close* to
        the actor (an intra-zone closeness Truth). This is what makes a whisper
        private even in a crowded room.
      - normal: the whole origin zone.
      - loud: the origin zone plus any adjacent zone reachable through a
        connection that currently transmits sound (one hop).
  * visual — requires the origin zone to be lit (line of sight). Same zone if
    lit; into the origin from an adjacent zone if the connection transmits sight
    and the origin is lit (you can see a lit room from a dark hall through an
    open door).
  * audiovisual — the union of the two.

`derive_overhears` turns the gap between *who could perceive* and the event's
*intended audience* into `may_have_perceived` events: a vague, content-level
hint addressed to each unintended perceiver, authored by a neutral `perception`
source (so an overhearer learns it sensed *something*, not who or what) and
linked to the source event via `derived_from`. The secret content never leaves
the original event's narrow audience.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .events import Event
from .world_state import WorldState

# Author of derived perception events. Neutral on purpose: an overhearer should
# learn that it sensed something, not the identity of who caused it.
PERCEPTION_AUTHOR = "perception"
MAY_HAVE_PERCEIVED = "may_have_perceived"

VOLUMES = frozenset({"whisper", "normal", "loud"})
MODALITIES = frozenset({"auditory", "visual", "audiovisual"})


@dataclass(frozen=True)
class Stimulus:
    """What an event gives off to be sensed.

    `volume` applies to the auditory channel only; visual reach is gated by
    lighting and line of sight, not volume.
    """

    modality: str = "auditory"
    volume: str = "normal"

    def __post_init__(self) -> None:
        if self.modality not in MODALITIES:
            raise ValueError(f"modality must be one of {sorted(MODALITIES)}")
        if self.volume not in VOLUMES:
            raise ValueError(f"volume must be one of {sorted(VOLUMES)}")

    @property
    def is_auditory(self) -> bool:
        return self.modality in ("auditory", "audiovisual")

    @property
    def is_visual(self) -> bool:
        return self.modality in ("visual", "audiovisual")


@dataclass
class Scene:
    """Volatile sensory conditions over a `WorldState`'s zone graph.

    The registered Scene/perception state. Holds only what changes as the
    fiction does: which zones are dark, and which connections are shut. Defaults
    are permissive — zones are lit and connections open — so a Scene with no
    overrides is a well-lit, open space.
    """

    world: WorldState
    dark_zones: set[str] = field(default_factory=set)
    closed_connections: set[frozenset[str]] = field(default_factory=set)

    def darken(self, zone: str) -> None:
        self.dark_zones.add(zone)

    def lit(self, zone: str) -> bool:
        return zone not in self.dark_zones

    def close(self, a: str, b: str) -> None:
        """Shut the doorway between two zones (blocks sound and sight across it)."""
        self.closed_connections.add(frozenset({a, b}))

    def transmits(self, a: str, b: str) -> bool:
        """Whether the a<->b connection currently carries sound/sight."""
        edge = frozenset({a, b})
        return edge in self.world.connections and edge not in self.closed_connections


def perception_map(
    scene: Scene, *, origin: str, actor: str, stimulus: Stimulus
) -> dict[str, set[str]]:
    """Map each entity that could sense the stimulus to the modalities it sensed.

    Pure read; the actor is excluded (you do not overhear yourself).

    A stimulus must originate in a real zone. An unknown `origin` is a caller
    error, not "nobody perceived" — silently returning an empty set there could
    mask a real overhear (under-disclosure that looks like secrecy holding), so
    fail loud instead.
    """
    world = scene.world
    if origin not in world.zones:
        raise ValueError(f"stimulus origin {origin!r} is not a known zone")
    sensed: dict[str, set[str]] = {}

    def add(entity: str, modality: str) -> None:
        if entity == actor:
            return
        sensed.setdefault(entity, set()).add(modality)

    if stimulus.is_auditory:
        if stimulus.volume == "whisper":
            # Only those close to the actor, and only within the origin zone.
            for other in world.entities_in(origin):
                if world.are_close(actor, other):
                    add(other, "auditory")
        else:
            for other in world.entities_in(origin):
                add(other, "auditory")
            if stimulus.volume == "loud":
                for adj in world.adjacent(origin):
                    if scene.transmits(origin, adj):
                        for other in world.entities_in(adj):
                            add(other, "auditory")

    if stimulus.is_visual and scene.lit(origin):
        for other in world.entities_in(origin):
            add(other, "visual")
        for adj in world.adjacent(origin):
            if scene.transmits(origin, adj):
                for other in world.entities_in(adj):
                    add(other, "visual")

    return sensed


def perceivers(scene: Scene, *, origin: str, actor: str, stimulus: Stimulus) -> set[str]:
    """The set of entities (other than the actor) that could sense the stimulus."""
    return set(perception_map(scene, origin=origin, actor=actor, stimulus=stimulus))


def _hint(modalities: set[str], volume: str, same_zone: bool) -> str:
    where = "nearby" if same_zone else "from another area"
    parts: list[str] = []
    if "auditory" in modalities:
        sound = {"loud": "a loud noise", "normal": "voices", "whisper": "a faint murmur"}[volume]
        parts.append(f"{sound} {where}")
    if "visual" in modalities:
        parts.append(f"movement {where}")
    return "(perceived) " + "; ".join(parts)


def derive_overhears(
    log,
    *,
    source_event: Event,
    scene: Scene,
    origin: str,
    actor: str,
    stimulus: Stimulus,
) -> list[Event]:
    """Append a `may_have_perceived` event for each unintended perceiver.

    An unintended perceiver is anyone who could sense the stimulus but is not in
    the source event's audience (and is not the actor). Each gets a vague,
    content-level hint authored by the neutral `perception` source, linked back
    to the source event via `derived_from`. The source event's own (narrow)
    audience and secret content are untouched.
    """
    sensed = perception_map(scene, origin=origin, actor=actor, stimulus=stimulus)
    overhearers = set(sensed) - set(source_event.audience)
    out: list[Event] = []
    for who in sorted(overhearers):
        same_zone = scene.world.zone_of(who) == origin
        out.append(
            log.append(
                author=PERCEPTION_AUTHOR,
                channel="system",
                type=MAY_HAVE_PERCEIVED,
                content=_hint(sensed[who], stimulus.volume, same_zone),
                audience=(who,),
                visibility="content",
                derived_from=(source_event.id,),
            )
        )
    return out
