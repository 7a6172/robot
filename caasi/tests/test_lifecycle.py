"""Tests for the persistent runtime lifecycle (Phase 7 Stage E4).

These cover the parts that can be verified without a live target: declaration
parsing, rendering, the revision chain, and the refusal rules that keep rollback
honest. The behaviour against a real systemd host is recorded in
``plan/phases/phase-07/stage-e4-report.md``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from caasi.core import lifecycle as L
from caasi.core.targets import Target
from caasi.utils.shell import ShellResult


SSH_TARGET = Target(
    name="robot",
    transport="ssh",
    host="192.0.2.10",
    port=22,
    user="zar",
    ssh_timeout=10.0,
)
LOCAL_TARGET = Target(name="local", transport="local")


def _decl(**over):
    base = {
        "kind": "systemd",
        "unit": "demo.service",
        "entrypoint": "python3 -u app.py",
        "working_dir": ".",
    }
    base.update(over)
    return L.parse_runtime(base)


# ---------------------------------------------------------------------------
# Declaration parsing
# ---------------------------------------------------------------------------


def test_undeclared_runtime_is_permitted():
    """A project need not declare a runtime; it simply has nothing to manage."""
    decl = L.parse_runtime(None)
    assert decl.declared is False


def test_half_declared_runtime_is_not_declared():
    """A unit without an entrypoint is incomplete, not a broken service."""
    decl = L.parse_runtime({"unit": "x.service"})
    assert decl.declared is False


def test_unknown_kind_is_rejected():
    with pytest.raises(L.RuntimeLifecycleError):
        L.parse_runtime({"kind": "openrc", "unit": "x", "entrypoint": "y"})


def test_environment_accepts_a_bare_string():
    decl = L.parse_runtime({"unit": "x", "entrypoint": "y", "environment": "export A=1"})
    assert decl.environment == ["export A=1"]


def test_environment_rejects_a_non_list():
    with pytest.raises(L.RuntimeLifecycleError):
        L.parse_runtime({"unit": "x", "entrypoint": "y", "environment": {"A": 1}})


# ---------------------------------------------------------------------------
# Environment rendering - the .bashrc replacement
# ---------------------------------------------------------------------------


def test_environment_is_split_into_assignments_and_sources():
    """Assignments and `source` lines need different treatment, so they are split."""
    exports, sources = L.split_environment(
        ["export A=1", "source /opt/ros/jazzy/setup.bash", "B=2", ". /x.sh"]
    )
    assert exports == ["export A=1", "B=2"]
    assert sources == ["source /opt/ros/jazzy/setup.bash", ". /x.sh"]


def test_env_fragment_strips_export_for_systemd():
    """systemd rejects `export A=1`; it was silently dropped on a real target."""
    frag = L.render_env_fragment(_decl(environment=["export MARKER=hello"]), "/dest")
    assert "MARKER=hello" in frag
    assert "export " not in frag


def test_env_fragment_omits_source_lines():
    """`source` cannot live in an EnvironmentFile, so it must not be emitted."""
    frag = L.render_env_fragment(
        _decl(environment=["source /opt/ros/jazzy/setup.bash", "export A=1"]), "/dest"
    )
    assert "source " not in frag
    assert "A=1" in frag


def test_env_fragment_resolves_dest_placeholder():
    frag = L.render_env_fragment(_decl(environment=["export P={{dest}}/lib"]), "/home/zar/dep")
    assert "P=/home/zar/dep/lib" in frag


def test_relative_source_is_resolved_against_destination():
    resolved = L.resolve_environment_line("source install/setup.bash", "/home/zar/dep")
    assert resolved == "source /home/zar/dep/install/setup.bash"


def test_dest_placeholder_is_not_double_prefixed():
    """A regression: substitution then prefixing produced `dest/dest/...`."""
    resolved = L.resolve_environment_line("source {{dest}}/install/setup.bash", "/home/zar/dep")
    assert resolved == "source /home/zar/dep/install/setup.bash"
    assert resolved.count("/home/zar/dep") == 1


def test_absolute_source_is_left_alone():
    resolved = L.resolve_environment_line("source /opt/ros/jazzy/setup.bash", "/dest")
    assert resolved == "source /opt/ros/jazzy/setup.bash"


# ---------------------------------------------------------------------------
# Unit rendering
# ---------------------------------------------------------------------------


def test_unit_uses_the_project_entrypoint():
    """caasi supplies structure; the project supplies what actually runs."""
    unit = L.render_systemd_unit(_decl(entrypoint="ros2 launch demo bootloader.launch.py"), "/dep")
    assert "ros2 launch demo bootloader.launch.py" in unit
    assert "ExecStart=" in unit


def test_unit_runs_a_login_shell_so_sources_apply():
    unit = L.render_systemd_unit(
        _decl(entrypoint="ros2 launch demo x", environment=["source /opt/ros/jazzy/setup.bash"]),
        "/dep",
    )
    exec_line = [ln for ln in unit.splitlines() if ln.startswith("ExecStart=")][0]
    assert "bash -lc" in exec_line
    assert "source /opt/ros/jazzy/setup.bash" in exec_line
    # `exec` so the entrypoint replaces the shell and systemd tracks the real PID.
    assert "exec ros2 launch demo x" in exec_line


def test_unit_references_the_env_fragment():
    unit = L.render_systemd_unit(_decl(environment=["export A=1"]), "/dep")
    assert f"EnvironmentFile=-/dep/{L.ENV_FRAGMENT}" in unit


def test_unit_working_directory_defaults_to_destination():
    unit = L.render_systemd_unit(_decl(working_dir="."), "/dep")
    assert "WorkingDirectory=/dep/" in unit


def test_unit_working_directory_absolute_is_honoured():
    unit = L.render_systemd_unit(_decl(working_dir="/srv/robot"), "/dep")
    assert "WorkingDirectory=/srv/robot" in unit


def test_unit_restart_policy_comes_from_the_project():
    unit = L.render_systemd_unit(_decl(restart="always"), "/dep")
    assert "Restart=always" in unit


def test_rendering_an_undeclared_runtime_is_an_error():
    with pytest.raises(L.RuntimeLifecycleError):
        L.render_systemd_unit(L.parse_runtime(None), "/dep")


# ---------------------------------------------------------------------------
# State serialisation
# ---------------------------------------------------------------------------


def test_runtime_state_round_trips():
    state = L.RuntimeState(deployment_id="d1", git_revision="abc", unit="x.service",
                           previous={"deployment_id": "d0"})
    assert L.RuntimeState.from_dict(state.to_dict()) == state


def test_runtime_state_ignores_unknown_keys():
    """An older/newer marker must not crash the reader."""
    state = L.RuntimeState.from_dict({"deployment_id": "d1", "future_field": 1})
    assert state.deployment_id == "d1"


def test_marker_path_is_inside_the_destination():
    assert L.marker_path("/dep") == f"/dep/{L.REVISION_MARKER}"


# ---------------------------------------------------------------------------
# Revision comparison
# ---------------------------------------------------------------------------


def test_dirty_suffix_is_not_a_different_revision():
    """`-dirty` describes the workstation tree, not the content identity."""
    assert L._same_revision("abc-dirty", "abc") is True
    assert L._same_revision("abc", "abc-dirty") is True


def test_genuinely_different_revisions_do_not_match():
    assert L._same_revision("abc", "def") is False


def test_missing_revision_does_not_match():
    assert L._same_revision(None, "abc") is False


# ---------------------------------------------------------------------------
# Rollback feasibility - the honesty rules
# ---------------------------------------------------------------------------


def test_rollback_refuses_without_a_previous_revision(tmp_path):
    ok, why = L.check_rollback_feasibility(SSH_TARGET, tmp_path, None)
    assert ok is False
    assert "nothing to roll back to" in why


def test_rollback_refuses_when_workstation_is_at_a_different_revision(monkeypatch, tmp_path):
    monkeypatch.setattr(L, "check_rollback_feasibility",
                        L.check_rollback_feasibility.__wrapped__
                        if hasattr(L.check_rollback_feasibility, "__wrapped__")
                        else L.check_rollback_feasibility)
    from caasi.core import provenance
    monkeypatch.setattr(provenance, "git_info",
                        lambda root: {"available": True, "head": "aaa", "dirty": False})
    ok, why = L.check_rollback_feasibility(SSH_TARGET, tmp_path, "bbb")
    assert ok is False
    assert "check out bbb" in why


def test_rollback_refuses_when_there_is_no_git_revision(monkeypatch, tmp_path):
    from caasi.core import provenance
    monkeypatch.setattr(provenance, "git_info",
                        lambda root: {"available": True, "head": None, "dirty": False})
    ok, why = L.check_rollback_feasibility(SSH_TARGET, tmp_path, "abc")
    assert ok is False
    assert "no git revision" in why


def test_rollback_allowed_when_revision_matches_and_tree_is_clean(monkeypatch, tmp_path):
    from caasi.core import provenance
    monkeypatch.setattr(provenance, "git_info",
                        lambda root: {"available": True, "head": "abc", "dirty": False})
    ok, why = L.check_rollback_feasibility(SSH_TARGET, tmp_path, "abc")
    assert ok is True
    assert why is None


def test_caasi_bookkeeping_is_not_treated_as_uncommitted_work(monkeypatch, tmp_path):
    """`git status` counts .caasi/ as dirt, but caasi wrote it and never deploys it.

    Treating it as user dirt produced a message telling the operator to check out
    the revision they were already on.
    """
    from caasi.core import provenance
    from caasi.utils import shell

    monkeypatch.setattr(provenance, "git_info",
                        lambda root: {"available": True, "head": "abc", "dirty": True})
    monkeypatch.setattr(shell, "run_cmd",
                        lambda argv, timeout=None: ShellResult(
                            0, "?? .caasi/deployments/robot/d1.json\n", ""))
    ok, why = L.check_rollback_feasibility(SSH_TARGET, tmp_path, "abc")
    assert ok is True
    assert why is None


def test_substantive_uncommitted_changes_block_rollback(monkeypatch, tmp_path):
    from caasi.core import provenance
    from caasi.utils import shell

    monkeypatch.setattr(provenance, "git_info",
                        lambda root: {"available": True, "head": "abc", "dirty": True})
    monkeypatch.setattr(shell, "run_cmd",
                        lambda argv, timeout=None: ShellResult(0, " M src/app.py\n", ""))
    ok, why = L.check_rollback_feasibility(SSH_TARGET, tmp_path, "abc")
    assert ok is False
    assert "uncommitted changes" in why


# ---------------------------------------------------------------------------
# Install / install plan
# ---------------------------------------------------------------------------


def test_install_writes_env_unit_and_marker(monkeypatch, tmp_path):
    written: dict[str, str] = {}

    def fake_write(target, path, content, timeout=None):
        written[path] = content
        return ShellResult(0, "", "")

    monkeypatch.setattr(L, "_write_remote", fake_write)
    monkeypatch.setattr(L, "_ssh", lambda *a, **k: ShellResult(0, "/home/zar/.config/systemd/user\n", ""))

    result, plan = L.install_runtime(
        SSH_TARGET, _decl(environment=["export A=1"]), "/dep", "dep-1", "rev-1",
        project="demo",
    )

    assert result.ok is True
    assert plan.env_fragment_path in written
    assert plan.unit_path in written
    assert L.marker_path("/dep") in written
    marker = json.loads(written[L.marker_path("/dep")])
    assert marker["deployment_id"] == "dep-1"
    assert marker["git_revision"] == "rev-1"
    # A first install has nothing to roll back to.
    assert marker["previous"] is None


def test_install_records_the_previous_revision(monkeypatch):
    written: dict[str, str] = {}
    monkeypatch.setattr(L, "_write_remote",
                        lambda target, path, content, timeout=None: (written.__setitem__(path, content), ShellResult(0, "", ""))[1])
    monkeypatch.setattr(L, "_ssh", lambda *a, **k: ShellResult(0, "/u\n", ""))

    prior = L.RuntimeState(deployment_id="dep-0", git_revision="rev-0")
    L.install_runtime(SSH_TARGET, _decl(), "/dep", "dep-1", "rev-1",
                      previous_state=prior)

    marker = json.loads(written[L.marker_path("/dep")])
    assert marker["previous"]["deployment_id"] == "dep-0"


def test_install_reports_which_write_failed(monkeypatch):
    """A partial install must say what failed, not fail silently."""
    def fake_write(target, path, content, timeout=None):
        if path.endswith(L.ENV_FRAGMENT):
            return ShellResult(1, "", "permission denied")
        return ShellResult(0, "", "")

    monkeypatch.setattr(L, "_write_remote", fake_write)
    monkeypatch.setattr(L, "_ssh", lambda *a, **k: ShellResult(0, "/u\n", ""))

    result, _ = L.install_runtime(SSH_TARGET, _decl(), "/dep", "dep-1", "rev-1")
    assert result.ok is False
    assert "permission denied" in result.detail


def test_install_dry_run_writes_nothing(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(L, "_write_remote",
                        lambda target, path, content, timeout=None: (calls.append(path), ShellResult(0, "", ""))[1])
    monkeypatch.setattr(L, "_ssh", lambda *a, **k: ShellResult(0, "/u\n", ""))

    result, plan = L.install_runtime(SSH_TARGET, _decl(), "/dep", "d", "r", dry_run=True)
    assert result.ok is True
    assert calls == []
    assert plan.unit_path.endswith("demo.service")


def test_install_refuses_an_undeclared_runtime():
    with pytest.raises(L.RuntimeLifecycleError):
        L.install_runtime(SSH_TARGET, L.parse_runtime(None), "/dep", "d", "r")


# ---------------------------------------------------------------------------
# Enable / start / status delegation
# ---------------------------------------------------------------------------


def test_enable_invokes_systemctl(monkeypatch):
    seen: list[list[str]] = []
    monkeypatch.setattr(L, "_ssh",
                        lambda target, argv, timeout=None: (seen.append(argv), ShellResult(0, "linked\n", ""))[1])
    result = L.enable_runtime(SSH_TARGET, "demo.service")
    assert result.ok is True
    assert seen[0][:4] == ["systemctl", "--user", "enable", "demo.service"]


def test_disable_invokes_the_disable_verb(monkeypatch):
    seen: list[list[str]] = []
    monkeypatch.setattr(L, "_ssh",
                        lambda target, argv, timeout=None: (seen.append(argv), ShellResult(0, "", ""))[1])
    L.enable_runtime(SSH_TARGET, "demo.service", enable=False)
    assert seen[0][:3] == ["systemctl", "--user", "disable"]


def test_start_invokes_systemctl(monkeypatch):
    seen: list[list[str]] = []
    monkeypatch.setattr(L, "_ssh",
                        lambda target, argv, timeout=None: (seen.append(argv), ShellResult(0, "", ""))[1])
    L.start_runtime(SSH_TARGET, "demo.service")
    assert seen[0][:3] == ["systemctl", "--user", "start"]


def test_status_reports_what_systemd_says(monkeypatch):
    def fake_ssh(target, argv, timeout=None):
        joined = " ".join(argv)
        if "show" in joined:
            return ShellResult(0, "ActiveState=active\nSubState=running\n"
                                  "UnitFileState=enabled\nMainPID=123\nExecMainStatus=0\n", "")
        if "is-enabled" in joined:
            return ShellResult(0, "enabled\n", "")
        return ShellResult(0, "active\n", "")

    monkeypatch.setattr(L, "_ssh", fake_ssh)
    status = L.runtime_status(SSH_TARGET, "demo.service")
    assert status["running"] is True
    assert status["enabled"] is True
    assert status["main_pid"] == "123"


def test_status_of_an_unknown_unit_is_not_running(monkeypatch):
    monkeypatch.setattr(L, "_ssh",
                        lambda target, argv, timeout=None: ShellResult(3, "inactive\nnot-found\n", ""))
    status = L.runtime_status(SSH_TARGET, "ghost.service")
    assert status["running"] is False
    assert status["enabled"] is False


# ---------------------------------------------------------------------------
# Verify - revision identity and drift
# ---------------------------------------------------------------------------


def _stub_verify(monkeypatch, *, marker, systemd):
    monkeypatch.setattr(L, "read_runtime_state", lambda *a, **k: marker)
    monkeypatch.setattr(L, "runtime_status", lambda *a, **k: systemd)


def _healthy_systemd():
    return {"unit": "demo.service", "active_state": "active", "sub_state": "running",
            "unit_file_state": "enabled", "main_pid": "1", "exec_main_status": "0",
            "enabled": True, "running": True}


def test_verify_passes_when_revision_matches(monkeypatch):
    _stub_verify(monkeypatch, marker=L.RuntimeState(deployment_id="d1", git_revision="abc",
                                                    unit="demo.service"),
                 systemd=_healthy_systemd())
    ok, problems, _ = L.verify_runtime(SSH_TARGET, "demo.service", "/dep",
                                       expect_deployment_id="d1", expect_git_revision="abc")
    assert ok is True
    assert problems == []


def test_verify_detects_revision_drift(monkeypatch):
    _stub_verify(monkeypatch, marker=L.RuntimeState(deployment_id="d1", git_revision="OLD",
                                                    unit="demo.service"),
                 systemd=_healthy_systemd())
    ok, problems, _ = L.verify_runtime(SSH_TARGET, "demo.service", "/dep",
                                       expect_git_revision="NEW")
    assert ok is False
    assert any("active git revision" in p for p in problems)


def test_verify_detects_a_stopped_service(monkeypatch):
    """Files can be correct while nothing is running."""
    sd = _healthy_systemd()
    sd.update(active_state="inactive", running=False)
    _stub_verify(monkeypatch, marker=L.RuntimeState(deployment_id="d1", git_revision="abc",
                                                    unit="demo.service"), systemd=sd)
    ok, problems, _ = L.verify_runtime(SSH_TARGET, "demo.service", "/dep")
    assert ok is False
    assert any("not active" in p for p in problems)


def test_verify_detects_an_installed_but_disabled_unit(monkeypatch):
    sd = _healthy_systemd()
    sd.update(unit_file_state="disabled", enabled=False)
    _stub_verify(monkeypatch, marker=L.RuntimeState(deployment_id="d1", git_revision="abc",
                                                    unit="demo.service"), systemd=sd)
    ok, problems, _ = L.verify_runtime(SSH_TARGET, "demo.service", "/dep")
    assert ok is False
    assert any("not enabled" in p for p in problems)


def test_verify_detects_a_never_installed_runtime(monkeypatch):
    _stub_verify(monkeypatch, marker=None, systemd={"unit": "demo.service", "enabled": False,
                                                    "running": False, "unit_file_state": "not-found",
                                                    "active_state": "inactive"})
    ok, problems, evidence = L.verify_runtime(SSH_TARGET, "demo.service", "/dep")
    assert ok is False
    assert evidence["runtime_state"] is None
    assert any("never installed" in p for p in problems)


def test_verify_does_not_care_that_a_rollback_changed_the_deployment_id(monkeypatch):
    """A deployment id identifies one deployment *act*; a rollback legitimately
    produces a new one while the revision is what the operator cares about."""
    _stub_verify(monkeypatch, marker=L.RuntimeState(deployment_id="new-act", git_revision="abc",
                                                    unit="demo.service"),
                 systemd=_healthy_systemd())
    ok, problems, evidence = L.verify_runtime(SSH_TARGET, "demo.service", "/dep",
                                              expect_deployment_id="old-act",
                                              expect_git_revision="abc")
    assert ok is True
    assert evidence["deployment_id_matches"] is False
    assert evidence["revision_matches"] is True


# ---------------------------------------------------------------------------
# Rollback behaviour
# ---------------------------------------------------------------------------


def test_rollback_refuses_without_a_marker(monkeypatch):
    monkeypatch.setattr(L, "read_runtime_state", lambda *a, **k: None)
    result = L.rollback_runtime(SSH_TARGET, _decl(), "/dep")
    assert result.ok is False
    assert "nothing to roll back to" in result.detail


def test_rollback_refuses_without_a_previous_revision(monkeypatch):
    monkeypatch.setattr(L, "read_runtime_state",
                        lambda *a, **k: L.RuntimeState(deployment_id="d1", previous=None))
    result = L.rollback_runtime(SSH_TARGET, _decl(), "/dep")
    assert result.ok is False
    assert "no previous revision" in result.detail


def test_rollback_requires_a_redeploy_function(monkeypatch):
    """Rollback restores content; it cannot be a marker rewrite alone."""
    monkeypatch.setattr(
        L, "read_runtime_state",
        lambda *a, **k: L.RuntimeState(deployment_id="d2", git_revision="B",
                                       previous={"deployment_id": "d1", "git_revision": "A"}),
    )
    result = L.rollback_runtime(SSH_TARGET, _decl(), "/dep")
    assert result.ok is False
    assert "redeploy" in result.detail


def test_rollback_refuses_when_feasibility_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(
        L, "read_runtime_state",
        lambda *a, **k: L.RuntimeState(deployment_id="d2", git_revision="B",
                                       previous={"deployment_id": "d1", "git_revision": "A"}),
    )
    monkeypatch.setattr(L, "check_rollback_feasibility",
                        lambda *a, **k: (False, "workstation is elsewhere"))
    called = []
    result = L.rollback_runtime(SSH_TARGET, _decl(), "/dep", source_root=tmp_path,
                                redeploy=lambda: called.append(True))
    assert result.ok is False
    assert "workstation is elsewhere" in result.detail
    # Nothing was redeployed, so the target is untouched.
    assert called == []


def test_rollback_does_not_touch_the_target_when_redeploy_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(
        L, "read_runtime_state",
        lambda *a, **k: L.RuntimeState(deployment_id="d2", git_revision="B",
                                       previous={"deployment_id": "d1", "git_revision": "A"}),
    )
    monkeypatch.setattr(L, "check_rollback_feasibility", lambda *a, **k: (True, None))
    writes = []
    monkeypatch.setattr(L, "_write_remote",
                        lambda *a, **k: (writes.append(a), ShellResult(0, "", ""))[1])

    result = L.rollback_runtime(
        SSH_TARGET, _decl(), "/dep", source_root=tmp_path,
        redeploy=lambda: L.LifecycleResult("redeploy", False, "robot", detail="rsync failed"),
    )
    assert result.ok is False
    assert "rsync failed" in result.detail
    # The marker must not be rewritten when the content was not restored.
    assert writes == []


def test_successful_rollback_records_the_previous_revision_as_active(monkeypatch, tmp_path):
    monkeypatch.setattr(
        L, "read_runtime_state",
        lambda *a, **k: L.RuntimeState(deployment_id="d2", git_revision="B", unit="demo.service",
                                       previous={"deployment_id": "d1", "git_revision": "A"}),
    )
    monkeypatch.setattr(L, "check_rollback_feasibility", lambda *a, **k: (True, None))
    written: dict[str, str] = {}
    monkeypatch.setattr(L, "_write_remote",
                        lambda t, p, c, timeout=None: (written.__setitem__(p, c), ShellResult(0, "", ""))[1])
    monkeypatch.setattr(L, "_ssh", lambda *a, **k: ShellResult(0, "", ""))
    monkeypatch.setattr(L, "verify_runtime", lambda *a, **k: (True, [], {}))

    result = L.rollback_runtime(
        SSH_TARGET, _decl(), "/dep", source_root=tmp_path,
        redeploy=lambda: L.LifecycleResult("redeploy", True, "robot"),
    )
    assert result.ok is True
    marker = json.loads(written[L.marker_path("/dep")])
    assert marker["git_revision"] == "A"
    # Rollback is itself reversible.
    assert marker["previous"]["git_revision"] == "B"


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


def test_update_carries_the_rollback_chain_forward_on_a_reinstall(monkeypatch):
    """Re-installing the same revision must not wipe the rollback point.

    A plain `runtime install` after a deploy would otherwise reset `previous` to
    null, leaving rollback with nothing to return to.
    """
    prior = L.RuntimeState(deployment_id="d2", git_revision="B",
                           previous={"deployment_id": "d1", "git_revision": "A"})
    monkeypatch.setattr(L, "read_runtime_state", lambda *a, **k: prior)
    written: dict[str, str] = {}
    monkeypatch.setattr(L, "_write_remote",
                        lambda t, p, c, timeout=None: (written.__setitem__(p, c), ShellResult(0, "", ""))[1])
    monkeypatch.setattr(L, "_ssh", lambda *a, **k: ShellResult(0, "/u\n", ""))
    monkeypatch.setattr(L, "verify_runtime", lambda *a, **k: (True, [], {}))

    # Same deployment id and revision: an update in name only.
    result, _plan, _prev = L.update_runtime(SSH_TARGET, _decl(), "/dep", "d2", "B")
    assert result.ok is True
    marker = json.loads(written[L.marker_path("/dep")])
    assert marker["previous"]["deployment_id"] == "d1"


def test_update_fails_when_verification_fails(monkeypatch):
    monkeypatch.setattr(L, "read_runtime_state", lambda *a, **k: None)
    monkeypatch.setattr(L, "_write_remote", lambda *a, **k: ShellResult(0, "", ""))
    monkeypatch.setattr(L, "_ssh", lambda *a, **k: ShellResult(0, "/u\n", ""))
    monkeypatch.setattr(L, "verify_runtime",
                        lambda *a, **k: (False, ["unit demo.service is not active (state=failed)"], {}))

    result, _plan, _prev = L.update_runtime(SSH_TARGET, _decl(), "/dep", "d1", "A")
    assert result.ok is False
    assert "verification failed" in result.detail
    assert "state=failed" in result.detail


def test_update_reports_the_failed_install_without_restarting(monkeypatch):
    monkeypatch.setattr(L, "read_runtime_state", lambda *a, **k: None)
    monkeypatch.setattr(L, "_write_remote", lambda *a, **k: ShellResult(1, "", "disk full"))
    calls: list[list[str]] = []
    monkeypatch.setattr(L, "_ssh",
                        lambda target, argv, timeout=None: (calls.append(argv), ShellResult(0, "", ""))[1])

    result, _plan, _prev = L.update_runtime(SSH_TARGET, _decl(), "/dep", "d1", "A")
    assert result.ok is False
    assert "disk full" in result.detail
    # A failed install must not be followed by a restart of the broken unit.
    assert not any("restart" in c for c in calls)
