"""Terminal runner for FABLE Table Engine."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TextIO

import anthropic

from .auditor import Auditor
from .budgeter import ContextBudgeter
from .campaign import CampaignPackage, load_campaign
from .character_sheet import CharacterSheet
from .effects import EffectExecutor
from .gm import AdjudicatorGM, NarratorGM, WorldSimulator
from .interface import HomeScreen, PlayInterface, build_play_interface
from .lorebook import LoreAssembler
from .persistence import SessionManager, attach_campaign
from .plot_manager import PlotManager
from .provider import ModelGateway, TelemetrySink
from .settings import SettingsManager
from .world_state import Entity, WorldState

DEFAULT_PLAYER_ID = "hero"
DEFAULT_PLAYER_NAME = "Hero"
DEFAULT_ZONE = "starting_area"


def load_dotenv(path: str | Path = ".env") -> None:
    """Load simple KEY=VALUE pairs into os.environ if they are not already set."""
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _cost_ceiling(settings: SettingsManager, campaign_id: str | None) -> float | None:
    raw = settings.get("session_cost_ceiling_usd", campaign_id=campaign_id)
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _ensure_default_player(world: WorldState, player_id: str = DEFAULT_PLAYER_ID) -> None:
    """Seed the minimal player/world state needed for a blank session."""
    if DEFAULT_ZONE not in world.zones:
        world.add_zone(DEFAULT_ZONE)
    if player_id not in world.entities:
        world.add_entity(
            Entity(
                id=player_id,
                kind="player",
                name=DEFAULT_PLAYER_NAME,
                resources={"stress": 0, "edge": 0},
            )
        )
    if world.zone_of(player_id) is None:
        world.place(player_id, DEFAULT_ZONE)


def _sheet_for(world: WorldState, player_id: str = DEFAULT_PLAYER_ID) -> CharacterSheet:
    entity = world.entities.get(player_id)
    resources = entity.resources if entity is not None else {}
    return CharacterSheet(
        entity_id=player_id,
        concept="Competent protagonist under pressure",
        skills={},
        stress=int(resources.get("stress", 0) or 0),
        edge=int(resources.get("edge", 0) or 0),
    )


def _load_campaign_by_index(
    campaigns: list[CampaignPackage],
    index_text: str,
) -> CampaignPackage | None:
    try:
        index = int(index_text)
    except ValueError:
        return None
    if not (1 <= index <= len(campaigns)):
        return None
    return campaigns[index - 1]


def _campaign_file_id(campaigns_dir: Path, package: CampaignPackage) -> str:
    for path in sorted(campaigns_dir.glob("*.json")):
        try:
            if load_campaign(path).title == package.title:
                return path.stem
        except ValueError:
            continue
    return package.title.lower().replace(" ", "_") or "campaign"


def _build_interface(
    *,
    log,
    world,
    scene,
    campaign: CampaignPackage | None,
    campaign_id: str | None,
    settings: SettingsManager,
    gateway: ModelGateway,
    sink: TelemetrySink,
    player_id: str = DEFAULT_PLAYER_ID,
) -> PlayInterface:
    _ensure_default_player(world, player_id)

    pipeline_graph = attach_campaign(log, campaign)
    if campaign is not None:
        campaign.seed_world(world)

    # These collaborators can safely hold separate CommitPipeline instances:
    # the append-only log remains the source of truth.
    from .access import CommitPipeline

    pipeline = CommitPipeline(log)
    executor = EffectExecutor(log, world, pipeline, scene=scene)
    simulator = WorldSimulator(log, world)
    plot_manager = PlotManager(pipeline_graph, pipeline, log)
    auditor = Auditor(gateway=gateway, semantic=False)
    budgeter = ContextBudgeter.from_settings(settings, campaign_id=campaign_id)
    lore_assembler = None
    if campaign is not None and campaign.lore_entries:
        window_raw = settings.get("lorebook_injection_window", campaign_id=campaign_id)
        try:
            max_entries = int(window_raw)
        except ValueError:
            max_entries = 5
        lore_assembler = LoreAssembler(campaign.lore_deck(), max_entries=max_entries)

    return build_play_interface(
        log=log,
        world=world,
        scene=scene,
        player_id=player_id,
        adjudicator=AdjudicatorGM(gateway),
        narrator=NarratorGM(gateway),
        settings=settings,
        roster=[player_id],
        campaign_id=campaign_id,
        sheets={player_id: _sheet_for(world, player_id)},
        executor=executor,
        auditor=auditor,
        simulator=simulator,
        plot_manager=plot_manager,
        budgeter=budgeter,
        lore_assembler=lore_assembler,
        sink=sink,
    )


class TerminalApp:
    """Small interactive shell around HomeScreen and PlayInterface."""

    def __init__(
        self,
        *,
        root: str | Path = ".",
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
    ) -> None:
        self.root = Path(root)
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.campaigns_dir = self.root / "campaigns"
        self.sessions_dir = self.root / "sessions"
        self.settings_dir = self.root / "settings"
        self.settings = SettingsManager(self.settings_dir)
        self.home = HomeScreen(
            campaigns_dir=self.campaigns_dir,
            sessions_dir=self.sessions_dir,
            settings_dir=self.settings_dir,
        )
        self.session_manager = SessionManager(self.sessions_dir)

    def _print(self, text: str = "") -> None:
        print(text, file=self.stdout)

    def _make_gateway(self, campaign_id: str | None) -> tuple[ModelGateway, TelemetrySink] | None:
        load_dotenv(self.root / ".env")
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            self._print(
                "ANTHROPIC_API_KEY is not set. Add it to .env before starting a live session."
            )
            return None
        sink = TelemetrySink(cost_ceiling_usd=_cost_ceiling(self.settings, campaign_id))
        client = anthropic.Anthropic(api_key=api_key)
        return ModelGateway(client, sink=sink, settings=self.settings), sink

    def run(self) -> int:
        self._print(self.home.render())
        self._print("")
        while True:
            print("home> ", end="", file=self.stdout, flush=True)
            raw = self.stdin.readline()
            if raw == "":
                return 0
            command = raw.strip()
            if not command:
                continue
            lower = command.lower()
            if lower in {"quit", "exit", "q"}:
                return 0
            if lower == "settings":
                self._print(self.settings.load_settings().__repr__())
                continue
            if lower.startswith("resume"):
                if self._resume(command):
                    return 0
                continue
            if lower.startswith("new"):
                if self._new(command):
                    return 0
                continue
            self._print("Unknown command. Use: new [n] [title], resume <n>, settings, quit")

    def _new(self, command: str) -> bool:
        parts = command.split(maxsplit=2)
        campaigns = self.home.available_campaigns()
        campaign: CampaignPackage | None = None
        title = "FABLE Session"
        campaign_id = "blank"

        if len(parts) >= 2 and parts[1].isdigit():
            campaign = _load_campaign_by_index(campaigns, parts[1])
            if campaign is None:
                self._print(f"No campaign #{parts[1]}.")
                return False
            campaign_id = _campaign_file_id(self.campaigns_dir, campaign)
            title = campaign.title
            if len(parts) == 3:
                title = parts[2]
        elif len(parts) >= 2:
            title = " ".join(parts[1:])

        gateway_pair = self._make_gateway(campaign_id)
        if gateway_pair is None:
            return False
        gateway, sink = gateway_pair

        manifest, log, world, scene = self.session_manager.create(campaign_id, title)
        try:
            iface = _build_interface(
                log=log,
                world=world,
                scene=scene,
                campaign=campaign,
                campaign_id=campaign_id,
                settings=self.settings,
                gateway=gateway,
                sink=sink,
            )
            self._print(f"Started session: {manifest.title}")
            self._play_loop(iface, manifest.session_id)
        finally:
            log.close()
        return True

    def _resume(self, command: str) -> bool:
        parts = command.split(maxsplit=1)
        sessions = self.home.available_sessions()
        if len(parts) != 2 or not parts[1].isdigit():
            self._print("Use: resume <n>")
            return False
        index = int(parts[1])
        if not (1 <= index <= len(sessions)):
            self._print(f"No saved session #{index}.")
            return False
        selected = sessions[index - 1]
        gateway_pair = self._make_gateway(selected.campaign_id)
        if gateway_pair is None:
            return False
        gateway, sink = gateway_pair

        manifest, log, world, scene = self.session_manager.resume(selected.session_id)
        campaign = self._campaign_for_id(manifest.campaign_id)
        try:
            iface = _build_interface(
                log=log,
                world=world,
                scene=scene,
                campaign=campaign,
                campaign_id=manifest.campaign_id,
                settings=self.settings,
                gateway=gateway,
                sink=sink,
            )
            self._print(f"Resumed session: {manifest.title}")
            self._play_loop(iface, manifest.session_id)
        finally:
            log.close()
        return True

    def _campaign_for_id(self, campaign_id: str) -> CampaignPackage | None:
        if campaign_id == "blank":
            return None
        path = self.campaigns_dir / f"{campaign_id}.json"
        if not path.exists():
            return None
        try:
            return load_campaign(path)
        except ValueError:
            return None

    def _play_loop(self, iface: PlayInterface, session_id: str) -> None:
        self._print("")
        self._print("Type an action. Commands: /help, /status, /history, /settings, /save, /quit")
        while True:
            status = iface.render_status()
            prompt = f"[{status}]> " if status else "> "
            print(prompt, end="", file=self.stdout, flush=True)
            raw = self.stdin.readline()
            if raw == "":
                self.session_manager.update_manifest(session_id)
                return
            text = raw.strip()
            if not text:
                continue
            if text.startswith("/"):
                if self._handle_play_command(text, iface, session_id):
                    return
                continue
            try:
                lines = iface.submit(text)
            except Exception as exc:
                self._print(f"Action failed: {exc}")
                self.session_manager.update_manifest(session_id)
                continue
            if not lines:
                self._print("(no player-visible update)")
            for line in lines:
                self._print(line)
            self.session_manager.update_manifest(
                session_id,
                last_scene_summary=text[:120],
            )

    def _handle_play_command(
        self,
        command: str,
        iface: PlayInterface,
        session_id: str,
    ) -> bool:
        lower = command.lower()
        if lower in {"/quit", "/exit", "/q"}:
            self.session_manager.update_manifest(session_id)
            self._print("Session saved.")
            return True
        if lower == "/save":
            self.session_manager.update_manifest(session_id)
            self._print("Session saved.")
            return False
        if lower == "/status":
            self._print(iface.render_status() or "(no status)")
            return False
        if lower == "/history":
            history = iface.history()
            self._print("\n".join(history) if history else "(no visible history)")
            return False
        if lower == "/settings":
            self._print(iface.render_settings())
            return False
        if lower == "/help":
            self._print(
                "Commands: /status, /history, /settings, /save, /quit. "
                "Anything else is submitted as your character's action."
            )
            return False
        self._print("Unknown command. Use /help.")
        return False


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    if argv and argv[0] in {"-h", "--help"}:
        print("Usage: fable-play\n\nRun the terminal FABLE Table Engine beta.")
        return 0
    if argv and argv[0] == "--version":
        print("fable-table-engine 0.0.0")
        return 0
    return TerminalApp().run()


if __name__ == "__main__":
    raise SystemExit(main())
