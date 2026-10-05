"""Tests for Stage F3: target-aware tool invocation (R2).

The principle under test is *"caasi supplies context, then gets out of the way."*
So these tests hold the line on the things that make that true:

* the mechanism is **generic** — a tool is a registry entry, not code;
* target facts are **never** substituted with local ones;
* the domain is **resolved or refused, never silently defaulted** — the
  empty-graph trap;
* tool arguments pass through **unchanged**;
* refusals are **first-class outcomes** with reasons.

The real cross-machine discovery result is recorded in the stage report, not here:
it is a property of the network, not of this code.
"""

from __future__ import annotations

import pytest

from caasi.core import toolctx as T
from caasi.core.targets import Target


def _ctx(
    *,
    reachable=True,
    ros_available=True,
    distro="jazzy",
    rmw=None,
    domain=None,
    error=None,
    transport="ssh",
):
    return T.TargetContext(
        target="robot",
        transport=transport,
        reachable=reachable,
        ros_available=ros_available,
        distro=distro,
        rmw=rmw,
        domain=domain,
        error=error,
    )


# ---------------------------------------------------------------------------
# Registry: a tool is data, not code
# ---------------------------------------------------------------------------


def test_builtin_registry_has_the_proof_cases():
    registry = T.load_registry()
    assert "rviz2" in registry
    assert "rosbag" in registry
    assert registry["rosbag"].invoke == "ros2 bag"


def test_registry_is_generic_not_rviz_specific():
    """Every built-in is the same shape; none has bespoke handling."""
    registry = T.load_registry()
    for spec in registry.values():
        assert isinstance(spec, T.ToolSpec)
        assert spec.invoke
        assert spec.needs


def test_config_extends_the_registry_without_code():
    """A new tool is a config entry — the point of a generic mechanism."""
    class _Cfg:
        def get(self, key, default=None):
            return {"myviz": {"invoke": "myviz --ros"}} if key == "tools" else default

    registry = T.load_registry(_Cfg())
    assert registry["myviz"].invoke == "myviz --ros"


def test_config_can_override_a_builtin_environment():
    class _Cfg:
        def get(self, key, default=None):
            return {"rviz2": {"invoke": "rviz2", "environment": ["A=1"]}} if key == "tools" else default

    registry = T.load_registry(_Cfg())
    assert registry["rviz2"].environment == ["A=1"]


def test_a_tools_entry_without_invoke_is_not_a_target_aware_tool():
    """The older `tools:` shape resolves versions; it must not become a command."""
    class _Cfg:
        def get(self, key, default=None):
            return {"isaacsim": {"version": "4.5.0"}} if key == "tools" else default

    registry = T.load_registry(_Cfg())
    assert "isaacsim" not in registry


def test_unknown_tool_is_refused_with_the_available_list():
    with pytest.raises(T.ToolInvocationError) as err:
        T.resolve_tool(T.load_registry(), "nope")
    assert "unknown" in str(err.value)
    assert "rviz2" in str(err.value)


# ---------------------------------------------------------------------------
# Environment: never substitute local facts for target facts
# ---------------------------------------------------------------------------


def test_target_distro_is_used():
    spec = T.load_registry()["rviz2"]
    env = T.build_environment(spec, _ctx(distro="humble"))
    assert env["ROS_DISTRO"] == "humble"


def test_rmw_is_exported_only_when_the_target_reports_one():
    """An unreported RMW must not be replaced with the workstation's value."""
    spec = T.load_registry()["rviz2"]
    assert "RMW_IMPLEMENTATION" not in T.build_environment(spec, _ctx(rmw=None))
    assert T.build_environment(spec, _ctx(rmw="rmw_cyclonedds_cpp"))["RMW_IMPLEMENTATION"] == (
        "rmw_cyclonedds_cpp"
    )


def test_domain_is_exported_when_known():
    spec = T.load_registry()["rviz2"]
    env = T.build_environment(spec, _ctx(domain="42"))
    assert env["ROS_DOMAIN_ID"] == "42"


def test_domain_is_not_exported_when_unset():
    """Absence must not become a fabricated default in the environment either."""
    spec = T.load_registry()["rviz2"]
    env = T.build_environment(spec, _ctx(domain=T.UNSET))
    assert "ROS_DOMAIN_ID" not in env


def test_declarative_environment_substitution():
    spec = T.ToolSpec(
        name="x", invoke="x", environment=["D={{context.domain_id}}", "R={{context.rmw}}"]
    )
    env = T.build_environment(spec, _ctx(domain="7", rmw="rmw_fastrtps_cpp"))
    assert env["D"] == "7"
    assert env["R"] == "rmw_fastrtps_cpp"


def test_substitution_of_an_unknown_value_is_empty_not_invented():
    spec = T.ToolSpec(name="x", invoke="x", environment=["R={{context.rmw}}"])
    env = T.build_environment(spec, _ctx(rmw=None))
    assert env["R"] == ""


# ---------------------------------------------------------------------------
# The domain hazard - the empty-graph trap
# ---------------------------------------------------------------------------


def test_explicit_domain_always_wins():
    domain, source = T.resolve_domain(_ctx(domain="42"), explicit=7)
    assert domain == "7"
    assert source == "explicit"


def test_target_reported_domain_is_used_when_authoritative():
    domain, source = T.resolve_domain(_ctx(domain="42"), explicit=None)
    assert domain == "42"
    assert source == "target"


def test_unset_domain_is_refused_not_defaulted():
    """The critical guard: assuming a domain silently shows an empty graph."""
    domain, reason = T.resolve_domain(_ctx(domain=T.UNSET), explicit=None)
    assert domain is None
    assert "does not set ROS_DOMAIN_ID" in reason
    assert "--domain" in reason


def test_unknown_domain_is_refused():
    domain, reason = T.resolve_domain(_ctx(domain=None), explicit=None)
    assert domain is None
    assert "--domain" in reason


def test_domain_is_never_defaulted_to_zero():
    """Zero is a legitimate explicit choice, never an implicit fallback."""
    domain, _ = T.resolve_domain(_ctx(domain=T.UNSET), explicit=None)
    assert domain != "0"


# ---------------------------------------------------------------------------
# Planning: refusals are first-class
# ---------------------------------------------------------------------------


def _spec(name="rviz2"):
    return T.load_registry()[name]


def test_plan_succeeds_with_a_known_domain():
    plan = T.plan_invocation(_spec(), Target(name="robot"), [], explicit_domain=0,
                             context=_ctx(domain=T.UNSET))
    assert plan.environment["ROS_DOMAIN_ID"] == "0"
    assert plan.domain_source == "explicit"


def test_plan_refuses_an_unreachable_target():
    with pytest.raises(T.ToolInvocationError) as err:
        T.plan_invocation(_spec(), Target(name="robot"), [],
                          context=_ctx(reachable=False, ros_available=False,
                                       error="Connection timed out"))
    assert "unreachable" in str(err.value)
    assert "Connection timed out" in str(err.value)


def test_plan_refuses_a_target_without_ros():
    with pytest.raises(T.ToolInvocationError) as err:
        T.plan_invocation(_spec(), Target(name="robot"), [],
                          context=_ctx(ros_available=False))
    assert "no ROS 2" in str(err.value)


def test_plan_refuses_when_the_domain_cannot_be_resolved():
    with pytest.raises(T.ToolInvocationError) as err:
        T.plan_invocation(_spec(), Target(name="robot"), [],
                          context=_ctx(domain=T.UNSET))
    assert "--domain" in str(err.value)


def test_plan_reports_a_missing_rmw_rather_than_defaulting_it():
    plan = T.plan_invocation(_spec(), Target(name="robot"), [], explicit_domain=0,
                             context=_ctx(rmw=None, domain=T.UNSET))
    assert any("no RMW_IMPLEMENTATION" in n for n in plan.notes)
    assert "RMW_IMPLEMENTATION" not in plan.environment


def test_a_tool_not_needing_a_domain_is_not_gated_on_one():
    spec = T.ToolSpec(name="plain", invoke="plain", needs=(), requires_domain=False)
    plan = T.plan_invocation(spec, Target(name="robot"), [],
                             context=_ctx(domain=T.UNSET))
    assert "ROS_DOMAIN_ID" not in plan.environment


def test_plan_is_serialisable_for_json():
    plan = T.plan_invocation(_spec(), Target(name="robot"), ["--flag"],
                             explicit_domain=3, context=_ctx(domain=T.UNSET))
    payload = plan.to_dict()
    assert payload["tool"] == "rviz2"
    assert payload["domain_source"] == "explicit"
    assert payload["context"]["target"] == "robot"


# ---------------------------------------------------------------------------
# Command construction: pass-through
# ---------------------------------------------------------------------------


def test_tool_arguments_pass_through_unchanged():
    spec = T.load_registry()["rosbag"]
    command = T.build_command(spec, ["record", "--unknown-flag", "-x", "/scan", "/tf"])
    assert command == ["ros2", "bag", "record", "--unknown-flag", "-x", "/scan", "/tf"]


def test_unknown_flags_reach_the_tool():
    """caasi parses only its own options; the rest is the tool's business."""
    spec = T.load_registry()["rosbag"]
    command = T.build_command(spec, ["--caasi-has-never-heard-of-this"])
    assert "--caasi-has-never-heard-of-this" in command


def test_invoke_may_be_a_multi_word_command():
    spec = T.ToolSpec(name="x", invoke="ros2 bag")
    assert T.build_command(spec, ["record"]) == ["ros2", "bag", "record"]


def test_no_arguments_means_no_arguments():
    spec = T.load_registry()["rviz2"]
    assert T.build_command(spec, []) == ["rviz2"]


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def test_run_tool_propagates_the_tools_own_exit_code():
    """caasi does not reinterpret the tool's exit status."""
    spec = T.ToolSpec(name="probe", invoke="sh -c 'exit 7'", needs=(), requires_domain=False)
    plan = T.plan_invocation(spec, Target(name="local"), [], context=_ctx(transport="local"))
    result = T.run_tool(plan)
    assert result.returncode == 7


def test_run_tool_applies_the_resolved_environment():
    spec = T.ToolSpec(
        name="probe", invoke="sh -c 'echo $CAASI_F3_PROBE'",
        needs=(), requires_domain=False, environment=["CAASI_F3_PROBE=present"],
    )
    plan = T.plan_invocation(spec, Target(name="local"), [], context=_ctx(transport="local"))
    result = T.run_tool(plan, capture=True)
    assert result.stdout.strip() == "present"


def test_run_tool_raises_for_a_missing_binary():
    spec = T.ToolSpec(name="ghost", invoke="definitely-not-a-real-binary-xyz",
                      needs=(), requires_domain=False)
    plan = T.plan_invocation(spec, Target(name="local"), [], context=_ctx(transport="local"))
    with pytest.raises(FileNotFoundError):
        T.run_tool(plan)


# ---------------------------------------------------------------------------
# Context probing
# ---------------------------------------------------------------------------


def test_probe_reports_reachability_and_ros_separately(monkeypatch):
    """A reachable target without ROS 2 is a different answer from unreachable."""
    from caasi.core import ros as ros_core

    monkeypatch.setattr(ros_core, "remote_ros_environment",
                        lambda target: {"available": False, "distro": None, "root": None,
                                        "rmw": None, "error": None})
    ctx = T.probe_target_context(Target(name="local", transport="local"))
    assert ctx.reachable is True
    assert ctx.ros_available is False


def test_probe_marks_an_unreachable_target(monkeypatch):
    from caasi.core import ros as ros_core

    monkeypatch.setattr(ros_core, "remote_ros_environment",
                        lambda target: {"available": False, "error": "unreachable"})
    ctx = T.probe_target_context(Target(name="r", transport="ssh", host="192.0.2.99"))
    assert ctx.reachable is False
    assert ctx.error == "unreachable"


def test_probe_records_an_unset_domain_as_measured_not_unknown(monkeypatch):
    """A target asked and reporting nothing is UNSET; None means 'could not ask'."""
    from caasi.core import ros as ros_core
    from caasi.utils import shell

    monkeypatch.setattr(ros_core, "remote_ros_environment",
                        lambda target: {"available": True, "distro": "jazzy", "root": "/opt/ros/jazzy",
                                        "rmw": None})
    monkeypatch.setattr(shell, "run_cmd",
                        lambda argv, timeout=None: shell.ShellResult(0, "D=\n", ""))
    ctx = T.probe_target_context(Target(name="r", transport="ssh", host="h"))
    assert ctx.domain == T.UNSET
    assert ctx.domain_is_known is False


def test_probe_captures_a_reported_domain(monkeypatch):
    from caasi.core import ros as ros_core
    from caasi.utils import shell

    monkeypatch.setattr(ros_core, "remote_ros_environment",
                        lambda target: {"available": True, "distro": "jazzy", "root": "/x", "rmw": None})
    monkeypatch.setattr(shell, "run_cmd",
                        lambda argv, timeout=None: shell.ShellResult(0, "D=42\n", ""))
    ctx = T.probe_target_context(Target(name="r", transport="ssh", host="h"))
    assert ctx.domain == "42"
    assert ctx.domain_is_known is True
