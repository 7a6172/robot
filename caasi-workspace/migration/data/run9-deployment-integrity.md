# Run 9: deployment integrity and a fresh sensor-contract measurement (robot charging)

The robot is on charge, so this round avoided the motor board entirely: a minimal stack of the
LiDAR adapter and `robot_state_publisher` only, started from the **deployed** caasi project.

## The `/scan` contract still matches ROS 1 exactly

Measured on the deployed build, compared with the baseline recorded from the ROS 1 robot:

| property | ROS 2 (measured) | ROS 1 (baseline) | |
| --- | --- | --- | --- |
| rate | 14.04 Hz | 14.059 Hz | same |
| samples | 1440 | 1440 | same |
| frame | `lidar_link` | `lidar_link` | same |
| angle min / max | ±3.141592741 | ±3.141592503 | same |
| angle increment | 0.004363323 | 0.004363323 | same |
| range min / max | 0.25 / 25.0 m | 0.25 / 25.0 m | same |
| `base_link -> lidar_link` | z 0.14114 m, roll 0.02618 (1.500°) | identical | same |

Two "differences" in the first run were mistakes in **my comparison script**, not the robot: the
recorded baseline `rpy` is `[roll, pitch, yaw]` and the LiDAR is tilted in **roll**, while I compared
against pitch; and a 14 s rate window makes 14.42 vs 14.06 Hz ordinary measurement noise. Corrected,
the contract verifies.

## Defect 16: the meshes were never installed

`CMakeLists.txt` installed `launch config urdf param rviz map` — but `robot_description.urdf` refers
to `package://swjtumover_bringup/meshes/...` **eight** distinct files (16 references). On the robot
the meshes were therefore absent, which is exactly the failure that shows up as rviz drawing a
bodyless robot. Not a build error, not a runtime error in the logs: a missing resource that only the
visualiser notices.

Fixed by installing `meshes`, and covered by a test that resolves every `package://` reference in the
URDF against the directories CMake actually installs — verified by removing `meshes` again (2
failures) and restoring it. On the robot afterwards: **8 package:// references, 0 missing**.

This is the sort of thing the user asked about directly — "the bringup and rviz module that is kind
of a core of swjtumover". rviz could never have shown the robot correctly.

## Deployment integrity, checked rather than assumed

| check | result |
| --- | --- |
| executables | 4 scripts + 2 `motor_node`/`screen_node` in `swjtumover_bringup`, `vanjee_scan_node` in `swjtumover_vanjee` |
| `MotorState` interface | 9 fields in the ROS 1 order: `header`, `phase_current`, `rpm`, `position_deg`, then the five fault flags |
| installed resources | 6 launch, 11 config, 8 param, 4 map, 1 urdf, 1 rviz, 8 meshes |
| `package://` resolution | 8 of 8 |

## State left behind

Minimal stack stopped, port 7000 free, no processes, temporary scripts removed from the robot.
