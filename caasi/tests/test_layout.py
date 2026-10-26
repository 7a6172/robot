"""The caasi directory layout is owned by caasi, not by the user.

These tests pin the tree so a future change is a deliberate decision, and so that the
default deployment destination keeps matching it instead of drifting back to an ad-hoc
"~/deployments/<project>" invented at a call site.
"""

from __future__ import annotations

import pytest

from caasi.core import layout


def test_root_and_roots_are_the_documented_tree():
    assert layout.ROOT == "~/caasi"
    assert layout.ROBOTS == "~/caasi/robots"
    assert layout.PROJECTS == "~/caasi/projects"
    assert layout.FLEET == "~/caasi/fleet"
    assert layout.WORKSPACES == "~/caasi/workspaces"
    assert layout.DATA == "~/caasi/data"
    assert layout.DATASETS == "~/caasi/data/datasets"
    assert layout.RECORDINGS == "~/caasi/data/recordings"
    assert layout.RESULTS == "~/caasi/data/results"
    assert layout.ARTIFACTS == "~/caasi/artifacts"
    assert layout.CACHE == "~/caasi/cache"


def test_every_root_lives_under_the_caasi_root():
    for root in layout.ALL_ROOTS:
        assert root.startswith("~/caasi/"), root
    assert len(set(layout.ALL_ROOTS)) == len(layout.ALL_ROOTS)


def test_robot_target_deploys_under_robots():
    assert layout.default_deployment_root("swjtumover05", ["robot"]) == (
        "~/caasi/robots/swjtumover05"
    )


def test_non_robot_target_deploys_under_workspaces():
    assert layout.default_deployment_root("gpu-builder", ["gpu", "compute"]) == (
        "~/caasi/workspaces/gpu-builder"
    )


def test_no_tags_defaults_to_workspaces():
    """An untagged target is not known to be a robot, so it is treated as compute."""
    assert layout.default_deployment_root("mystery") == "~/caasi/workspaces/mystery"


def test_robot_owns_the_robot_directory_itself():
    """A robot's code lives at robots/<robot>; the project name is not appended.

    swjtumover05 and openmover are two *robots*, not a robot and a project.
    """
    assert layout.deployment_destination("swjtumover05", "openmover", ["robot"]) == (
        "~/caasi/robots/swjtumover05"
    )
    assert layout.deployment_destination("openmover", "openmover", ["robot"]) == (
        "~/caasi/robots/openmover"
    )


def test_compute_target_still_gets_one_directory_per_project():
    assert layout.deployment_destination("gpu-builder", "openmover", ["gpu"]) == (
        "~/caasi/workspaces/gpu-builder/openmover"
    )


@pytest.mark.parametrize("tags", [["robot"], ["robot", "swjtumover", "wifi"]])
def test_robot_detection_is_by_tag_not_hostname(tags):
    """Any robot name works; nothing is hardcoded to our current robot."""
    assert layout.default_deployment_root("anyrobot07", tags) == "~/caasi/robots/anyrobot07"


def test_default_never_scatters_a_new_home_directory_entry():
    """The old default was ~/deployments/<project>, a new top-level entry per project."""
    dest = layout.deployment_destination("swjtumover05", "openmover", ["robot"])
    assert dest.startswith("~/caasi/"), dest
    assert "/deployments/" not in dest
