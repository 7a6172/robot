"""Target-aware compatibility: can this project work on *that target*? (Stage F1)

The Check Contract (``core/check.py``) already answers *"can this work **here**?"*
with one vocabulary shared by every entry point. Its one local assumption is the
fact source: ``detect()`` reads versions from ``config`` and ``shell.which()``,
which describes the **local machine**.

This module supplies the missing half — the same verdict ladder, the same §57
caution (a version outside a range must **not** assert incompatibility), and the
same exit policy, but with the detected facts coming from a **target's own
discovery** instead of the local machine.

Design rules held here:

* **No new compatibility semantics.** The ladder and its notes are the Check
  Contract's; this module only chooses where facts come from.
* **Advisory, never choosing.** Nothing here selects a target for execution. It
  reports verdicts and the reasons behind them.
* **"Not measured" is a first-class outcome.** A fact a target does not expose is
  reported as ``untested`` with a note, never as compatibility or
  incompatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import check as check_core
from . import requirements as requirements_core
from .check import CheckItem
from .targets import Target, TargetEnvironment, TargetInspection, TargetResources

# Verdicts that describe the target itself rather than a requirement. Kept
# separate from the Check Contract's per-item vocabulary because they are
# properties of *inspection*, not of a requirement match.
TARGET_UNREACHABLE = "unreachable"


#: Sentinel used when a tool is present but reports no version. Mirrors the Check
#: Contract's own convention (``check._isaac_version`` returns "installed"), and
#: matters because ``None`` would be read as *absent*: a target with Isaac Sim
#: installed but no version recorded would be reported as not having it at all.
INSTALLED = "installed"


def _version_str(value: Any) -> str | None:
    """Normalise a discovered fact to the string form the ladder compares.

    A discovery entry that reports the tool present without a version becomes
    :data:`INSTALLED` rather than ``None``, so presence is never mistaken for
    absence. This mirrors ``check._isaac_version``, which returns "installed" in
    exactly this situation.
    """
    if value is None:
        return None
    if isinstance(value, dict):
        # Isaac entries are dicts carrying status/provenance; a version is what a
        # requirement is matched against, but status says whether it exists at all.
        inner = value.get("version")
        if inner not in (None, ""):
            return str(inner)
        status = str(value.get("status") or "").strip().lower()
        if status in ("ok", "detected", "installed", "present"):
            return INSTALLED
        return None
    text = str(value).strip()
    return text or None


#: Facts a target inspection actually probes, and therefore may be trusted to
#: report an *absence* for. Anything outside this set was never asked about, so a
#: requirement on it is UNMEASURED rather than missing -- the difference between
#: "the target looked and does not have it" and "nobody looked".
PROBED_FACTS: frozenset[str] = frozenset(
    {"ros2", "isaac_sim", "isaac_lab", "python", "cuda", "docker", "gpu"}
)


def target_facts(inspection: TargetInspection) -> dict[str, Any]:
    """Map a target's discovered facts onto the names the Check Contract uses.

    Only facts the target actually reported are included. A key that is absent
    means **not measured**, which the ladder renders as ``untested`` — it must
    never be filled in with a local value, because that would silently claim the
    remote target matches the workstation.
    """
    env: TargetEnvironment | None = inspection.environment
    res: TargetResources | None = inspection.resources
    facts: dict[str, Any] = {}

    if env is not None:
        facts["ros2"] = env.ros_distro
        facts["isaac_sim"] = env.isaac_sim
        facts["isaac_lab"] = env.isaac_lab
        facts["python"] = env.python_version
        facts["cuda"] = env.cuda_toolkit or env.cuda_version
        if env.docker:
            facts["docker"] = "present"

    # GPU count is a resource fact, exposed under the name a `requires` entry
    # would use. An inspected target reporting *no* GPUs is a MEASURED ABSENCE
    # ("this machine has none"), which is different from a target that could not
    # be asked at all ("not measured"). Collapsing the two would tell an operator
    # "unknown" when the true answer is "none", so the empty list is preserved and
    # only a missing inspection leaves the key out.
    if res is not None:
        facts["gpu"] = list(res.gpus)

    return facts


@dataclass
class RequirementVerdict:
    """One requirement evaluated against one target."""

    name: str
    required: str | None
    detected: str | None
    verdict: str  # the Check Contract compatibility vocabulary
    note: str = ""
    verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "required": self.required,
            "detected": self.detected,
            "verdict": self.verdict,
            "note": self.note,
            "verified": self.verified,
        }


@dataclass
class SelectReport:
    """Per-target selection verdict: advisory, with the reasons attached."""

    target: str
    status: str  # "ready" | "warning" | "incompatible" | "unreachable"
    reachable: bool
    verdicts: list[RequirementVerdict] = field(default_factory=list)
    summary: str = ""
    error: str | None = None

    @property
    def compatible(self) -> bool:
        return self.reachable and self.status != "incompatible"

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "status": self.status,
            "reachable": self.reachable,
            "verdicts": [v.to_dict() for v in self.verdicts],
            "summary": self.summary,
            "error": self.error,
        }


def _entry_matches_gpu(name: str) -> bool:
    return name.strip().lower() in ("gpu", "gpus", "cuda_gpu")


def _gpu_verdict(name: str, entry: Any, facts: dict[str, Any]) -> RequirementVerdict:
    """GPU requirements are resource-shaped, so they cannot use version matching."""
    gpus = facts.get("gpu")
    spec = entry if isinstance(entry, dict) else {}
    want_count = spec.get("count")
    want_memory = spec.get("memory_gb")

    if gpus is None:
        # The target was never asked: unmeasured, which is NOT the same as absent.
        return RequirementVerdict(
            name, str(spec) if spec else None, None, "untested",
            "target was not inspected for GPUs (not measured)",
        )

    if not gpus:
        # Asked, and the answer was none. This is a measured absence, so it is a
        # definite "missing" rather than an unverifiable warning.
        return RequirementVerdict(
            name, str(want_count) if want_count is not None else None, "0",
            "missing", "target reports no GPUs",
        )

    count = len(gpus)
    if want_count is not None and count < int(want_count):
        return RequirementVerdict(
            name, str(want_count), str(count), "missing",
            f"target reports {count} GPU(s), {want_count} required",
        )

    if want_memory is not None:
        sizes = [
            (g.get("memory_total_mib") or 0) / 1024.0
            for g in gpus
            if isinstance(g, dict)
        ]
        best = max(sizes) if sizes else 0.0
        required = float(want_memory)
        if best and best < required:
            return RequirementVerdict(
                name, f"{required:g}GB", f"{best:g}GB", "untested",
                f"largest GPU has {best:g}GB, {required:g}GB required (not asserted incompatible)",
            )

    return RequirementVerdict(name, str(spec) if spec else None, f"{count} GPU(s)", "compatible")


def evaluate_requirements(
    requirements: dict[str, Any],
    facts: dict[str, Any],
    tested: list[Any] | None = None,
) -> list[RequirementVerdict]:
    """Evaluate *requirements* against a target's *facts*.

    Uses the **same ladder** as local ``check`` (:func:`check.evaluate_requirement`),
    so a requirement cannot produce different verdicts depending on whether it was
    evaluated through ``caasi check`` or ``caasi target select``. Before the F1
    consolidation this was a second, hand-written copy of the ladder, and the two
    paths diverged under ``check.strict``.

    Only two things are target-specific, and both are about *where the fact came
    from* rather than how it is judged:

    * **Not-measured vs absent.** A component the target was never probed for is
      ``untested``, because its absence carries no information. A probed component
      the target does not have is a genuine ``missing``.
    * **Presence without a version.** A tool confirmed present whose version is not
      recorded cannot be compared, and the note says so.
    """
    verdicts: list[RequirementVerdict] = []

    for name in sorted(requirements):
        entry = requirements[name]

        if _entry_matches_gpu(name):
            # Resource-shaped, so no version ladder applies.
            verdicts.append(_gpu_verdict(name, entry, facts))
            continue

        detected = _version_str(facts.get(name))
        probed = name.strip().lower() in PROBED_FACTS

        if detected is None and not probed:
            # Never asked about, so this is unmeasured rather than absent.
            verdicts.append(
                RequirementVerdict(
                    name, check_core._version_spec(entry), None, "untested",
                    "target discovery does not report this component, so it is "
                    "not measured (not evidence of absence)",
                )
            )
            continue

        item = check_core.evaluate_requirement(name, entry, detected, tested)
        note = item.note
        if detected == INSTALLED and item.compatibility == "untested":
            # Name the actual cause; the generic ladder note would be misleading.
            note = (
                f"{name} is present but its version is not recorded, so it "
                f"cannot be compared against {item.required}"
            )
        verdicts.append(
            RequirementVerdict(
                name=item.name,
                required=item.required,
                detected=item.detected,
                verdict=item.compatibility,
                note=note,
                verified=item.verified,
            )
        )

    return verdicts


def _summary(verdicts: list[RequirementVerdict]) -> str:
    if not verdicts:
        return "no requirements declared"
    counts: dict[str, int] = {}
    for verdict in verdicts:
        counts[verdict.verdict] = counts.get(verdict.verdict, 0) + 1
    parts = [f"{n} {v}" for v, n in sorted(counts.items())]
    return ", ".join(parts)


def select_target(
    target: Target,
    requirements: dict[str, Any],
    inspection: TargetInspection | None,
    tested: list[Any] | None = None,
    strict: bool | None = None,
) -> SelectReport:
    """Evaluate one target against requirements. Advisory: it decides nothing."""
    if inspection is None or not inspection.reachable:
        reason = (inspection.error if inspection is not None else None) or "target could not be inspected"
        return SelectReport(
            target=target.name, status=TARGET_UNREACHABLE, reachable=False,
            summary="unreachable - not evaluated", error=reason,
        )

    facts = target_facts(inspection)
    verdicts = evaluate_requirements(requirements, facts, tested)
    items = [
        CheckItem(v.name, v.required, v.detected, v.verdict, v.note, v.verified)  # type: ignore[arg-type]
        for v in verdicts
    ]
    # `check.strict` is honoured here exactly as `caasi check` honours it. Before
    # consolidation this was hardcoded to False, so a project with
    # `check.strict: true` got `incompatible` from `check` and only a `warning`
    # from `target select` for the SAME requirement.
    result = check_core.summarize(items, strict=bool(strict))

    return SelectReport(
        target=target.name,
        status=result,
        reachable=True,
        verdicts=verdicts,
        summary=_summary(verdicts),
    )


def select_all(
    targets: list[Target],
    requirements: dict[str, Any],
    inspected: dict[str, TargetInspection],
    tested: list[Any] | None = None,
    strict: bool | None = None,
) -> list[SelectReport]:
    """Evaluate several targets. Still advisory — it ranks nothing and chooses nothing."""
    return [
        select_target(t, requirements, inspected.get(t.name), tested, strict=strict)
        for t in targets
    ]
