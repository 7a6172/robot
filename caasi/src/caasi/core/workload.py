"""Workload declaration.

A *workload* is the work a project wants done, expressed as **data**: what it
needs, and (from Stage F2) the operations that carry it out. It is deliberately
**not** a script, a DAG or an execution engine — ``steps`` name operations caasi
already has, and this module never runs anything.

Stage F1 introduces the **minimal** model needed for target selection: a name and
``requires``. Steps and outputs arrive in F2, once selection is proven. Keeping F1
minimal is deliberate: selection does not need a composition vocabulary, and
adding one now would fix an abstraction before there is evidence to choose it.

Relationship to existing concepts:

* ``Experiment`` (``core/experiment.py``) describes a *runnable* — a script, a
  backend, env — and is local-only.
* The manifest (``caasi.yaml``) carries the *project's* ``requires`` and ``tested``.
* A :class:`Workload` carries **work-specific** requirements, which are combined
  with the project's for evaluation. A workload may declare none, in which case the
  project's requirements alone decide.

Nothing here is ROS- or project-specific: ``requires`` entries are ordinary
requirement specs, so a Python workload and a ROS 2 workload use the same model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

#: Directory, relative to the project root, holding workload declarations.
WORKLOAD_DIR = "workloads"

#: The fixed, ordered vocabulary of operations a workload may compose (Stage F2).
#:
#: These are *existing* caasi operations, not a new execution engine. The list is
#: deliberately closed: a step name outside it is rejected at parse time rather
#: than silently ignored, and there are no conditionals, loops or expressions. A
#: workload needing real control flow is a program, and the workload invokes it
#: through ``run`` -- caasi does not grow a workflow language.
KNOWN_STEPS: tuple[str, ...] = ("deploy", "build", "run", "collect")

#: Steps that take no configuration and are therefore written bare or as ``{}``.
_CONFIGURABLE_STEPS = ("build", "run")


class WorkloadError(ValueError):
    """Raised for an invalid workload declaration."""


@dataclass
class Step:
    """One composed operation. Names an existing caasi operation; runs nothing itself."""

    name: str
    options: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "options": dict(self.options)}


@dataclass
class Workload:
    """Declared work: what it needs (F1), how it runs (F2), what it yields (F2)."""

    name: str
    requires: dict[str, Any] = field(default_factory=dict)
    #: Where the declaration was read from, for provenance and error messages.
    config_path: Path | None = None
    steps: list["Step"] = field(default_factory=list)
    outputs: list[Any] = field(default_factory=list)
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"name": self.name, "requires": dict(self.requires)}
        if self.steps:
            data["steps"] = [s.to_dict() for s in self.steps]
        if self.outputs:
            data["outputs"] = list(self.outputs)
        if self.description:
            data["description"] = self.description
        return data


def parse_steps(raw: Any) -> list[Step]:
    """Parse a workload's ``steps`` into the fixed operation vocabulary.

    Two spellings are accepted for each entry, and no others:

    ``- deploy``                 (bare, for steps needing no configuration)
    ``- build: {packages: [x]}`` (one key naming the step, its options as the value)

    An unknown step name is **rejected**, not ignored: silently skipping a step the
    author wrote would run a different sequence than the declaration says.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise WorkloadError("'steps' must be a list")

    steps: list[Step] = []
    for index, entry in enumerate(raw):
        where = f"steps[{index}]"

        if isinstance(entry, str):
            name, options = entry.strip(), {}
        elif isinstance(entry, dict):
            if len(entry) != 1:
                raise WorkloadError(
                    f"{where}: a step must have exactly one key "
                    f"(the operation name), got {len(entry)}"
                )
            name, options = next(iter(entry.items()))
            name = str(name).strip()
            options = options if isinstance(options, dict) else {}
            if options == {} and entry[name] is not None and not isinstance(entry[name], dict):
                raise WorkloadError(
                    f"{where}: '{name}' options must be a mapping or empty"
                )
        else:
            raise WorkloadError(f"{where}: a step must be a name or a single-key mapping")

        if name not in KNOWN_STEPS:
            raise WorkloadError(
                f"{where}: unknown step '{name}' "
                f"(known steps: {', '.join(KNOWN_STEPS)})"
            )
        steps.append(Step(name=name, options=dict(options)))

    return steps


def parse_workload(data: Any, name: str | None = None, path: Path | None = None) -> Workload:
    """Parse a workload declaration. Permissive about shape, strict about meaning.

    A single top-level ``workload:`` wrapper is accepted and unwrapped, because
    that spelling appears naturally in project files. Anything else unrecognised is
    **reported** rather than ignored: silently reading an empty ``requires`` from a
    mis-shaped file would tell an operator "nothing is required", which is the
    opposite of the truth.
    """
    if not isinstance(data, dict):
        raise WorkloadError("workload declaration must be a mapping")

    # Accept the wrapped spelling, but reject an ambiguous file that has both.
    if "workload" in data and isinstance(data["workload"], dict):
        extra = set(data) - {"workload"}
        if extra:
            raise WorkloadError(
                f"workload file mixes a 'workload:' block with top-level keys "
                f"({', '.join(sorted(extra))}); use one spelling"
            )
        data = data["workload"]

    known = {"name", "requires", "steps", "outputs", "description"}
    unknown = set(data) - known
    if unknown:
        raise WorkloadError(
            f"unknown workload key(s): {', '.join(sorted(unknown))} "
            f"(known: {', '.join(sorted(known))})"
        )

    requires = data.get("requires") or {}
    if not isinstance(requires, dict):
        raise WorkloadError("'requires' must be a mapping of requirement specs")

    steps = parse_steps(data.get("steps"))

    outputs = data.get("outputs") or []
    if not isinstance(outputs, list):
        raise WorkloadError("'outputs' must be a list")

    resolved_name = str(data.get("name") or name or (path.stem if path else "") or "").strip()
    if not resolved_name:
        raise WorkloadError("workload has no name")

    return Workload(
        name=resolved_name,
        requires=dict(requires),
        config_path=path,
        steps=list(steps),
        outputs=list(outputs),
        description=(str(data["description"]) if data.get("description") else None),
    )


def load_workload(path: Path | str) -> Workload:
    """Read one workload declaration from a YAML file."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise WorkloadError(f"workload declaration not found: {resolved}")
    try:
        data = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise WorkloadError(f"invalid YAML in {resolved}: {exc}") from exc
    return parse_workload(data, path=resolved)


def workload_dir(project_root: Path) -> Path:
    return Path(project_root) / WORKLOAD_DIR


def list_workloads(project_root: Path) -> list[Workload]:
    """Every readable workload under the project's ``workloads/`` directory.

    A malformed file is reported rather than skipped silently, so a typo surfaces
    as a problem instead of a missing workload.
    """
    directory = workload_dir(project_root)
    if not directory.is_dir():
        return []
    found: list[Workload] = []
    for path in sorted(directory.glob("*.y*ml")):
        found.append(load_workload(path))
    return found


def find_workload(project_root: Path, name: str) -> Workload | None:
    """Resolve a workload by exact name or unique name prefix."""
    query = (name or "").strip()
    workloads = list_workloads(project_root)
    exact = [w for w in workloads if w.name == query]
    if exact:
        return exact[0]
    matches = [w for w in workloads if w.name.startswith(query)]
    return matches[0] if len(matches) == 1 else None


def combined_requirements(
    project_requires: dict[str, Any],
    workload: Workload | None,
) -> dict[str, Any]:
    """Merge a project's requirements with a workload's.

    Workload requirements **extend** the project's, because a workload runs inside
    the project and inherits its needs. On collision the workload wins: it is the
    more specific statement of what this particular work needs.
    """
    merged = dict(project_requires or {})
    if workload is not None:
        merged.update(workload.requires or {})
    return merged
