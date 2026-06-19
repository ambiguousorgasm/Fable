"""Phase 21 deliverable 5: D-031 correction and retcon event types."""
from __future__ import annotations

import pytest

from fable_table_engine import (
    CORRECTION_TYPES,
    EventLog,
)
from fable_table_engine.console import render_event
from fable_table_engine.events import Event, ProjectedEvent


# --------------------------------------------------------------------------- #
# Helpers                                                                       #
# --------------------------------------------------------------------------- #

def _proj(
    type_: str,
    content: str = "text",
    *,
    superseded_by: str | None = None,
    author: str = "gm",
) -> ProjectedEvent:
    return ProjectedEvent(
        sequence=0, id="e1", timestamp="2026-06-19T00:00:00",
        author=author, channel="public", type=type_,
        visibility="content", content=content,
        superseded_by=superseded_by,
    )


# --------------------------------------------------------------------------- #
# CORRECTION_TYPES constant                                                     #
# --------------------------------------------------------------------------- #

class TestCorrectionTypes:

    def test_contains_correction_and_retcon(self):
        assert CORRECTION_TYPES == {"correction", "retcon"}

    def test_is_frozenset(self):
        assert isinstance(CORRECTION_TYPES, frozenset)


# --------------------------------------------------------------------------- #
# Event.authorized_by field                                                     #
# --------------------------------------------------------------------------- #

class TestEventAuthorizedBy:

    def test_default_empty(self):
        log = EventLog()
        e = log.append(
            author="gm", channel="public", type="narration",
            content="text", audience=("gm",),
        )
        assert e.authorized_by == ()

    def test_stored_correctly(self):
        log = EventLog()
        e = log.append(
            author="gm", channel="system", type="correction",
            content="fix", audience=("gm", "hero"),
            authorized_by=("hero",),
        )
        assert e.authorized_by == ("hero",)

    def test_retcon_requires_authorized_by(self):
        with pytest.raises(ValueError, match="authorized_by"):
            Event(
                sequence=0, id="x", timestamp="t", author="gm",
                channel="system", audience=("gm", "hero"),
                visibility="content", type="retcon",
                content="we say it didn't happen",
                # authorized_by omitted → empty tuple → should raise
            )

    def test_retcon_with_authorized_by_accepted(self):
        log = EventLog()
        original = log.append(
            author="gm", channel="public", type="narration",
            content="the door was red", audience=("hero", "gm"),
        )
        retcon = log.append(
            author="gm", channel="system", type="retcon",
            content="the door was blue (table consensus)",
            audience=("hero", "gm"),
            derived_from=(original.id,),
            authorized_by=("hero",),
        )
        assert retcon.authorized_by == ("hero",)
        assert retcon.type == "retcon"

    def test_correction_without_authorized_by_is_fine(self):
        log = EventLog()
        original = log.append(
            author="gm", channel="public", type="narration",
            content="ther door was red", audience=("hero", "gm"),
        )
        correction = log.append(
            author="gm", channel="system", type="correction",
            content="the door was red",
            audience=("hero", "gm"),
            derived_from=(original.id,),
        )
        assert correction.type == "correction"
        assert correction.authorized_by == ()

    def test_to_dict_includes_authorized_by(self):
        log = EventLog()
        original = log.append(
            author="gm", channel="public", type="narration",
            content="text", audience=("gm",),
        )
        retcon = log.append(
            author="gm", channel="system", type="retcon",
            content="revised", audience=("gm", "hero"),
            derived_from=(original.id,),
            authorized_by=("hero",),
        )
        assert retcon.to_dict()["authorized_by"] == ["hero"]


# --------------------------------------------------------------------------- #
# ProjectedEvent.superseded_by                                                  #
# --------------------------------------------------------------------------- #

class TestProjectedEventSupersededBy:

    def test_uncorrected_event_superseded_by_none(self):
        log = EventLog()
        log.append(
            author="gm", channel="public", type="narration",
            content="all is well", audience=("hero", "gm"),
        )
        proj = log.project_for("hero")
        assert proj[0].superseded_by is None

    def test_corrected_event_has_superseded_by(self):
        log = EventLog()
        original = log.append(
            author="gm", channel="public", type="narration",
            content="ther door was red", audience=("hero", "gm"),
        )
        correction = log.append(
            author="gm", channel="system", type="correction",
            content="the door was red",
            audience=("hero", "gm"),
            derived_from=(original.id,),
        )
        proj = log.project_for("hero")
        orig_proj = next(p for p in proj if p.id == original.id)
        assert orig_proj.superseded_by == correction.id

    def test_correction_event_itself_not_superseded(self):
        log = EventLog()
        original = log.append(
            author="gm", channel="public", type="narration",
            content="typo", audience=("hero", "gm"),
        )
        correction = log.append(
            author="gm", channel="system", type="correction",
            content="correct", audience=("hero", "gm"),
            derived_from=(original.id,),
        )
        proj = log.project_for("hero")
        corr_proj = next(p for p in proj if p.id == correction.id)
        assert corr_proj.superseded_by is None

    def test_retcon_supersedes_referenced_events(self):
        log = EventLog()
        e1 = log.append(
            author="gm", channel="public", type="narration",
            content="original scene", audience=("hero", "gm"),
        )
        e2 = log.append(
            author="hero", channel="public", type="narration",
            content="original action", audience=("hero", "gm"),
        )
        retcon = log.append(
            author="gm", channel="system", type="retcon",
            content="we revisit: the scene played out differently",
            audience=("hero", "gm"),
            derived_from=(e1.id, e2.id),
            authorized_by=("hero",),
        )
        proj = log.project_for("hero")
        by_id = {p.id: p for p in proj}
        assert by_id[e1.id].superseded_by == retcon.id
        assert by_id[e2.id].superseded_by == retcon.id
        assert by_id[retcon.id].superseded_by is None

    def test_superseded_by_not_in_projection_when_gm_only_audience(self):
        log = EventLog()
        original = log.append(
            author="gm", channel="public", type="narration",
            content="gm narration", audience=("gm",),
        )
        log.append(
            author="gm", channel="system", type="correction",
            content="corrected", audience=("gm",),
            derived_from=(original.id,),
        )
        # player never sees the original, so no superseded marker in their view
        proj = log.project_for("hero")
        assert proj == ()


# --------------------------------------------------------------------------- #
# render_event — correction and retcon types                                    #
# --------------------------------------------------------------------------- #

class TestRenderEventCorrection:

    def test_correction_type_rendered(self):
        e = _proj("correction", "the door was red (not blue)")
        assert render_event(e) == "[correction] the door was red (not blue)"

    def test_retcon_type_rendered(self):
        e = _proj("retcon", "we revisit: the patrol arrives later")
        assert render_event(e) == "[retcon] we revisit: the patrol arrives later"

    def test_correction_empty_content_returns_none(self):
        e = _proj("correction", "")
        assert render_event(e) is None

    def test_retcon_empty_content_returns_none(self):
        e = _proj("retcon", "")
        assert render_event(e) is None


class TestRenderEventSupersededMarker:

    def test_superseded_narration_has_prefix(self):
        e = _proj("narration", "ther door was red", superseded_by="corr-01")
        result = render_event(e)
        assert result is not None
        assert result.startswith("[superseded] ")
        assert "ther door was red" in result

    def test_unsuperseded_narration_has_no_prefix(self):
        e = _proj("narration", "the door was red")
        assert render_event(e) == "the door was red"

    def test_superseded_dice_roll_has_prefix(self):
        e = _proj("dice_roll", "3d6=[2,2,2]=6", superseded_by="corr-02")
        result = render_event(e)
        assert result is not None
        assert result.startswith("[superseded] [roll]")

    def test_superseded_resolution_has_prefix(self):
        e = _proj("resolution", "margin -2 → Cost", superseded_by="corr-03")
        result = render_event(e)
        assert result is not None
        assert result.startswith("[superseded] [outcome]")

    def test_superseded_ooc_has_prefix(self):
        e = _proj("ooc", "wait I meant the left door", superseded_by="corr-04")
        result = render_event(e)
        assert result is not None
        assert result.startswith("[superseded] [OOC]")

    def test_correction_event_itself_never_superseded_prefix(self):
        # correction events have no superseded_by by construction; extra safety
        e = _proj("correction", "fix text", superseded_by=None)
        assert render_event(e) == "[correction] fix text"


# --------------------------------------------------------------------------- #
# Round-trip through project_for + render_event                                 #
# --------------------------------------------------------------------------- #

class TestCorrectionRoundTrip:

    def test_player_transcript_shows_superseded_then_correction(self):
        log = EventLog()
        original = log.append(
            author="gm", channel="public", type="narration",
            content="ther door was red", audience=("hero", "gm"),
        )
        log.append(
            author="gm", channel="system", type="correction",
            content="the door was red",
            audience=("hero", "gm"),
            derived_from=(original.id,),
        )
        proj = log.project_for("hero")
        lines = [render_event(e) for e in proj if render_event(e) is not None]
        assert any("[superseded]" in l for l in lines), "superseded marker missing"
        assert any("[correction]" in l for l in lines), "correction event missing"
        # original text still present (not omitted)
        assert any("ther door was red" in l for l in lines)
        # corrected text also present
        assert any("the door was red" in l and "[correction]" in l for l in lines)
