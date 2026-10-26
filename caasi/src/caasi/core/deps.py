"""Operation-aware dependency inspection for a target (read-only).

Answers one question: *can this target perform this operation, and if not, what exactly is
missing?* It does not install anything, change configuration, or start anything.

Reuse rather than reinvent:

* the requirement ladder is :func:`caasi.core.check.evaluate_requirement` -- the single
  implementation used by both local ``caasi check`` and target selection, including its
  §57 caution that an out-of-range version is not proof of incompatibility;
* requirements come from the project manifest (``caasi.yaml`` ``requires:``), which is the
  authoritative declaration, plus a small scope table for the tools an *operation* needs
  beyond what the project declares;
* remote facts come from :func:`caasi.core.execution.run_on_target` in one round-trip --
  there is no second SSH implementation here.

Scopes are the caasi operations that actually exist, not an invented taxonomy:

``build``     compile the workspace (needs a build tool and a ROS underlay)
``bringup``   run the robot's hardware stack -- simulation-only requirements are excluded
``sim``       run the simulation stack -- simulation requirements are required here
``project``   (default) exactly what the project declares, nothing added
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import execution
from . import check as check_core

#: Dependencies that only matter when simulating. Kept deliberately explicit and small:
#: a name-based guess would eventually mark something required that is not.
SIMULATION_ONLY = frozenset({"isaac_sim", "isaac_lab", "ros_gz_sim", "ros_gz_bridge", "gazebo"})

#: Packages an operation needs that a project manifest does not normally declare.
#: ``(name, why)`` -- the *why* is reported verbatim, so it must stay true.
SCOPE_EXTRAS: dict[str, tuple[tuple[str, str], ...]] = {
    "build": (
        ("colcon", "the workspace is compiled with colcon"),
        ("ros2", "the toolchain comes from the target's ROS 2 installation"),
    ),
    "bringup": (
        ("joint_state_publisher", "bringup launches it to publish joint states"),
        ("robot_state_publisher", "bringup needs it to publish the robot's TF tree"),
    ),
    "sim": (
        ("ros_gz_sim", "the simulator is launched through ros_gz_sim"),
        ("ros_gz_bridge", "simulation topics are bridged into ROS 2 by ros_gz_bridge"),
    ),
    "project": (),
}

#: ROS packages delivered by sudo apt on a ROS 2 distribution.
_ROS_PACKAGE_PREFIX = "ros"

STATE_INSTALLED = "installed"
STATE_MISSING = "missing"
STATE_INCOMPATIBLE = "incompatible"
STATE_OPTIONAL_ABSENT = "optional-absent"
STATE_UNKNOWN = "unknown"


@dataclass(frozen=True)
class Dependency:
    name: str
    required: bool
    why: str
    spec: str | None = None
    #: True when the requirement came from the project manifest rather than a scope table.
    declared: bool = False


@dataclass
class DependencyResult:
    dependency: Dependency
    state: str
    detected: str | None
    note: str = ""
    install_command: str | None = None
    #: A command is only "verified" when the distro and package manager are known.
    install_verified: bool = False


@dataclass
class DepsReport:
    target: str
    scope: str
    reachable: bool
    os: str | None = None
    ros_distro: str | None = None
    results: list[DependencyResult] = field(default_factory=list)
    error: str = ""

    def counts(self) -> dict[str, int]:
        out = {STATE_INSTALLED: 0, STATE_MISSING: 0, STATE_INCOMPATIBLE: 0,
               STATE_OPTIONAL_ABSENT: 0, STATE_UNKNOWN: 0}
        for r in self.results:
            out[r.state] = out.get(r.state, 0) + 1
        return out

    @property
    def ok(self) -> bool:
        """True only when nothing required is missing, incompatible or unknown."""
        return self.reachable and not any(
            r.state in (STATE_MISSING, STATE_INCOMPATIBLE, STATE_UNKNOWN)
            for r in self.results
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "scope": self.scope,
            "reachable": self.reachable,
            "os": self.os,
            "ros_distro": self.ros_distro,
            "ok": self.ok,
            "error": self.error,
            "counts": self.counts(),
            "dependencies": [
                {
                    "name": r.dependency.name,
                    "required": r.dependency.required,
                    "declared": r.dependency.declared,
                    "spec": r.dependency.spec,
                    "state": r.state,
                    "detected": r.detected,
                    "why": r.dependency.why,
                    "note": r.note,
                    "install_command": r.install_command,
                    "install_verified": r.install_verified,
                }
                for r in self.results
            ],
        }


def _probe_script(deps: list[str], executables: list[str]) -> str:
    """One read-only round-trip: OS, ROS installs, package presence, tool presence.

    Only inspecting: ``dpkg -s`` reads metadata, ``command -v`` looks at PATH, and the
    two file reads are configuration. Nothing is installed, updated or started.
    """
    parts = [
        'echo "CAASI_OS=$( . /etc/os-release 2>/dev/null; echo "${PRETTY_NAME:-unknown}" )"',
        'echo "CAASI_DISTROS=$(ls -d /opt/ros/*/setup.bash 2>/dev/null | sed -e \'s|/opt/ros/||\' -e \'s|/setup.bash||\' | tr \'\\n\' \' \')"',
    ]
    for exe in executables:
        parts.append(
            f'if command -v {exe} >/dev/null 2>&1; then echo "CAASI_EXE:{exe}=$(command -v {exe})"; '
            f'else echo "CAASI_EXE:{exe}="; fi'
        )
    for pkg in deps:
        # A ROS package is identified by its share directory: the Debian package is named
        # ros-<distro>-<name>, so a dpkg lookup by the ROS name reports installed
        # packages as missing (observed on the real robot). The share tree is the
        # authoritative answer; dpkg's version is a fallback for plain system packages.
        parts.append(
            f'sh=$(ls -d /opt/ros/*/share/{pkg} 2>/dev/null | head -1); '
            f'v=$(dpkg-query -W -f=\'${{Version}}\' {pkg} 2>/dev/null); '
            f'fam=$(ls -d /opt/ros/*/share/{pkg}_* 2>/dev/null '
            f'| xargs -r -n1 basename | sort -u | tr \'\\n\' \',\'); '
            f'echo "CAASI_PKG:{pkg}=$sh|$v|$fam"'
        )
    return " ; ".join(parts)


@dataclass
class _Facts:
    os: str | None = None
    distros: list[str] = field(default_factory=list)
    executables: dict[str, str] = field(default_factory=dict)
    packages: dict[str, str] = field(default_factory=dict)
    #: Packages sharing a prefix with a requested name, e.g. nav2 -> nav2_costmap_2d.
    #: A metapackage is often not installed itself while its components are.
    families: dict[str, list[str]] = field(default_factory=dict)
    error: str = ""


def gather_facts(target, deps: list[str], executables: list[str],
                 timeout: float = 30.0) -> _Facts:
    """Collect the facts the report needs, in one round-trip."""
    request = execution.ExecRequest(
        argv=["bash", "-c", _probe_script(deps, executables)], timeout=timeout
    )
    result = execution.run_on_target(target, request)
    facts = _Facts()
    if not result.ran:
        facts.error = result.error or "inspection did not run"
        return facts

    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("CAASI_OS="):
            facts.os = line.split("=", 1)[1].strip() or None
        elif line.startswith("CAASI_DISTROS="):
            facts.distros = [d for d in line.split("=", 1)[1].split() if d]
        elif line.startswith("CAASI_EXE:"):
            name, _, path = line[len("CAASI_EXE:"):].partition("=")
            facts.executables[name] = path.strip()
        elif line.startswith("CAASI_PKG:"):
            name, _, payload = line[len("CAASI_PKG:"):].partition("=")
            fields = payload.split("|")
            share = fields[0].strip() if fields else ""
            version = fields[1].strip() if len(fields) > 1 else ""
            family = [f for f in (fields[2] if len(fields) > 2 else "").split(",") if f]
            # Prefer the installed share path (proves the ROS package is present), then
            # the dpkg version for plain system packages.
            facts.packages[name] = share or version
            if family:
                facts.families[name] = family
    return facts


def _apt_name(name: str, distro: str | None) -> str | None:
    """Best-effort Debian package name for a dependency, or None when not derivable."""
    if name == "colcon":
        return "python3-colcon-common-extensions"
    if name.startswith("ros_gz_") or name.startswith("joint_") or name.endswith("_publisher"):
        if not distro:
            return None
        return f"{_ROS_PACKAGE_PREFIX}-{distro}-{name.replace('_', '-')}"
    return None


def _classify(dep: Dependency, facts: _Facts) -> DependencyResult:
    """Turn facts into a state, reusing the shared requirement ladder for versions."""
    detected: str | None

    if dep.name == "ros2":
        detected = facts.distros[0] if facts.distros else None
    elif dep.name in facts.executables:
        detected = facts.executables[dep.name] or None
    else:
        detected = facts.packages.get(dep.name) or None

    # A named ROS distribution is an identity, not a version range: asking for jazzy and
    # finding humble is a genuine mismatch, unlike §57's "version outside a range".
    if dep.name == "ros2" and dep.spec and detected and dep.spec != detected:
        return DependencyResult(
            dep, STATE_INCOMPATIBLE, detected,
            note=f"target provides '{detected}', the project asks for '{dep.spec}'",
        )

    if detected is None and facts.families.get(dep.name):
        # Satisfied by components of a metapackage rather than by an exact match.
        # Reporting this as "missing" would be a false negative on a real target.
        return DependencyResult(
            dep, STATE_INSTALLED, ", ".join(facts.families[dep.name][:3]),
            note="satisfied by component packages",
        )

    if detected is None:
        state = STATE_MISSING if dep.required else STATE_OPTIONAL_ABSENT
        reason = "not found on the target" if dep.required else "not present (not required here)"
        return DependencyResult(dep, state, None, note=reason)

    item = check_core.evaluate_requirement(dep.name, dep.spec, detected, scope="target")
    if item.compatibility == "compatible":
        return DependencyResult(dep, STATE_INSTALLED, detected, note=item.note or "")
    if item.compatibility == "untested" and dep.spec:
        # Keep the §57 caution: out-of-range is reported, not asserted as broken.
        return DependencyResult(dep, STATE_UNKNOWN, detected, note=item.note or "")
    return DependencyResult(dep, STATE_INSTALLED, detected, note=item.note or "")


def inspect_target_deps(
    target,
    *,
    scope: str = "project",
    requires: dict | None = None,
    timeout: float = 30.0,
) -> DepsReport:
    """Build the report for *target* and *scope*. Read-only."""
    if scope not in SCOPE_EXTRAS:
        raise ValueError(f"unknown scope '{scope}' (expected one of {sorted(SCOPE_EXTRAS)})")

    requires = dict(requires or {})
    deps: list[Dependency] = []

    for name, entry in requires.items():
        spec = None
        if isinstance(entry, dict):
            spec = entry.get("version")
        elif isinstance(entry, str):
            spec = entry
        required = not (scope == "bringup" and name in SIMULATION_ONLY)
        why = (
            "declared by the project manifest"
            if required
            else "declared by the project, but only needed for simulation"
        )
        deps.append(Dependency(name, required, why, spec=spec, declared=True))

    for name, why in SCOPE_EXTRAS[scope]:
        if any(d.name == name for d in deps):
            continue
        deps.append(Dependency(name, True, why))

    report = DepsReport(target=target.name, scope=scope, reachable=False)

    package_names = [d.name for d in deps if d.name not in ("ros2", "colcon")]
    executable_names = ["colcon", "ros2"]
    facts = gather_facts(target, package_names, executable_names, timeout=timeout)
    if facts.error:
        report.error = facts.error
        # An inspection that did not run is NOT "everything installed", and it is also
        # not proof of absence: every dependency is reported unknown.
        for dep in deps:
            report.results.append(
                DependencyResult(dep, STATE_UNKNOWN, None, note="inspection failed")
            )
        return report

    report.reachable = True
    report.os = facts.os
    report.ros_distro = facts.distros[0] if facts.distros else None

    for dep in deps:
        result = _classify(dep, facts)
        apt = _apt_name(dep.name, report.ros_distro)
        if result.state in (STATE_MISSING, STATE_OPTIONAL_ABSENT) and apt:
            result.install_command = f"sudo apt install -y {apt}"
            # Only call it verified when the target is Debian-based and the ROS release is
            # known; otherwise it is a suggestion that still needs review.
            result.install_verified = bool(
                report.ros_distro and (facts.os or "").lower().find("ubuntu") >= 0
            )
        elif result.state in (STATE_MISSING, STATE_OPTIONAL_ABSENT):
            result.note = (result.note + " (no package name derivable; review manually)").strip()
        report.results.append(result)

    return report
