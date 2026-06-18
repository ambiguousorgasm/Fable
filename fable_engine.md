# FABLE — Engine Schema (v4)

*The irreducible mechanical specification, fused with the design philosophy it enforces. Every surface has one job; every promise has a mechanical enforcement point. Examples, teaching, and calibration live in the Starter Kit — this document is the spec.*

---

## 0. Design Claim

FABLE models **capable people changing dangerous situations in a causal world under pressure.** The drama comes from cost, uncertainty, consequence, and world motion — never from incompetence or random failure. One act is at once a **strategic move** and an **act of character.**

The engine cares about six things: **Intent** (what someone tries to make true), **Uncertainty** (whether dice are still needed), **Cost** (what sour outcomes demand), **Effect** (how much success changes), **Truth** (what persists), and **Time** (what advances while people act).

> **Central thesis.** Preparation changes the *shape* of risk, not its existence. It can remove **reducible** uncertainty, but never **irreducible** uncertainty unless the fiction removes that uncertainty's source.

> **Interiority.** Dice change circumstances, costs, pressures, relationships, reputations, wounds, and facts. Dice never decide what a player character feels, believes, wants, or becomes inside.

---

## 1. Promises & Enforcement

Every philosophical promise has a mechanical enforcement point; every surface exists to keep a promise. A rule that serves no promise is rejected; a promise with no enforcement is unfinished.

| Promise | Enforced by | Failure mode it prevents |
|---|---|---|
| Strategy matters | Ledger · Truths · Preparation · Top Exit | cleverness paying only at GM whim |
| Strategy is not deterministic | Exit Check · Simple/Complex obstacles · Clocks · Fronts | the scene solved before it begins |
| Competence is reliable | the 3d6 curve · no roll produces nothing | drama-by-whiffing |
| Danger is not difficulty | the TN / Exposure split | inflating TN to express threat |
| Tension survives competence | Exposure · Effect limits · Clocks · Fronts · Seams | a tensionless clean-success treadmill |
| Consequences persist | Truths · Scars · clocks landing Truths | a world that forgets |
| Drama is mechanical, not bait | Drive · Question · Bonds · compels · Edge | roleplay-for-XP |
| The interior is sovereign | Held Truths · the interiority invariant | dice dictating feelings |
| Time is the spine | Clocks · preparation costs time · world motion · maintained Truths | pressure that never moves; advantages that never erode |
| One engine, no bloat | the Mode rule · the surface test | subsystem growth |

---

## 2. Mechanical Surfaces

Each surface has exactly one job.

| Surface | Term | Job |
|---|---|---|
| Task difficulty | **TN** | how hard the task is to perform |
| Consequence severity | **Exposure** | how bad sour results are |
| Amount achieved | **Effect** | how much success accomplishes |
| Risk/effect swap | **Trade** | a voluntary pre-roll exchange of Exposure for Effect |
| Advantage conversion | **Ledger** | turns fictional advantage into stakes or permission |
| No-roll impossibility | **Bottom Exit** | the approach cannot work |
| No-roll certainty | **Top Exit** | no live uncertainty remains |
| Persistent reality | **Truth** | something true until changed |
| Time pressure | **Clock** | a countdown toward a Truth |
| World pressure | **Front** | an active force that owns clocks |
| Personal resource | **Edge** | a capped resource for pressing advantage |
| Short-term pressure | **Stress** | recoverable pressure and harm |
| Lasting consequence | **Scar** | persistent harm, mark, or loss |

> **Invariant.** No rule may use one surface to do another surface's job.

---

## 3. Core Loop

```text
Intent → Situation → Ledger → Exit Check → Roll → Record → World Responds
```

1. **Intent** — state what the acting character wants to make true.
2. **Situation** — establish position, known Truths, active clocks, opposition, tools, and stakes.
3. **Ledger** — claimed advantages convert to Position, Leverage, Access, or Seam.
4. **Exit Check** — decide Bottom Exit, Top Exit, or Live Roll.
5. **Roll** — if uncertainty remains, roll 3d6 + Skill vs TN.
6. **Record** — write Stress, Scars, Truths, clock ticks, and changed circumstances.
7. **World Responds** — Fronts and consequences advance through costs, setbacks, clocks, and Truths.

---

## 4. Characters & Skills

A character is: **Concept · Skills · Traits · Bonds · Drive · Question · Gear · Stress · Scars · Edge.**

Skills are rated **0–4**: 0 untrained · 1 capable · 2 professional · 3 expert · 4 master. At creation, spend **12 points**, maximum **3** in any skill. There are no attributes beneath skills; the skill follows the fictional approach.

> **Untrained.** Using Skill 0 for professional work or harder raises **Exposure by 1**. The task is no harder; the character is less protected from consequence.

---

## 5. The Roll

Roll only when the intent matters, the outcome is genuinely uncertain, the approach is possible, and the result would change the situation.

```text
Roll = 3d6 + Skill      Margin = Roll − TN
```

| Margin | Result | Meaning |
|---|---|---|
| **+3 or more** | **Triumph** | intent succeeds; Effect steps up once; gain 1 Edge |
| **0 to +2** | **Success** | intent succeeds cleanly at stated Effect |
| **−1 to −2** | **Cost** | intent succeeds at stated Effect, and a cost lands at stated Exposure |
| **−3 or less** | **Setback** | intent does not land, and the situation turns against the actor at stated Exposure |

No roll produces "nothing happens."

> **The Anchor.** Before adjusting, assume **TN 10 · Exposure 1 · Effect Standard**. Change only what the fiction makes different.

> **No empty rolls.** Because success is reliable, the engine supplies no tension through failure. A roll with **no live clock and no meaningful Exposure** changes nothing worth rolling — resolve it as a **Top Exit**. Tension lives in cost, time, and consequence; if none is at stake, do not roll.

> **No post-roll renegotiation.** TN, Exposure, Effect, Skill, and stakes are fixed before the roll.

---

## 6. TN

TN measures the task, not the danger.

| TN | Task |
|---|---|
| **8** | simple trained work |
| **10** | standard professional work |
| **12** | genuinely challenging work |
| **13** | hard specialist work |
| **14** | extreme, reputation-making work |

**Contested TN = 10 + opposing Skill**, used when a capable opponent actively contests the intent.

> **Invariant.** Danger never increases TN. Danger changes Exposure.

---

## 7. Exposure

Exposure measures the severity of sour results (range 0–2; modules may add higher tiers).

| Exposure | Cost | Setback |
|---|---|---|
| **0** | minor, recoverable | the chance slips; no direct Scar; a retry raises Exposure |
| **1** | real | serious escalation or harm |
| **2** | severe | severe turn; a Scar only via a live Seam or Stress overflow |

**Cost registers** — when a Cost or Setback lands, pick the one the fiction supports:

| Register | Meaning |
|---|---|
| **Harm** | mark Stress |
| **Time** | tick a Clock |
| **Ground** | lose footing, distance, control, access, cover, or tempo |
| **Trace** | leave evidence, witnesses, suspicion, or attention |
| **Resource** | spend, damage, or lose gear or supply |
| **Relational** | strain a bond, favor, reputation, trust, or obligation |

**Harm guideline:** Exposure 0 → 1 Stress · Exposure 1 → 2–3 Stress · Exposure 2 → 4–5 Stress, or a Scar via a live Seam or overflow.

---

## 8. Effect

Effect measures how much success accomplishes.

| Effect | Delivers |
|---|---|
| **Limited** | part of the intent: narrower, weaker, slower, conditional, or needing another step |
| **Standard** | the intent as stated |
| **Great** | the intent plus reach: faster, quieter, broader, cleaner, more durable |
| **Spectacular** | beyond normal scope; only from a Triumph when Effect was already Great |

Effect cannot drop below Limited. Declared Effect caps at Great; Spectacular is Triumph overflow.

---

## 9. Trade

Before rolling, the actor may choose one Trade.

| Trade | Effect | Exposure |
|---|---|---|
| **Aggressive** | +1 step | +1 |
| **Measured** | — | — |
| **Guarded** | −1 step | −1 |

Both sides must land: Aggressive is unavailable if Exposure can't worsen; Guarded if Effect would fall below Limited. Trade never changes TN and is locked before the roll.

---

## 10. Ledger

The Ledger converts fictional advantage into mechanical permission or stakes.

| Category | Advantage makes you… | It pays |
|---|---|---|
| **Position** | safer | reduce Exposure by 1 |
| **Leverage** | stronger | increase Effect by 1 |
| **Access** | able | a Bottom Exit becomes a Live Roll |
| **Seam** | able to end it | terminal consequence becomes possible |

**Rules.** One source pays one category per roll; one roll claims one primary payout unless a rule says otherwise. The Ledger never changes TN and never creates Top Exit. Information *reveals* opportunities; action *claims* them. Baseline fiction is not a payout — a source must be created, seized, timed, earned, or established to pay.

---

## 11. Exit Check

Before rolling, decide whether dice exist.

| State | Meaning | Result |
|---|---|---|
| **Bottom Exit** | the approach cannot work | no roll; change approach or find Access |
| **Top Exit** | no live uncertainty remains | no roll; narrate and move on |
| **Live Roll** | uncertainty matters | roll |

**Simple obstacles** hold only known, reducible uncertainty; removing it in the fiction reaches Top Exit. **Complex obstacles** hold irreducible uncertainty — hidden information, chance, adaptive opposition, or volatility — and cannot reach Top Exit until that source is removed or neutralized in the fiction.

> **Learning.** If the intent is to discover the unknown, the unknown *is* the live uncertainty. Learning rolls never reach Top Exit unless the answer is already known. Preparation can make learning safer, narrower, or stronger — never certain.

> **No-stakes obstacles are Top Exits.** An obstacle with no irreducible uncertainty *and* no live clock or Exposure is solved — narrate it. (See §5, No empty rolls.)

---

## 12. Truth

A Truth is a persistent fact of the game world — world state, location, relationship, reputation, injury, debt, promise, resource, belief, faction state, condition, or status. Truths persist until changed by play and are not consumed by use.

| Type | Authorship | Use |
|---|---|---|
| **Fact** | Open | a world truth anyone may claim |
| **Bond** | Held | a relationship, belief, duty, reputation, Drive, or Question belonging to a character |
| **Trait** | Held, charged | a double-edged self-truth invoked through Edge |
| **Scar** | Open, about a character | lasting Wound, Mark, or Loss |

A Truth informs the **baseline** of every action it touches, but pays a **Ledger** step only where it *changes* that baseline. Open Truths may be claimed by anyone; Held Truths may be pressured or compelled by the world, but only the owning player may rewrite them.

**Standing and maintained.** Most Truths are **standing**: they persist until changed by play. Some are **maintained**: true *now*, but the kind of thing the world erodes — suppression, a distraction, a held door, a sustained effect, a cover that is holding, ground seized but not secured. A maintained Truth **lapses on the next world-motion unless renewed**; when something actively works to undo it, give it a **recovery clock** (§16) the opposition ticks toward its end. A maintained Truth informs baseline and pays the Ledger **only while it lasts** — which is what makes setup-and-exploit a race rather than a guarantee.

> **Interiority.** Dice may pressure a character's situation, relationships, resources, reputation, or body. Dice never rewrite a player character's inner beliefs or feelings.

---

## 13. Edge

Edge is a capped personal resource. **Cap = 3.**

**Gain 1 Edge** when you:
- roll a **Triumph**;
- **accept a compel** (the world's complication on one of your Truths — *reactive* expression); or
- **act on a Drive, Question, Bond, or Held Truth at a real cost** to your position, safety, resources, relationship, or opportunity (*proactive* expression).

The cost gates the proactive trigger: you cannot gain Edge by expression alone, only by paying for it. (See §23, expression invariant.)

**Spend Edge:**

| Spend | Cost | Timing | Effect |
|---|---|---|---|
| **Lean** | 1 | before roll | invoke a relevant Trait/Bond/Truth: reduce Exposure by 1 |
| **Lean** | 1 | after roll | invoke a relevant Trait/Bond/Truth: step the result up one band |
| **Push** | 1 + 2 Stress | after roll | step the result up one band with no relevant Truth |
| **Shield** | 1 | when an ally takes Harm | take the incoming Stress or Scar route yourself, if fiction allows |

**Rules.** A roll may be stepped up **at most once** by Edge. Edge never changes TN and never creates Top Exit. A band reached by spending Edge generates no Edge. A spend that would do nothing is not spent. Pre-roll Lean cannot reduce Exposure below 0.

> **Invariant.** Edge moves results in band-space (Setback → Cost → Success → Triumph), never by modifying the die total. It is the only resource that may improve a result after the roll, and it cannot snowball.

---

## 14. Stress & Scars

**Stress** is short-term pressure of any kind — injury, exhaustion, fear, social pressure, backlash, overextension. **Track = 6 boxes.** A genuine breather clears Stress (and ticks every Clock whose domain the character remains inside).

> Stress is pressure *toward a breaking point*. Its mechanical result is always **external or situational** — a Mark, a forced exit, a lost position. The player narrates what it feels like inside.

**Scars** are lasting Truths about a character. **Slots = 3.** At 3 Scars the character is **Broken**: out of the scene in a way fiction and tone define.

| Scar | Meaning |
|---|---|
| **Wound** | lasting bodily harm |
| **Mark** | lasting reputational, legal, social, or psychological pressure made external |
| **Loss** | lasting loss of gear, ally, tie, office, standing, or access |

Scars are **situational** — never a global penalty. A Scar bites where relevant: worse Exposure, reduced Effect, a compelled Truth, a Seam for others, Access blocked or opened, or a clock trigger.

> **Scar Route Invariant.** A Scar lands only through **Stress overflow** or **a live Seam exploited by a terminal consequence**. There is no third route. On overflow: take exactly **1 Scar**, then clear Stress. No single event cascades into multiple Scars unless a module allows it.

---

## 15. Seam & Terminal Consequence

A **Seam** is an established vulnerability that makes a lasting, decisive, or terminal consequence possible. A Seam does not grant success; it changes what success can *accomplish*.

| Intent | Meaning | Examples |
|---|---|---|
| **Situational** | changes circumstances | disarm, delay, expose, get past, separate, corner, reveal |
| **Terminal** | attempts lasting resolution | kill, cripple, ruin, depose, destroy, permanently expose, end |

> A terminal intent against a significant target requires a **live Seam**. Without one, a successful terminal intent resolves as situational: deal Stress, create a Truth, improve position, expose a future Seam, tick a defeat clock, or reduce options.

A Seam may be **created, discovered, seized, or exploited**, and may come from a prior Truth, a Scar, surprise, isolation, a named weakness, a debt, a legal vulnerability, a ritual anchor, a true name, a broken formation, or a clock reaching a threshold.

---

## 16. Clocks

A Clock tracks pressure accumulating toward a Truth.

| Size | Use |
|---|---|
| **4** | immediate pressure |
| **6** | a staged threat or project |
| **8** | slow, campaign-scale pressure |

When a Clock fills, a Truth lands. Clocks tick when a Cost or Setback advances them, a loud action draws attention, a Front moves, characters take a breather or complete a Prep Round inside the domain, or an active threat is ignored in conflict — and as **time passes, but only when the domain's time meaningfully advances** (not every scene ticks every clock).

A **recovery clock** is the opposition's countdown toward undoing a **maintained Truth** (§12); when it fills, that Truth lapses. Use one only when something actively works to undo the Truth — otherwise a maintained Truth simply lapses on the next world-motion.

> **Clock rule.** A clock must have a named trigger and a named landing Truth. Keep no more than three important clocks in focus at once.

---

## 17. Fronts

A Front is an active source of pressure: **Name · Agenda · Standing Truth · Clock(s) · Levers · Seams · what it does if ignored · the Truth that lands when its clock fills.**

Fronts take no separate turns. They act through costs, setbacks, clock ticks, filled-clock Truths, compels, new opposition, and changed baselines.

> In beat-by-beat conflict, after each full crew exchange, tick each active unaddressed pressure clock once — unless the crew spent action to stop, delay, redirect, or absorb it.

---

## 18. Preparation

Preparation happens in **Prep Rounds**. During a Prep Round each character takes one prep action — creating Truths, revealing clock states, establishing Access, creating Position or Leverage, discovering Seams, or reducing uncertainty — and at the round's end the relevant Front or mission Clock ticks once.

Information gained in prep *reveals* Ledger opportunities; it pays only once acted on or established as a Truth. Preparation reaches Top Exit only by removing all live uncertainty from a **Simple** obstacle; a **Complex** obstacle needs its source of complexity removed first.

---

## 19. Opposition

| Class | Handling |
|---|---|
| **Obstacle** | resolved by TN, Exposure, Effect, Truths, and clocks |
| **Minor opponent** | no Scar track; situational success may remove, bypass, or rout it if fiction supports |
| **Significant opponent** | has Stress, a clock, Scar capacity, or Front structure; terminal removal requires a Seam |
| **Front** | acts through clocks, Truths, costs, and world motion |

Opposition does not roll separately by default: a single player roll resolves the actor's intent and the opposition's immediate response. A significant opponent may be **worn down by a clock that, when filled, lands a Truth** — a blocked Access or a live Seam — rather than by depleting a health total. (Significant opposition is noted as: Skill · Exposure baseline · any Stress/clock/Scar capacity · Seam(s) · goal · what it does if ignored.)

---

## 20. Volatile

**Volatile** is a tag for unstable power — magic, experimental tech, psychic force, dangerous rituals, hazardous energies. Volatile actions have **minimum Exposure 1** and **cannot reach Top Exit** unless the volatility is removed from the fiction. Their consequences take this overlay:

| Result | Overlay |
|---|---|
| **Triumph** | succeeds with stepped-up Effect, but a tell, omen, or instability appears |
| **Success** | succeeds, but leaves a minor tell or unstable residue |
| **Cost** | succeeds; treat the Cost one Exposure tier higher — **at Exposure 2, route the excess to a Scar via overflow or a live Seam instead** |
| **Setback** | the situation turns hard; if a Seam is live, a Scar or major Truth may land |

Define a Volatile power by **Source · Domain · Method · Cost · Limit · Tell**, never a fixed list.

---

## 21. Advancement

Mechanical growth comes only from **causal accomplishment** — things that happen through play, never from declared roleplay. Mark an advance when:

- you reach a **Top Exit** on a significant obstacle;
- a **Truth you authored is cashed by another character**;
- a **compel genuinely costs you** something;
- a **Held Truth changes** through play;
- a **Scar reshapes** how you play;
- a **significant Front or Clock resolves** through your action.

Spend marks for **+1 Skill** (cap 4; mastery 3→4 also requires a breakthrough written as a Truth) or a **new Trait or Bond.**

> **Table-conferred moments.** At session's end, players name *each other's* standout moments; a conferred moment **deepens a Bond or evolves a Question** — never mechanical power.

---

## 22. Modes

A Mode is not a subsystem. It is a configuration of the same primitives — Roll, Ledger, Truth, Clock, Stress, Scar, Edge, Front — for a kind of conflict.

> **A Mode changes what the engine looks at, not what the engine is.**

| Mode | Primary pressure |
|---|---|
| **Combat** | Harm, ground, tempo, morale, Scars |
| **Intrigue** | Trace, reputation, leverage, access, Marks |
| **Investigation** | questions, clues, hidden Truths, time, false leads |
| **Exploration** | time, resource, hazard, route, environment |
| **Politics** | Fronts, legitimacy, coalition, public Truths |
| **Magic** | volatile power, cost, backlash, transformation |

> **Mode rule.** If a Mode seems to need a new core mechanic, first express it as TN, Exposure, Effect, Ledger, Truth, Clock, Stress, Scar, Edge, or Front. If it still needs a new resolution engine, reject it as subsystem growth.

---

## 23. Invariants

These define the engine. A rule that violates one is rejected.

1. TN measures task difficulty only.
2. Exposure measures consequence severity only.
3. Effect measures amount accomplished only.
4. The Ledger never changes TN.
5. Edge never creates Top Exit, and moves results only in band-space, never by die-total.
6. Top Exit is earned by fiction, never bought.
7. Bottom Exit is overcome by Access or a changed approach.
8. A Seam is required for terminal consequence against significant targets.
9. Scars land only by Stress overflow or Seam-enabled terminal consequence.
10. Truths persist until changed — standing Truths until play changes them, maintained Truths until world-motion erodes them; they inform baseline everywhere but pay Ledger only where they change baseline.
11. No roll produces nothing — and where nothing is at stake, there is no roll.
12. No post-roll renegotiation.
13. Dice never author player-character interiority.
14. Opposition acts through consequences, clocks, and Truths unless a module adds opposed rolling.
15. Preparation costs time.
16. Competence is reliable success; tension comes from Exposure, Effect limits, Clocks, Fronts, Seams, and world motion — never from whiffing.
17. Expression refreshes Edge; it never advances mechanical power. Advancement comes only from causal accomplishment.
18. Every mechanic must route through the core surfaces or be rejected as subsystem growth.

---

## 24. Engine at a Glance

```text
A character states an Intent.

Establish:    TN = task difficulty   Exposure = severity   Effect = amount
              (default TN 10 · Exposure 1 · Effect Standard)

Claim one Ledger payout from a real fictional advantage:
   Position → −1 Exposure
   Leverage → +1 Effect
   Access   → Bottom Exit becomes a Live Roll
   Seam     → terminal consequence becomes possible

Exit Check:   Bottom Exit → no roll, find Access.
              Top Exit    → no roll, narrate.   (Simple only; Complex keeps the roll;
                            no live clock or Exposure → also a Top Exit)
              Otherwise    → roll 3d6 + Skill vs TN:
                 Triumph (+3↑): intent + Effect step + 1 Edge
                 Success (0..+2): intent
                 Cost   (−1/−2): intent + a cost at Exposure
                 Setback (−3↓): intent fails + the situation worsens at Exposure

Record:       lasting change → Truth (standing, or maintained and eroding on world-motion).
              accumulating pressure → Clock.   short-term pressure → Stress.
              overflow or live Seam → one Scar.
Edge:         gain on Triumph, compel, or costly expression of a Truth;
              spend to step a result up one band (≤ once/roll); never touches dice or TN.
Advance:      only on causal accomplishment. Expression buys agency, never power.
World:        Fronts advance when ignored, triggered, or clocked;
              maintained advantages lapse unless renewed.
Return to the next live Intent.
```
