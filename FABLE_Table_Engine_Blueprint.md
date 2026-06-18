# FABLE Table Engine — Design Blueprint

*Working title; the program facilitates live play of the FABLE tabletop RPG with an AI-run table. Rename freely.*

**Status:** Foundational design brief. This is the source document everything else derives from. It is written to stand alone — no prior context required.

---

## 0. How to use this document

This brief defines *what the system is, why it is shaped this way, and what must be built*. It is deliberately architecture-first and implementation-light: it should remain stable while code, models, and the FABLE ruleset underneath it evolve. When a downstream decision conflicts with this document, either the decision is wrong or this document needs a conscious, logged revision. Sections 1–3 are the philosophy and vocabulary; 4–8 are the system; 9–13 are the practical on-ramp to building.

**Document set and precedence.** This file (CORE) is the authoritative spine. It is accompanied by satellite files, each with a distinct change-rate and a single responsibility: `COMPONENTS.md` (the authoritative registry of every model, service, and store, with what depends on each), `DECISIONS.md` (the living log of open and resolved design decisions), `STATUS.md` (design-vs-built tracking), `CHANGELOG.md` (append-only history), and `00_README.md` (directory map and the change protocol to follow on every edit). **Precedence rule:** where any satellite file conflicts with CORE, CORE wins until CORE is consciously revised. Satellites hold detail and state; CORE holds structure and intent.

---

## 1. Goal and design philosophy

### 1.1 The goal

Build a system that **genuinely simulates a live tabletop RPG session** — one human player seated at a table run entirely by AI: an AI Game Master, AI teammates who play their own characters, and a populated, reactive world. The target is not "a chatbot that narrates a story," but the *felt experience of a real table*: teammates who know things you don't, a GM who builds a consistent world and improvises gracefully, NPCs with their own attitudes, secrets that actually stay secret, and a world that holds together over hours of play without contradicting itself.

Initial scope is **one human player + an AI table**. The architecture must not preclude multiple human players later, but the first target is the single-player case.

### 1.2 The two failure modes this system exists to defeat

Every prior AI-TTRPG approach fails in one of two ways, and the entire design is organized around defeating both:

- **Omniscience collapse (the single-model failure).** When one model runs the whole table, it necessarily holds all information at once. It is then *structurally impossible* for it to maintain differential knowledge — teammates can't have private perspectives, secrets can't be kept from some parties and not others, and the GM always knows more than a GM should. The world feels like one mind puppeting everyone, because it is.
- **Ineffective agent networks (the naive multi-model failure).** The obvious fix — a model per character — introduces coordination cost that is often *worse* than the disease. If every agent must talk to every other agent, context explodes, state desyncs, and the table descends into incoherence. "Many agents wired together badly" is not an improvement over "one agent that knows everything."

The design threads between these: partition information by point of view (defeating omniscience) while routing all communication through shared, mediated state rather than agent-to-agent messaging (defeating the N² network).

### 1.3 The five load-bearing principles

Everything in this document is a consequence of these five ideas. If a component seems arbitrary, trace it back to one of them.

1. **The determinism boundary.** Draw a hard line between what is decided by *deterministic code* and what is decided by a *model*. Code owns everything with a correct answer: dice resolution, resource tracking, positions and distances, legality of an action, the rules math. Models own only voice, intent, drama, and judgment under genuine ambiguity. Almost every classic bug — mistakes sliding, lost context, self-contradiction — is a model being trusted with something that had a correct answer. This boundary is the spine of the whole system.

2. **Information is partitioned by point of view; the GM is not architecturally special.** Every agent, *including the GM*, receives a constructed *view* of the world, never the whole world. The GM is simply the agent whose private knowledge happens to include the world's hidden state. This single mechanism — fog of war applied uniformly — dissolves omniscience collapse. A teammate "doesn't know the secret" not because a model is pretending, but because the relevant tokens are never placed in its context.

3. **Agents read filtered state and propose actions to a mediator; they do not message each other.** A real table is not a mesh network — nobody telepathically syncs with anyone. Players observe a shared fiction and react to it. The system mirrors this with a **blackboard**: shared authoritative state is the table, each agent's fog-of-war filter is its seat, agents write proposed actions to a queue, and a mediator plus the rules engine arbitrate and commit results back to shared state. This kills the context explosion that makes naive multi-agent systems incoherent.

4. **Honesty is enforceable only because of principle 1.** "Players call out the GM for a mistake" has no solution in a single-model world — there is no independent ground truth to check against. Once state lives in deterministic code, a referee can watch the GM's narration against authoritative state and flag contradictions mechanically. Integrity is a *property of the architecture*, not a behavior we hope the model exhibits.

5. **Fidelity tiering.** Not every entity is a full agent. A bartender who appears once needs no belief store, no relationship graph, no persistent persona — the GM puppets a lightweight, ephemeral voice. Cost forces this and realism does not require otherwise. Reserve full persistent agents for the player's AI teammates and for recurring NPCs who genuinely need an inner life.

### 1.4 The meta-pattern

One idea recurs at every layer of the system: **separate the invariant truth from its presentation, and gate the presentation by audience.** Cold engine result vs. warm narration. What physically happened vs. how it is narrated to each point of view. A plot's underlying *function* vs. the specific *fixture* that delivers it. The access framework (Section 6) is this same pattern applied to *who is permitted to see which layer*. Build this one idea well and secrets, consistency, and invisible improvisation all fall out of it.

---

## 2. Problems to resolve

These are the concrete capabilities the system must deliver. Each is a requirement, and each maps to subsystems later in the document.

- **Differential information / real teammates.** AI teammates must hold and act on knowledge other parties lack (including knowledge whispered privately by the player), so their public actions are explicable in hindsight but not pre-explained to those who didn't share the secret.
- **Per-character channels and attribution.** Each character and NPC speaks in its own attributed stream, not as text the GM writes on everyone's behalf. (This is a *free consequence* of genuinely separate agents; it is hard only when faked by a single model.)
- **World consistency and non-contradiction.** Once the GM establishes a fact (a distance, a locked door, an NPC's name), it is binding. No party may act in violation of it, and the GM may not silently contradict it. Spatial coherence is the canonical case: if the tower is 100 feet off, no one touches it without traversing that distance over time.
- **GM authority with graceful improvisation.** The GM constructs the world by declaration and runs a planned plot, but must be able to revise the plot when players make the plan impossible or pull strongly toward an unplanned thread — without railroading the player and without losing continuity.
- **Honesty / self-correction.** The system must catch the GM's (and characters') mistakes the way a human player would, rather than letting errors accumulate.
- **No over-rolling.** Trivial, stakes-free actions must resolve in the fiction without invoking dice or mechanics, while still rippling through the world (perception, attitude) where appropriate.
- **Relationship/disposition dynamics.** The system tracks how characters feel about one another and lets that shape behavior and (carefully) mechanics.
- **Cost and latency.** The table must stay responsive; flow dies if every exchange takes tens of seconds or burns enormous token budgets.

---

## 3. Core concepts and vocabulary

Precise terms, used consistently throughout the codebase and docs.

- **Event.** The atomic unit of everything that happens. Append-only. Carries `{author, channel, audience, visibility, type, content, commitments, derived_from, sequence}`. The event log is the single source of historical truth.
- **Channel.** The medium an event travels on: `public` (the shared table), `whisper` (private between named parties), `ooc` (out-of-character / rules talk), `dice` (results feed), `system` (engine/meta). Channel shapes default audience but does not solely determine it.
- **Audience.** The set of entities permitted to witness an event. *This field is the access-control mechanism.* "Who is in the audience" is the complete answer to "whose context changes."
- **Visibility.** Whether an audience member receives an event's **content** or only its **metadata** (that it happened, by whom, on what channel). Can vary per audience member.
- **World state.** The authoritative, structured, deterministic representation of everything with a correct answer: entities, positions, conditions, resources, clocks/fronts, the scene/zone graph, terrain. Lives in code.
- **Commitment / commit.** A structured fact lifted from a declaration and written into world state, after which it is binding. Committing is the moment a declaration stops being fiat and becomes law.
- **Canon ledger.** The subset of committed facts that have been *revealed to players*. Immutable. The boundary above which nothing may be silently changed.
- **Fact-extraction.** The step that parses a GM (or other) declaration in prose into candidate structured commitments, and checks them against existing state. This same step is the contradiction detector: a candidate that conflicts with the ledger is, by definition, "contradictory."
- **Belief store.** A *derived* view: the projection of the event log onto a single agent, filtered by that agent's audience membership. Not a separately authored store — computed (and optionally cached) from the log.
- **Context assembly.** The step that builds an agent's prompt for a beat from its belief-store projection, its persona, relevant retrieved memory, and the relationship/state facts it is entitled to see. Implements fog of war.
- **Perception model.** The subsystem that decides *what an entity could sense* given the scene: presence, line of sight, audibility, lighting, positioning. It computes/validates audiences (e.g., whether an adjacent enemy overhears a whisper). The load-bearing wall — secrets are only as good as this.
- **Rules engine.** Deterministic code implementing FABLE's mechanics: resolution, stances, the Trade/Ledger economy, combat math, clocks/fronts. The single authority for mechanical outcomes.
- **Dice service.** Logged, auditable randomness. No outcome a model claims is real unless it came from here.
- **Stakes gate.** The adjudicator's first question on any declared action: *are there stakes?* If no risk, no opposition, no uncertain outcome — no roll. Most lifelike texture comes from stakes-free actions that still ripple through perception and disposition.
- **Cold/warm split.** Adjudication (cold, rules-bound, defers to the engine) is separated from narration (warm, dramatic). The narrator never sees the dice; it sees the resolved result and dresses it.
- **Orchestrator / Director.** Flow control: decides who may act next. Operates on routing metadata (presence, spotlight, initiative order), *not* on private content, so it cannot itself become an omniscience leak.
- **Spotlight / Initiative.** Two turn modes. Initiative = structured order (combat), engine-driven. Spotlight = free-flowing social scenes; the director picks who is most pressed to act, or agents *bid* to speak.
- **Auditor / Referee.** Watches narration and proposed actions against world state and the rules engine; flags contradictions and illegal outcomes. Live validation gates.
- **Disposition graph.** A directed graph of attitudes between characters, multi-axis (e.g. trust, affection, respect, obligation), asymmetric (A→B ≠ B→A), with every change derived from and linked to a logged event.
- **Strings.** A spendable unit of relational leverage (PbtA-style) — the preferred way to couple disposition to mechanics, instead of an always-on passive modifier.
- **Plot graph.** The GM's prepared structure as a graph of fronts, clocks, hooks, secrets, and hidden nodes with preconditions — not a linear script. Distinguishes plot **functions** (the need: "player must get a hint to location Y") from **fixtures** (the delivery: "this NPC gives it").
- **Plot-manager.** A dedicated agent that owns the *future*: tracks the plot graph, detects divergence, re-binds functions to new fixtures, promotes high-interest threads, and accumulates player-interest signals. Edits only the hidden graph, never the canon ledger.
- **Front / Clock.** Offscreen threats and progress trackers that advance over time (FABLE's Long Game machinery).
- **Agent.** A model instance with a persistent persona, goals, and a belief store. **Teammate (TM)** = an agent playing a character alongside the player. **NPC** = a character without its own agent, puppeted by the GM or by a single **NPC-manager** agent aligned with the GM.
- **Override.** A *deliberate*, logged revision of committed state by an authorized party (rule-of-cool, or the GM correcting its own slip). Distinguished from a bug precisely because it is logged as intentional, so the auditor treats it as fiat, not error.

---

## 4. System architecture

### 4.1 The four layers

**Interface layer.** Per-character channels and feeds: the public table, whisper/OOC channels, the dice+voice feed (per-character TTS). Because agents are genuinely separate and emit attributed output, the separate-chat-box UI is a direct consequence of the architecture, not a thing to fake.

**Agent layer (model-driven).** The GM agent (role-decomposed; see below) and the character agents (each = persona + belief store + goals). Optionally an NPC-manager agent.

**Mediation layer.** The orchestrator/director (turn routing on metadata), the context-assembly / fog-of-war filter (per-POV view construction), and the referee/auditor (narration vs. ground truth). This layer is mostly deterministic; the auditor may use a small model for natural-language surfacing.

**Deterministic core (code, not models).** World state, the rules engine, the dice service, the append-only event log, and the relationship/disposition graph (maintained by the disposition engine, which derives every delta from a logged event). This is the ground truth the GM writes into and is bound by, and the thing every other layer checks against.

The **determinism boundary** runs between the agent layer (models) and everything below it (code). Everything below the line carries truth; everything above it carries presentation.

### 4.2 GM decomposition

The reason single-model GMs let mistakes slide is that narration and adjudication happen in one forward pass, and the drama bias contaminates fairness — a model that wants the scene to be exciting quietly rounds a 14 up to a hit. So decompose the GM:

- **Adjudicator** (cold): decides whether an action has stakes, what is at risk, and *reads* the mechanical outcome from the rules engine. It does not invent outcomes.
- **Narrator** (warm): renders the resolved, cold result into prose. Never sees the dice.
- **World-simulator / front-runner:** advances clocks and offscreen threats.

The plot-manager (Section 7.4) is a separate agent, not part of the GM: the **GM-narrator owns the present (the mouth); the plot-manager owns the future (the prep brain)**. Splitting them is what lets the GM improvise hard without losing the thread.

### 4.3 The blackboard topology

Agents never call each other. They read filtered views of shared state and write proposed actions to a queue — a *transient, non-authoritative* proposal buffer, distinct from the append-only event log: it holds candidates, and a proposal becomes a logged event only once resolved and committed (so unresolved proposals never enter another agent's belief projection). The orchestrator and engine arbitrate, commit results to shared state, log events, and update beliefs and relationships. The updated, re-filtered state is what agents see on the next beat. This is the table: you observe the shared fiction and react, you do not sync minds.

---

## 5. The beat loop

The runtime cycle, executed each "beat":

1. **Route.** The orchestrator decides who may act — initiative order in combat, spotlight or bidding in social scenes — using routing metadata only.
2. **Assemble view.** The context layer builds that agent's filtered prompt: belief-store projection + persona + retrieved memory + entitled state and relationship facts.
3. **Propose.** The agent emits an intent (and any dialogue) to the queue.
4. **Stakes gate.** The adjudicator asks whether resolution is needed. If not, skip to 6.
5. **Resolve.** The rules engine resolves mechanical parts deterministically (dice via the dice service), producing ground truth.
6. **Extract and commit.** Any new declared facts are lifted into structured commitments and checked against the canon ledger (see Section 6).
7. **Audit.** The referee checks the proposed narration/outcome against world state and the rules engine.
8. **Narrate.** The narrator renders the cold result into warm prose. It never saw the dice.
9. **Commit and log.** State updates; an event is appended with its audience and visibility; affected belief stores update, and the disposition engine derives any disposition-edge deltas from the new event (each linked to its causal event id).
10. **Render.** The UI routes output to the correct channels/boxes; TTS queues in turn order (the same scheduler that prevents voice overlap).

Loop.

---

## 6. The access and information model

This is the spine of the system. It is the read/write framework all behavior derives from.

### 6.1 The event lifecycle (authoring → binding)

A declaration is **a write that immediately becomes a binding read.** The GM (or any author) has *authoring authority* by fiat but loses *revision authority* the instant it speaks:

1. **Declare.** The author narrates in prose ("the tower looms a hundred feet off across a marsh, its gate barred from within, one guard pacing the rampart").
2. **Extract.** Fact-extraction lifts structured commitments: `tower @ ~100ft`, `terrain = marsh`, `gate.state = barred-inside`, `entity guard @ rampart, behavior = pacing`.
3. **Consistency-check.** Each candidate is checked against the canon ledger. *This check is the operational definition of "contradictory."* Consistent → commit. Conflicting → it is a "mistake"; do not silently canonize (auto-flag back to the author for a corrected declaration before it reaches players, or surface via the auditor if already shown).
4. **Bind.** Committed facts are law. From the next beat on, all queries about them are reads, and the GM is bound by them exactly as the players are.

The deterministic core is therefore not a pre-measured world the GM queries — it is **a ledger the GM writes into by declaration, which then holds the GM to its own words.** Its job is to *remember and enforce* what the GM invented so the GM cannot drift.

### 6.2 The three legal state-change modes (and the one forbidden move)

- **Add** (fiat): introduce new facts freely ("a portal opens" — new entity, committed). Always allowed.
- **Change via causation:** alter facts through sanctioned in-world events (the party moves → the engine updates positions → now they are five feet away). Always allowed.
- **Override** (logged): a deliberate revision of committed state by an authorized party, logged as intentional so the auditor reads it as fiat, not a bug. The escape hatch for rule-of-cool and self-correction.
- **Forbidden: silent contradiction.** Negating or overwriting a committed fact without logging it as an override ("actually, you were always touching the tower").

The frame: **the GM authors the geometry; the engine enforces the physics.** The GM can place the tower anywhere, but once placed, it is as bound by the distance as anyone.

### 6.3 Belief stores as projections

An agent's belief store is the read-time projection of the event log filtered by that agent's audience membership. **Recommendation:** derive on read from the single log (one source of truth, no desync) and cache for speed, rather than materializing separate stores at write time. The cost of an extra projection is cheap; the cost of two stores drifting apart is the omniscience bug returning by the back door.

### 6.4 The access matrix (worked)

The four canonical scenarios, showing that the audience field does all the work. `content` = sees what was said/done; `metadata` = knows it happened; `—` = nothing; `signal` = receives a soft interest cue:

| Event | Actor | Whisper target | Other teammates | NPC-manager | GM | Plot-manager |
|---|---|---|---|---|---|---|
| Whisper to a teammate | content | content | — | — *(unless overheard)* | content | metadata |
| Distance query | content | — | — | — | content *(serves it)* | signal |
| Trivial action (jump) | content | content | content | content + perception | content | signal |
| Plot-breaking action | content | content | content | content | content | content + revises hidden graph |

---

## 7. Key subsystems in depth

### 7.1 The perception model (build this first and carefully)

Secrets, fog of war, dramatic irony, and overheard whispers all depend on one hard computation: *what could this entity sense?* Witnessing is a judgment grounded in scene state — presence, line of sight, audibility, lighting, positioning. The audience of an event is not just its intended recipients; it is the intended recipients **plus anyone the perception model says could perceive it.** A whisper in an empty room reaches only its targets; the same whisper with an enemy in the adjacent square may yield a derived `may-have-overheard` event to the NPC-manager. Get this right and differential information is automatic; get it wrong and secrets leak in exactly the way the whole design exists to prevent.

### 7.2 Cold adjudication / warm narration

Two separated steps. The adjudicator runs the stakes gate, calls the rules engine, and obtains ground truth. The narrator receives only the resolved result and renders prose. Because the narrator cannot see the dice, it cannot bias the outcome — most of the honesty problem is solved here, before the auditor even runs.

### 7.3 Fact-extraction and commit pipeline

The mechanism that converts improvised natural-language worldbuilding into enforceable, self-binding state. Two viable approaches to resolve during design: (a) a structured-output extraction pass over the GM's free prose, or (b) requiring the GM to emit a structured commitment block *alongside* its prose. Either way, the pipeline must run the consistency-check (Section 6.1) and is the upstream prerequisite for the auditor — without committed facts, the auditor has nothing to check against.

### 7.4 The plot-manager

Owns graceful improvisation. Player agency is **sovereign over the plot**: the engine never negates a player's action to protect a script (that is railroading). When an action diverges from the plan, the plot-manager absorbs it by separating **function** from **fixture**:

- If a fixture is destroyed (the quest-giver dies), the *function* persists (the player still needs the hint) and is re-bound to a new fixture (a journal, a rival faction, a clue at the scene).
- If players diverge by *interest* (fixating on a discarded thread), the plot-manager promotes it: spins up a front, gives it stakes, and seeks a latent connection to existing structure.

The discipline that keeps flexibility from becoming incoherence: **the plot-manager may edit only the hidden, not-yet-revealed portion of the plot graph; it may never contradict the canon ledger.** Future is fluid; disclosed past is immutable. Players see only in-fiction consequences, never the revision — at a real table, good improvisation is invisible, and here it is invisible because the plot graph is in no player's audience. The plot-manager is also the home for accumulated interest signals (from distance queries, behavior, dialogue focus), giving the GM a model of where the table is leaning.

### 7.5 The disposition system

A directed, asymmetric, multi-axis graph (trust / affection / respect / obligation as a starting set; two characters can respect and dislike each other simultaneously). Every change is **derived from a logged event** ("took a hit meant for me: +trust") so attitudes are auditable and explainable, never free-floating vibes. Disposition feeds two places: agent context (the prompt states current attitude) and, carefully, mechanics.

**Mechanical-coupling caution.** A persistent passive cooperation modifier looks great and quietly corrupts the EV math — it incentivizes approval-farming and compounds unpredictably. Prefer the **Strings** model: disposition is a spendable resource, banked and spent for one-time, legible effects, rather than an always-on multiplier. Whatever coupling is chosen must pass the same EV audit as any other FABLE mechanic before it reaches a live table.

### 7.6 The auditor

Live validation gates. Because world state is deterministic, the auditor has ground truth to check narration against: an outcome that violates the rules engine, or a narration that contradicts committed state (touching a tower 100 feet away with no traversal logged), is mechanically detectable. The auditor distinguishes a contradiction the GM *meant* (an override, logged) from one it did not (a bug, flagged).

---

## 8. Data model sketch

Concrete enough to begin schema design; not final. These are partially realized as JSON Schema skeletons in `schemas/` (`event`, `world_state`, `character_sheet`), with fields deliberately left open where a decision is unresolved (e.g. `position` is untyped pending D-002). The schemas are skeletons that track this sketch, not an independent source of truth — reconcile them with this section when either changes.

- **Event log** (append-only): `id, sequence, timestamp, author, channel, audience[], visibility, type, content, commitments[], derived_from[]`.
- **World state:** entities (characters, objects) with positions, conditions, resources; the scene/zone graph and terrain; clocks and fronts. Spatial representation per FABLE's native abstraction (range bands vs. grid — see Open Decisions).
- **Character sheet:** FABLE stats, current stance, resources/economy state. Mechanical truth, owned by the core.
- **Canon ledger:** the immutable set of revealed, committed facts. May be implemented as a view over committed+disclosed events, but is conceptually a distinct, protected boundary.
- **Belief store (derived):** per-agent projection over the event log; cached, never authoritative.
- **Action queue (transient):** the blackboard's pending-proposal buffer; non-authoritative and drained each beat. Distinct from the event log — a proposal becomes an event only on commit, so it never enters a belief projection while still a candidate.
- **Disposition graph:** directed edges `A→B` with axis values, each delta linked to its causal event id.
- **Plot graph:** fronts, clocks, hooks, secrets, hidden nodes with preconditions; function nodes and their current fixture bindings; an interest-signal accumulator. Hidden from all player/TM audiences.
- **Persona spec:** per character agent — voice, values, public goals, hidden agenda.
- **Perception / scene state:** presence, line of sight, audibility, lighting, positioning; the inputs to perception checks.

---

## 9. Worked scenarios (behavioral spec)

These are acceptance examples — the system is correct when it behaves this way.

**A. Player whispers to a teammate (GM aware; no one else).** Event logs with `audience = [player, teammate, GM], visibility = content`. The context filter includes it for the teammate and GM, excludes it from all other teammates and the NPC-manager — it never enters their prompts. The teammate now acts on private knowledge; when it later acts on that knowledge, others witness the action but not its cause. The perception model still runs: positioning may yield a `may-have-overheard` event in tight quarters. This case is impossible single-model and trivial here.

**B. "How far am I from the tower?"** If the distance is already committed, the GM *reads* it from world state and only narrates it. If it is not yet established, the GM *authors* it by fiat ("call it a hundred feet"), which commits the fact; from then on it is binding. Either way the answer is consistent with what the engine will enforce when the player moves. The query also emits an interest signal to the plot-manager. (Decide: free OOC read vs. in-character assessment; whether unexplored map distances are themselves fogged.)

**C. "I jump up and down."** The stakes gate returns *no stakes* → no dice, no rules-engine resolution; the action lands in the fiction. But stakes-free is not effect-free: the engine updates posture/noise/conspicuousness, runs perception checks (a guard may notice; stealth may break), and may emit small event-derived disposition nudges. Present witnesses' views update; the orchestrator may grant a teammate the spotlight to react — emergent banter from the same machinery, not a special case.

**D. Player does something contrary to the GM's plan.** The engine resolves it normally; the world reflects what actually happened (the quest-giver is dead). The plot-manager detects divergence and reconciles by re-binding the function to a new fixture, or promotes the unplanned thread the players are pulling toward — editing only the hidden graph, never the canon ledger. The player experiences seamless responsiveness and never sees the revision.

---

## 10. Build roadmap

Ordered so that each phase rests on a foundation the previous phase laid. The ordering is itself a design claim: honesty and consistency are impossible until the deterministic core exists, so it comes first.

1. **Deterministic core + event log.** World state, rules engine (FABLE mechanics), dice service, append-only event log with the `audience`/`visibility` schema. Nothing downstream can be honest until this exists.
2. **Access model + fact-extraction/commit.** Audience tagging, the commit pipeline, the canon ledger, and the consistency-check. This is the spine of differential information and non-contradiction.
3. **Perception model.** Presence/LOS/audibility, feeding audience computation. The load-bearing wall — prototype it early and stress it hard.
4. **Context assembly.** Per-POV view construction (belief-store projections). Fog of war becomes real here.
5. **Cold/warm GM.** The minimal playable GM: adjudicator (with stakes gate) + narrator, plus the world-simulator. First playable loop.
6. **Character agents.** Teammates with personas, goals, and belief stores. Differential teammate behavior appears here.
7. **Orchestrator / spotlight.** Multi-party turn flow: initiative for combat, spotlight/bidding for social scenes; TTS turn-gating.
8. **Auditor.** Live validation gates against the now-rich committed state.
9. **Plot-manager.** Function/fixture re-binding, hidden-graph revision, interest signals.
10. **Disposition system.** Multi-axis graph, event-derived deltas, Strings coupling (EV-audited).
11. **Interface and voice polish.** Per-character channels, whisper/OOC, TTS, render.

The two phases most responsible for how *lifelike* the result feels — and least likely to exist already — are **3 (perception-gated belief store)** and **5 (cold/warm GM split)**. Weight effort there.

---

## 11. Open design decisions

These are tracked as a living log in `DECISIONS.md` (open and resolved, each with options, recommendation, rationale, and date). `DECISIONS.md` is authoritative for their status; the list below is only a CORE-side index of what is currently unresolved:

- Belief store: read-time projection vs. write-time materialization.
- Spatial model: abstract range bands vs. coordinates/grid.
- Positioning queries: free OOC read vs. in-character assessment; map fog-of-war or not.
- Disposition→mechanics coupling: passive modifier vs. Strings.
- Spotlight: director-picks-next vs. agent-bidding/raise-hand.
- NPC management: GM puppets minor NPCs ad hoc vs. dedicated NPC-manager agent.
- Fact-extraction: post-hoc extraction pass vs. GM-emitted structured commitment block.
- Override authority: who may invoke it, and how it is surfaced and logged.
- Canon ledger: separate store vs. a view over committed-and-disclosed events.
- Disposition-delta recognition: deterministic rule table vs. model-proposed deltas (the disposition engine is the authoritative writer either way).

See `DECISIONS.md` for the reasoning and any resolutions.

---

## 12. Non-goals and scope boundaries

- Not a general-purpose chatbot or open-ended story generator; it facilitates *FABLE play*.
- Not a fully unauthored sandbox; it runs prepared fronts/plot, improvised around, not invented from nothing each beat.
- Not an attempt to fully replace a human GM's taste; it aims to facilitate convincingly, with override hatches for human judgment.
- No graphics/VTT scope in v1; text + per-character voice.
- Initial scope is one human player; multi-human is a later extension the architecture must not preclude.

---

## 13. Success criteria

The system is working when these hold, each operationally testable by transcript/state inspection:

- **Secret-keeping:** a fact shared on a whisper channel never appears in a non-audience agent's context or output (verify by probing those agents).
- **Spatial/causal consistency:** no agent interacts with an object across a committed distance without a logged traversal; the auditor produces no false negatives on these.
- **No over-rolling:** stakes-free actions resolve without dice, verified by a roll-appropriateness audit.
- **Invisible improvisation:** plot revisions never contradict the canon ledger, and a re-binding is not detectable from the player-visible transcript.
- **Differential believability:** teammates demonstrably act on private knowledge, and their public actions are explicable-in-hindsight but not pre-explained to non-audience parties.
- **Responsiveness:** routine beats resolve within the chosen wall-clock and token budget.

---

## Appendix: relationship to existing implementation

The FABLE ruleset (fronts/clocks and the Long Game, Stances, the Trade/Ledger economy, EV-audited combat) instantiates the **rules engine** slot. Existing code — a FastAPI + SQLite + React/TypeScript engine, and a Python playtest harness with director-pattern turn routing (`[SPOTLIGHT:]` tagging) and per-character TTS — is the implementation substrate. This blueprint is the target those iterate *toward*; where current behavior conflicts with it, the blueprint is the authority unless consciously revised.
