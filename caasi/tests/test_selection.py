"""Tests for Stage F1: the Workload model and target-aware selection.

The design's central claim is that target selection **reuses the Check Contract**
rather than introducing a second compatibility semantics. These tests hold that
claim to account, and pin the evidence-discipline rules that make the feature
honest:

* an out-of-range version is a warning, never asserted as incompatibility (§57);
* a fact a target does not expose is *unmeasured*, not absent;
* a fact a target was asked about and lacks is a real *absence*.

The behaviour against real targets is recorded in the stage report.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from caasi.core import selection as S
from caasi.core import workload as W
from caasi.core.targets import (
    Target,
    TargetEnvironment,
    TargetInspection,
    TargetResources,
)


def _inspection(
    *,
    ros_distro: str | None = None,
    isaac_sim: dict | None = None,
    python_version: str | None = None,
    cuda_toolkit: str | None = None,
    docker: bool = False,
    gpus: list[dict] | None = None,
    reachable: bool = True,
    error: str | None = None,
) -> TargetInspection:
    return TargetInspection(
        target=Target(name="robot"),
        reachable=reachable,
        status="online" if reachable else "unreachable",
        environment=TargetEnvironment(
            ros_distro=ros_distro,
            isaac_sim=isaac_sim,
            python_version=python_version,
            cuda_toolkit=cuda_toolkit,
            docker=docker,
        ),
        resources=TargetResources(gpus=gpus if gpus is not None else []),
        discovered_capabilities=[],
        error=error,
    )


# ---------------------------------------------------------------------------
# Fact mapping - the source of truth changes, not the semantics
# ---------------------------------------------------------------------------


def test_ros_distro_is_mapped_to_the_contract_name():
    facts = S.target_facts(_inspection(ros_distro="jazzy"))
    assert facts["ros2"] == "jazzy"


def test_absent_facts_are_not_invented():
    """An unreported fact must not be back-filled from anywhere local."""
    facts = S.target_facts(_inspection())
    assert facts.get("ros2") is None
    assert facts.get("isaac_sim") is None


def test_isaac_dict_is_reduced_to_its_version():
    """Requirements compare against a version, not the discovery record."""
    facts = S.target_facts(_inspection(isaac_sim={"version": "4.5.0", "status": "detected"}))
    assert S._version_str(facts["isaac_sim"]) == "4.5.0"


def test_docker_is_reported_as_present_only_when_detected():
    assert S.target_facts(_inspection(docker=True))["docker"] == "present"
    assert not S.target_facts(_inspection(docker=False)).get("docker")


# ---------------------------------------------------------------------------
# The four verdict paths - each a deliberate rule
# ---------------------------------------------------------------------------


def test_satisfied_requirement_is_compatible():
    verdicts = S.evaluate_requirements(
        {"ros2": {"version": "jazzy"}}, {"ros2": "jazzy"}
    )
    assert verdicts[0].verdict == "compatible"


def test_satisfied_range_is_compatible():
    verdicts = S.evaluate_requirements(
        {"python": {"version": ">=3.10"}}, {"python": "3.12.3"}
    )
    assert verdicts[0].verdict == "compatible"


def test_out_of_range_is_a_warning_not_incompatible():
    """§57 evidence-not-guarantees: a version range alone asserts nothing."""
    verdicts = S.evaluate_requirements(
        {"ros2": {"version": "humble"}}, {"ros2": "jazzy"}
    )
    assert verdicts[0].verdict == "untested"
    assert "outside the required range" in verdicts[0].note


def test_out_of_range_reports_both_required_and_detected():
    verdicts = S.evaluate_requirements(
        {"ros2": {"version": "humble"}}, {"ros2": "jazzy"}
    )
    assert verdicts[0].required == "humble"
    assert verdicts[0].detected == "jazzy"


def test_probed_but_absent_component_is_missing():
    """The target was asked and does not have it, so the absence is real."""
    verdicts = S.evaluate_requirements(
        {"isaac_sim": {"version": ">=5.0"}}, {"isaac_sim": None}
    )
    assert verdicts[0].verdict == "missing"


def test_unprobed_component_is_untested_not_missing():
    """`torch` is never probed by target discovery, so its absence is not evidence.

    Reporting `missing` here would assert a fact nobody looked for.
    """
    verdicts = S.evaluate_requirements({"torch": {"version": ">=2.0"}}, {})
    assert verdicts[0].verdict == "untested"
    assert "not measured" in verdicts[0].note


def test_requirement_without_a_version_is_untested():
    verdicts = S.evaluate_requirements({"ros2": {}}, {"ros2": "jazzy"})
    assert verdicts[0].verdict == "untested"


# ---------------------------------------------------------------------------
# GPU - a resource, not a version, with measured absence
# ---------------------------------------------------------------------------


def test_gpu_requirement_met():
    verdicts = S.evaluate_requirements(
        {"gpu": {"count": 1, "memory_gb": 8}},
        {"gpu": [{"memory_total_mib": 10240.0}]},
    )
    assert verdicts[0].verdict == "compatible"


def test_no_gpus_reported_is_a_measured_absence():
    """An inspected target with zero GPUs is a definite 'no', not 'unknown'."""
    verdicts = S.evaluate_requirements({"gpu": {"count": 1}}, {"gpu": []})
    assert verdicts[0].verdict == "missing"
    assert verdicts[0].detected == "0"
    assert "no GPUs" in verdicts[0].note


def test_gpu_not_inspected_is_unmeasured():
    """Distinct from the above: nobody asked, so nothing is known."""
    verdicts = S.evaluate_requirements({"gpu": {"count": 1}}, {})
    assert verdicts[0].verdict == "untested"
    assert "not inspected" in verdicts[0].note


def test_gpu_memory_shortfall_is_a_warning_not_incompatible():
    """A GPU exists but is too small: reported, not asserted as incompatible."""
    verdicts = S.evaluate_requirements(
        {"gpu": {"memory_gb": 48}}, {"gpu": [{"memory_total_mib": 10240.0}]}
    )
    assert verdicts[0].verdict == "untested"
    assert "not asserted incompatible" in verdicts[0].note


def test_insufficient_gpu_count_is_missing():
    verdicts = S.evaluate_requirements({"gpu": {"count": 2}}, {"gpu": [{"memory_total_mib": 10240.0}]})
    assert verdicts[0].verdict == "missing"


# ---------------------------------------------------------------------------
# Target-level reporting
# ---------------------------------------------------------------------------


def test_unreachable_target_is_its_own_verdict():
    """Unreachable is a transport result, not a compatibility verdict."""
    report = S.select_target(
        Target(name="robot"), {"ros2": {"version": "jazzy"}},
        _inspection(reachable=False, error="Could not connect to 192.0.2.99:22"),
    )
    assert report.status == S.TARGET_UNREACHABLE
    assert report.reachable is False
    assert report.compatible is False
    assert "Could not connect" in report.error


def test_unreachable_target_is_not_evaluated():
    report = S.select_target(
        Target(name="robot"), {"ros2": {"version": "jazzy"}},
        _inspection(reachable=False),
    )
    assert report.verdicts == []


def test_missing_inspection_is_unreachable():
    report = S.select_target(Target(name="robot"), {"ros2": {}}, None)
    assert report.status == S.TARGET_UNREACHABLE


def test_ready_target_reports_compatible():
    report = S.select_target(
        Target(name="robot"), {"ros2": {"version": "jazzy"}},
        _inspection(ros_distro="jazzy"),
    )
    assert report.status == "ready"
    assert report.compatible is True


def test_incompatible_target_is_not_compatible():
    report = S.select_target(
        Target(name="robot"), {"isaac_sim": {"version": ">=5.0"}},
        _inspection(),
    )
    assert report.status == "incompatible"
    assert report.compatible is False


def test_select_all_covers_every_target_including_unreachable():
    """A target that cannot be inspected still appears, with a reason."""
    targets = [Target(name="a"), Target(name="b")]
    inspected = {"a": _inspection(ros_distro="jazzy"), "b": _inspection(reachable=False)}
    reports = S.select_all(targets, {"ros2": {"version": "jazzy"}}, inspected)
    assert [r.target for r in reports] == ["a", "b"]
    assert reports[1].status == S.TARGET_UNREACHABLE


def test_select_reports_serialise_unmeasured_as_first_class():
    report = S.select_target(Target(name="robot"), {"torch": {"version": ">=2"}},
                             _inspection())
    payload = report.to_dict()
    assert payload["verdicts"][0]["verdict"] == "untested"
    assert payload["verdicts"][0]["detected"] is None


# ---------------------------------------------------------------------------
# Workload model
# ---------------------------------------------------------------------------


def test_workload_parses_requirements():
    w = W.parse_workload({"name": "train", "requires": {"gpu": {"count": 1}}})
    assert w.name == "train"
    assert w.requires == {"gpu": {"count": 1}}


def test_workload_accepts_a_single_wrapped_block():
    """`workload: {...}` is a natural spelling in a project file."""
    w = W.parse_workload({"workload": {"name": "train", "requires": {"ros2": {}}}})
    assert w.name == "train"
    assert w.requires == {"ros2": {}}


def test_workload_rejects_a_mixed_wrapper():
    with pytest.raises(W.WorkloadError):
        W.parse_workload({"workload": {"name": "t"}, "requires": {"ros2": {}}})


def test_workload_rejects_unknown_keys():
    """A typo must be reported, not silently read as 'no requirements'."""
    with pytest.raises(W.WorkloadError) as err:
        W.parse_workload({"name": "t", "requiers": {"ros2": {}}})
    assert "unknown workload key" in str(err.value)


def test_workload_requires_must_be_a_mapping():
    with pytest.raises(W.WorkloadError):
        W.parse_workload({"name": "t", "requires": ["ros2"]})


def test_workload_needs_a_name():
    with pytest.raises(W.WorkloadError):
        W.parse_workload({"requires": {}})


def test_workload_name_falls_back_to_the_filename(tmp_path):
    path = tmp_path / "train.yaml"
    path.write_text("requires:\n  ros2: {}\n")
    w = W.load_workload(path)
    assert w.name == "train"


def test_load_workload_reports_a_missing_file():
    with pytest.raises(W.WorkloadError):
        W.load_workload("/nonexistent/workload.yaml")


def test_list_workloads_reads_the_directory(tmp_path):
    d = tmp_path / "workloads"
    d.mkdir()
    (d / "a.yaml").write_text("name: a\n")
    (d / "b.yml").write_text("name: b\n")
    assert sorted(w.name for w in W.list_workloads(tmp_path)) == ["a", "b"]


def test_list_workloads_is_empty_without_the_directory(tmp_path):
    assert W.list_workloads(tmp_path) == []


def test_find_workload_by_prefix(tmp_path):
    d = tmp_path / "workloads"
    d.mkdir()
    (d / "gpu-train.yaml").write_text("name: gpu-train\n")
    assert W.find_workload(tmp_path, "gpu").name == "gpu-train"


def test_find_workload_rejects_an_ambiguous_prefix(tmp_path):
    d = tmp_path / "workloads"
    d.mkdir()
    (d / "a.yaml").write_text("name: train-a\n")
    (d / "b.yaml").write_text("name: train-b\n")
    assert W.find_workload(tmp_path, "train") is None


def test_workload_requirements_extend_the_projects():
    merged = W.combined_requirements(
        {"ros2": {"version": "jazzy"}}, W.parse_workload({"name": "t", "requires": {"gpu": {"count": 1}}})
    )
    assert merged == {"ros2": {"version": "jazzy"}, "gpu": {"count": 1}}


def test_workload_requirement_wins_on_collision():
    """The workload is the more specific statement of what this work needs."""
    merged = W.combined_requirements(
        {"ros2": {"version": "humble"}},
        W.parse_workload({"name": "t", "requires": {"ros2": {"version": "jazzy"}}}),
    )
    assert merged["ros2"] == {"version": "jazzy"}


def test_combined_requirements_without_a_workload_is_the_project_requirements():
    merged = W.combined_requirements({"ros2": {}}, None)
    assert merged == {"ros2": {}}


def test_steps_and_outputs_parse_but_f1_does_not_act_on_them():
    """F1 records them so a workload declaring steps now still loads."""
    w = W.parse_workload({"name": "t", "steps": [{"run": {"command": "x"}}], "outputs": [{"path": "*.log"}]})
    assert w.steps == [{"run": {"command": "x"}}]
    assert w.outputs == [{"path": "*.log"}]

# ---------------------------------------------------------------------------
# Presence without a version (found on the real workstation)
# ---------------------------------------------------------------------------


def test_present_but_unversioned_is_not_reported_as_absent():
    """Isaac Sim was detected on the workstation with status ok and no version.

    Mapping that to None made the ladder read it as *absent*, reporting a machine
    that has Isaac Sim as not having it at all. The Check Contract's own
    convention (``_isaac_version`` returning "installed") is followed instead.
    """
    facts = S.target_facts(_inspection(isaac_sim={"status": "ok", "detail": "Isaac Sim at /x"}))
    assert S._version_str(facts["isaac_sim"]) == S.INSTALLED


def test_present_but_unversioned_requirement_is_untested_not_missing():
    verdicts = S.evaluate_requirements(
        {"isaac_sim": {"version": ">=5.0"}},
        {"isaac_sim": S.INSTALLED},
    )
    assert verdicts[0].verdict == "untested"
    assert verdicts[0].verdict != "missing"


def test_present_but_unversioned_note_names_the_cause():
    verdicts = S.evaluate_requirements(
        {"isaac_sim": {"version": ">=5.0"}}, {"isaac_sim": S.INSTALLED}
    )
    assert "version is not recorded" in verdicts[0].note


def test_a_failed_isaac_status_is_absent():
    """Status is what says whether the tool exists; a failure is a real absence."""
    facts = S.target_facts(_inspection(isaac_sim={"status": "fail"}))
    assert S._version_str(facts["isaac_sim"]) is None


def test_isaac_status_ok_with_a_version_uses_the_version():
    facts = S.target_facts(_inspection(isaac_sim={"status": "ok", "version": "4.5.0"}))
    assert S._version_str(facts["isaac_sim"]) == "4.5.0"


def test_present_but_unversioned_without_a_range_is_untested():
    """Even with no range declared, presence alone is not a comparison."""
    verdicts = S.evaluate_requirements({"isaac_sim": {}}, {"isaac_sim": S.INSTALLED})
    assert verdicts[0].verdict == "untested"
