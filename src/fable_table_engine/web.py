"""Local browser GUI for FABLE Table Engine beta."""
from __future__ import annotations

import errno
import json
import os
import signal
import sys
import webbrowser
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import anthropic

from .campaign import CampaignPackage, load_campaign
from .cli import (
    _build_interface,
    _campaign_file_id,
    _cost_ceiling,
    _load_campaign_by_index,
    load_dotenv,
)
from .interface import HomeScreen, PlayInterface
from .persistence import SessionManager, SQLiteEventLog
from .provider import ModelGateway, TelemetrySink
from .settings import SettingsManager


@dataclass
class ActiveSession:
    session_id: str
    title: str
    campaign_id: str
    log: SQLiteEventLog
    iface: PlayInterface


class WebAppState:
    """Mutable process state for the local browser app."""

    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root)
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
        self.active: dict[str, ActiveSession] = {}

    def close(self) -> None:
        for active in list(self.active.values()):
            active.log.close()
        self.active.clear()

    def api_home(self) -> dict[str, Any]:
        load_dotenv(self.root / ".env")
        campaigns = self.home.available_campaigns()
        sessions = self.home.available_sessions()
        return {
            "key_configured": bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
            "campaigns": [
                {
                    "index": i,
                    "title": c.title,
                    "description": c.description,
                }
                for i, c in enumerate(campaigns, 1)
            ],
            "sessions": [
                {
                    "index": i,
                    "session_id": s.session_id,
                    "campaign_id": s.campaign_id,
                    "title": s.title,
                    "updated_at": s.updated_at,
                    "last_scene_summary": s.last_scene_summary,
                }
                for i, s in enumerate(sessions, 1)
            ],
        }

    def new_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        campaign_index = payload.get("campaign_index")
        title = str(payload.get("title") or "FABLE Session").strip() or "FABLE Session"

        campaign: CampaignPackage | None = None
        campaign_id = "blank"
        if campaign_index not in (None, "", 0):
            campaign = _load_campaign_by_index(self.home.available_campaigns(), str(campaign_index))
            if campaign is None:
                raise ValueError(f"No campaign #{campaign_index}.")
            campaign_id = _campaign_file_id(self.campaigns_dir, campaign)
            if not payload.get("title"):
                title = campaign.title

        gateway, sink = self._make_gateway(campaign_id)
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
        except Exception:
            log.close()
            raise

        self.active[manifest.session_id] = ActiveSession(
            session_id=manifest.session_id,
            title=manifest.title,
            campaign_id=manifest.campaign_id,
            log=log,
            iface=iface,
        )
        return self._session_payload(manifest.session_id)

    def resume_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        session_id = str(payload.get("session_id") or "").strip()
        if not session_id:
            index = int(payload.get("index") or 0)
            sessions = self.home.available_sessions()
            if not (1 <= index <= len(sessions)):
                raise ValueError(f"No saved session #{index}.")
            session_id = sessions[index - 1].session_id

        if session_id in self.active:
            return self._session_payload(session_id)

        manifest, log, world, scene = self.session_manager.resume(session_id)
        campaign = self._campaign_for_id(manifest.campaign_id)
        gateway, sink = self._make_gateway(manifest.campaign_id)
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
        except Exception:
            log.close()
            raise

        self.active[manifest.session_id] = ActiveSession(
            session_id=manifest.session_id,
            title=manifest.title,
            campaign_id=manifest.campaign_id,
            log=log,
            iface=iface,
        )
        return self._session_payload(manifest.session_id)

    def submit_action(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        active = self._active(session_id)
        text = str(payload.get("text") or "").strip()
        if not text:
            raise ValueError("Action text is required.")
        lines = active.iface.submit(text)
        self.session_manager.update_manifest(
            session_id,
            last_scene_summary=text[:120],
        )
        return {
            "session": self._session_payload(session_id),
            "lines": lines,
        }

    def save_session(self, session_id: str) -> dict[str, Any]:
        self._active(session_id)
        self.session_manager.update_manifest(session_id)
        return self._session_payload(session_id)

    def settings_text(self, session_id: str) -> dict[str, str]:
        return {"text": self._active(session_id).iface.render_settings()}

    def _session_payload(self, session_id: str) -> dict[str, Any]:
        active = self._active(session_id)
        return {
            "session_id": active.session_id,
            "title": active.title,
            "campaign_id": active.campaign_id,
            "status": active.iface.render_status(),
            "history": active.iface.history(),
        }

    def _active(self, session_id: str) -> ActiveSession:
        try:
            return self.active[session_id]
        except KeyError as exc:
            raise KeyError("Session is not open in this browser process. Resume it from Home.") from exc

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

    def _make_gateway(self, campaign_id: str | None) -> tuple[ModelGateway, TelemetrySink]:
        load_dotenv(self.root / ".env")
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to .env before starting a session.")
        sink = TelemetrySink(cost_ceiling_usd=_cost_ceiling(self.settings, campaign_id))
        client = anthropic.Anthropic(api_key=api_key)
        return ModelGateway(client, sink=sink, settings=self.settings), sink


def create_handler(state: WebAppState):
    class FableHandler(BaseHTTPRequestHandler):
        server_version = "FableWeb/0.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/":
                    self._send_html(INDEX_HTML)
                elif parsed.path == "/api/home":
                    self._send_json(state.api_home())
                elif parsed.path.startswith("/api/session/"):
                    session_id = parsed.path.removeprefix("/api/session/").strip("/")
                    self._send_json(state._session_payload(session_id))
                elif parsed.path == "/rules":
                    self._send_rules_pdf()
                else:
                    self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._send_error(exc)

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            payload = self._read_json()
            try:
                if parsed.path == "/api/session/new":
                    self._send_json(state.new_session(payload))
                    return
                if parsed.path == "/api/session/resume":
                    self._send_json(state.resume_session(payload))
                    return
                if parsed.path.startswith("/api/session/") and parsed.path.endswith("/action"):
                    session_id = parsed.path.removeprefix("/api/session/").removesuffix("/action").strip("/")
                    self._send_json(state.submit_action(session_id, payload))
                    return
                if parsed.path.startswith("/api/session/") and parsed.path.endswith("/save"):
                    session_id = parsed.path.removeprefix("/api/session/").removesuffix("/save").strip("/")
                    self._send_json(state.save_session(session_id))
                    return
                if parsed.path.startswith("/api/session/") and parsed.path.endswith("/settings"):
                    session_id = parsed.path.removeprefix("/api/session/").removesuffix("/settings").strip("/")
                    self._send_json(state.settings_text(session_id))
                    return
                self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._send_error(exc)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8")
            return json.loads(raw) if raw.strip() else {}

        def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, html: str) -> None:
            body = html.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_rules_pdf(self) -> None:
            path = state.root / "static" / "fable_rules.pdf"
            if not path.exists():
                self._send_json({"error": "Rules PDF not found."}, status=HTTPStatus.NOT_FOUND)
                return
            body = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_error(self, exc: Exception) -> None:
            status = HTTPStatus.BAD_REQUEST
            if isinstance(exc, KeyError):
                status = HTTPStatus.NOT_FOUND
            self._send_json({"error": str(exc)}, status=status)

    return FableHandler


def run_server(host: str = "127.0.0.1", port: int = 8765, *, open_browser: bool = True) -> int:
    state = WebAppState(".")
    try:
        server = ThreadingHTTPServer((host, port), create_handler(state))
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            raise
        server = ThreadingHTTPServer((host, 0), create_handler(state))
    url = f"http://{host}:{server.server_address[1]}"

    def _shutdown(_signum=None, _frame=None) -> None:
        state.close()
        server.server_close()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _shutdown)
    print(f"FABLE web beta running at {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    finally:
        state.close()
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or sys.argv[1:])
    host = os.environ.get("FABLE_HOST", "127.0.0.1")
    port = int(os.environ.get("FABLE_PORT", "8765"))
    open_browser = True
    if "--no-open" in argv:
        open_browser = False
        argv.remove("--no-open")
    if "--host" in argv:
        i = argv.index("--host")
        host = argv[i + 1]
    if "--port" in argv:
        i = argv.index("--port")
        port = int(argv[i + 1])
    if "--help" in argv or "-h" in argv:
        print("Usage: fable-web [--host 127.0.0.1] [--port 8765] [--no-open]")
        return 0
    return run_server(host=host, port=port, open_browser=open_browser)


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>FABLE Table Engine</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f2ec;
      --panel: #fffdf8;
      --panel-2: #ece8df;
      --ink: #191816;
      --muted: #66625a;
      --line: #d6d0c3;
      --accent: #245c54;
      --accent-2: #8f3d2e;
      --focus: #d9a441;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--ink);
    }
    button, input, select, textarea {
      font: inherit;
    }
    button {
      border: 1px solid var(--line);
      border-radius: 6px;
      background: var(--panel);
      color: var(--ink);
      padding: 8px 10px;
      cursor: pointer;
    }
    button.primary {
      background: var(--accent);
      color: white;
      border-color: var(--accent);
    }
    button:disabled { opacity: .55; cursor: not-allowed; }
    .app {
      min-height: 100vh;
      display: grid;
      grid-template-columns: 320px minmax(0, 1fr);
    }
    aside {
      border-right: 1px solid var(--line);
      background: var(--panel);
      padding: 18px;
      overflow: auto;
    }
    main {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
      min-width: 0;
      min-height: 100vh;
    }
    h1 {
      font-size: 22px;
      margin: 0 0 4px;
      letter-spacing: 0;
    }
    h2 {
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: .04em;
      color: var(--muted);
      margin: 22px 0 8px;
    }
    .tagline {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.35;
      margin-bottom: 16px;
    }
    .key {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      font-size: 13px;
      background: var(--panel-2);
    }
    .key.ok { border-color: #8bb49b; background: #eef7f1; }
    .key.missing { border-color: #c98d82; background: #fff0ed; }
    .row {
      display: flex;
      gap: 8px;
      align-items: center;
    }
    .stack { display: grid; gap: 8px; }
    input, select, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: white;
      color: var(--ink);
      padding: 9px 10px;
    }
    textarea {
      resize: vertical;
      min-height: 70px;
      max-height: 180px;
    }
    .list {
      display: grid;
      gap: 6px;
    }
    .item {
      width: 100%;
      text-align: left;
      background: white;
    }
    .item small {
      display: block;
      color: var(--muted);
      margin-top: 3px;
      line-height: 1.3;
    }
    .topbar {
      border-bottom: 1px solid var(--line);
      background: rgba(255, 253, 248, .86);
      padding: 12px 16px;
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
    }
    .session-title {
      font-weight: 700;
      overflow-wrap: anywhere;
    }
    .status {
      color: var(--muted);
      font-size: 13px;
    }
    .transcript {
      padding: 18px;
      overflow: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .empty {
      margin: auto;
      max-width: 520px;
      text-align: center;
      color: var(--muted);
      line-height: 1.5;
    }
    .bubble {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px 13px;
      max-width: 760px;
      background: var(--panel);
      line-height: 1.45;
      white-space: pre-wrap;
    }
    .bubble.player {
      margin-left: auto;
      background: #edf3f1;
      border-color: #c7dad5;
    }
    .composer {
      border-top: 1px solid var(--line);
      background: var(--panel);
      padding: 12px 16px;
      display: grid;
      gap: 8px;
    }
    .error {
      color: #8f3d2e;
      font-size: 13px;
      min-height: 18px;
    }
    dialog {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 0;
      width: min(720px, calc(100vw - 32px));
    }
    dialog::backdrop { background: rgba(0, 0, 0, .32); }
    .modal-head {
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    pre {
      margin: 0;
      padding: 14px;
      overflow: auto;
      white-space: pre-wrap;
      max-height: 70vh;
    }
    @media (max-width: 780px) {
      .app { grid-template-columns: 1fr; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
      main { min-height: 62vh; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <h1>FABLE</h1>
      <div class="tagline">Text beta for one human player. Code owns truth; models own voice.</div>
      <div id="keyState" class="key">Checking API key...</div>

      <h2>New Session</h2>
      <div class="stack">
        <input id="sessionTitle" placeholder="Session title" value="FABLE Session" />
        <select id="campaignSelect"><option value="">Blank session</option></select>
        <button id="newBtn" class="primary">Start</button>
      </div>

      <h2>Saved Sessions</h2>
      <div id="sessions" class="list"></div>

      <h2>Reference</h2>
      <div class="stack">
        <button id="rulesBtn">Rules PDF</button>
        <button id="settingsBtn" disabled>Settings</button>
        <button id="saveBtn" disabled>Save</button>
      </div>
    </aside>

    <main>
      <div class="topbar">
        <div>
          <div id="sessionName" class="session-title">No session open</div>
          <div id="sessionStatus" class="status">Start or resume a session.</div>
        </div>
      </div>
      <div id="transcript" class="transcript">
        <div class="empty">Open a session to begin testing the live text loop.</div>
      </div>
      <div class="composer">
        <textarea id="actionInput" placeholder="Describe your action..." disabled></textarea>
        <div class="row">
          <button id="sendBtn" class="primary" disabled>Send</button>
          <button id="historyBtn" disabled>History</button>
        </div>
        <div id="error" class="error"></div>
      </div>
    </main>
  </div>

  <dialog id="modal">
    <div class="modal-head">
      <strong id="modalTitle">Details</strong>
      <button id="modalClose">Close</button>
    </div>
    <pre id="modalBody"></pre>
  </dialog>

  <script>
    let home = null;
    let active = null;

    const $ = id => document.getElementById(id);
    const transcript = $("transcript");
    const errorBox = $("error");

    function setError(message) {
      errorBox.textContent = message || "";
    }

    async function api(path, options = {}) {
      const res = await fetch(path, {
        ...options,
        headers: {"Content-Type": "application/json", ...(options.headers || {})}
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Request failed");
      return data;
    }

    async function refreshHome() {
      home = await api("/api/home");
      const key = $("keyState");
      key.className = "key " + (home.key_configured ? "ok" : "missing");
      key.textContent = home.key_configured
        ? "Anthropic key detected"
        : "ANTHROPIC_API_KEY missing in .env";

      const select = $("campaignSelect");
      select.innerHTML = '<option value="">Blank session</option>';
      for (const c of home.campaigns) {
        const opt = document.createElement("option");
        opt.value = c.index;
        opt.textContent = c.title;
        select.appendChild(opt);
      }

      const sessions = $("sessions");
      sessions.innerHTML = "";
      if (!home.sessions.length) {
        const div = document.createElement("div");
        div.className = "status";
        div.textContent = "No saved sessions.";
        sessions.appendChild(div);
      } else {
        for (const s of home.sessions) {
          const btn = document.createElement("button");
          btn.className = "item";
          btn.innerHTML = `${escapeHtml(s.title || s.session_id)}<small>${escapeHtml((s.updated_at || "").slice(0, 10))}</small>`;
          btn.onclick = () => resumeSession(s.session_id);
          sessions.appendChild(btn);
        }
      }
    }

    function renderSession(session) {
      active = session;
      $("sessionName").textContent = session.title || "FABLE Session";
      $("sessionStatus").textContent = session.status || "Session open";
      $("actionInput").disabled = false;
      $("sendBtn").disabled = false;
      $("historyBtn").disabled = false;
      $("settingsBtn").disabled = false;
      $("saveBtn").disabled = false;
      renderTranscript(session.history || []);
    }

    function renderTranscript(lines) {
      transcript.innerHTML = "";
      if (!lines.length) {
        const div = document.createElement("div");
        div.className = "empty";
        div.textContent = "No player-visible events yet. Enter your first action.";
        transcript.appendChild(div);
        return;
      }
      for (const line of lines) {
        const div = document.createElement("div");
        div.className = "bubble";
        div.textContent = line;
        transcript.appendChild(div);
      }
      transcript.scrollTop = transcript.scrollHeight;
    }

    async function startSession() {
      setError("");
      try {
        const title = $("sessionTitle").value.trim();
        const campaign_index = $("campaignSelect").value || null;
        const session = await api("/api/session/new", {
          method: "POST",
          body: JSON.stringify({title, campaign_index})
        });
        renderSession(session);
        await refreshHome();
      } catch (err) {
        setError(err.message);
      }
    }

    async function resumeSession(session_id) {
      setError("");
      try {
        const session = await api("/api/session/resume", {
          method: "POST",
          body: JSON.stringify({session_id})
        });
        renderSession(session);
      } catch (err) {
        setError(err.message);
      }
    }

    async function sendAction() {
      if (!active) return;
      const input = $("actionInput");
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      setError("");
      $("sendBtn").disabled = true;
      try {
        const playerBubble = document.createElement("div");
        playerBubble.className = "bubble player";
        playerBubble.textContent = text;
        transcript.appendChild(playerBubble);
        transcript.scrollTop = transcript.scrollHeight;

        const result = await api(`/api/session/${active.session_id}/action`, {
          method: "POST",
          body: JSON.stringify({text})
        });
        renderSession(result.session);
      } catch (err) {
        setError(err.message);
      } finally {
        $("sendBtn").disabled = false;
        input.focus();
      }
    }

    async function saveActive() {
      if (!active) return;
      setError("");
      try {
        const session = await api(`/api/session/${active.session_id}/save`, {method: "POST"});
        renderSession(session);
        await refreshHome();
      } catch (err) {
        setError(err.message);
      }
    }

    async function showSettings() {
      if (!active) return;
      try {
        const result = await api(`/api/session/${active.session_id}/settings`, {method: "POST"});
        showModal("Settings", result.text);
      } catch (err) {
        setError(err.message);
      }
    }

    function showHistory() {
      if (!active) return;
      showModal("History", (active.history || []).join("\n\n") || "(no visible history)");
    }

    function showModal(title, text) {
      $("modalTitle").textContent = title;
      $("modalBody").textContent = text;
      $("modal").showModal();
    }

    function escapeHtml(text) {
      const span = document.createElement("span");
      span.textContent = text;
      return span.innerHTML;
    }

    $("newBtn").onclick = startSession;
    $("sendBtn").onclick = sendAction;
    $("saveBtn").onclick = saveActive;
    $("settingsBtn").onclick = showSettings;
    $("historyBtn").onclick = showHistory;
    $("rulesBtn").onclick = () => window.open("/rules", "_blank");
    $("modalClose").onclick = () => $("modal").close();
    $("actionInput").addEventListener("keydown", event => {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) sendAction();
    });

    refreshHome().catch(err => setError(err.message));
  </script>
</body>
</html>"""


if __name__ == "__main__":
    raise SystemExit(main())
