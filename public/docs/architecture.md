# Architecture

## Core principle

**Code owns truth; models own voice.**

Dice rolls, rules resolution, world state mutations, audience computation, fact commits, and the event log are all deterministic Python. Language models produce narration, proposals, and judgment under ambiguity — but they never decide outcomes directly and never see information they are not entitled to.

---

## Event log

The `EventLog` is append-only. Every action, dice roll, adjudication, committed fact, and narration becomes an event with a stable `id`, monotone `sequence`, and an `audience` tuple that names every entity entitled to see it.

World state, belief stores, and the canon ledger are **derived views** over the log — not separate authoritative stores. The log is the source of truth.

Each event carries:

| Field | Description |
|---|---|
| `id` | UUID |
| `sequence` | Global append order |
| `timestamp` | UTC ISO-8601 |
| `author` | Who emitted this event |
| `channel` | `public`, `whisper`, `ooc`, `dice`, or `system` |
| `audience` | Tuple of entity IDs entitled to see this event |
| `visibility` | `content` or `metadata` per audience member |
| `commitments` | Structured facts committed by this event |
| `roll_visibility` | `table`, `roller_only`, `gm_only`, or `revealed` (dice events) |

---

## Differential knowledge

`EventLog.project_for(entity_id)` returns only the events that entity is entitled to see, with a contiguous per-POV index (so two agents cannot infer each other's sequence counts from gaps).

`ContextAssembler.belief_store(entity_id)` builds a `BeliefStore` from each entity's projection:

- `beliefs` — confirmed facts (`epistemic_type="fact"`) the entity has seen
- `claims` — attributed assertions (`epistemic_type="claim"`)
- `observations` — perceptual evidence (`epistemic_type="observation"`)
- `theories` — inferences and suspicions (`epistemic_type="theory"`)

`BeliefStore` is a snapshot, never an authoritative writer.

---

## Beat loop

A "beat" is one action by one actor (`BeatRunner.run(actor_id, intent_text)`):

```
1.  Parse/receive Proposal (human text or AI proposal)
2.  Validate action (auditor pre-check)
3.  Adjudicator GM (cold) — decides stakes, TN, skill, exposure, effect tier,
    consequence palette, declared facts
4.  If has_stakes:
      DiceService.roll() → dice_roll event + resolution event (band)
5.  Effects applied via EffectExecutor (typed effects)
6.  Fact commits via CommitPipeline (canon-contradiction check)
7.  Narrator GM (warm) — produces prose from the player's filtered context;
    never receives dice values or hidden state
8.  Auditor post-narration check
9.  Narration logged; clocks advanced; beat committed atomically
```

Steps 5–9 run inside a single SQLite transaction. A post-narration audit block rolls back all fact commits and effects from that beat.

---

## GM split

The GM is two separate model calls with separate prompts and separate context views:

**Adjudicator (cold)** — evaluates the player's action using a structured tool call. Outputs: `has_stakes`, `skill`, `tn`, `exposure`, `effect`, `consequence_palette`, `declared_facts`. Never produces player-facing prose.

**Narrator (warm)** — receives the player's filtered event history and writes prose. Never receives dice values, raw adjudicator output, or `gm_only` roll results.

This split is structural: the narrator cannot reveal hidden information because it never receives it.

---

## Rules engine and dice

`RulesEngine.resolve_check(skill, tn, ...)` rolls 3d6 + skill vs TN via `DiceService`, then maps the margin to a band:

| Band | Margin |
|---|---|
| Triumph | ≥ +3 |
| Success | 0 to +2 |
| Cost | −1 to −2 |
| Setback | ≤ −3 |

The adjudicator supplies the consequence palette for each band. On a Cost or Setback outcome, `EffectExecutor` applies the matching palette effects inside the beat transaction.

---

## Typed effects

`EffectExecutor` applies typed, validated effects to world state:

| Effect | Action |
|---|---|
| `CreateTruth` | Add a standing truth to world state |
| `ChangeTruth` | Modify an existing truth |
| `ExpireTruth` | Remove a standing truth |
| `CreateMaintainedTruth` | Add a truth that lapses unless renewed |
| `ExpireMaintainedTruth` | Remove a maintained truth |
| `AdvanceClock` | Tick a named clock; fires `front_advance` on fill |
| `ApplyStress` | Add stress to an entity (cap: 6; overflow → Scar) |
| `ApplyScar` | Add a scar to an entity (cap: 3; at cap → `character_broken`) |
| `GainEdge` / `SpendEdge` | Adjust Edge currency (cap: 3) |
| `MoveEntity` | Move an entity between zones |
| `ChangeResource` | Modify an arbitrary resource key on an entity |
| `ChangeAccess` | Modify access rights |

Effects that fail validation log an `audit_advisory` event and do not abort the beat.

---

## Commit pipeline

`CommitPipeline.commit(subject, predicate, value, ...)` validates proposed facts against the canon ledger before they become truth. Rules:

- A second commit to the same `(subject, predicate)` with a different `value` raises `CanonConflictError`.
- Override requires `override=True` + `reason=` (logged, auditor-visible).
- All commits are reflected in `canon_ledger()` — a pure fold over the event log; no separate store.

---

## Character agents

`CharacterAgent.propose(assembler, ...)` builds each agent's belief store from its own entitled projection, then calls the model with a `propose_action` tool schema. The model sees only what that character knows. Hidden goals and persona live in the agent's system prompt only.

The orchestrator (`Orchestrator`, `SceneCadence`) decides which agents are activated each round and in what order, based on spotlight priority (least-recently-acted).

---

## Persistence and sessions

`open_session(db_path)` returns `(EventLog, WorldState, Scene)`. Everything shares a single SQLite connection and `_tx_active` flag, so beat-level atomicity covers the event log, world state, scene, plot graph, and disposition graph simultaneously.

`SessionManager` handles create/list/resume with `SessionManifest` metadata. Schema version is checked on open; `_MIGRATION_REGISTRY` walks old sessions forward automatically.

---

## Provider gateway

`ModelGateway` is the single model-call seam. All calls go through it; `TelemetrySink` records cost, latency, and tokens per call. Telemetry never enters the event log (the two are structurally isolated).

Per-role model routing: `SettingsManager` resolves which model each role uses at call time. `ProviderAdapter` (currently `AnthropicAdapter`) wraps the SDK and handles tool-call retries.

---

## Lorebook

`LoreAssembler` injects audience-gated background entries into model prompts. Audience gate fires **before** keyword matching: `gm_only` entries never reach player or character-agent prompts regardless of what keywords appear in the corpus.

---

## Auditor

`Auditor` runs two hooks per beat:

1. **Pre-commit** — structural contradiction check against the canon ledger before facts are committed.
2. **Post-narration** — optional model-assisted semantic check; escalates to `CRITICAL` only at high confidence + revealed canon + no logged transition or override.

Audit events carry `audience=(gm,)` only. A `CRITICAL` flag aborts the beat and rolls back the transaction.
