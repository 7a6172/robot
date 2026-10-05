"""Target-aware tool invocation of existing tools against a target.

The principle:

    **caasi supplies context, then gets out of the way.**

Given a tool name and a target, resolve the context that tool needs to operate
against that target's ROS 2 system, then ``exec`` the *real* tool. caasi
implements no part of the tool, and no part of DDS.

What is deliberately NOT here:

* **No DDS discovery, networking or tunnels.** Cross-machine discovery is the DDS
  implementation's responsibility. If it does not traverse a given network (a
  Tailscale link, for example), that is a network/DDS fact to report, not something
  to work around inside caasi.
* **No GUI forwarding.** The tool runs locally; the graph is remote.
* **No per-tool code.** A tool is a registry entry (``invoke`` + environment), not
  a subclass. rviz2, rqt and rosbag are entries, not integrations.
* **No target selection.** The target is named; this module never picks one.

The one genuinely subtle part is the **domain ID** -- see :func:`resolve_domain`.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass, field
from typing import Any

from .targets import Target

#: A tool entry that does not declare its required context is assumed to want ROS.
DEFAULT_NEEDS = ("ros2",)

#: Sentinel for "the target was asked and reported no value". Distinct from
#: ``None``, which means "the target was never asked" -- the same
#: measured-absence-versus-unmeasured distinction used everywhere else.
UNSET = "<unset>"


class ToolInvocationError(ValueError):
    """Raised when a tool cannot be invoked. Always carries a reason."""


@dataclass
class TargetContext:
    """The context a local tool needs in order to talk to a target's ROS 2 system.

    Every field records **what the target actually said**. An absent value is
    never back-filled from the workstation: substituting a local ``RMW`` or domain
    would silently change the tool's behaviour and could point it at the wrong
    graph entirely.
    """

    target: str
    transport: str
    reachable: bool
    ros_available: bool
    distro: str | None = None
    ros_root: str | None = None
    rmw: str | None = None
    #: Target-reported domain, ``UNSET`` when the target was asked and had none.
    domain: str | None = None
    #: Where the domain value came from: "explicit", "target" or None.
    domain_source: str | None = None
    error: str | None = None

    @property
    def domain_is_known(self) -> bool:
        return self.domain not in (None, UNSET)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "transport": self.transport,
            "reachable": self.reachable,
            "ros_available": self.ros_available,
            "distro": self.distro,
            "ros_root": self.ros_root,
            "rmw": self.rmw,
            "domain": self.domain,
            "domain_source": self.domain_source,
            "error": self.error,
        }


def probe_target_context(target: Target, timeout: float | None = None) -> TargetContext:
    """Ask the target for the ROS 2 context a tool would need.

    Reuses the E2 probe (``ros.remote_ros_environment``) and additionally asks for
    ``ROS_DOMAIN_ID``, which the tool case needs and the observability case did not.
    """
    from . import ros as ros_core
    from . import targets as targets_core

    base = ros_core.remote_ros_environment(target)

    # Reachability and ROS availability are separate facts: a reachable target
    # without ROS 2 is a different answer from an unreachable one, and a tool must
    # report the right one. The probe sets `error` only when it could not reach.
    context = TargetContext(
        target=target.name,
        transport=target.transport,
        reachable=not base.get("error"),
        ros_available=bool(base.get("available")),
        distro=base.get("distro"),  # type: ignore[arg-type]
        ros_root=(str(base["root"]) if base.get("root") else None),
        rmw=base.get("rmw"),  # type: ignore[arg-type]
        error=base.get("error"),  # type: ignore[arg-type]
    )

    if not context.reachable:
        return context

    # Ask specifically for the domain. `ROS_DOMAIN_ID` is unset on most targets,
    # which is a real answer (the DDS default), not an unknown one -- but the two
    # are recorded differently so neither is mistaken for the other.
    if target.transport == "ssh":
        prefix = targets_core.target_ssh_prefix(target)
        probe = 'if [ -n "${ROS_DOMAIN_ID+x}" ]; then echo "D=${ROS_DOMAIN_ID}"; else echo "D="; fi'
        from ..utils import shell

        result = shell.run_cmd(
            [*prefix, probe], timeout=max(10.0, float(target.ssh_timeout) * 2)
        )
        if result.ok:
            reported = result.stdout.strip().removeprefix("D=")
            # Empty output means the target was asked and sets no domain. That is a
            # real answer (the DDS default), recorded as UNSET rather than as
            # unknown; None is reserved for "could not ask".
            context.domain = reported or UNSET
        else:
            context.domain = None
    else:
        value = os.environ.get("ROS_DOMAIN_ID")
        context.domain = (value if value else UNSET)

    return context


def resolve_domain(
    context: TargetContext, explicit: int | str | None = None
) -> tuple[str | None, str]:
    """Decide which domain to use, and say where it came from.

    Order, per the design:

    1. an explicit ``--domain`` **always wins**;
    2. otherwise the target's own value, **if the target reported one**;
    3. otherwise **refuse** -- return ``None`` and a reason.

    Step 3 is the important one. Defaulting silently would let a tool attach to the
    workstation's default domain, find nothing, and look like it worked -- the same
    empty-graph trap already guarded against in remote ROS queries.
    """
    if explicit is not None:
        return str(explicit), "explicit"

    if context.domain_is_known:
        return str(context.domain), "target"

    if context.domain == UNSET:
        return None, (
            f"target '{context.target}' does not set ROS_DOMAIN_ID, so the domain it "
            f"runs on is unknown; pass --domain explicitly rather than assuming the "
            f"default (an assumed domain can silently show an empty ROS graph)"
        )

    return None, (
        f"the ROS domain for target '{context.target}' could not be determined; "
        f"pass --domain explicitly (an assumed domain can silently show an empty "
        f"ROS graph)"
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass
class ToolSpec:
    """A registry entry: the real tool, plus what context it needs.

    This is data, not behaviour. A new tool is a new entry.
    """

    name: str
    invoke: str
    needs: tuple[str, ...] = DEFAULT_NEEDS
    environment: list[str] = field(default_factory=list)
    requires_domain: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "invoke": self.invoke,
            "needs": list(self.needs),
            "environment": list(self.environment),
            "requires_domain": self.requires_domain,
        }


#: Built-in defaults. Deliberately tiny: these exist to prove the mechanism is
#: generic, not to build tool integrations. Any of them can be overridden or
#: extended from configuration.
BUILTIN_TOOLS: dict[str, ToolSpec] = {
    "rviz2": ToolSpec(name="rviz2", invoke="rviz2"),
    "rqt": ToolSpec(name="rqt", invoke="rqt"),
    "rosbag": ToolSpec(name="rosbag", invoke="ros2 bag"),
}


def load_registry(config: Any = None) -> dict[str, ToolSpec]:
    """Tool registry: built-ins, extended or overridden by config ``tools:``.

    Config entries are merged over the built-ins, so a project may add a tool or
    adjust the environment a known tool receives, without a code change.
    """
    registry = dict(BUILTIN_TOOLS)
    if config is None:
        return registry

    declared = config.get("tools")
    if not isinstance(declared, dict):
        return registry

    for name, spec in declared.items():
        if not isinstance(spec, dict):
            continue
        invoke = spec.get("invoke")
        if not invoke:
            # A `tools:` entry without `invoke` is the older tool-registry shape
            # (version resolution), not a target-aware invocation. Leave it be.
            continue
        needs = spec.get("needs") or list(DEFAULT_NEEDS)
        if isinstance(needs, str):
            needs = [needs]
        environment = spec.get("environment") or []
        if isinstance(environment, str):
            environment = [environment]
        registry[str(name)] = ToolSpec(
            name=str(name),
            invoke=str(invoke),
            needs=tuple(str(n) for n in needs),
            environment=[str(e) for e in environment],
            requires_domain=bool(spec.get("requires_domain", True)),
        )
    return registry


def resolve_tool(registry: dict[str, ToolSpec], name: str) -> ToolSpec:
    """Look up a tool, or fail with the list of what is available."""
    spec = registry.get(name)
    if spec is None:
        known = ", ".join(sorted(registry)) or "-"
        raise ToolInvocationError(
            f"unknown target-aware tool '{name}' (available: {known}). "
            f"Add it under 'tools:' in the configuration to use it."
        )
    return spec


# ---------------------------------------------------------------------------
# Environment construction
# ---------------------------------------------------------------------------


def build_environment(spec: ToolSpec, context: TargetContext) -> dict[str, str]:
    """The environment overrides the tool needs to reach the target.

    Only facts the target actually reported are exported. An unreported ``RMW`` is
    left alone rather than replaced with the workstation's, because doing so would
    silently change the target's DDS behaviour.
    """
    env: dict[str, str] = {}

    if "ros2" in spec.needs:
        if context.distro:
            env["ROS_DISTRO"] = context.distro

    if context.rmw:
        env["RMW_IMPLEMENTATION"] = str(context.rmw)

    if spec.requires_domain and context.domain_is_known:
        env["ROS_DOMAIN_ID"] = str(context.domain)

    # Declarative per-tool extras, with {{context.*}} substitution.
    for line in spec.environment:
        rendered = _render_env_line(line, context)
        name, sep, value = rendered.partition("=")
        if sep:
            env[name.strip()] = value.strip()

    return env


def _render_env_line(line: str, context: TargetContext) -> str:
    """Substitute ``{{context.*}}`` placeholders from measured target facts."""
    mapping = {
        "context.domain_id": str(context.domain) if context.domain_is_known else "",
        "context.rmw": str(context.rmw or ""),
        "context.distro": str(context.distro or ""),
        "context.target": context.target,
    }
    rendered = line
    for key, value in mapping.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


def build_command(spec: ToolSpec, tool_args: list[str]) -> list[str]:
    """The command to run. Tool arguments pass through unchanged."""
    return [*shlex.split(spec.invoke), *tool_args]


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------


@dataclass
class InvocationPlan:
    """Everything the invocation will do, before it does it."""

    tool: str
    target: str
    command: list[str]
    environment: dict[str, str]
    context: TargetContext
    notes: list[str] = field(default_factory=list)
    domain_source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "target": self.target,
            "command": self.command,
            "environment": dict(self.environment),
            "domain_source": self.domain_source,
            "notes": list(self.notes),
            "context": self.context.to_dict(),
        }


def plan_invocation(
    spec: ToolSpec,
    target: Target,
    tool_args: list[str],
    explicit_domain: int | str | None = None,
    context: TargetContext | None = None,
) -> InvocationPlan:
    """Resolve everything and decide whether the invocation may proceed.

    Raises :class:`ToolInvocationError` with a reason when it may not. Refusing is
    a first-class outcome: it is the correct answer for an unreachable target, a
    target with no ROS 2, or an unknown domain.
    """
    ctx = context if context is not None else probe_target_context(target)
    notes: list[str] = []

    if not ctx.reachable:
        raise ToolInvocationError(
            f"target '{target.name}' is unreachable"
            + (f": {ctx.error}" if ctx.error else "")
        )

    if "ros2" in spec.needs and not ctx.ros_available:
        raise ToolInvocationError(
            f"target '{target.name}' has no ROS 2 installation detectable, so "
            f"'{spec.name}' has nothing to attach to"
        )

    domain_source: str | None = None
    if spec.requires_domain:
        domain, reason = resolve_domain(ctx, explicit_domain)
        if domain is None:
            raise ToolInvocationError(reason)
        # resolve_domain returned a value, so mirror it onto the context used for
        # environment construction.
        ctx = TargetContext(
            target=ctx.target,
            transport=ctx.transport,
            reachable=ctx.reachable,
            ros_available=ctx.ros_available,
            distro=ctx.distro,
            ros_root=ctx.ros_root,
            rmw=ctx.rmw,
            domain=domain,
            domain_source=reason,
            error=ctx.error,
        )
        domain_source = reason
        if reason == "explicit":
            notes.append(f"domain {domain} from --domain")
        else:
            notes.append(f"domain {domain} reported by the target")
    else:
        notes.append("tool does not attach to a ROS domain")

    if not ctx.rmw:
        # A measured absence, stated rather than silently defaulted.
        notes.append(
            "target reports no RMW_IMPLEMENTATION; leaving the local default in place"
        )
    if ctx.distro:
        notes.append(f"target ROS distro {ctx.distro}")

    return InvocationPlan(
        tool=spec.name,
        target=target.name,
        command=build_command(spec, tool_args),
        environment=build_environment(spec, ctx),
        context=ctx,
        notes=notes,
        domain_source=domain_source,
    )


def exec_tool(plan: InvocationPlan) -> int:
    """``exec`` the real tool with the resolved environment.

    ``exec`` rather than a supervising subprocess: the tool replaces caasi and
    behaves exactly as if the operator had run it. caasi does not manage the tool's
    lifecycle, does not daemonise it, and does not restart it.
    """
    env = dict(os.environ)
    env.update(plan.environment)
    os.execvpe(plan.command[0], plan.command, env)
    # execvpe only returns on failure.
    raise ToolInvocationError(f"could not execute '{plan.command[0]}'")


def run_tool(
    plan: InvocationPlan, capture: bool = False, timeout: float | None = None
) -> subprocess.CompletedProcess:
    """Run the tool as a subprocess. Used by tests and by non-interactive checks.

    Interactive use goes through :func:`exec_tool`; this variant exists so the
    mechanism can be exercised without replacing the caller's process.
    """
    env = dict(os.environ)
    env.update(plan.environment)
    return subprocess.run(
        plan.command,
        env=env,
        capture_output=capture,
        text=True,
        timeout=timeout,
    )
