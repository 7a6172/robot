"""Tests for `--where` explicit target selection (Phase 7).

The property under test is the boundary between **selection** and **scheduling**:

    --where answers "which currently suitable target should I use?"
    A scheduler would answer "when and where should this eventually run?"

So these tests hold the line on: explicit opt-in, explained choices, deterministic
ordering, occupancy as a preference rather than a reservation, and **failure rather
than queueing** when nothing fits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from caasi.core import where as W


# ---------------------------------------------------------------------------
# Policy parsing
# ---------------------------------------------------------------------------


def test_any_and_idle_parse():
    assert W.parse_policy("any") == ("any", None)
    assert W.parse_policy("idle") == ("idle", None)


def test_prefer_parses_its_tag():
    assert W.parse_policy("prefer:gpu") == ("prefer", "gpu")


def test_unknown_policy_is_rejected_not_defaulted():
    """Silently falling back to `any` would choose differently than asked."""
    with pytest.raises(W.SelectionError):
        W.parse_policy("best")


def test_empty_string_is_rejected():
    with pytest.raises(W.SelectionError):
        W.parse_policy("")


def test_prefer_without_a_tag_is_rejected():
    with pytest.raises(W.SelectionError) as err:
        W.parse_policy("prefer:")
    assert "needs a tag" in str(err.value)


def test_a_bare_tag_is_not_a_policy():
    """`--where gpu` must not be silently read as prefer:gpu."""
    with pytest.raises(W.SelectionError):
        W.parse_policy("gpu")


# ---------------------------------------------------------------------------
# Decision inputs
# ---------------------------------------------------------------------------


@dataclass
class _Verdict:
    name: str
    verdict: str
    note: str = ""


@dataclass
class _Report:
    target: str
    status: str = "ready"
    reachable: bool = True
    verdicts: list[Any] = field(default_factory=list)
    summary: str = ""
    error: str | None = None

    @property
    def compatible(self) -> bool:
        return self.reachable and self.status != "incompatible"


def _ok(name, **kw):
    return _Report(target=name, **kw)


def _bad(name, requirement="gpu", note="target reports no GPUs"):
    return _Report(
        target=name, status="incompatible",
        verdicts=[_Verdict(requirement, "missing", note)],
    )


def _unreachable(name, error="Connection timed out"):
    return _Report(target=name, status="unreachable", reachable=False, error=error)


# ---------------------------------------------------------------------------
# Eligibility
# ---------------------------------------------------------------------------


def test_incompatible_is_ineligible():
    d = W.decide("w", "any", [_ok("good"), _bad("bad")])
    assert d.selected == "good"
    assert [e.target for e in d.eliminated] == ["bad"]


def test_an_unmeasured_target_remains_eligible():
    """Absence of evidence is not evidence of absence -- `warning` is eligible."""
    d = W.decide("w", "any", [_Report(target="warned", status="warning")])
    assert d.selected == "warned"


def test_unmeasured_notes_are_reported_for_the_selected_target():
    d = W.decide(
        "w", "any", [_Report(target="warned", status="warning")],
        unmeasured_by_target={"warned": ["torch: not measured"]},
    )
    assert d.unmeasured == ["torch: not measured"]


def test_unreachable_is_eliminated_with_the_transport_reason():
    d = W.decide("w", "any", [_ok("good"), _unreachable("down")])
    eliminated = {e.target: e for e in d.eliminated}
    assert "unreachable" in eliminated["down"].reason
    assert eliminated["down"].evidence == "Connection timed out"


def test_elimination_names_the_failing_requirement_and_evidence():
    d = W.decide("w", "any", [_ok("good"), _bad("bad")])
    eliminated = d.eliminated[0]
    assert "gpu" in eliminated.reason
    assert eliminated.evidence == "target reports no GPUs"


# ---------------------------------------------------------------------------
# Nothing fits -- the anti-scheduler property
# ---------------------------------------------------------------------------


def test_nothing_fits_selects_nothing():
    d = W.decide("w", "any", [_bad("a"), _bad("b")])
    assert d.selected is None
    assert d.ok is False


def test_nothing_fits_explains_every_target():
    d = W.decide("w", "any", [_bad("a"), _bad("b")])
    assert {e.target for e in d.eliminated} == {"a", "b"}
    assert all(e.evidence for e in d.eliminated)


def test_nothing_fits_says_so_rather_than_returning_a_default():
    d = W.decide("w", "any", [_bad("a")])
    assert "no target satisfies" in d.reason


# ---------------------------------------------------------------------------
# Determinism -- the tie-break is stated, not incidental
# ---------------------------------------------------------------------------


def test_any_orders_by_target_name():
    d = W.decide("w", "any", [_ok("zeta"), _ok("alpha"), _ok("mid")])
    assert d.selected == "alpha"


def test_any_is_deterministic_regardless_of_input_order():
    forward = W.decide("w", "any", [_ok("a"), _ok("b")]).selected
    reverse = W.decide("w", "any", [_ok("b"), _ok("a")]).selected
    assert forward == reverse == "a"


def test_ordering_note_states_how_the_choice_was_made():
    assert "target name" in W.decide("w", "any", [_ok("a")]).ordering_note


# ---------------------------------------------------------------------------
# prefer:<tag>
# ---------------------------------------------------------------------------


def test_prefer_tag_wins_over_name_order():
    d = W.decide(
        "w", "prefer:gpu", [_ok("alpha"), _ok("zeta")],
        tags_by_target={"alpha": [], "zeta": ["gpu"]},
    )
    assert d.selected == "zeta"


def test_prefer_tag_falls_back_to_name_order_and_says_so():
    """Returning an untagged target silently would misrepresent the policy."""
    d = W.decide(
        "w", "prefer:gpu", [_ok("alpha"), _ok("zeta")],
        tags_by_target={"alpha": [], "zeta": []},
    )
    assert d.selected == "alpha"
    assert "no eligible target carries" in d.reason


def test_prefer_tag_ignores_ineligible_tagged_targets():
    """A tag must not resurrect a target that fails the requirements."""
    d = W.decide(
        "w", "prefer:gpu", [_ok("alpha"), _bad("zeta")],
        tags_by_target={"alpha": [], "zeta": ["gpu"]},
    )
    assert d.selected == "alpha"


# ---------------------------------------------------------------------------
# Occupancy: an observation, never a guarantee
# ---------------------------------------------------------------------------


def test_idle_prefers_the_unoccupied_target():
    d = W.decide(
        "w", "idle", [_ok("busy"), _ok("free")],
        occupancy={"busy": {"occupying": 1}, "free": {"occupying": 0}},
    )
    assert d.selected == "free"


def test_idle_states_the_occupancy_evidence():
    d = W.decide("w", "idle", [_ok("a")], occupancy={"a": {"occupying": 0}})
    assert "occupying run" in d.reason


def test_idle_still_selects_when_every_target_is_busy():
    """Occupancy is a preference, NOT a gate -- it never blocks or waits."""
    d = W.decide(
        "w", "idle", [_ok("a"), _ok("b")],
        occupancy={"a": {"occupying": 3}, "b": {"occupying": 2}},
    )
    assert d.selected == "b"  # fewer occupying runs
    assert d.ok is True


def test_idle_tie_breaks_on_name():
    d = W.decide(
        "w", "idle", [_ok("z"), _ok("a")],
        occupancy={"z": {"occupying": 1}, "a": {"occupying": 1}},
    )
    assert d.selected == "a"


def test_unknown_run_state_is_reported_not_resolved():
    """`lost` is neither busy nor free, and must not be silently decided."""
    d = W.decide(
        "w", "idle", [_ok("a")],
        occupancy={"a": {"occupying": 0, "unknown": 2}},
    )
    assert any("unknown state" in note for note in d.unknown_occupancy)


def test_unknown_state_does_not_make_a_target_ineligible():
    d = W.decide("w", "idle", [_ok("a")], occupancy={"a": {"occupying": 0, "unknown": 5}})
    assert d.selected == "a"


def test_no_reservation_is_attempted():
    """Two simultaneous decisions may both see a target as idle -- by design."""
    first = W.decide("w", "idle", [_ok("a")], occupancy={"a": {"occupying": 0}})
    second = W.decide("w", "idle", [_ok("a")], occupancy={"a": {"occupying": 0}})
    assert first.selected == second.selected == "a"


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def test_decision_serialises_the_full_explanation():
    d = W.decide(
        "w", "prefer:gpu", [_ok("a"), _bad("b")],
        tags_by_target={"a": ["gpu"], "b": []},
        occupancy={"b": {"occupying": 0, "unknown": 1}},
    )
    payload = d.to_dict()
    assert payload["selected"] == "a"
    assert payload["policy"] == "prefer:gpu"
    assert payload["policy_kind"] == "prefer"
    assert payload["ordering"]
    assert payload["eliminated"][0]["target"] == "b"
    assert payload["eliminated"][0]["evidence"]
    assert payload["unknown_occupancy"]


def test_every_evaluated_target_appears_in_the_result():
    """Neither silently selected nor silently dropped."""
    reports = [_ok("a"), _bad("b"), _unreachable("c")]
    d = W.decide("w", "any", reports)
    accounted = {d.selected} | {e.target for e in d.eliminated}
    assert accounted == {"a", "b", "c"}


def test_no_scoring_or_weighting_exists():
    """`prefer` is a filter then name order, not a preference score.

    Checked against the executable code, not the docstring -- the docstring
    deliberately states that these things are absent.
    """
    import ast
    import inspect as _inspect

    tree = ast.parse(_inspect.getsource(W.decide))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)

    # Names and string literals that are not documentation.
    identifiers: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.append(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.append(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value not in docstrings:
                identifiers.append(node.value)

    blob = " ".join(identifiers).lower()
    for forbidden in ("score", "weight", "cost", "balance"):
        assert forbidden not in blob


def test_where_module_imports_no_runtime_scheduler_machinery():
    import inspect as _inspect
    import caasi.core.where as mod

    source = _inspect.getsource(mod)
    for forbidden in ("threading", "asyncio", "queue.Queue", "sleep("):
        assert forbidden not in source
