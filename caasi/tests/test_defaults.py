"""`caasi choose` and the resolution it feeds.

The point of a chosen target is that `-t` stops being mandatory — which makes it possible to act on
the wrong machine, so precedence and reporting are tested here rather than assumed.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from caasi import state
from caasi.cli.main import app
from caasi.core import project as project_core
from caasi.core import defaults as defaults_core
from caasi.core.config import Config


def write_config(tmp_path, monkeypatch, data):
    path = tmp_path / "caasi.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setenv("CAASI_CONFIG", str(path))
    state.reset()
    return path


TARGETS = {
    "targets": {
        "robot-01": {"host": "10.0.0.11", "user": "robot"},
        "robot-02": {"host": "10.0.0.12", "user": "robot"},
    }
}


def test_resolution_precedence(tmp_path, monkeypatch):
    """flag > session > chosen > local, each one overriding the next."""
    path = write_config(tmp_path, monkeypatch, {**TARGETS, "defaults": {"target": "robot-01"}})
    cfg = Config.load()

    monkeypatch.delenv(defaults_core.ENV_TARGET, raising=False)
    assert defaults_core.resolve_target_name(cfg) == "robot-01"
    assert defaults_core.target_origin(cfg) == defaults_core.ORIGIN_SELECTION

    monkeypatch.setenv(defaults_core.ENV_TARGET, "robot-02")
    assert defaults_core.resolve_target_name(cfg) == "robot-02"
    assert defaults_core.target_origin(cfg) == defaults_core.ORIGIN_SESSION

    assert defaults_core.resolve_target_name(cfg, "robot-01") == "robot-01"
    assert defaults_core.target_origin(cfg, "robot-01") == defaults_core.ORIGIN_FLAG

    monkeypatch.delenv(defaults_core.ENV_TARGET, raising=False)
    path.write_text(yaml.safe_dump(TARGETS), encoding="utf-8")
    state.reset()
    bare = Config.load()
    assert defaults_core.resolve_target_name(bare) == defaults_core.LOCAL
    assert defaults_core.target_origin(bare) == defaults_core.ORIGIN_DEFAULT


def test_the_note_says_which_machine_and_stays_silent_when_explicit(tmp_path, monkeypatch):
    write_config(tmp_path, monkeypatch, {**TARGETS, "defaults": {"target": "robot-01"}})
    monkeypatch.delenv(defaults_core.ENV_TARGET, raising=False)
    cfg = Config.load()

    assert defaults_core.target_note(cfg) == "target: robot-01 (from selection)"
    assert defaults_core.target_note(cfg, "robot-02") is None

    state.reset()
    write_config(tmp_path, monkeypatch, TARGETS)
    bare = Config.load()
    note = defaults_core.target_note(bare)
    assert "local" in note and "caasi choose target" in note


def test_choose_target_writes_the_default_and_rejects_unknown_names(runner, tmp_path, monkeypatch):
    path = write_config(tmp_path, monkeypatch, TARGETS)
    monkeypatch.delenv(defaults_core.ENV_TARGET, raising=False)

    result = runner.invoke(app, ["choose", "target", "robot-02"])
    assert result.exit_code == 0, result.output
    saved = yaml.safe_load(path.read_text())
    assert saved["defaults"]["target"] == "robot-02"

    result = runner.invoke(app, ["choose", "target", "nope"])
    assert result.exit_code == 1
    assert "Unknown target" in result.output
    # a rejected name must not overwrite the stored one
    assert yaml.safe_load(path.read_text())["defaults"]["target"] == "robot-02"


def test_choose_session_prints_an_export_instead_of_storing(runner, tmp_path, monkeypatch):
    path = write_config(tmp_path, monkeypatch, TARGETS)
    monkeypatch.delenv(defaults_core.ENV_TARGET, raising=False)

    result = runner.invoke(app, ["choose", "--session", "target", "robot-01"])
    assert result.exit_code == 0, result.output
    assert "export CAASI_TARGET=" in result.output
    assert "defaults" not in (yaml.safe_load(path.read_text()) or {})


def test_choose_show_reports_the_origin(runner, tmp_path, monkeypatch):
    write_config(tmp_path, monkeypatch, {**TARGETS, "defaults": {"target": "robot-01"}})
    monkeypatch.delenv(defaults_core.ENV_TARGET, raising=False)
    result = runner.invoke(app, ["choose"])
    assert result.exit_code == 0, result.output
    assert "robot-01" in result.output
    assert "selection" in result.output


def test_choose_project_validates_the_manifest(runner, tmp_path, monkeypatch):
    write_config(tmp_path, monkeypatch, TARGETS)
    project = tmp_path / "proj"
    project.mkdir()
    (project / project_core.PROJECT_FILE).write_text(
        yaml.safe_dump({"schema": 1, "name": "demo"}), encoding="utf-8")

    result = runner.invoke(app, ["choose", "project", str(project)])
    assert result.exit_code == 0, result.output

    result = runner.invoke(app, ["choose", "project", str(tmp_path / "nowhere")])
    assert result.exit_code == 1
    assert "No project called" in result.output


def test_a_chosen_project_applies_when_the_cwd_is_not_inside_one(tmp_path, monkeypatch):
    """The fallback is what lets commands run from anywhere once a project is chosen."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / project_core.PROJECT_FILE).write_text(
        yaml.safe_dump({"schema": 1, "name": "demo"}), encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    project_core.set_fallback_root(None)
    assert project_core.find_project_root() is None

    project_core.set_fallback_root(project)
    assert project_core.find_project_root() == project.resolve()
    # a caller that asks about a specific directory must not be redirected
    assert project_core.find_project_root(elsewhere) is None

    project_core.set_fallback_root(None)


def test_logs_without_a_query_reads_the_latest_run(runner, tmp_path, monkeypatch):
    """`caasi logs` alone must not be a usage error: the previous run is what you want."""
    write_config(tmp_path, monkeypatch, {"paths": {"runs": str(tmp_path / "runs")}})
    result = runner.invoke(app, ["logs", "--lines", "5"])
    # no runs exist in this scratch directory, so it reports that rather than a missing argument
    assert "Missing argument" not in result.output


# ---------------------------------------------------------------------------
# Finding a robot or a project by name in the caasi tree
# ---------------------------------------------------------------------------


def make_tree(home, relative, name="demo"):
    """Plant a project/robot manifest in the caasi layout under *home*."""
    root = home / "caasi" / relative
    root.mkdir(parents=True, exist_ok=True)
    (root / "caasi.yaml").write_text(
        yaml.safe_dump({"schema": 1, "name": name}), encoding="utf-8")
    return root


def test_a_name_is_searched_on_the_chosen_target_first(tmp_path, monkeypatch):
    """With a target chosen, the search happens there; `local` is only the fallback."""
    write_config(tmp_path, monkeypatch, {**TARGETS, "defaults": {"target": "robot-01"}})
    cfg = Config.load()
    machine, notice = defaults_core.working_machine(cfg)
    assert machine == "robot-01"
    assert notice is None

    # the other side is still reported, so "on the robot, not here" is distinguishable
    locations = defaults_core.search(cfg, "robot", "demo")
    assert any(loc.machine == "robot-01" and loc.path == "~/caasi/robots/demo"
               for loc in locations)


def test_no_target_says_so_and_searches_this_machine(tmp_path, monkeypatch):
    """The operator is told a search fell back, because the wrong copy is otherwise invisible."""
    write_config(tmp_path, monkeypatch, TARGETS)
    monkeypatch.delenv(defaults_core.ENV_TARGET, raising=False)
    cfg = Config.load()
    assert defaults_core.working_machine(cfg) == (
        defaults_core.LOCAL, defaults_core.NO_TARGET_NOTICE)


def test_robots_and_projects_look_in_different_roots():
    assert defaults_core.KIND_ROOTS["robot"] == ("robots",)
    assert defaults_core.KIND_ROOTS["project"] == ("projects", "workspaces")


def test_name_from_strips_the_tree_prefix():
    assert defaults_core.name_from("robot", "~/caasi/robots/swjtumover") == "swjtumover"
    assert defaults_core.name_from("project", "~/caasi/projects/hw1") == "hw1"
    # an explicit path is not a name and is returned untouched
    assert defaults_core.name_from("project", "/work/hw1") == "/work/hw1"


def test_choose_finds_a_robot_in_the_local_tree(runner, tmp_path, monkeypatch):
    """`caasi choose robot <name>` needs no path: the layout says where robots live."""
    home = tmp_path / "home"      # isolated_env points HOME here and creates it
    write_config(tmp_path, monkeypatch, TARGETS)
    planted = make_tree(home, "robots/demo")

    result = runner.invoke(app, ["choose", "robot", "demo"])
    assert result.exit_code == 0, result.output
    assert "no target set" in result.output
    assert yaml.safe_load((tmp_path / "caasi.yaml").read_text())["defaults"]["robot"] == "demo"
    found = defaults_core.resolve_named(Config.load(), "robot", "demo")
    assert found.machine == "local"
    # the reported path is the layout-relative one; on this machine it is the planted directory
    assert Path(found.path).expanduser() == planted


def test_choose_finds_a_project_in_the_local_tree_and_keeps_its_name(runner, tmp_path, monkeypatch):
    home = tmp_path / "home"      # isolated_env points HOME here and creates it
    write_config(tmp_path, monkeypatch, TARGETS)
    make_tree(home, "projects/hw1", name="hw1")

    result = runner.invoke(app, ["choose", "project", "hw1"])
    assert result.exit_code == 0, result.output
    # the name is stored, not the tree path: a path would be searched for as a name next time
    assert yaml.safe_load((tmp_path / "caasi.yaml").read_text())["defaults"]["project"] == "hw1"


def test_a_missing_name_names_the_places_it_looked(runner, tmp_path, monkeypatch):
    home = tmp_path / "home"      # isolated_env points HOME here and creates it
    write_config(tmp_path, monkeypatch, TARGETS)

    result = runner.invoke(app, ["choose", "project", "nope"])
    assert result.exit_code == 1
    assert "No project called 'nope'" in result.output
    assert "~/caasi/projects/nope" in result.output
    assert "~/caasi/workspaces/nope" in result.output


def test_a_bare_project_name_resolves_to_the_local_directory(tmp_path, monkeypatch):
    """A chosen name must still be a directory for the commands that read project files."""
    home = tmp_path / "home"      # isolated_env points HOME here and creates it
    write_config(tmp_path, monkeypatch, {**TARGETS, "defaults": {"project": "hw1"}})
    planted = make_tree(home, "projects/hw1", name="hw1")

    assert defaults_core.resolve_project_root(Config.load()) == planted


# ---------------------------------------------------------------------------
# Roles: simulation must not silently land on a machine without a GPU
# ---------------------------------------------------------------------------


def test_a_role_ignores_the_general_chosen_target(tmp_path, monkeypatch):
    """`caasi choose target robot` must not send simulation to the robot: it has no GPU.

    A role falls back to this machine, never to whatever machine happens to be current. Sending a
    workload somewhere it cannot run is worse than running it here, where caasi can report what the
    machine lacks.
    """
    write_config(tmp_path, monkeypatch, {
        **TARGETS,
        "defaults": {"target": "robot-01", "targets": {"gpu": "gpu-01"}},
    })
    cfg = Config.load()
    assert defaults_core.resolve_role_target_name(cfg, "gpu") == "gpu-01"

    # the general choice is not consulted at all
    write_config(tmp_path, monkeypatch, {**TARGETS, "defaults": {"target": "robot-01"}})
    assert defaults_core.resolve_role_target_name(Config.load(), "gpu") == defaults_core.LOCAL


def test_a_role_honours_flag_then_session(tmp_path, monkeypatch):
    write_config(tmp_path, monkeypatch, {
        **TARGETS, "defaults": {"targets": {"gpu": "gpu-01"}},
    })
    cfg = Config.load()
    monkeypatch.delenv(defaults_core.role_env("gpu"), raising=False)
    assert defaults_core.resolve_role_target_name(cfg, "gpu", "gpu-02") == "gpu-02"

    monkeypatch.setenv(defaults_core.role_env("gpu"), "gpu-03")
    assert defaults_core.resolve_role_target_name(cfg, "gpu") == "gpu-03"
    assert defaults_core.resolve_role_target_name(cfg, "gpu", "gpu-02") == "gpu-02"


def test_the_role_note_says_where_simulation_will_run(tmp_path, monkeypatch):
    write_config(tmp_path, monkeypatch, {**TARGETS, "defaults": {"targets": {"gpu": "gpu-01"}}})
    cfg = Config.load()
    monkeypatch.delenv(defaults_core.role_env("gpu"), raising=False)
    assert defaults_core.role_note(cfg, "gpu") == "gpu: gpu-01 (from defaults.targets.gpu)"

    state.reset()
    write_config(tmp_path, monkeypatch, TARGETS)
    note = defaults_core.role_note(Config.load(), "gpu")
    assert "local" in note and "--role gpu" in note
    assert defaults_core.role_note(Config.load(), "gpu", "gpu-01") is None


def test_choose_target_with_a_role_is_stored_separately(runner, tmp_path, monkeypatch):
    path = write_config(tmp_path, monkeypatch, TARGETS)
    monkeypatch.delenv(defaults_core.ENV_TARGET, raising=False)

    result = runner.invoke(app, ["choose", "target", "robot-02", "--role", "gpu"])
    assert result.exit_code == 0, result.output
    saved = yaml.safe_load(path.read_text())
    assert saved["defaults"]["targets"]["gpu"] == "robot-02"
    # the general choice is untouched: a role is not a machine-wide default
    assert "target" not in saved["defaults"]


# ---------------------------------------------------------------------------
# A chosen robot or project is where relative paths are looked up
# ---------------------------------------------------------------------------


def test_a_chosen_robot_makes_relative_paths_work_from_anywhere(tmp_path, monkeypatch, runner):
    """`caasi choose robot` must be worth doing: paths resolve into that robot's tree."""
    home = tmp_path / "home"
    robot = make_tree(home, "robots/demo")
    (robot / "experiments").mkdir()
    (robot / "experiments" / "bringup.yaml").write_text(
        yaml.safe_dump({"name": "demo-bringup", "backend": "python", "script": "x.py"}),
        encoding="utf-8")
    write_config(tmp_path, monkeypatch, TARGETS)
    assert runner.invoke(app, ["choose", "robot", "demo"]).exit_code == 0

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    from caasi.core import project as project_core

    assert project_core.resolve_path(Path("experiments/bringup.yaml")) == (
        robot / "experiments" / "bringup.yaml")
    assert project_core.chosen_robot_root() == robot


def test_a_path_that_exists_here_is_never_redirected(tmp_path, monkeypatch, runner):
    """Manual directory calling keeps working: the current directory wins over any choice."""
    home = tmp_path / "home"
    robot = make_tree(home, "robots/demo")
    (robot / "experiments").mkdir()
    (robot / "experiments" / "bringup.yaml").write_text("name: x\n", encoding="utf-8")
    write_config(tmp_path, monkeypatch, TARGETS)
    assert runner.invoke(app, ["choose", "robot", "demo"]).exit_code == 0

    here = tmp_path / "here"
    (here / "experiments").mkdir(parents=True)
    local = here / "experiments" / "bringup.yaml"
    local.write_text("name: local\n", encoding="utf-8")
    monkeypatch.chdir(here)

    from caasi.core import project as project_core

    assert project_core.resolve_path(Path("experiments/bringup.yaml")) == Path("experiments/bringup.yaml")


def test_an_experiment_path_resolves_through_the_chosen_tree(tmp_path, monkeypatch, runner):
    home = tmp_path / "home"
    robot = make_tree(home, "robots/demo")
    (robot / "experiments").mkdir()
    (robot / "scripts").mkdir()
    (robot / "scripts" / "launch.py").write_text("print('x')\n", encoding="utf-8")
    (robot / "experiments" / "bringup.yaml").write_text(
        yaml.safe_dump({"name": "demo", "backend": "python",
                        "script": "../scripts/launch.py"}), encoding="utf-8")
    write_config(tmp_path, monkeypatch, TARGETS)
    assert runner.invoke(app, ["choose", "robot", "demo"]).exit_code == 0

    monkeypatch.chdir(tmp_path / "home")
    from caasi.core import experiment as experiment_core

    exp = experiment_core.load_experiment("experiments/bringup.yaml")
    assert exp.config_path == robot / "experiments" / "bringup.yaml"
    # the script inside it is relative to the experiment, as always
    assert exp.script_path == robot / "scripts" / "launch.py"


def test_the_not_found_message_names_what_was_searched(tmp_path, monkeypatch, runner):
    home = tmp_path / "home"
    make_tree(home, "robots/demo")
    write_config(tmp_path, monkeypatch, TARGETS)
    assert runner.invoke(app, ["choose", "robot", "demo"]).exit_code == 0
    monkeypatch.chdir(tmp_path)

    from caasi.core import experiment as experiment_core

    message = experiment_core.experiment_not_found_message(Path("experiments/nope.yaml"))
    assert "also tried" in message
    assert "robots/demo" in message
