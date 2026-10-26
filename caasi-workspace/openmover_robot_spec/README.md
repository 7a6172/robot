# openmover_robot_spec — Robot ROS 1 Source Snapshot (IMMUTABLE REFERENCE)

This directory is a **read-only snapshot** of the ROS 1 source running on the physical
robot `swjtumover05` (Ubuntu 20.04.6, `/dev/sda2`). It exists so the robot's existing
implementation can be analysed and diffed without depending on the robot being online
or the partition being mounted.

**Do not edit anything under `src/`.** It is evidence, not a working tree.

## Provenance

| | |
|---|---|
| Captured | 2026-10-25T23:27:02+08:00 |
| Source | `swjtumover@10.212.19.95:/mnt/ubuntu20/home/swjtumover/swjtumover/swjtumover_ws/src` |
| Partition | `/dev/sda2`, ext4, Ubuntu 20.04.6 LTS "Focal", ROS Noetic |
| Method | one-way `rsync -a` over SSH (Wi-Fi, `10.212.19.95`) |
| Files | 696 |
| Tree SHA-256 | `9d46a6c515dc74ae1d136baadfdb503a3e06fe8cd61ad915d189601c0b29b78d` |
| VCS | **none** — the robot source has no git history |

Per-file hashes: see `SNAPSHOT-MANIFEST.txt`.

**Version control:** the committed tree is the **regular-file source only** — 335 files, hash
`7a71cc1e924e370a2026790b1cf441ef52e354b5138b2ebf3a376c6669a26f2b`. Build output copied from
the robot (`vanjee_lidar_sdk/build/`, `vanjee_lidar_sdk/src/vanjee_driver/build/`) and the
absolute `src/CMakeLists.txt` symlink are excluded as regenerable/machine-specific. The manifest
records both hashes.

## Contents

- `swjtumover_bringup/` — motor_node, screen_node, teleop_node + launch/urdf/config
- `swjtumover_msgs/`    — `motor_state.msg` (only message)
- `vanjee_lidar_sdk/`   — Vanjee 718H ESL SDK, vendor **dual ROS 1 / ROS 2**

## Relationship to the lab code

This is **not** the code in `/openmover_robot`. It is a different robot with a different
chassis and a different sensor set. See
`caasi/plan/phases/phase-08/four-way-discrepancy-report.md` for the full comparison.

The motor wire protocol, however, is **byte-identical** to the lab's, and
`motor_node.cpp` is a ~78 % fork of the lab's `motor_handler.cpp`.

## Re-verifying this snapshot

```bash
cd caasi-workspace/openmover_robot_spec
find src -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum
# expect: 9d46a6c515dc74ae1d136baadfdb503a3e06fe8cd61ad915d189601c0b29b78d  -
```
