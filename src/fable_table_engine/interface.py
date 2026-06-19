"""Home screen and play interface for FABLE Table Engine.

Text-only session view: home screen (campaign listing + session resume),
event stream rendering, settings panel. Client never computes audiences,
derives hidden state, or transfers knowledge between views. See Phase 21
deliverable 10 and D-041.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .campaign import CampaignPackage, load_campaign
from .console import PlaytestSession
from .persistence import SessionManifest, SessionManager
from .settings import SettingsManager, SettingsRegistry

if TYPE_CHECKING:
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
    """

    def __init__(
        self,
        session: PlaytestSession,
        settings: SettingsManager,
        roster: list[str] | tuple[str, ...] = (),
        campaign_id: str | None = None,
        world: WorldState | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._roster = list(roster)
        self._campaign_id = campaign_id
        self._world = world

    @property
    def player_id(self) -> str:
        return self._session.player_id

    def submit(self, text: str) -> list[str]:
        """Submit a player action and return new entitled display lines."""
        return self._session.step(text)

    def history(self) -> list[str]:
        """Return all entitled display lines from the current session."""
        return self._session.player_view()

    def export_transcript(self) -> str:
        """Full entitled event stream as newline-separated text."""
        return self._session.export_transcript()

    def render_status(self) -> str:
        """Format time-anchor status as a display string.

        Returns an empty string when no WorldState was provided.
        """
        if self._world is None:
            return ""
        w = self._world
        parts = [f"scene:{w.scene_phase}", f"beat:{w.beat_index}"]
        if w.prose_time_label:
            parts.append(w.prose_time_label)
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
        session, settings, roster=roster, campaign_id=campaign_id, world=world
    )
