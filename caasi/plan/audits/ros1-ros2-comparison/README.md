# ROS 1 ↔ ROS 2 comparison scripts

Reproducible tooling for
[`../ros1_to_ros2_functional_equivalence.md`](../ros1_to_ros2_functional_equivalence.md).

These scripts assume:

- the host reference trees at `/home/zar/Documents/phd/robot/{openmover_robot,openmover_ws}`
  (never written to), and
- for live ROS 1 captures, a running container named `ros1-ref` built from
  `osrf/ros:noetic-desktop-full` with the reference copied to `~/openmover_robot`.

## Reproduce from scratch

```bash
# 1. Stage the reference read-only and start the ROS 1 environment
bash stage_ros1.sh
docker run -d --name ros1-ref --network host --shm-size=2g \
  -v /tmp/ros1-ref-staging:/mnt/ref:ro osrf/ros:noetic-desktop-full sleep infinity
docker exec ros1-ref bash -c 'cp -r /mnt/ref ~/openmover_robot'

# 2. Execute install.sh in its own order (see `classify_steps.py` for the step audit)
docker cp ros1_install_phase1.sh ros1-ref:/root/phase1.sh && docker exec ros1-ref bash /root/phase1.sh
docker cp ros1_install_phase2.sh ros1-ref:/root/phase2.sh && docker exec ros1-ref bash /root/phase2.sh
docker cp ros1_install_phase4.sh ros1-ref:/root/phase4.sh && docker exec ros1-ref bash /root/phase4.sh

#    phase2 needs the container-side compatibility fixes first; see §2.1 of the audit:
#      - toplevel.cmake must be a symlink, not a 49-byte regular file
#      - relocalization_request.srv must exist (reference has RelocalizationRequest.srv)
#      - openmover_msgs/action/ must exist (reference has an empty add_action_files block)

# 3. Verify the ROS 1 system is operational, and capture live definitions
docker cp verify_ros1.sh      ros1-ref:/root/verify.sh && docker exec ros1-ref bash /root/verify.sh
docker cp ros1_rawdefs.sh     ros1-ref:/root/  && docker exec ros1-ref bash /root/ros1_rawdefs.sh  > /tmp/ros1_msgdefs_raw.txt
docker cp ros1_srvdefs.sh     ros1-ref:/root/  && docker exec ros1-ref bash /root/ros1_srvdefs.sh  > /tmp/ros1_srvdefs.txt
docker cp ros1_msgdefs.sh     ros1-ref:/root/  && docker exec ros1-ref bash /root/ros1_msgdefs.sh  > /tmp/ros1_msgdefs.txt
docker cp ros1_tf_capture.sh  ros1-ref:/root/  && docker exec ros1-ref bash /root/ros1_tf_capture.sh > /tmp/ros1_tf.json

# 4. Run the comparisons
python3 ab_kinematics.py     # T1/T2  needs /tmp/ros1_tf.json     -> 40/40 @ 1e-9
python3 ab_messages2.py      # T3/T4  needs the /tmp captures      -> 8/8 msgs, 10/10 srvs
python3 cmp_launch_norm.py   # T5                                 -> 36/36, 0 genuine diffs
python3 cmp_topics.py        # T6
python3 cmp_configs.py       # T7/T8
python3 cmp_nav_cfg.py       # T9
python3 cmp_handlers.py      # T10
python3 cmp_sources.py       # file-level correspondence
python3 cmp_nav_src.py       # algorithm similarity
python3 classify_nav_diff.py # API-translation vs algorithmic change classification
python3 classify_steps.py    # install.sh step audit
```

## Script index

| Script | Purpose |
| :--- | :--- |
| `classify_steps.py` | Classifies every `install.sh` step as RUN / ADAPTED / SKIP with rationale. |
| `stage_ros1.sh` | Read-only staging of the reference (excludes prior build artifacts). |
| `ros1_install_phase1.sh` | install.sh deps (lines 2–42). |
| `ros1_install_phase2.sh` | abseil, Cartographer, OSQP (lines 45–77). |
| `ros1_install_phase4.sh` | OpenMover workspace in install.sh whitelist order (lines 80–98). |
| `verify_ros1.sh` | Operational verification (packages, nodes, interfaces, Cartographer). |
| `ros1_rawdefs.sh` | Live `rosmsg show -r` capture — **raw** defs, needed for a fair field comparison. |
| `ros1_srvdefs.sh` / `ros1_msgdefs.sh` | Live service / recursive message definition capture. |
| `ros1_tf_capture.sh` | Live kinematic capture from a running ROS 1 master's `/robot_description`. |
| `ab_kinematics.py` | Kinematic A/B (live ROS 1 vs port URDF), tolerance 1e-9. |
| `ab_messages2.py` | Message + service field A/B (name, type, order). |
| `cmp_msgs.py` | Message-definition correspondence by normalized name. |
| `cmp_urdf.py` / `cmp_urdf_params.py` | URDF joint/link structure and raw physical parameters. |
| `cmp_sources.py` | File-level correspondence: identical / modified / only-one-side. |
| `cmp_launch_norm.py` | Launch parameter comparison with ROS1↔ROS2 syntax normalization. |
| `cmp_configs.py` | `hardwares.yaml` / `modules.yaml` value-set comparison. |
| `cmp_nav_cfg.py` | `navigation.yaml` / `mapping.yaml` leaf-value comparison. |
| `cmp_topics.py` | Topic + TF frame surface extraction. |
| `check_ros1_topics.py` | Distinguishes real node-code references from Rviz/doc-only mentions. |
| `cmp_handlers.py` | Per-component topic/service surface (missing vs added). |
| `cmp_nav_src.py` | Line-level similarity per navigation/localization component. |
| `classify_nav_diff.py` | Separates ROS API translation from algorithmic change. |

## Behavioral pass (simulator-free runtime comparison)

These produce the runtime evidence in §12 of the audit. All drive **identical
inputs** into both stacks with no simulator.

```bash
# Tests A/B/C - simulation_handler (cmd_vel, odometry) + obstacle_handler
docker cp behavioral_ros1.sh ros1-ref:/root/beh.sh && docker exec ros1-ref bash /root/beh.sh > /tmp/ros1_beh.log
bash behavioral_ros2_run.sh > /tmp/ros2_beh.log
python3 compare_abc.py            # -> 29/29 PASS

# Test D - TF forward kinematics (identical URDF + joint state)
docker cp tf_probe.py ros1-ref:/root/ && docker cp test_d_ros1.sh ros1-ref:/root/
docker exec ros1-ref bash /root/test_d.sh > /tmp/ros1_test_d.log
bash test_d_ros2.sh > /tmp/ros2_test_d.log
python3 compare_d.py              # -> 6/6 PASS @ 1e-12

# Test E - laserscan_multi_merger on identical dual scans
docker cp merger_probe.py ros1-ref:/root/ && docker cp test_e_ros1.sh ros1-ref:/root/
docker exec ros1-ref bash /root/test_e.sh > /tmp/ros1_test_e.log
bash test_e_ros2.sh > /tmp/ros2_test_e.log
# compare the emitted JSON scan fields bit-for-bit (see audit §12.6)

# Test F - global planner algorithm A/B on identical synthetic costmaps
docker cp planner_ab_ros1.cpp ros1-ref:/root/ && docker cp build_planner_ros1.sh ros1-ref:/root/
docker exec ros1-ref bash /root/build_planner.sh > /tmp/ros1_test_f.log
bash build_planner_ros2.sh > /tmp/ros2_test_f.log
python3 compare_f.py              # -> 2/2 PASS @ 1 cell
```

### Harness notes (learned the hard way)

- The ROS 1 planner harness needs planner params in the namespaces the planner
  actually reads: `~/<name>/<param>` for `private_nh` and `~/<param>` for
  `global_nh` (i.e. `/planner_ab_ros1/global_planner/...` and
  `/planner_ab_ros1/footprint`). `/footprint` must be an `XmlRpcValue` array of
  pairs or the planner throws.
- The ROS 2 planner declares its own parameters during `initialize()`; two
  planner instances must not share one node or `ParameterAlreadyDeclaredException`
  is thrown. The harness gives each scenario its own node.
- The ROS 2 harness links against the workspace's prebuilt static libs
  (`libglobal_planner_deps.a`, `libmath_utils.a`) using the exact flags and link
  line CMake recorded, so it exercises the same compiled planner as the shipping
  nodes. The recorded link line contains a stale path
  (`libfastcdr.so.2.2.5`); the harness redirects it to a local shim rather than
  modifying the system.
- `robot_state_publisher` in ROS 2 should receive the URDF via a params file;
  passing XML with comment headers through `--ros-args` is unreliable.

## Caveats

- `rosmsg show` **without** `-r` expands nested types; comparing that against
  ROS 2 `.msg` sources fabricates differences. Always use the raw capture
  (`ros1_rawdefs.sh`) for field-level comparison.
- The reference tree contains three pre-existing build-hygiene defects fixed
  only inside the container (see §2.1 of the audit). The host reference is
  never modified.
- Non-deterministic GCC crashes during the ROS 1 build are caused by Docker's
  default 64 MiB `/dev/shm` under high parallelism, not by project source.
- Test F compares the planner **algorithm** only. The ROS-service-level planner
  path (`navfn/MakeNavPlan` vs Nav2) has no common scenario and is NOT directly
  comparable.
- Test F's pass tolerance is **one grid cell (0.05 m)** on the Hausdorff distance
  between routes. Waypoints are not byte-identical; the residual comes from
  GCC 9.4 (ROS 1) vs GCC 13.3 (ROS 2). Do not compare waypoints index-by-index,
  and do not round coordinates to cell indices — that metric is unstable near
  boundaries and understates agreement.
