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


def _version_str(value: Any) -> str | None:
    """Normalise a discovered fact to the string form the ladder compares."""
    if value is None:
        return None
    if isinstance(value, dict):
        # Isaac entries are dicts carrying a version plus provenance; the version
        # is what a requirement is matched against.
        inner = value.get("version")
        return str(inner) if inner not in (None, "") else None
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

    Mirrors :meth:`check.ProjectRequirementsChecker._requirement_item` exactly, so
    the verdicts a target produces are the same kind a local ``check`` produces.
    The only difference is the fact source.
    """
    verdicts: list[RequirementVerdict] = []

    for name in sorted(requirements):
        entry = requirements[name]

        if _entry_matches_gpu(name):
            verdicts.append(_gpu_verdict(name, entry, facts))
            continue

        spec = check_core._version_spec(entry)
        detected = _version_str(facts.get(name))

        if detected is None:
            if name.strip().lower() not in PROBED_FACTS:
                # Discovery never asks about this, so its absence carries no
                # information. Reporting "missing" here would assert a fact the
                # target was never examined for.
                verdicts.append(
                    RequirementVerdict(
                        name, spec, None, "untested",
                        "target discovery does not report this component, so it is "
                        "not measured (not evidence of absence)",
                    )
                )
            else:
                verdicts.append(
                    RequirementVerdict(name, spec, None, "missing",
                                       "required component was not detected on this target")
                )
            continue

        if not spec:
            verdicts.append(
                RequirementVerdict(name, None, detected, "untested",
                                   "version not declared, so it cannot be compared")
            )
            continue

        result = requirements_core.satisfies(detected, spec)
        if result is True:
            verdicts.append(RequirementVerdict(name, spec, detected, "compatible"))
        elif result is False:
            # §57 evidence-not-guarantees: an out-of-range version is a warning
            # with an explanation, never an assertion of incompatibility.
            verdicts.append(
                RequirementVerdict(
                    name, spec, detected, "untested",
                    f"detected {detected} is outside the required range {spec} "
                    f"(not asserted incompatible from a version range alone)",
                )
            )
        else:
            verdicts.append(
                RequirementVerdict(
                    name, spec, detected, "untested",
                    f"could not compare {detected} against {spec}",
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
    result = check_core.summarize(items, strict=False)

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
) -> list[SelectReport]:
    """Evaluate several targets. Still advisory — it ranks nothing and chooses nothing."""
    return [
        select_target(t, requirements, inspected.get(t.name), tested) for t in targets
    ]
