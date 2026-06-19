"""Plot manager — runtime guardian of the campaign's narrative structure (phase 9).

Sole authoritative writer of the PlotGraph (D-016). Other agents may propose
changes; nothing writes the graph directly except this class.

Responsibilities:
  - Detect fixture entities that are destroyed or blocked in the current canon
  - Propose re-bindings to available alternatives; emit `plot_revision` events
  - Handle clock-fired events by logging front consequences
  - Accumulate interest signals and surface promotion candidates
  - Provide a GM-facing summary of active hooks and pressing fronts

All events emitted here carry `audience=(gm_entity, plot_manager_entity)` so
they never reach player or TM belief projections (CORE §2, principle 1).
"""

from __future__ import annotations

from dataclasses import dataclass

from .plot_graph import FixtureBinding, Front, Hook, PlotGraph


# --------------------------------------------------------------------------- #
# Constants                                                                     #
# --------------------------------------------------------------------------- #

_BLOCKING_CONDITIONS = frozenset(
    {"destroyed", "captured", "dead", "unavailable", "eliminated"}
)


# --------------------------------------------------------------------------- #
# FixtureIssue                                                                  #
# --------------------------------------------------------------------------- #

@dataclass
class FixtureIssue:
    """A hook whose current fixture is blocked in the world state."""

    hook: Hook
    reason: str  # "fixture_blocked" | "precondition_failed"


# --------------------------------------------------------------------------- #
# PlotManager                                                                   #
# --------------------------------------------------------------------------- #

class PlotManager:
    """Runtime plot-graph guardian.

    Construct once per session from the campaign's PlotGraph, the CommitPipeline
    (for canon queries), and the event log. The log reference is the same log
    passed to BeatRunner — plot_revision events land in the shared append-only
    history.

    Workflow::

        pm = PlotManager(graph, pipeline, log)
        issues = pm.check_fixture_health()
        for issue in issues:
            proposed = pm.propose_rebinding(issue)
            if proposed is not None:
                pm.accept_rebinding(issue.hook, proposed)

    `post_beat` is a convenience wrapper that does all three steps and handles
    any clock-fired consequences.
    """

    def __init__(
        self,
        plot_graph: PlotGraph,
        pipeline,
        log,
        gm_entity: str = "gm",
        plot_manager_entity: str = "plot_manager",
    ) -> None:
        self._graph = plot_graph
        self._pipeline = pipeline
        self._log = log
        self._gm = gm_entity
        self._pm = plot_manager_entity

    # ------------------------------------------------------------------ #
    # Internal helpers                                                      #
    # ------------------------------------------------------------------ #

    def _is_fixture_blocked(self, entity_id: str, canon: dict) -> bool:
        cond = canon.get((entity_id, "condition"))
        if cond is not None and cond.value in _BLOCKING_CONDITIONS:
            return True
        avail = canon.get((entity_id, "available"))
        if avail is not None and not avail.value:
            return True
        return False

    def _pm_audience(self) -> tuple[str, str]:
        return (self._gm, self._pm)

    # ------------------------------------------------------------------ #
    # Fixture health                                                        #
    # ------------------------------------------------------------------ #

    def check_fixture_health(self) -> list[FixtureIssue]:
        """Return all active hooks whose current fixture is blocked in canon."""
        canon = self._pipeline.canon_ledger()
        issues: list[FixtureIssue] = []
        for hook in self._graph.hooks:
            if not hook.active:
                continue
            if self._is_fixture_blocked(hook.binding.fixture_entity_id, canon):
                issues.append(FixtureIssue(hook=hook, reason="fixture_blocked"))
        return issues

    def propose_rebinding(self, issue: FixtureIssue) -> FixtureBinding | None:
        """Select the first unblocked alternative and emit a plot_revision event.

        Returns the proposed FixtureBinding, or None if no alternative is
        available (emits a plot_advisory event in that case instead).
        The caller is responsible for calling accept_rebinding to apply the change
        once the proposal is reviewed (D-016 two-step write).
        """
        canon = self._pipeline.canon_ledger()
        alternatives = self._graph.alternative_fixtures.get(issue.hook.function_id, [])

        for binding in alternatives:
            if binding.fixture_entity_id == issue.hook.binding.fixture_entity_id:
                continue
            if not self._is_fixture_blocked(binding.fixture_entity_id, canon):
                self._log.append(
                    author=self._pm,
                    channel="system",
                    type="plot_revision",
                    content=(
                        f"[plot_revision] function '{issue.hook.function_id}': "
                        f"rebind {issue.hook.binding.fixture_entity_id!r} → "
                        f"{binding.fixture_entity_id!r} ({issue.reason})"
                    ),
                    audience=self._pm_audience(),
                    visibility="content",
                )
                return binding

        self._log.append(
            author=self._pm,
            channel="system",
            type="plot_advisory",
            content=(
                f"[plot_advisory] function '{issue.hook.function_id}': "
                f"fixture '{issue.hook.binding.fixture_entity_id}' blocked "
                f"but no alternative available"
            ),
            audience=self._pm_audience(),
            visibility="content",
        )
        return None

    def accept_rebinding(self, hook: Hook, new_binding: FixtureBinding) -> None:
        """Apply an accepted re-binding to the plot graph (D-016: sole writer)."""
        self._graph.update_hook_binding(hook.function_id, new_binding)

    # ------------------------------------------------------------------ #
    # Clock / front handling                                               #
    # ------------------------------------------------------------------ #

    def handle_clock_fired(self, clock_name: str) -> Front | None:
        """Log the consequence for any front that owns the clock that just fired.

        Emits a `front_consequence` event (GM + plot_manager only). Actual
        commitment of `landing_truth` into the canon ledger is a separate step
        the caller performs through CommitPipeline (D-026).
        """
        front = self._graph.front_for_clock(clock_name)
        if front is None:
            return None

        self._log.append(
            author=self._pm,
            channel="system",
            type="front_consequence",
            content=(
                f"[front: {front.id}] '{front.name}' fires — "
                f"consequence: {front.consequence_truth}"
            ),
            audience=self._pm_audience(),
            visibility="content",
        )
        return front

    # ------------------------------------------------------------------ #
    # Convenience: post-beat step                                          #
    # ------------------------------------------------------------------ #

    def post_beat(self, clocks_fired: list[str]) -> list[FixtureBinding]:
        """Handle clock-fired events and fixture health after one beat.

        Fires front consequences for any filled clocks, then checks all active
        hooks. For each blocked hook, proposes and auto-accepts the first
        available alternative binding.

        Returns the list of FixtureBindings that were accepted (empty when
        nothing changed).
        """
        for clock_name in clocks_fired:
            self.handle_clock_fired(clock_name)

        issues = self.check_fixture_health()
        accepted: list[FixtureBinding] = []
        for issue in issues:
            proposed = self.propose_rebinding(issue)
            if proposed is not None:
                self.accept_rebinding(issue.hook, proposed)
                accepted.append(proposed)
        return accepted

    # ------------------------------------------------------------------ #
    # GM context summary                                                   #
    # ------------------------------------------------------------------ #

    def gm_context_summary(self) -> str:
        """Return a GM-facing summary of active hooks and pressing fronts.

        Included in the adjudicator's world_summary (never passed to narrator
        or player — the adjudicator owns the full GM view).
        """
        active_hooks = [h for h in self._graph.hooks if h.active]
        if not active_hooks and not self._graph.fronts:
            return "(no active hooks or fronts)"

        lines: list[str] = []
        if active_hooks:
            lines.append("Active hooks:")
            for hook in active_hooks:
                fn = self._graph.function_nodes.get(hook.function_id)
                fn_desc = fn.description if fn else hook.function_id
                lines.append(
                    f"  [{hook.function_id}] {fn_desc}"
                    f" → {hook.binding.fixture_entity_id}"
                    f" ({hook.binding.description})"
                )

        if self._graph.fronts:
            lines.append("Active fronts:")
            for front in self._graph.fronts:
                lines.append(f"  [{front.id}] {front.name}: {front.threat}")
                lines.append(
                    f"    Clock: {front.clock_name} → {front.consequence_truth}"
                )

        return "\n".join(lines)
