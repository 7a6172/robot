"""Tests for run result/output collection and routing (Phase 7 Stage E1).

These exercise caasi's own behaviour: classification, declaration matching,
routing policy, inventory, planning and record round-tripping. SSH and target
access are mocked, so no network is required.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from caasi.core import artifacts as A
from caasi.core.config import Config


# ---------------------------------------------------------------------------
# Classification and bookkeeping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,expected",
    [
        ("checkpoints/model.pt", "model"),
        ("results/metrics.json", "metrics"),
        ("video/episode.mp4", "media"),
        ("maps/grid.pgm", "map"),
        ("bag/run.mcap", "dataset"),
        ("weights.tar.gz", "archive"),
        ("run.log", "log"),
        ("notes.unknown", "other"),
        ("noext", "other"),
    ],
)
def test_classify_kind(path: str, expected: str) -> None:
    assert A.classify_kind(path) == expected


def test_provenance_bundle_is_not_an_artifact() -> None:
    """caasi's own provenance files must never be reported as run results.

    Observed during E1 validation: the run-directory provenance bundle was
    initially inventoried as artifacts, which is wrong - it is provenance.
    """
    for name in (
        "manifest.yaml", "environment.yaml", "hardware.yaml", "dependencies.yaml",
        "configuration.yaml", "git.json", "processes.json", "exit_code",
        "stdout.log", "stderr.log", "run.sh", "pid", "pgid",
    ):
        assert A.is_bookkeeping(name), f"{name} should be bookkeeping"


def test_declared_results_are_artifacts() -> None:
    assert not A.is_bookkeeping("outputs/results/metrics.json")
    assert not A.is_bookkeeping("outputs/checkpoints/model.pt")


# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------


def test_parse_outputs_accepts_short_and_long_forms() -> None:
    decls = A.parse_outputs([
        "results/*.json",
        {"path": "checkpoints/*.pt", "kind": "model", "destination": "target_local"},
    ])
    assert decls[0].pattern == "results/*.json"
    assert decls[0].kind == "metrics"          # inferred from the pattern
    assert decls[1].destination == "target_local"
    assert decls[1].kind == "model"


def test_parse_outputs_rejects_unknown_destination() -> None:
    with pytest.raises(A.ArtifactError):
        A.parse_outputs([{"path": "x/*", "destination": "somewhere-else"}])


def test_declaration_matches_glob_and_directory_prefix() -> None:
    glob_decl = A.OutputDeclaration(pattern="outputs/results/*.json", kind="metrics")
    assert glob_decl.matches("outputs/results/metrics.json")
    assert not glob_decl.matches("outputs/checkpoints/model.pt")

    dir_decl = A.OutputDeclaration(pattern="checkpoints", kind="model")
    assert dir_decl.matches("checkpoints/a.pt")
    assert not dir_decl.matches("results/a.json")


# ---------------------------------------------------------------------------
# Routing policy
# ---------------------------------------------------------------------------


def test_unclassified_defaults_to_target_local() -> None:
    """Nothing is copied by default; the record simply says where it is."""
    policy = A.RoutingPolicy()
    route = policy.for_artifact("other", [], "scratch.bin")
    assert route.destination == "target_local"
    assert route.reason == "unclassified"


def test_declaration_overrides_policy() -> None:
    decls = A.parse_outputs([
        {"path": "checkpoints/*.pt", "kind": "model", "destination": "target_local"},
    ])
    policy = A.RoutingPolicy()
    assert policy.for_artifact("model", decls, "checkpoints/m.pt").destination == "target_local"
    assert policy.for_artifact("model", decls, "checkpoints/m.pt").declared is True


def test_declared_without_destination_uses_kind_policy() -> None:
    decls = A.parse_outputs(["results/*.json"])
    policy = A.RoutingPolicy()
    route = policy.for_artifact("metrics", decls, "results/m.json")
    assert route.destination == "workstation"   # small results come back
    assert route.declared is True


def test_routing_policy_from_config() -> None:
    cfg = Config({"artifact_routing": {
        "metrics": {"destination": "target_local"},
        "unclassified": "workstation",
    }}, [])
    policy = A.RoutingPolicy.from_config(cfg)
    assert policy.by_kind["metrics"] == "target_local"
    assert policy.unclassified == "workstation"


def test_routing_policy_ignores_invalid_destinations() -> None:
    cfg = Config({"artifact_routing": {"metrics": {"destination": "mars"}}}, [])
    policy = A.RoutingPolicy.from_config(cfg)
    assert policy.by_kind.get("metrics") != "mars"


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------


def test_inventory_filters_to_declared_when_present(tmp_path: Path) -> None:
    """A declaration defines what the run produces, excluding source/scratch."""
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "metrics.json").write_text("{}")
    (tmp_path / "script.py").write_text("print(1)")
    (tmp_path / "scratch.tmp").write_text("junk")

    decls = A.parse_outputs(["results/*.json"])
    arts = A.inventory_directory(tmp_path, "run-1", declarations=decls)
    assert [a.path for a in arts] == ["results/metrics.json"]


def test_inventory_without_declaration_reports_everything(tmp_path: Path) -> None:
    """With nothing declared, a project still loses nothing."""
    (tmp_path / "results").mkdir()
    (tmp_path / "results" / "metrics.json").write_text("{}")
    (tmp_path / "other.bin").write_bytes(b"x")

    arts = A.inventory_directory(tmp_path, "run-1")
    assert {a.path for a in arts} == {"results/metrics.json", "other.bin"}


def test_inventory_hashes_small_files_by_default(tmp_path: Path) -> None:
    (tmp_path / "small.json").write_text('{"a":1}')
    arts = A.inventory_directory(tmp_path, "run-1", hash_max_bytes=1024)
    assert arts[0].sha256 is not None


def test_inventory_skips_hashing_large_files_unless_verified(tmp_path: Path) -> None:
    (tmp_path / "big.pt").write_bytes(b"0" * 4096)

    arts = A.inventory_directory(tmp_path, "run-1", hash_max_bytes=1024)
    assert arts[0].sha256 is None

    arts = A.inventory_directory(tmp_path, "run-1", verify=True, hash_max_bytes=1024)
    assert arts[0].sha256 is not None


def test_artifact_id_uses_content_when_hashed(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text('{"a":1}')
    (tmp_path / "b.json").write_text('{"a":1}')   # identical content

    arts = A.inventory_directory(tmp_path, "run-1")
    ids = sorted(a.artifact_id for a in arts)
    # Same bytes => same identity, regardless of path.
    assert ids[0] == ids[1]


# ---------------------------------------------------------------------------
# Collection planning
# ---------------------------------------------------------------------------


def test_plan_splits_fetch_and_leave() -> None:
    arts = [
        A.Artifact("id1", "run", "results/m.json", "metrics", 10, "target", "/t/m.json",
                   route=A.ArtifactRoute("workstation", "declared", True)),
        A.Artifact("id2", "run", "ckpt/m.pt", "model", 5000, "target", "/t/m.pt",
                   route=A.ArtifactRoute("target_local", "declared", True)),
    ]
    plan = A.plan_collection(arts)
    assert [a.path for a in plan.to_fetch] == ["results/m.json"]
    assert [a.path for a in plan.to_leave] == ["ckpt/m.pt"]
    assert plan.to_dict()["fetch_bytes"] == 10


def test_plan_does_not_fetch_what_is_already_local() -> None:
    """A local run's outputs are already on the workstation; nothing to copy."""
    arts = [A.Artifact("id", "run", "r.json", "metrics", 5, "workstation", "/h/r.json",
                       route=A.ArtifactRoute("workstation", "declared", True))]
    plan = A.plan_collection(arts)
    assert plan.to_fetch == []
    assert [a.path for a in plan.to_leave] == ["r.json"]


# ---------------------------------------------------------------------------
# Record round-trip
# ---------------------------------------------------------------------------


def test_artifact_record_round_trips(tmp_path: Path) -> None:
    arts = [
        A.Artifact(
            "abc123", "run-1", "results/m.json", "metrics", 29, "target",
            "/t/results/m.json", sha256="abc123def",
            route=A.ArtifactRoute("workstation", "declared-kind-policy", True),
            collected_to=str(tmp_path / "artifacts/results/m.json"), declared=True,
        ),
    ]
    record = A.ArtifactRecord(
        run_id="run-1", project="demo", target_name="box", target_transport="ssh",
        run_status="succeeded", deployment_id="dep-1", git_revision="abc",
        artifacts=arts,
    )
    path = A.save_artifact_record(record, tmp_path)
    assert path is not None and path.name == "artifacts.yaml"

    loaded = A.load_artifact_record(tmp_path)
    assert loaded is not None
    assert loaded.run_id == "run-1"
    assert loaded.deployment_id == "dep-1"
    assert loaded.run_status == "succeeded"
    assert len(loaded.artifacts) == 1
    got = loaded.artifacts[0]
    assert got.path == "results/m.json"
    assert got.sha256 == "abc123def"
    assert got.route.destination == "workstation"
    assert got.collected_to is not None
    assert loaded.total_bytes == 29
    assert loaded.by_kind() == {"metrics": 1}


def test_load_artifact_record_missing_is_none(tmp_path: Path) -> None:
    assert A.load_artifact_record(tmp_path) is None


# ---------------------------------------------------------------------------
# Lifecycle intent (E1.5)
# ---------------------------------------------------------------------------


def test_lifecycle_defaults_to_persistent() -> None:
    """An undeclared project is never treated as disposable."""
    assert A.resolve_lifecycle(None) == "persistent"
    assert A.resolve_lifecycle(Config({}, [])) == "persistent"


def test_lifecycle_resolution_precedence() -> None:
    cfg = Config({"lifecycle": "ephemeral"}, [])
    assert A.resolve_lifecycle(cfg) == "ephemeral"
    assert A.resolve_lifecycle(cfg, "persistent") == "persistent"   # explicit wins
    assert A.resolve_lifecycle(Config({"lifecycle": "nonsense"}, [])) == "persistent"


class _Rec:
    def __init__(self, lifecycle: str, releasable: bool) -> None:
        self.lifecycle = lifecycle
        self.releasable = releasable


@pytest.mark.parametrize(
    "lifecycle,releasable,expected",
    [
        ("ephemeral", True, True),
        ("ephemeral", False, False),    # uncollected results are not disposable
        ("persistent", True, False),    # a robot is never "releasable"
        ("persistent", False, False),
    ],
)
def test_releasable_requires_ephemeral_and_collection(
    lifecycle: str, releasable: bool, expected: bool
) -> None:
    assert A.is_releasable(_Rec(lifecycle, releasable)) is expected


def test_persistent_deployment_is_never_marked_releasable(
    tmp_path: Path, monkeypatch
) -> None:
    """Collecting a log from a robot must not make the robot look disposable."""
    import caasi.core.project as projects

    dep_dir = tmp_path / ".caasi" / "deployments" / "robot"
    dep_dir.mkdir(parents=True)
    (dep_dir / "dep-1.json").write_text(
        json.dumps({"deployment_id": "dep-1", "lifecycle": "persistent"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(projects, "find_project_root", lambda *a, **k: tmp_path)

    record = A.ArtifactRecord(run_id="r", target_name="robot", deployment_id="dep-1")
    changed, detail = A.mark_deployment_releasable(record, Config({}, []))
    assert changed is False
    assert "persistent" in detail

    data = json.loads((dep_dir / "dep-1.json").read_text())
    assert data.get("releasable") is not True


def test_ephemeral_deployment_is_marked_releasable_after_collection(
    tmp_path: Path, monkeypatch
) -> None:
    import caasi.core.project as projects

    dep_dir = tmp_path / ".caasi" / "deployments" / "gpu"
    dep_dir.mkdir(parents=True)
    (dep_dir / "dep-2.json").write_text(
        json.dumps({"deployment_id": "dep-2", "lifecycle": "ephemeral"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(projects, "find_project_root", lambda *a, **k: tmp_path)

    record = A.ArtifactRecord(run_id="r", target_name="gpu", deployment_id="dep-2")
    changed, detail = A.mark_deployment_releasable(record, Config({}, []))
    assert changed is True
    assert "recorded only" in detail

    data = json.loads((dep_dir / "dep-2.json").read_text())
    assert data["releasable"] is True
    assert data.get("releasable_at")
    # Recording only: the deployment metadata itself is otherwise untouched.
    assert data["deployment_id"] == "dep-2"
    assert data["lifecycle"] == "ephemeral"


def test_mark_releasable_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    import caasi.core.project as projects

    dep_dir = tmp_path / ".caasi" / "deployments" / "gpu"
    dep_dir.mkdir(parents=True)
    (dep_dir / "dep-3.json").write_text(
        json.dumps({"deployment_id": "dep-3", "lifecycle": "ephemeral",
                    "releasable": True}),
        encoding="utf-8",
    )
    monkeypatch.setattr(projects, "find_project_root", lambda *a, **k: tmp_path)
    record = A.ArtifactRecord(run_id="r", target_name="gpu", deployment_id="dep-3")
    changed, detail = A.mark_deployment_releasable(record, Config({}, []))
    assert changed is False
    assert "already" in detail


# ---------------------------------------------------------------------------
# Declared kind wins over extension inference
# ---------------------------------------------------------------------------


def test_declared_kind_overrides_extension_inference() -> None:
    """A declaration names the artifact better than its extension does.

    Found against real project data: SLAM/mapping results are .json, which
    extension inference calls 'metrics'. A project that declares them as 'map'
    must be believed.
    """
    decls = A.parse_outputs([{"path": "maps/*.json", "kind": "map"}])
    assert A.resolve_kind("maps/grid.json", decls) == "map"
    # Without a matching declaration, inference still applies.
    assert A.resolve_kind("maps/grid.json", []) == "metrics"
    assert A.resolve_kind("other/grid.json", decls) == "metrics"


def test_declared_kind_drives_routing(tmp_path: Path) -> None:
    (tmp_path / "maps").mkdir()
    (tmp_path / "maps" / "grid.json").write_text("{}")

    decls = A.parse_outputs([
        {"path": "maps/*.json", "kind": "map", "destination": "target_local"},
    ])
    arts = A.inventory_directory(tmp_path, "run-1", declarations=decls)
    assert arts[0].kind == "map"
    assert arts[0].route.destination == "target_local"


# ---------------------------------------------------------------------------
# The destination model, as documented (0.4.0 R9)
#
# `artifacts.py`'s module docstring is the authoritative reference for the routing
# model: the resolution order, the per-kind defaults, configuration, and what a
# third destination would require. These tests keep that documentation honest --
# prose that drifts from the code is worse than no prose.
# ---------------------------------------------------------------------------


def test_the_two_destinations_are_the_documented_ones() -> None:
    assert A.DESTINATIONS == ("workstation", "target_local")


def test_documented_resolution_order_holds() -> None:
    """declared -> declared-kind-policy -> kind-policy -> unclassified, in order."""
    policy = A.RoutingPolicy()
    decls = A.parse_outputs([
        {"path": "explicit.json", "kind": "metrics", "destination": "target_local"},
        {"path": "kinded.json", "kind": "metrics"},
    ])

    # 1. A declaration naming a destination wins outright.
    assert policy.for_artifact("log", decls, "explicit.json").reason == "declared"
    assert policy.for_artifact("log", decls, "explicit.json").destination == "target_local"

    # 2. A declaration without one falls back to its kind's policy.
    r = policy.for_artifact("log", decls, "kinded.json")
    assert r.reason == "declared-kind-policy"
    assert r.destination == "workstation"

    # 3. No declaration: the inferred kind's rule applies.
    r = policy.for_artifact("metrics", [], "anything.json")
    assert r.reason == "kind-policy"
    assert r.destination == "workstation"

    # 4. Nothing applies: the unclassified destination.
    r = policy.for_artifact("mystery", [], "anything.bin")
    assert r.reason == "unclassified"
    assert r.destination == "target_local"


def test_declared_flag_distinguishes_instruction_from_default() -> None:
    """A reader must be able to tell a deliberate declaration from a default."""
    policy = A.RoutingPolicy()
    decls = A.parse_outputs([{"path": "a.json", "kind": "metrics"}])
    assert policy.for_artifact("log", decls, "a.json").declared is True
    assert policy.for_artifact("metrics", [], "b.json").declared is False


def test_documented_per_kind_defaults() -> None:
    policy = A.RoutingPolicy()
    for kind in ("metrics", "report", "log"):
        assert policy.by_kind[kind] == "workstation"
    assert policy.unclassified == "target_local"


def test_documented_configuration_shape() -> None:
    """`artifact_routing` configures by kind, with a fallback key."""
    policy = A.RoutingPolicy.from_config(
        Config({"artifact_routing": {"metrics": "target_local", "default": "workstation"}}, [])
    )
    assert policy.by_kind["metrics"] == "target_local"
    assert policy.unclassified == "workstation"


def test_config_accepts_the_documented_fallback_aliases() -> None:
    for key in ("unclassified", "default", "*"):
        policy = A.RoutingPolicy.from_config(
            Config({"artifact_routing": {key: "workstation"}}, [])
        )
        assert policy.unclassified == "workstation"


def test_unknown_destination_in_config_is_ignored_not_guessed() -> None:
    """A typo must not silently route data somewhere unintended.

    `metrics` always exists in `by_kind` (it is a built-in default), so the check
    is that its value was NOT replaced by the unknown name -- not that the key is
    absent. A new kind is also rejected outright.
    """
    policy = A.RoutingPolicy.from_config(
        Config({"artifact_routing": {"metrics": "archive", "brand-new": "archive"}}, [])
    )
    assert policy.by_kind["metrics"] == "workstation"   # unchanged by the typo
    assert "archive" not in policy.by_kind.values()
    assert "brand-new" not in policy.by_kind


def test_a_third_destination_is_not_implemented() -> None:
    """R9 documents the extension point; it deliberately builds no third destination.

    If this ever changes, the module's documented prerequisites must be met --
    a name alone would produce a destination that cannot receive anything.
    """
    assert len(A.DESTINATIONS) == 2
    assert "archive" not in A.DESTINATIONS
    assert "store" not in A.DESTINATIONS


def test_the_extension_point_is_documented() -> None:
    """The docstring must state what a third destination would require."""
    doc = A.__doc__ or ""
    assert "THE DESTINATION MODEL" in doc
    assert "What a third destination would require" in doc
    # The explicit non-requirement matters as much as the requirements.
    assert "content-addressed store" in doc
    assert "object store" in doc
