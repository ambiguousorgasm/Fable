---
name: reference-gui-mockup
description: Location and backend-relevant content of the GUI mockup (The Salt Lantern, React/JSX)
metadata:
  type: reference
---

## Location

`uploads/fable_mockup/` — React/JSX mockup of the FABLE table interface. Entry points:
- `The Salt Lantern.html` / `The Salt Lantern (standalone).html` — playable in a browser
- `scene.js` — all scene data (characters, clocks, beats, case file, composer state)
- `app.jsx` — engine loop, event dispatch, layout wiring
- `composer.jsx` — delivery model, reachability table, action-resolution card
- `transcript.jsx` — turn/bubble rendering, delivery labels, dice display
- `scene-tab.jsx` — Situation, Active Pressures, Current Advantages, Maintained, Just Changed
- `character-tab.jsx` — crew rail, PC full sheet, ally/NPC visible sheet, presence states
- `notes-tab.jsx` / `sidebar.jsx` / `chrome.jsx` / `ui.jsx` / `styles.css`

A `v1/` subdirectory contains an earlier iteration.

## Backend-relevant content

### Delivery channel model (composer.jsx)
The UI defines 6 IC delivery types: `open`, `quiet`, `whisper`, `loud`, `signal`, `silent`, plus `gmq` (Private GM Query) and `ooc`. The backend currently has `public | whisper | ooc`. A mapping is needed:
- `open / quiet / signal / loud / silent` → `public` (varying reach, enforced by perception model)
- `whisper` → `whisper` (D-033 enforces this)
- `ooc` → `ooc`
- `gmq` → **not yet modeled in backend**; goes only to the asking player + GM, private response; the warm GM answers, the cold GM does not adjudicate it

### REACH table (composer.jsx)
Enforces zone × delivery → `{ ok, why? }` client-side. Backend should enforce via the perception model (D-012). `SETTINGS_JSON.communication.enforce_reach: true` is the session flag.

### Private GM Query (gmq) — unmodeled in backend
A player sends a meta question only the GM sees; the GM responds in a private `gmq: true` bubble visible only to that player. Distinct from OOC (which is all-table table-talk). Needs a new backend channel or a directed whisper-to-GM path. **Open decision not yet recorded; note here for when GUI work begins.**

### Character presence states (character-tab.jsx, scene.js)
Characters carry `presence: "present" | "separated" | "hidden" | "incapacitated" | "unavailable"` and `presenceNote`. These drive the crew rail dots and affect reach/addressee availability. The backend `WorldState` does not currently track named presence states — it has entity positions and conditions. A presence field or convention is needed.

### CASEFILE structure (scene.js)
The Notes → Case File tab organizes known information into: People, Places, Factions, Known Truths, Clues, Open Questions, Promises & Debts. This is a player-facing view over the fact/commitment model with a named grouping/category. Informs D-032 (epistemic certainty presentation). The category would likely be a field on `Commitment` or a derived annotation.

### Action resolution card (composer.jsx)
Fields the UI shows: `skill`, `rating`, `tn`, `exposure`, `effect`, `ledger: { group, text }`, `trade: [...]`, `tradeDefault`, `edge: { label }`, `seam` (bool), `volatile` (bool). These match `StakesDecision` and D-025's `ResolutionPlan`. The backend must emit these for the UI to render the action card **before** the roll. `seam` and `volatile` are flags the adjudicator must set.

### Frontend event protocol (app.jsx `applyEvent`)
The channel router must produce events in this format (turn `kind`):
- `gm` — GM narration text
- `ally` / `npc` — character speech (with `who`)
- `system` — mechanics line (also feeds "Just Changed" recent feed)
- `dice` — `{ skill, pool, rolled, result, tn, big? }`
- `beat` — centered scene divider text
- `tick` — `{ clock, to }` — set a clock's fill count
- `stat` — `{ who, track, to }` or `{ who, scar }` — update edge/stress/scars
- `spotlight` — `{ who }` — update spotlight indicator
- `recent` — prepend to Just Changed without a bubble

These are a frontend delivery contract the backend's channel router (phase 11) must satisfy.

### MAINTAINED list (scene.js, scene-tab.jsx)
Items display as "Dossan is holding the west stairwell. — Lapses on next world motion." These are held truths with a lapse condition. The backend needs to track and expire them. Related to D-026 (clock triggers and world motion), the truth/commitment model, and D-030 (fictional time).

### SETTINGS_JSON session config (scene.js)
Backend-relevant settings:
- `communication.whisper_is_telepathy: false` — D-033 (fixed)
- `communication.enforce_reach: true` — perception model enforcement
- `rolls.show_dice: true` — D-029 (roll visibility policy)
- `rolls.auto_resolve_partials: false` — whether backend auto-handles Cost outcomes
- `rolls.crit_on: "two-sixes"` — dice rules (already implemented)
- `gm.temperature`, `gm.narration_length` — model config, relates to D-017

### Clocks (scene.js)
Clocks carry `category: "threat" | "mission" | "access"` and `consequence: string`. Backend clock schema has `domain` and `trigger_types` (D-026) but not `category`. The UI grouping by category is a display concern; the `consequence` string matches `landing_truth` in spirit but is different in form (prose vs. structured Truth).

**Why:** All of the above represent contracts the backend must satisfy at phase 11. Noting them now prevents surprises when the channel router is built.
