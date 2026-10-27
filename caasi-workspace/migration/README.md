# Migration campaign working area (ROS 1 ⇄ ROS 2 equivalence)

Evidence and tooling for comparing the original Ubuntu 20.04 / ROS 1 Noetic robot with the
Ubuntu 24.04 / ROS 2 Jazzy migration, on the **same physical robot** (`swjtumover05`) in the
walled maze.

```
scripts/     render_run.py, render_map.py  — visual reports from recorded data (no display needed)
data/        derived datasets: map, trace JSON, measurement summary (raw bags stay outside git)
figures/     rendered PNGs for human inspection
```

## Why rendering instead of RViz

RViz needs a display, and the robot is headless. Rendering from recorded data works for both
systems with identical code, so the two figures are directly comparable, and it can be rerun
offline at any time. The figures are for a human to look at; the numbers next to them are what
the campaign judges.

## ROS 1 baseline (captured 2026-10-27)

See `data/ros1_summary.json` for the numbers and `figures/ros1_mapping_run.png` /
`figures/ros1_maze_map.png` for the visuals.

Key reference values:

| quantity | ROS 1 (Ubuntu 20.04 / Noetic) |
| --- | --- |
| scan | 14.059 Hz, 1440 samples, `lidar_link`, ±3.141592503, inc 0.004363323, 0.25–25 m |
| scan invalid | 1401 valid / 39 no-return / 0 infinite |
| odometry | 25.245 Hz, `odom` → `base_link`, quaternion norm 1.0 |
| `base_link → lidar_link` | xyz (0, 0, **0.14114**), rpy (**0.02618**, 0, 0) — published by robot_state_publisher from the URDF |
| `odom → base_link` | motor_node (single owner in ROS 1) |
| forward 0.10 m/s × 2 s | 0.195 m and 0.176 m (ratio 0.976 / 0.881), yaw +0.017 / +0.014 rad |
| rotate 0.5 rad/s × 1 s | 0.510 rad (ratio 1.019) |
| motor watchdog | **none** — motor_node holds the last `cmd_vel` indefinitely |
| actuation gate | **none** in ROS 1: any `cmd_vel` publisher moves the robot |
| map (gmapping) | 0.05 m, walls over 6.2 × 6.2 m, scan-to-map median offset 2.6 cm |

Two consequences for the campaign:

* ROS 1 has **no command watchdog**. Stopping must be an explicit zero-velocity command; a
  killed node or a dropped connection does not stop the robot. ROS 2's `cmd_vel_timeout`
  watchdog is a genuine safety improvement, and ROS 1 motion tests must always end with an
  explicit zero (the campaign's scripts chain a zero-velocity fence for this reason).
* The ROS 1 URDF confirms the physical LiDAR mounting (`0.14114 m`, `1.500°` pitch) that the
  ROS 2 stack had been publishing as identity until commit `c5c8365`.

## Not yet established

* The existing `openmover_robot/maps/real-world/navigation.pgm` (8.5 × 9.55 m) has **not**
  been shown to describe this maze. A single-scan fit is not discriminating (it fits the
  simulation map equally well), and cross-correlating the fresh gmapping map against it gave
  only 30% overlap with a degenerate translation. Treat its provenance as unverified.
* ROS 1 navigation (amcl + move_base) behaviour was not captured.
* RealSense, screen and teleop behaviour under ROS 1 not captured (no display; screen payloads
  need separate authorisation).
