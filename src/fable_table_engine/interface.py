"""Home screen and play interface for FABLE Table Engine.

Text-only session view: home screen (campaign listing + session resume),
event stream rendering, settings panel. Client never computes audiences,
derives hidden state, or transfers knowledge between views. See Phase 21
deliverable 10 and D-041.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .campaign import CampaignPackage, load_campaign
from .console import PlaytestSession
from .persistence import SessionManifest, SessionManager
from .settings import SettingsManager, SettingsRegistry

if TYPE_CHECKING:
    from .provider import TelemetrySink
    from .world_state import WorldState


class HomeScreen:
    """Navigation state for the FABLE home screen.

    Lists pre-built campaign packages and saved sessions. Does not create
    or resume sessions — that requires model clients supplied by the caller.
    HomeScreen is pure navigation and rendering.
    """

    def __init__(
        self,
        campaigns_dir: str | Path = "campaigns",
        sessions_dir: str | Path = "sessions",
        settings_dir: str | Path = "settings",
    ) -> None:
        self._campaigns_dir = Path(campaigns_dir)
        self._sessions_dir = Path(sessions_dir)
        self._settings_dir = Path(settings_dir)

    def available_campaigns(self) -> list[CampaignPackage]:
        """Return all loadable CampaignPackage objects, sorted by filename."""
        if not self._campaigns_dir.exists():
            return []
        packages = []
        for path in sorted(self._campaigns_dir.glob("*.json")):
            try:
                packages.append(load_campaign(str(path)))
            except Exception:
                pass  # skip malformed packages silently
        return packages

    def available_sessions(self) -> list[SessionManifest]:
        """Return saved sessions (newest-first) from sessions_dir."""
        if not self._sessions_dir.exists():
            return []
        return SessionManager(str(self._sessions_dir)).list_sessions()

    def session_manager(self) -> SessionManager:
        """Return a SessionManager for this home screen's sessions directory."""
        return SessionManager(str(self._sessions_dir))

    def settings_manager(self) -> SettingsManager:
        """Return a SettingsManager for this home screen's settings directory."""
        return SettingsManager(str(self._settings_dir))

    def render(self) -> str:
        """Format the home screen as a display string."""
        campaigns = self.available_campaigns()
        sessions = self.available_sessions()
        lines = ["=== FABLE Table Engine ===", ""]

        lines.append("Saved sessions:")
        if sessions:
            for i, s in enumerate(sessions, 1):
                updated = s.updated_at[:10] if s.updated_at else "?"
                label = s.title or s.session_id
                lines.append(f"  [{i}] {label}  ({updated})")
        else:
            lines.append("  (none — start a new session below)")

        lines.append("")
        lines.append("Available campaigns:")
        if campaigns:
            for i, c in enumerate(campaigns, 1):
                lines.append(f"  [{i}] {c.title}")
        else:
            lines.append(
                "  (none — add campaign JSON files to the campaigns/ directory)"
            )

        lines.append("")
        lines.append("Commands:  resume <n>  ·  new <n>  ·  settings  ·  quit")
        return "\n".join(lines)


class PlayInterface:
    """Rendering and input layer over PlaytestSession.

    Accesses the event log only through PlaytestSession (which reads via
    project_for(player_id) — never log.all()). Never computes audiences or
    derives hidden state.

    Parameters
    ----------
    session:
        Pre-wired PlaytestSession for the active player seat.
    settings:
        SettingsManager instance for the active settings directory.
    roster:
        Entity IDs for character agent seats; drives the settings panel
        character-slot rows. Empty by default.
    campaign_id:
        Used for per-campaign settings layer lookup. None means user-level only.
    world:
        Optional WorldState for render_status(). None means status is blank.
    sink:
        Optional TelemetrySink for cost-ceiling status in render_status().
        When the ceiling is at WARNING or EXCEEDED, render_status() appends a
        [cost: WARNING] or [cost: EXCEEDED] indicator. None means no cost display.
    """

    def __init__(
        self,
        session: PlaytestSession,
        settings: SettingsManager,
        roster: list[str] | tuple[str, ...] = (),
        campaign_id: str | None = None,
        world: WorldState | None = None,
        sink: TelemetrySink | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._roster = list(roster)
        self._campaign_id = campaign_id
        self._world = world
        self._sink = sink

    @property
    def player_id(self) -> str:
        return self._session.player_id

    def submit(self, text: str) -> list[str]:
        """Submit a player action and return new entitled display lines."""
        return self._session.step(text)

    def submit_both(self, text: str) -> tuple[list[str], list[dict]]:
        """Submit an action and return ``(text_lines, gui_events)`` in one call."""
        return self._session.step_both(text)

    def history(self) -> list[str]:
        """Return all entitled display lines from the current session."""
        return self._session.player_view()

    def history_json(self) -> list[dict]:
        """Full entitled event stream as typed GUI dicts (for session resume)."""
        return self._session.history_json()

    def session_state(self) -> dict:
        """Return current character/clock/scene snapshot for the browser GUI.

        Reads only from ``self._world`` (already available on PlayInterface).
        Character stats are sourced from entity.resources, which EffectExecutor
        keeps in sync with the deterministic state.
        """
        player_id = self._session.player_id
        world = self._world
        characters: dict = {}
        clocks: list = []
        scene: dict = {}

        if world is not None:
            for eid, entity in world.entities.items():
                res = entity.resources
                stress_val = int(res.get("stress", 0))
                edge_val = int(res.get("edge", 0))
                scars_raw: list = list(res.get("scars", []))
                scars_padded: list = [
                    {"type": s.get("scar_type", "Wound"), "label": s.get("description", "")}
                    if isinstance(s, dict) else {"type": "Wound", "label": str(s)}
                    for s in scars_raw
                ] + [None] * max(0, 3 - len(scars_raw))
                characters[eid] = {
                    "id": eid,
                    "kind": "you" if eid == player_id else "ally",
                    "name": entity.name or eid,
                    "concept": str(res.get("concept", "")),
                    "role": str(res.get("role", "")),
                    "presence": str(res.get("presence", "present")),
                    "presenceNote": str(res.get("presence_note", "")),
                    "edge": {"val": edge_val, "max": 3},
                    "stress": {"val": stress_val, "max": 6},
                    "scars": scars_padded[:3],
                    "scarsList": [
                        {"kind": s["type"], "text": s["label"]}
                        for s in scars_padded if s
                    ],
                    "skills": _skills_list(res.get("skills", {})),
                    "traits": list(res.get("traits", [])),
                    "bonds": list(res.get("bonds", [])),
                    "advances": int(res.get("advances", 0)),
                    "activity": str(res.get("activity", "")),
                    "condition": str(res.get("condition", "")),
                    "gear": list(res.get("gear", [])),
                    "visibleGear": [],
                    "drive": str(res.get("drive", "")),
                    "question": str(res.get("question", "")),
                }

            for cname, cdata in world.clocks.items():
                if not isinstance(cdata, dict):
                    continue
                size = int(cdata.get("size", 4))
                filled = int(cdata.get("filled", 0))
                clocks.append({
                    "id": cname,
                    "name": cname.replace("-", " ").replace("_", " ").title(),
                    "size": size,
                    "filled": filled,
                    "domain": str(cdata.get("domain", "threat")),
                })

            scene = {
                "phase": world.scene_phase,
                "beat_index": world.beat_index,
                "time_label": world.prose_time_label or "",
            }

        crew_order = [k for k, v in characters.items() if v["kind"] == "you"] + \
                     [k for k, v in characters.items() if v["kind"] == "ally"]
        return {
            "player_id": player_id,
            "characters": characters,
            "crew_order": crew_order,
            "clocks": clocks,
            "scene": scene,
        }

    def export_transcript(self) -> str:
        """Full entitled event stream as newline-separated text."""
        return self._session.export_transcript()

    def render_status(self) -> str:
        """Format time-anchor + cost-ceiling status as a display string.

        Returns an empty string when neither WorldState nor a cost alert is
        present. Appends [cost: WARNING] or [cost: EXCEEDED] whenever the
        TelemetrySink ceiling is breached.
        """
        parts: list[str] = []
        if self._world is not None:
            w = self._world
            parts = [f"scene:{w.scene_phase}", f"beat:{w.beat_index}"]
            if w.prose_time_label:
                parts.append(w.prose_time_label)
        if self._sink is not None:
            from .provider import CostCeilingStatus
            cs = self._sink.ceiling_status()
            if cs == CostCeilingStatus.EXCEEDED:
                parts.append("[cost: EXCEEDED]")
            elif cs == CostCeilingStatus.WARNING:
                parts.append("[cost: WARNING]")
        return "  ".join(parts)

    def render_settings(self) -> str:
        """Format the settings panel as a display string.

        Shows all essential settings with current values and marks overrides.
        Character agent slot rows are derived from the roster supplied at
        construction (empty roster = no slot rows).
        """
        settings = self._settings.load_settings(self._campaign_id)
        slots = self._settings.character_slots(self._roster, self._campaign_id)

        lines = ["=== Settings ===", ""]
        lines.append(f"Settings file:  {self._settings.user_settings_path()}")
        if self._campaign_id:
            lines.append(
                f"Campaign file:  "
                f"{self._settings.campaign_settings_path(self._campaign_id)}"
            )
        lines.append("")
        lines.append("Essential settings  (* = overridden from default):")
        for key in sorted(SettingsRegistry.ESSENTIAL_KEYS):
            default = SettingsRegistry.DEFAULTS[key]
            value = settings.get(key, default)
            marker = " *" if value != default else ""
            lines.append(f"  {key}: {value}{marker}")

        if slots:
            lines.append("")
            lines.append("Character agent slots  (* = per-entity override):")
            default_model = settings.get(
                "character_agent_default_model",
                SettingsRegistry.DEFAULTS["character_agent_default_model"],
            )
            for entity_id in sorted(slots):
                model = slots[entity_id]
                marker = " *" if model != default_model else ""
                lines.append(f"  {entity_id}: {model}{marker}")

        lines.append("")
        lines.append(
            "Settings are read from JSON files and take effect on next session open."
        )
        return "\n".join(lines)


def _skills_list(raw: object) -> list[dict]:
    """Normalise skills resource to [{name, r}] regardless of source format."""
    if isinstance(raw, dict):
        return [{"name": k, "r": int(v)} for k, v in raw.items()]
    if isinstance(raw, list):
        result = []
        for s in raw:
            if isinstance(s, dict):
                result.append({"name": str(s.get("name", "")), "r": int(s.get("r", s.get("rank", 0)))})
            else:
                result.append({"name": str(s), "r": 0})
        return result
    return []


def bootstrap_opening(log: Any, player_id: str, campaign: CampaignPackage) -> None:
    """Emit opening narration events for a new session seeded by a campaign package.

    Commits up to two GM narration events into the event log so the player
    sees them immediately on session open, before the first player action:
      1. ``player_intro`` — the player-facing premise/backstory.
      2. ``starting_scene`` — the opening scene description (if different from intro).

    Skipped if the campaign has no intro or scene text. The events appear in
    ``history_json()`` / ``PlayInterface.history_json()`` automatically because
    both read from the same append-only log.

    ``gm_context`` and ``initial_hidden_truths`` are never emitted here — they
    remain available only to the GM via the session's system context.
    """
    from .access import CommitPipeline

    intro = (campaign.player_intro or "").strip()
    scene_text = (campaign.starting_scene or "").strip()
    if not intro and not scene_text:
        return

    pipeline = CommitPipeline(log)
    audience: tuple[str, ...] = (player_id, "gm")

    if intro:
        pipeline.commit(
            author="gm",
            channel="public",
            type="narration",
            content=intro,
            audience=audience,
        )

    if scene_text and scene_text != intro:
        pipeline.commit(
            author="gm",
            channel="public",
            type="narration",
            content=scene_text,
            audience=audience,
        )


def build_play_interface(
    log,
    world: WorldState,
    scene,
    player_id: str,
    adjudicator,
    narrator,
    settings: SettingsManager,
    roster: list[str] | tuple[str, ...] = (),
    campaign_id: str | None = None,
    sheets: dict | None = None,
    executor=None,
    auditor=None,
    simulator=None,
    plot_manager=None,
    budgeter=None,
    lore_assembler=None,
    sink=None,
) -> PlayInterface:
    """Wire engine components into a ready-to-use PlayInterface.

    Constructs CommitPipeline, RulesEngine, DiceService, ContextAssembler,
    BeatRunner, and PlaytestSession from the provided log/world/scene and
    model gateway instances, then wraps everything in a PlayInterface.

    adjudicator and narrator should be AdjudicatorGM / NarratorGM instances
    (or test mocks of the same interface).

    Optional subsystems (all default to None / disabled):
      executor      -- EffectExecutor for deterministic typed effects
      auditor       -- Auditor for post-beat invariant checks
      simulator     -- WorldSimulator for pre-beat world projection
      plot_manager  -- PlotManager for front/clock interest signals
      budgeter      -- ContextBudgeter for per-role token budgets
      lore_assembler -- LoreAssembler for lorebook keyword injection
      sink          -- TelemetrySink for cost-ceiling display in render_status()
    """
    from .access import CommitPipeline
    from .beat import BeatRunner
    from .context import ContextAssembler
    from .dice import DiceService
    from .rules import RulesEngine

    pipeline = CommitPipeline(log)
    dice = DiceService(log)
    rules = RulesEngine(log, dice)
    assembler = ContextAssembler(log, scene, budgeter=budgeter, lore_assembler=lore_assembler)
    runner = BeatRunner(
        log=log,
        world=world,
        pipeline=pipeline,
        rules=rules,
        assembler=assembler,
        adjudicator=adjudicator,
        narrator=narrator,
        sheets=sheets or {},
        executor=executor,
        auditor=auditor,
        simulator=simulator,
        plot_manager=plot_manager,
        budgeter=budgeter,
    )
    session = PlaytestSession(runner, assembler, player_id)
    return PlayInterface(
        session, settings, roster=roster, campaign_id=campaign_id, world=world, sink=sink
    )
