"""Explicit target selection for workloads (Phase 7 — ``--where``).

The distinction this module exists to preserve:

    ``--where`` answers "which currently suitable target should I use?"
    A scheduler would answer "when and where should this eventually run?"

So this is a **decision over an already-evaluated set**, taken once, explained, and
never revisited. There is no waiting, no queue, no reservation and no retry: if
nothing fits, it fails and says why.

What it reuses rather than rebuilds:

* :func:`selection.select_all` — already evaluates every target against the
  requirements and already ranks nothing;
* the existing run records — **occupancy is derived, not tracked**.

Nothing here adds persistent state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Policies. Deliberately few: `any` (no preference), `idle` (prefer unoccupied),
#: and `prefer:<tag>` (prefer a tag). None of them scores or balances.
POLICY_ANY = "any"
POLICY_IDLE = "idle"
POLICY_PREFER_PREFIX = "prefer:"


class SelectionError(ValueError):
    """Raised for an unusable policy. Distinct from 'nothing fits'."""


def parse_policy(raw: str) -> tuple[str, str | None]:
    """Validate a ``--where`` value into ``(kind, tag)``.

    An unknown policy is an error rather than a silent fallback to ``any``: quietly
    ignoring a policy the operator wrote would choose differently than they asked.
    """
    value = (raw or "").strip()
    if value == POLICY_ANY:
        return POLICY_ANY, None
    if value == POLICY_IDLE:
        return POLICY_IDLE, None
    if value.startswith(POLICY_PREFER_PREFIX):
        tag = value[len(POLICY_PREFER_PREFIX):].strip()
        if not tag:
            raise SelectionError(
                "'--where prefer:' needs a tag (for example --where prefer:gpu)"
            )
        return "prefer", tag
    raise SelectionError(
        f"unknown --where policy '{raw}' "
        f"(expected: any, idle, or prefer:<tag>)"
    )


# ---------------------------------------------------------------------------
# Occupancy: an observation, never a guarantee
# ---------------------------------------------------------------------------

#: States that mean a target is currently occupied. Terminal states do not.
OCCUPYING_STATES = ("running", "paused")


def occupancy_by_target(config) -> dict[str, dict[str, Any]]:
    """Live occupancy per target, derived from the existing run records.

    Returns, per target, how many occupying runs there are plus any runs whose
    state is **unknown** (``lost``).

    ``lost`` is deliberately reported separately and counted as neither busy nor
    free. An unknown state must not be silently resolved into either -- the same
    rule that governs unmeasured requirements applies to unmeasured run states.
    """
    from . import runs as runs_core

    summary: dict[str, dict[str, Any]] = {}
    try:
        records = runs_core.list_runs(config)
    except Exception:  # noqa: BLE001 - unreadable run state must not block selection
        return summary

    for record in records:
        bucket = summary.setdefault(
            record.target, {"occupying": 0, "unknown": 0, "run_ids": []}
        )
        try:
            status = runs_core.effective_status(record, config)
        except Exception:  # noqa: BLE001
            status = None

        if status in OCCUPYING_STATES:
            bucket["occupying"] += 1
            bucket["run_ids"].append(record.run_id)
        elif status == runs_core.LOST:
            # Unknown, not busy. Recorded so it can be reported rather than hidden.
            bucket["unknown"] += 1

    return summary


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------


@dataclass
class EliminatedTarget:
    """A target that was evaluated and not selected, with the reason."""

    target: str
    reason: str
    evidence: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"target": self.target, "reason": self.reason, "evidence": self.evidence}


@dataclass
class SelectionDecision:
    """The outcome of applying a policy to the evaluated targets.

    Purely a reporting type: it holds no state and outlives nothing.
    """

    workload: str
    policy: str
    #: The raw policy string as the operator wrote it, e.g. ``prefer:gpu``.
    policy_raw: str
    selected: str | None = None
    reason: str | None = None
    eliminated: list[EliminatedTarget] = field(default_factory=list)
    #: Requirements that could not be measured on the SELECTED target. Reported,
    #: never converted into absence.
    unmeasured: list[str] = field(default_factory=list)
    #: Targets whose run state is unknown (`lost`), reported but not blocking.
    unknown_occupancy: list[str] = field(default_factory=list)
    #: How the policy ordered the eligible set, for the "why this one" question.
    ordering_note: str = ""
    #: Every evaluated target's verdict summary, so the report can show the measured
    #: evidence behind a decision without the caller re-deriving it.
    evidence_by_target: dict[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.selected is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "workload": self.workload,
            "policy": self.policy_raw,
            "policy_kind": self.policy,
            "selected": self.selected,
            "reason": self.reason,
            "eliminated": [e.to_dict() for e in self.eliminated],
            "unmeasured": list(self.unmeasured),
            "unknown_occupancy": list(self.unknown_occupancy),
            "ordering": self.ordering_note,
            "evidence": dict(self.evidence_by_target),
            "ok": self.ok,
        }


def _elimination_reason(report) -> tuple[str, str | None]:
    """Why a report is not eligible, and the evidence behind it."""
    if not report.reachable:
        return "unreachable", report.error
    blocking = [v for v in report.verdicts if v.verdict in ("missing", "incompatible")]
    if blocking:
        first = blocking[0]
        return f"does not satisfy '{first.name}'", first.note or None
    return "ineligible", None


def decide(
    workload_name: str,
    policy_raw: str,
    reports: list[Any],
    occupancy: dict[str, dict[str, Any]] | None = None,
    unmeasured_by_target: dict[str, list[str]] | None = None,
    tags_by_target: dict[str, list[str]] | None = None,
) -> SelectionDecision:
    """Apply a policy to evaluated reports and return an explained decision.

    Determinism is explicit rather than incidental: the eligible set is ordered by
    the policy key and then by **target name**. There is no scoring, weighting, cost
    model or load balancing anywhere in this function.
    """
    kind, tag = parse_policy(policy_raw)
    occupancy = occupancy or {}
    unmeasured_by_target = unmeasured_by_target or {}
    tags_by_target = tags_by_target or {}

    decision = SelectionDecision(
        workload=workload_name, policy=kind, policy_raw=policy_raw
    )

    for report in reports:
        detail = ", ".join(
            f"{v.name} {v.verdict}" + (f" ({v.note})" if v.note else "")
            for v in getattr(report, "verdicts", [])
        )
        decision.evidence_by_target[report.target] = detail or report.summary or report.status

    eligible: list[Any] = []
    for report in reports:
        if report.compatible:
            eligible.append(report)
            continue
        reason, evidence = _elimination_reason(report)
        decision.eliminated.append(
            EliminatedTarget(target=report.target, reason=reason, evidence=evidence)
        )
        # Only a target that was actually evaluated can report unmeasured facts.
        notes = unmeasured_by_target.get(report.target) or []
        if notes:
            decision.eliminated[-1].reason += " (see notes)"

    if not eligible:
        decision.reason = "no target satisfies this workload"
        decision.ordering_note = "no eligible targets"
        return decision

    # Order: policy key first, then TARGET NAME. Name is the tie-break because it is
    # the one ordering an operator can reason about and reproduce.
    if kind == POLICY_IDLE:
        eligible.sort(key=lambda r: (occupancy.get(r.target, {}).get("occupying", 0), r.target))
        best = occupancy.get(eligible[0].target, {}).get("occupying", 0)
        decision.ordering_note = (
            "ordered by live run count, then target name "
            f"(selected target has {best} occupying run(s))"
        )
    elif kind == "prefer":
        eligible.sort(key=lambda r: (0 if tag in tags_by_target.get(r.target, []) else 1, r.target))
        matched = tag in tags_by_target.get(eligible[0].target, [])
        decision.ordering_note = (
            f"targets carrying tag '{tag}' first, then target name "
            f"({'matched' if matched else 'no eligible target carries it'})"
        )
    else:  # POLICY_ANY
        eligible.sort(key=lambda r: r.target)
        decision.ordering_note = "ordered by target name (no preference applied)"

    chosen = eligible[0]
    decision.selected = chosen.target

    if kind == "prefer" and tag not in tags_by_target.get(chosen.target, []):
        # Be explicit rather than quietly returning an untagged target.
        decision.reason = (
            f"selected '{chosen.target}' by name order; no eligible target carries "
            f"tag '{tag}'"
        )
    elif kind == POLICY_IDLE:
        busy = occupancy.get(chosen.target, {}).get("occupying", 0)
        decision.reason = (
            f"selected '{chosen.target}'; it satisfies the requirements and has "
            f"{busy} occupying run(s)"
        )
    else:
        decision.reason = f"selected '{chosen.target}'; it satisfies the requirements"

    decision.unmeasured = list(unmeasured_by_target.get(chosen.target) or [])

    for report in eligible[1:]:
        decision.eliminated.append(
            EliminatedTarget(
                target=report.target,
                reason="suitable, but not chosen by this policy",
                evidence=decision.ordering_note,
            )
        )

    # Unknown occupancy is surfaced, never resolved into busy or free.
    unknown: list[str] = []
    for report in reports:
        entry = occupancy.get(report.target) or {}
        if entry.get("unknown"):
            unknown.append(f"{report.target}: {entry['unknown']} run(s) in an unknown state")
    decision.unknown_occupancy = unknown

    return decision

