# Current Project Status

## Repository Baseline
- **Root Repository Location**: `/home/zar/Documents/phd/robot/`
- **Baseline Commit**: `79dc52f80f156b36c1383a5cb19315dc87eb858e`
- **Latest Checkpoint**: `99fc43c` (Stage D code fixes: remote SSH discovery + target-native build)
- **Branch**: `master`
- **Scope Tracked**:
  - `caasi/`: Caasi package, CLI tools, documentation, tests, and persistent `/plan`
  - `openmover_robot/`: Legacy ROS 1 OpenMover source reference (**STRICT READ-ONLY**)
  - `openmover_ws/`: ROS 2 + Isaac Sim/Lab reference source & assets (**STRICT READ-ONLY**)
  - `caasi-workspace/`: Primary writable Caasi working environment (`caasi-workspace/openmover_ws/`)
  - `draft/`: Research papers, presentation, and figures

## Safety Boundaries Enforced
- `/openmover_robot` and `/openmover_ws` are strictly read-only and preserved untouched on disk.
- Over 5 GB of runtime logs, build/install outputs, and Isaac Lab RL video/checkpoints remain intact on disk and are excluded from Git object tracking via root `.gitignore`.

## Current State & Next Steps
- **Completed**:
  - Baseline Git Checkpoint established (`79dc52f80f156b36c1383a5cb19315dc87eb858e`).
  - **Phase 1: Discovery & Inventory completed**:
    - [caasi v0.3.0 Capability Audit](file:///home/zar/Documents/phd/robot/caasi/plan/audits/caasi_v0.3.0_audit.md)
    - [OpenMover Inventory](file:///home/zar/Documents/phd/robot/caasi/plan/audits/openmover_inventory.md)
    - [OpenMover Architecture Reference](file:///home/zar/Documents/phd/robot/caasi/plan/reference/openmover_architecture.md)
    - [Capability Mapping & Gaps](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-01/mapping_and_gaps.md)
    - [Phase 1 Summary Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-01/phase-01-report.md)
    - [Packaging & Testing Audit](file:///home/zar/Documents/phd/robot/caasi/plan/audits/packaging_and_testing_audit.md)
    - [Testing Strategy & Proposals](file:///home/zar/Documents/phd/robot/caasi/plan/audits/testing_strategy_and_proposals.md)
  - **caasi Testing Infrastructure Baseline**:
    - **T1**: Sourced ROS 2 pytest plugin conflict resolved in `pyproject.toml`.
    - **T4**: Added `pytest-cov>=5.0` to optional dev dependencies; verified opt-in.
    - **T3**: Implemented un-mocked real-subprocess smoke tests in `caasi/tests/test_real_subprocess.py` (5 tests passing in 0.84s).
    - **T2**: Implemented `caasi test` command with default full suite, tiers (`full`, `unit`, `smoke`), deterministic checkout binding, opt-in coverage, filtering (`-k`), verbose mode, machine-readable `--json`, and dedicated CLI tests in `tests/test_test_cmd.py` (12 tests passing in 0.42s).
    - Verified full test suite executed via native `caasi test`: **55 test modules, 859 passing tests** in 183.32s.
  - **Phase 2: caasi-Managed OpenMover Workspace completed**:
    - [Phase 2 Summary Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-02/phase-02-report.md)
    - [Phase 2 Case Study Evidence](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-02/case_studies.md)
    - Fully represented OpenMover in `/home/zar/Documents/phd/robot/caasi-workspace/openmover_ws/` (`caasi.yaml`, `caasi.lock`, `robots/`, `scenes/`, `tasks/`, `ros/`, `nav/`, `experiments/`).
    - Preflight checks verified: `caasi check project` (READY), `caasi sim check` (READY), `caasi audit` (PASSED).
    - Executed live headless Isaac Sim run via `caasi sim run` (Run ID: `20261003-154048-isaac-sim-smoke`, PID 110981, 60 physics frames stepped at 2432 steps/s, exit code 0, 11 provenance artifacts captured).
    - Re-evaluated Phase 1 candidate gaps (none are blockers; existing tools and patterns handle all requirements).
    - Identified two minor friction points (`cwd` relative resolution and Isaac Lab launcher override flag).
  - **Phase 3: Multi-Subsystem Integration completed**:
    - [Phase 3 Summary Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-03/phase-03-report.md)
    - [Phase 3 Case Study Evidence](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-03/case_studies.md)
    - Verified live Isaac Sim warehouse simulation with ROS 2 bridge (`/clock`, `/odom`, `/tf`, `/scan`, `/cmd_vel`). Measured cold startup (150.3s with RTX PSO compilation) vs warm startup (10.2s).
    - Verified Nav2 closed-loop navigation against live simulation: `laserscan_multi_merger` (360° scan on `/scan`), `slam_toolbox` mapping, Nav2 costmap generation, and path execution driving robot to goal `pos=(+0.89, -0.01)`.
    - Executed simultaneous decoupled runs under `caasi run list` (`backend: sim` and `backend: ros`).
    - Verified Isaac Lab evaluation campaign scheduler (`33_run_campaign.py --dry_run`, 56 maps, 4.38h budget) and Gym RL environment (`21_run_openmover_nav.py`, `backend: lab`, 20 steps @ 35 env-steps/s on CUDA:0).
  - **Phase 4: Meaningful Campaign Execution, Result Inspection, and Recovery completed**:
    - [Phase 4 Summary Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-04/phase-04-report.md)
    - [Phase 4 Case Study Evidence](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-04/case_studies.md)
    - Managed multi-arm procedural campaign run (`astar_dwa` vs `astar_dwa_shield`) via `caasi run start` (Run ID: `20261003-190446-isaac-lab-campaign-bounded`, PID 263110, 53 env-steps/s, 762 steps/run, exit code 0).
    - Verified complete process group termination via `caasi run stop` mid-campaign without orphaned Kit simulator processes; status captured as `stopped`.
    - Verified deterministic resumption via `caasi run restart` (Run ID: `20261003-190733-isaac-lab-campaign-interrupted`, PID 265486), confirming domain runner skipped completed maps and recorded lineage `restarted_from`.
    - Verified domain aggregation (`34_aggregate_campaign.py`) and artifact inspection (`caasi run inspect`).
    - Confirmed zero Category D gaps: existing `caasi` capabilities fully manage robotics campaign workflows.
  - **Phase 5: Physical Robot Hardware Transition, Discovery, and Non-Motion Preflight Validation completed**:
    - [Phase 5 Summary Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-05/phase-05-report.md)
    - [Phase 5 Case Study Evidence](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-05/case_studies.md)
    - Audited OpenMover's real hardware architecture: industrial Ethernet UDP transport for differential-drive motors (`192.168.100.100:23`), IO board (`192.168.100.100:26`), dual 2D LiDARs (`192.168.100.101/102:502`), and V4L2 USB camera.
    - Evaluated `caasi sensor list / inspect` for non-intrusive peripheral discovery, detecting active V4L2 cameras (HIK 2K Camera) and serial interface states.
    - Evaluated `caasi env inspect`, `caasi check project`, and `caasi doctor` for preflight hardware environment compatibility and permission verification.
    - Enforced strict safety boundaries: non-destructive inspection, zero motor motion commands, zero unconnected socket flooding.
    - Confirmed zero Category D gaps: existing `caasi` diagnostic, execution, and provenance capabilities cleanly support the physical hardware workflow without turning `caasi` into a hardware driver.
- **Current State**: Phase 5 successfully closed. Read-only trees preserved untouched; working tree clean.
  - **Phase 6: Full Project Adoption & Caasi-Native Isaac/ROS Workspace completed**:
    - [Phase 6 Architectural Proposal](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-06/phase-06-proposal.md)
    - [Phase 6 Summary Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-06/phase-06-report.md)
    - [Phase 6 Case Study Evidence](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-06/case_studies.md)
    - Materialized the canonical caasi-native OpenMover project at `/home/zar/Documents/phd/robot/caasi-workspace/openmover/` with ROS 2 packages (`src/`), centralized assets (`assets/robots/`, `assets/scenes/`), Isaac Lab Gym tasks (`lab/`), simulation bridges (`sim/bridges/`), configurations (`config/`), and declarative experiments (`experiments/`).
    - Implemented `caasi build`: resource-aware workspace build orchestrator wrapping `colcon build --symlink-install` with continuous RAM-budgeted worker sizing using conservative default heuristic policies ($\text{RAM\_PER\_WORKER} = 6.0\text{ GiB}$, $\text{SYSTEM\_RESERVED} = 2.0\text{ GiB}$, deriving $\min(20, \lfloor 44.8 / 6.0 \rfloor) = 7$ parallel workers on 46.8 GiB RAM), selective package building (`-p`, `-u`), clean builds, and output streaming.
    - Implemented automatic project overlay chaining in `caasi.core.rosenv`: commands executed via caasi immediately discover and chain `<project_root>/install/setup.bash` after the ROS 2 underlay without manual shell sourcing.
    - Added `project_layout` field to manifest dataclass and schema; verified round-trip preservation in `caasi.yaml` and generated `caasi.lock`.
    - Injected `CAASI_PROJECT_ROOT` into child processes and refactored asset resolution in `sim/bridges/common.py` and `lab/openmover_lab/openmover_cfg.py` to eliminate hardcoded machine paths.
    - Empirically validated end-to-end workflows strictly from fresh, unsourced subshells (`env -i`):
      * `caasi check project`: verified environment compatibility and lockfile `caasi.lock`.
      * `caasi build --clean`: compiled 9 ROS 2 packages from scratch across 7 parallel workers in 73.56s.
      * `caasi native ros interface show openmover_msgs/msg/Obstacle`: verified custom ROS 2 message interface in fresh shell without sourcing.
      * End-to-end closed loop: Isaac Sim warehouse simulation (`final-closedloop-sim`, run `20261004-000809-final-closedloop-sim`) + ROS 2 navigation stack (`final-closedloop-stack`, run `20261004-000838-final-closedloop-stack`). Verified RTX dual-LiDAR publishing $\rightarrow$ `laserscan_multi_merger` $\rightarrow$ 360° `/scan` $\rightarrow$ `slam_toolbox` mapping $\rightarrow$ Nav2 costmap resizing ($324 \times 313$ cells) $\rightarrow$ `/cmd_vel` velocity commanding ($v = 0.3\text{ m/s}$) $\rightarrow$ robot physically driven in simulation from $\text{pos}=(+0.01, -0.00)$ to $(+7.62, -2.07)$ over 2,400 scans $\rightarrow$ controlled stop.
      * `caasi lab run experiments/lab_smoke.yaml`: bounded Isaac Lab RL task rollout (`final-lab-smoke`, run `20261004-000252-final-lab-smoke`, 20 steps @ 35 env-steps/s on `cuda:0`, status `succeeded`).
      * `caasi run start experiments/lab_campaign.yaml`: planned 56-map procedural evaluation campaign (`final-lab-campaign`, run `20261004-000642-final-lab-campaign`, 4.38h estimate, status `succeeded`).
      * Complete Level 6 execution provenance and process lifecycle (`caasi run stop`) verified.
    - Verified full regression test suite: **870 passing tests** in 185.94s (11 new tests in `tests/test_build.py`).
- **Current State**: Phase 6 closed. Migration and equivalence audit completed ([Migration Audit Report](file:///home/zar/Documents/phd/robot/caasi/plan/audits/migration_and_equivalence_audit.md)).
  - **Phase 7: Execution Targets, Remote Deployment & Fleet Orchestration**:
    - [Phase 7 Architectural Proposal](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/phase-07-proposal.md)
    - [Phase 7 Stage A Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/phase-07-report.md)
    - **Stage A completed & verified (Target Model & Capability Discovery)**:
      * Implemented project-agnostic execution target model in `caasi.core.targets` (`Target`, `TargetResources`, `TargetEnvironment`, `TargetInspection`).
      * First-class local workstation target model with automatic injection and zero configuration required.
      * Backward-compatible import of legacy `remotes:` configurations into the target registry.
      * Discovered target facts: hardware specs (CPU model/cores, total/available memory, GPU accelerators) and software environment (OS, kernel, architecture, Python, ROS 2 distro, CUDA, Docker, Isaac Sim, Isaac Lab).
      * Bounded non-blocking remote discovery via TCP socket preflight and compact remote Python probes over SSH without preinstall dependencies.
      * Declarative vs discovered compatibility and mismatch engine (detects architecture mismatches, missing GPU/CUDA, ROS distro divergence, missing domain capabilities).
      * Refined semantics: disambiguated network latency (`ping_ms`) from discovery probe duration (`probe_duration_ms`), and driver-supported maximum runtime CUDA version (`cuda_driver_max`) from compiler toolkit version (`cuda_toolkit`).
      * Implemented CLI commands: `caasi target list [--check] [--json]`, `caasi target inspect <name> [--json]`, `caasi target check <name> [--json]`, with `caasi node` alias.
      * Added 19 comprehensive unit tests in `caasi/tests/test_targets.py`.
    - **Stage B completed & verified (Deployment Foundation & Synchronization Engine)**:
      * [Phase 7 Stage B Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/phase-07-report.md)
      * Implemented deployment abstractions in `caasi.core.deploy` (`DeploymentSpec`, `DeploymentRecord`).
      * Strict separation of project content (`caasi.yaml`, `caasi.lock`, `src/`, `config/`, selective `assets/`) from development-only content (`build/`, `install/`, `log/`, `.git/`, `tests/`, `.caasi/runs/`, `.caasi/deployments/`).
      * Incremental synchronization engine built on `rsync` over local/SSH transports with itemized change tracking.
      * Target preflight & capability compatibility verification before file transfer.
      * Two-sided provenance tracking: `<destination>/.caasi-deployment.json` on target and `.caasi/deployments/<target>/<id>.json` on host.
      * Post-deployment verification engine structurally validating project manifest, source tree, and deployment metadata integrity.
      * CLI interface: `caasi deploy <target> [--dry-run] [--force] [--dest <path>] [--status] [--list] [--json]`.
      * Added 13 dedicated unit tests in `caasi/tests/test_deploy.py` (total 902 tests passing across suite).
      * Empirically validated on canonical OpenMover: 833 files (40.4 MiB) synchronized in 0.63s; subsequent unchanged synchronization transferred 0 regular file bytes in 0.60s. Tested offline targets, incompatible targets, and permission failures.
    - **Stage C1 completed & verified (Target-Native Build)**:
      * [Phase 7 Stage C1 Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/phase-07-report.md#stage-c1-report-target-native-build)
      * Implemented generalized target-native build interface: `caasi build --target <name>` / `-t <name>`. Local workstation build behavior is preserved identically.
      * RAM-safe parallel worker count derivation (`derive_target_workers`) based on target physical RAM and CPU cores ($\text{RAM\_PER\_WORKER} = 6.0\text{ GiB}$, $\text{SYSTEM\_RESERVED} = 2.0\text{ GiB}$).
      * Verified deployment preflight enforcing active materialization via `get_deployment_status`; fails fast if project is undeployed.
      * Remote colcon build orchestration over SSH with target-native ROS 2 underlay sourcing and live console streaming.
      * Architecture-specific compilation outputs (`build/`, `install/`, `log/`) strictly retained on the target without workstation leakage.
      * Two-sided build provenance recorded in `<dest>/.caasi-build.json` and host `.caasi/builds/<target>/<build_id>.json`.
      * Added 10 dedicated unit tests in `caasi/tests/test_target_build.py` (total 912 tests passing across suite).
      * Empirically validated on canonical OpenMover: verified local build, nonexistent target rejection, undeployed target rejection, prerequisite build failure capture, and complete 6-package native build on target sandbox in 61.4s.
    - **Stage C2 completed & verified (Target-Native Remote Run Execution & Lifecycle Management)**:
      * [Phase 7 Stage C2 Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/phase-07-report.md#stage-c2-report-target-native-remote-run-execution--lifecycle-management)
      * Implemented target-aware run lifecycle in `caasi.core.runs` and `caasi.cli.run_cmd`: `caasi run start --target <name>`, `status`, `logs`, `inspect`, `stop`, `list`.
      * Strict preflight verification: target reachability, deployment verification, target-native build verification.
      * Detached process supervision via `nohup setsid` ensuring runs survive workstation SSH disconnections; tracks PID and PGID.
      * Process-group signaling (`kill -TERM -<pgid>`, fallback `kill -KILL -<pgid>`), verified zero orphaned processes across multi-node trees.
      * Remote log streaming (`caasi run logs -f`) and remote run inventory auditing (`caasi run inspect`).
      * Two-sided run provenance recorded on host (`~/.caasi/runs/<run_id>/manifest.yaml` + Level 6 bundle) and target (`<remote_run_dir>/manifest.yaml`).
      * Added 8 dedicated unit tests in `caasi/tests/test_target_run.py` (total 50 target tests passing across target suite).
      * Empirically validated on canonical OpenMover: verified undeployed target rejection, unbuilt target rejection, successful detached execution, live ROS 2 and package imports, remote log streaming, run file inspection, and complete process group termination with zero orphans.
    - **Current State**: Phase 7 Stage C2 completed and verified. Ready for user review before proceeding.

  - **ROS 1 → ROS 2 Functional Equivalence Validation completed** (inserted before Phase 7 Stage D):
    - [ROS 1 → ROS 2 Functional Equivalence Audit](file:///home/zar/Documents/phd/robot/caasi/plan/audits/ros1_to_ros2_functional_equivalence.md)
    - [Comparison scripts](file:///home/zar/Documents/phd/robot/caasi/plan/audits/ros1-ros2-comparison/)
    - **Question answered**: is the ROS 2 OpenMover a faithful *functional* port of ROS 1
      OpenMover? **Yes, for the functionality actually tested** — every compared artifact
      matched with zero differences.
    - **ROS 1 reference environment**: Docker container `ros1-ref` from
      `osrf/ros:noetic-desktop-full` (Ubuntu 20.04.6, ROS Noetic, glibc 2.31),
      `--network host --shm-size=2g`. Docker is the ROS 1 reference environment only;
      it is **not** a caasi target and caasi does not manage the ROS 1 system.
    - **`install.sh` treated as authoritative.** Every step executed in order. Only three
      steps SKIPPED with documented reasons and zero equivalence impact: mainline kernel
      install (impossible in a container; host provisioning, not ROS functionality),
      re-adding ROS apt source (base image already provides Noetic; skipping preserves the
      working configuration), and `ufw allow ssh` (no firewall in container). Two steps
      ADAPTED: passwordless sudo (container is root) and the pip mirror (unreachable; default
      PyPI used).
    - **ROS 1 system verified operational** (not merely built): all 9 packages discoverable,
      8 message + 10 service types generated, all 9 C++ node executables built, 5 Python
      servers present, HAL modules importable, Cartographer binaries installed, and a live
      `roscore` session with `robot_state_publisher` publishing `/tf`/`/tf_static`.
    - **Measured equivalence results (all zero differences)**:
      * Messages: **8/8 exact** on field name + type + order (live `rosmsg show -r` vs ROS 2 `.msg`).
      * Services: **10/10 exact** including `NavToRequest` (13 request fields).
      * Kinematics: **40/40 joint fields @ 1e-9** (8 joints × type/parent/child/origin/axis); 9 links, 8 joints, identical sets.
      * Physical constants: wheel separation `0.324`, wheel radius `0.05035` (= diameter/2 exactly), LiDAR model (600 samples, ±1.57 rad, 0.22–10.0 m, 15 Hz) all identical.
      * Driver/config: `bluesea2` + `laserscan_multi_merger` **36/36 literals match, 0 genuine differences**; `hardwares.yaml` 15/15 and `modules.yaml` 9/9 identical.
      * Topics: **0 missing** across all 9 handler components; TF frames **6/6 identical**.
      * Algorithm cores: global planner 95.6% (9 files byte-identical, remainder API-translation only), local planner 98.7%, math_utils 99.1%.
      * Launch files: **11/11 ported** to `.launch.py`.
    - **Intentional port differences documented** (not failures): `rospy`→`rclpy`,
      `roscpp`→`rclcpp`, catkin→colcon/ament, `roslaunch`→ROS 2 launch, `ROS_*`→`RCLCPP_*`,
      `costmap_2d`→`nav2_costmap_2d`, `tf::getYaw`→`tf2::getYaw`, `boost::thread`→`std::thread`,
      Gazebo Classic→Gazebo Harmonic, Cartographer/OSQP source builds→binary underlays,
      `snake_case`→`PascalCase` service type names, and a Cartographer `odom` remap that
      **fixes a ROS 1 type mismatch** (`PoseWithCovarianceStamped` vs `nav_msgs/Odometry`).
    - **No functional gap identified.** Items that first appeared as gaps were each resolved:
      5 "missing" message fields were a measurement artifact (`rosmsg show` recursive type
      expansion — re-run with `-r`), `control/joy` is commented out in ROS 1 itself, and the
      7 `mapping/lio/*` topics exist only in Rviz configs with no node code referencing them.
    - **One genuine numeric difference recorded, unresolved**: ROS 1 `costmap.update_frequency`
      is `1.0` while ROS 2's `global_costmap` uses `3.0`. Its behavioral impact was **not**
      measured and it is not claimed equivalent.
    - **NOT VERIFIED (explicitly not claimed equivalent)**: Gazebo Classic vs Harmonic vs
      Isaac Sim **physics** behavior; end-to-end ROS 1 navigation; LiDAR/odometry message
      value equivalence; planner path output A/B; physical hardware paths
      (`motor_handler`, `io_board_handler`, live `bluesea2` UDP — requires the real robot,
      deliberately out of scope). The simulator was **replaced**, not shown equivalent; only
      the *model and ROS interface* it must satisfy were shown equivalent.
    - **Reference integrity preserved**: `openmover_robot` was fingerprinted before and after
      — file count 2552 and tree hash
      `f17c242a8cb64b4f987ae606f9c749e278690f109d8159b145ed0cbb697c1886` unchanged, 0 dirty
      entries. All builds occurred in the container copy; the host reference was never written to.
    - **Two inaccuracies in the existing migration audit corrected**: it cited a
      `Motion.msg` that does not exist in either tree (actual ROS 1 set is 8 messages), and
      its Hop 1 equivalence was previously inferred rather than measured. Both are now fixed,
      and the two audits cross-link.
    - **Environment issues investigated to conclusion (not port defects)**: non-deterministic
      GCC `internal compiler error` crashes traced to Docker's default 64 MiB `/dev/shm`
      under high `-j20` parallelism (resolved by raising `/dev/shm` and reducing parallelism;
      cgroup `oom_kill` counters were 0, so not OOM); three **pre-existing reference-tree
      build-hygiene defects** (a regular file where catkin expects a `toplevel.cmake` symlink,
      a case-mismatched `relocalization_request.srv`, and a vestigial empty
      `add_action_files` block) fixed only in the container copy.
    - **Behavioral equivalence pass completed (simulator-free runtime comparison)**:
      * Added audit section §12 with six deterministic runtime tests, each driving
        **identical inputs** into both stacks. No simulator was used, and no source
        file was modified for any harness.
      * **Test A — `cmd_vel` response**: 6 cases (manual/auto channel gating, mode
        service, emergency-stop zeroing) plus 3 service calls. **29/29 checks PASS**;
        every forwarded value identical, emergency correctly zeroes while still
        publishing.
      * **Test B — odometry/twist transform**: identical `nav_msgs/Odometry` in;
        `/hardware/odom` and `/hardware/twist` out with matching frame ids and
        numeric fields. **PASS, 0 ULP**.
      * **Test C — obstacle grid**: identical 360-sample `LaserScan` with 4 known
        returns → 5×4 obstacle grid. **PASS, bit-identical** (verified via IEEE-754
        hex: `0x3ffbae1480000000`, `0x3fe75c2900000000`, `0x3fe0f5c280000000`,
        `0x3fd1eb8520000000` on both sides).
      * **Test D — TF forward kinematics**: identical URDF + identical joint state
        into `robot_state_publisher`. **6/6 frames PASS at 1e-12 declared tolerance**;
        worst observed difference `1.11e-16` (one ULP). `lidar_forward_link`
        bit-identical.
      * **Test E — `laserscan_multi_merger`**: identical dual scans + identical
        static transforms → 903-sample merged scan. **PASS, bit-identical** across
        every scan field and the merged return.
      * **Test F — global planner algorithm**: both sides called `make_plan()`
        directly on identical synthetic costmaps (200×200 @ 0.05 m), same
        start/goal/params, two scenarios (free map; wall with doorway). **2/2 PASS**
        at a declared **1-cell (0.05 m)** route tolerance — Hausdorff `7.48e-03 m`
        (0.150 cells) and `2.14e-02 m` (0.428 cells); path lengths agree to
        `1.2e-04 m` and `1.1e-02 m`.
      * **Residual planner waypoint drift explained**: waypoints are not
        byte-identical because the stacks use different compilers — GCC 9.4.0
        (Ubuntu 20.04, ROS 1) vs GCC 13.3.0 (Ubuntu 24.04, ROS 2). Floating-point
        contraction/reassociation differs, shifting sub-cell interpolation. This is
        consistent with the byte-identical / API-translation-only source finding,
        so no algorithmic difference is needed to explain it. Each side is
        individually deterministic (ROS 2 re-run reproduced its output exactly).
      * **Two measurement artifacts caught and corrected rather than reported as
        findings**: (1) `rosmsg show` recursive expansion vs `-r` (see the static
        pass); (2) naive cell-index rounding to compare planner routes gave a
        misleadingly low 86–89% "similarity" — the boundary-stable Hausdorff metric
        shows sub-cell agreement, and the naive metric was discarded.
      * **Costmap frequency left untouched and unresolved**: ROS 1
        `costmap.update_frequency = 1.0` vs ROS 2 `global_costmap = 3.0`. Neither
        value was changed. The behavioral pass did **not** measure its significance
        because the costmap update loop needs a live costmap and no common runtime
        scenario exists between the stacks. It remains classified as *observed
        configuration difference; behavioral significance not yet measured*.
      * **Deliberately NOT compared, with reasons recorded**: Gazebo Classic vs
        Harmonic vs Isaac Sim **physics** (no common OpenMover scenario — the
        `warehouse_simulation` demo in both trees is a *Pioneer 3DX + gmapping +
        move_base* demo using neither the OpenMover robot nor its navigation stack);
        the ROS-service-level planner path (`navfn/MakeNavPlan` vs Nav2 — no common
        service scenario); physical hardware paths (require the real robot).
      * **Conclusion (scoped)**: for the six tested simulator-free behaviors, the
        ROS 2 implementation faithfully preserves ROS 1 operational behavior. No
        behavioral discrepancy attributable to the port was found. The conclusion
        explicitly does **not** extend to simulation physics, SLAM output,
        end-to-end navigation, `navigation_handler`/`localization_handler` runtime
        behavior, or hardware.
      * **Reference integrity re-verified after the behavioral pass**:
        `openmover_robot` unchanged at 2552 files and tree hash
        `f17c242a8cb64b4f987ae606f9c749e278690f109d8159b145ed0cbb697c1886`, 0 dirty.
      * Behavioral harnesses committed under
        `caasi/plan/audits/ros1-ros2-comparison/` (`behavioral_*.sh/py`,
        `test_d_*.sh`, `test_e_*.sh`, `merger_probe.py`, `tf_probe.py`,
        `planner_ab_ros1.cpp`/`planner_ab_ros2.cpp`, `build_planner_*.sh`,
        `compare_abc.py`, `compare_d.py`, `compare_f.py`) with README reproduction
        steps and harness caveats.
    - **Three-way behavioral equivalence validation completed — chain closed**:
      * **Canonical result**:
        ```text
        original ROS1  →  existing ROS2 reference  →  caasi-native ROS2
        ROS1-reference     ROS2-reference              caasi-ROS2

        ROS1 ≈ ROS2-reference ≡ caasi-ROS2
        ```
        — for the **six tested simulator-independent behaviors only**.
      * **ROS1-reference ↔ ROS2-reference**: behavioral equivalence **within
        declared tolerances**.
      * **ROS2-reference ↔ caasi-ROS2**: **byte-identical outputs for all six
        tested behaviors** (identical per-test output hashes; planner plans
        byte-identical with exactly equal path lengths).
      * Closed the remaining gap: the chain had been **A↔B runtime-validated** and
        **B↔C source-parity + Isaac Lab runtime**, but **A↔C had never been
        behaviorally compared**, and the B↔C runtime evidence came from a
        different test domain (GPU RL) than the A↔B evidence (ROS 2 message nodes).
      * **Tree labels introduced** to stop the previous collision with behavioral
        test names: `ROS1-reference` (`openmover_robot`), `ROS2-reference`
        (`openmover_ws`), `caasi-ROS2` (`caasi-workspace/openmover`). Behavioral
        tests are now numbered 1–6 (A→1, B→2, C→3, D→4, E→5, F→6).
      * **No new methodology.** The four ROS 2 harnesses gained one
        `--tree <workspace>` argument; inputs, cases, metrics and pre-declared
        tolerances are unchanged from A↔B.
      * **Behavior-preservation verified first**: every parameterized harness run
        against its default tree reproduced the previous B results
        **byte-identically** (all four). `caasi-ROS2` determinism also confirmed.
      * **Result: 18/18 pairings PASS.**
        | Behavior | ROS1↔ROS2ref | ROS2ref↔caasi | ROS1↔caasi |
        |---|---|---|---|
        | cmd_vel gating/mode/emergency | PASS (0 ULP) | PASS (0 ULP) | PASS (0 ULP) |
        | odometry/twist | PASS (0 ULP) | PASS (0 ULP) | PASS (0 ULP) |
        | obstacle grid | PASS (0 ULP) | PASS (0 ULP) | PASS (0 ULP) |
        | TF kinematics | PASS (1.11e-16) | PASS (**0.0, bit-identical**) | PASS (1.11e-16) |
        | scan merger | PASS (bit-identical) | PASS (bit-identical) | PASS (bit-identical) |
        | planner algorithm | PASS (0.428 cell) | PASS (**0.000 cell**) | PASS (0.428 cell) |
      * **Key result — `ROS2-reference` ≡ `caasi-ROS2`, not merely ≈**: the two
        ROS 2 implementations produced **byte-identical structured output on all
        six behaviors** (identical per-test output hashes; planner plans
        byte-identical with exactly equal path lengths). **The caasi migration
        introduced no observable behavioral change in the tested behaviors.**
      * **The only residual difference is A vs {B,C}, and it is unchanged** from
        the earlier pass: TF one ULP (quaternion, differing trig), planner
        0.150–0.428 cells. Both track the **compiler boundary exactly** — g++
        9.4.0 (Ubuntu 20.04, ROS1) vs g++ 13.3.0 (Ubuntu 24.04, both ROS 2). Where
        the two ROS 2 trees share a toolchain their output is bit-identical; no
        algorithmic difference is required or observed.
      * **No discrepancy hidden or tolerance loosened.** No C-specific difference
        was found to investigate; all tolerances remain exactly as declared for A↔B.
      * **Compact committed evidence**: `three_way_records.json` (5.8 KB —
        hashes, pairings, verdicts, environment/toolchain records) plus
        `compare_three_way.py`. Raw harness logs are deliberately **not**
        committed; the committed harnesses regenerate them, and regeneration was
        verified to reproduce the committed records exactly.
      * **Reference integrity re-verified after the work**: `openmover_robot`
        `f17c242a…` and `openmover_ws` `1e09f5de…` both **unchanged** (0 dirty);
        `caasi-workspace/openmover` `24ef2da4…` **unchanged by this work**. Only
        intended locations changed (4 harnesses, comparator, records, docs).
      * **Scope — six deterministic behaviors only.** Not established, and not
        claimed equivalent:
        - **No simulator-physics equivalence.** Gazebo Classic → Gazebo Harmonic /
          Isaac Sim remains an **intentional simulator replacement**; no common
          OpenMover simulator scenario exists and neither simulator was run for
          equivalence.
        - **No physical-hardware equivalence.** `motor_handler`, `io_board_handler`
          and live `bluesea2` UDP require the real robot (deliberately not exercised).
        - **No full end-to-end navigation/SLAM equivalence.** `navigation_handler`,
          `localization_handler` and Cartographer output were not run.
        - **Planner comparison remains algorithm-level** on identical synthetic
          costmaps; the ROS-service-level planner path has no common scenario.
        - **ROS1 compiler-boundary differences remain as measured** (see below).
      * **ROS1 reference container**: kept **independent** (no caasi inside it, no
        caasi reference to it) so it remains an external oracle. Do not make caasi
        manage the ROS1 reference; container orchestration remains a separate
        future capability.
  - **Phase 7 Stage D (Real Remote Target Validation): COMPLETED against a real machine.**
    - [Stage D Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/stage-d-report.md)
    - **Target**: `u24-307`, a genuinely separate Ubuntu 24.04 machine over
      **SSH/Tailscale** (relay "hkg"), CPU-only (no GPU, no Docker). Distinct from the
      workstation in hostname, kernel (6.8.0-139 vs 6.8.0-142), CPU (Xeon E5-2630 v2,
      12 cores vs i7-12700K, 20 cores) and RAM (62.7 vs 46.8 GiB). The released PyPI
      `caasi 0.3.0` pipx install on the target was left **untouched**; the workstation
      dev checkout remained the controller.
    - **Lifecycle verified end-to-end**: `target check` → `deploy` (VERIFIED, 835 files)
      → `build --target` (185.83 s, artifacts only on the target, **10 workers derived
      from the target's own 62.7 GiB / 12 cores**) → `run start` (detached, PPID 1)
      → **tested SSH-disconnect survival** → fresh-invocation `status`/`logs`/`inspect`
      → `run stop` (`stopped`, tested tree gone) → two-sided provenance → bounded
      offline failure (~2.1 s) → connectivity restored.
    - **SSH-disconnect survival was actually TESTED**, not inferred: the local SSH client
      was SIGKILLed mid-run (0 ssh processes remained), and the run continued with the
      **same PID 77787**, heartbeats advancing step 20 → 110. This strengthens the
      Stage C2 claim, since the launching invocation had already exited beforehand.
    - **Three genuine caasi defects exposed and fixed** (each documented before fixing,
      each fix the smallest general change):
      * **[G1] `stage-d-gap-ssh-timeout.md`** — hardcoded 3 s SSH probe/connect timeout
        made a real remote target permanently unreachable (measured: TCP 350 ms vs SSH
        5–6 s). Fixed with an optional per-target `ssh_timeout` (default 3.0 preserved).
      * **[G2] `stage-d-gap-run-timeouts.md`** — 12 hardcoded 5 s/10 s budgets in the
        remote run paths caused `run stop` to time out and **mis-report `lost`** even
        though the kill had succeeded. Fixed by deriving per-call budgets from
        `ssh_timeout`, and by treating "kill sent" and "state confirmed" as different
        facts so a delivered signal is never downgraded to `lost`.
      * **[G3] `stage-d-gap-deploy-status.md`** — `deploy --status` could not find a
        deployment it had just created, because the read path used the bare
        `deployment_root` while the write path appended the project name. Fixed by
        using the same resolver on both paths. Latency-independent; affects the
        documented default destination layout generally.
    - **Tests added**: 9 (5 in `test_targets.py`, 2 in `test_target_run.py`,
      2 in `test_deploy.py`). Target-related suites: **125 passing**. Full suite:
      **928 passed, 1 failed** — the single failure
      (`test_perception_cmd.py::test_perception_segment_dry_run_passes_extra_args`) is
      **pre-existing and unrelated**, verified by stashing the Stage D changes and
      reproducing it on the unmodified commit.
    - **Scope limits**: no GPU/simulation claim (the target has no NVIDIA GPU and was
      never used for Isaac Sim/Lab); the workload is the project's existing CPU-only
      `target_smoke` experiment. No physical-robot claim. No fleet/scheduling claim
      (one target only). Process cleanup is reported for **the tested process group and
      its spawned child**, not as a universal zero-orphan guarantee. No ROS 1 involvement.
    - **Reference integrity preserved**: `openmover_robot` `f17c242a…` and `openmover_ws`
      `1e09f5de…` both unchanged throughout.
    - **Next step (not auto-proceeded)**: decide between fleet/resource orchestration and
      artifact management; container orchestration as a first-class transport is a
      separate future capability and was deliberately not introduced here.
  - **Phase 7 Stage E2 (Remote ROS 2 Observability): COMPLETED.**
    - [Stage E2 Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/stage-e2-report.md)
    - [Stage E Discovery](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/stage-e-discovery.md)
    - [Observability Addendum](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/stage-e-observability-addendum.md)
    - Made caasi's existing ROS 2 query surface **target-aware**, so a workstation can
      observe a ROS 2 runtime on a separate machine through caasi:
      `caasi ros status|list|graph|node|topic|service|doctor --target <t>`.
    - **Thin delegation, no reimplementation**: the target's own `ros2` CLI produces
      every answer. The target-side snippet sources the ROS underlay (and optional
      project overlay), then `exec ros2 "$@"`. caasi contributes only transport,
      environment sourcing and presentation — no DDS or ROS 2 internals rebuilt.
    - Added **`--domain` / `-d`** (ROS_DOMAIN_ID) because a runtime may live on a
      non-default domain, where querying the default returns an **empty graph rather
      than an error** — silently misleading.
    - Deliberately **excluded** from `--target`: `ros launch` and `ros topic --echo`,
      since they start long-lived processes (the *execution* lifecycle, not
      observability). Remote `--echo` says so and points at `run start --target`.
    - **`caasi target state` was NOT implemented.** Every input it would aggregate
      already exists as a composable command (`target check`, `target list --check`,
      `deploy --status`, `run list --target`), so it would duplicate without adding
      capability. Recorded as a decision, not an omission.
    - **Validation used standard ROS 2 demo nodes, NOT OpenMover** (per instruction to
      use the smallest workload giving valid evidence): `demo_nodes_cpp talker`,
      `listener`, `add_two_ints_server` on `u24-307`, ROS_DOMAIN_ID 42. Reproducible
      start/stop scripts committed under `phase-07/e2-demo-runtime/`.
    - **Decisive cross-check**: with the same domain, the workstation's own ROS
      returned nothing while `--target u24-307` returned the 3 demo nodes — proving
      caasi observes the **remote** runtime, not local state.
    - **Validation matrix all PASS**: reachable+ROS running; reachable+ROS unavailable
      (rc 127 + marker); unreachable (rc 1, bounded ~22s, clear message); query failure
      for a missing node (rc 1, "ROS 2 ran and returned no match"); unknown target (rc 1,
      no silent local fallback); fresh invocation from a fully-unsourced shell; and
      local commands unchanged when `--target` is omitted.
    - **Failure classification**: unreachable vs no-ROS2 vs not-found vs generic query
      failure are reported distinctly, because they have different remedies. All failure
      paths exit 1.
    - **Tests**: 8 new in `tests/test_ros_cmd.py` (16 → 24 passing). Full suite:
      **936 passed, 1 failed** — the failure is the **pre-existing** terminal-width
      artifact in `test_perception_cmd.py`, proven unrelated to E2 (and to Stage D).
    - **Observed**: Tailscale relay probe latency climbed 6.0→10.0s across repeated
      checks against the 20s budget, with one transient UNREACHABLE before recovering.
      Recorded as an environmental observation, not an E2 defect.
    - **Untested (explicitly)**: non-ROS runtimes (container/systemd/process adapters
      are not implemented — `caasi monitor` remains local-only); multi-target/fleet
      aggregation; continuous polling (on-demand only, by design); non-SSH transports;
      cross-host DDS discovery within a domain; SROS 2/DDS security; OpenMover
      integration (not used for E2; a natural follow-up, not a prerequisite).
    - **Ordering note**: E2 was done before E1 at the user's direction. Per the agreed
      staging, **E1 (result/output collection)** remains the next bounded step.
  - **Phase 7 Stage E1 (Result/Output Collection): COMPLETED.**
    - [Stage E1 Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/stage-e1-report.md)
    - Closed the compute-side lifecycle:
      `project → deployment → target → build → run → artifacts/results → destination`.
    - **New module** `caasi.core.artifacts`: `Artifact`, `ArtifactRoute`,
      `ArtifactRecord`, `OutputDeclaration`, `RoutingPolicy`, local/remote
      inventory, collection planning, collection, and the sibling `artifacts.yaml`
      record. caasi **routes, it does not interpret** — it never parses a
      checkpoint or metric, and `kind` never gates collection.
    - **CLI**: `caasi run artifacts <run> [--collect] [--dry-run] [--verify] [--json]`.
    - **Decisions taken before implementation** (all three as recommended in the
      investigation): unclassified outputs **stay on the target** with their
      location recorded; **small files hashed by default, large only with
      `--verify`**; artifacts collected for **succeeded, failed and stopped** runs.
    - **A declaration is a filter.** Declaring `outputs:` defines what the run
      produces (separating results from source/scratch); with no declaration every
      non-bookkeeping file is inventoried so nothing is lost.
    - **E1.5 lifecycle intent**: `lifecycle: ephemeral | persistent` (default
      persistent). After an ephemeral deployment's declared results are collected
      it is marked `releasable` — **a recording only**; caasi has no delete or
      release operation, and the CLI states "recorded only; nothing was removed".
      A persistent deployment is **never** marked releasable.
    - **Validated on the real remote `u24-307`** with a minimal generated-file
      workload (2 small results + one 2 MiB checkpoint): remote inventory over SSH,
      a collection plan of `fetch=2 / leave=1`, and collection that copied exactly
      the two results — **content verified byte-identical by sha256** — while the
      2 MiB checkpoint stayed on the target. Target left fully intact
      (deployment present, all 3 files, checkpoint present).
    - **Ephemeral vs persistent proven distinct**: ephemeral → `releasable: True`
      recorded after collection; persistent → not marked, despite identical
      collection behaviour.
    - **Additional evidence from real OpenMover data** (241 map JSONs, 6.2 MB in
      `lab/`): undeclared inventory found 306 files including 28 `.py` source
      files (showing why declarations matter); declared narrowed correctly to 241
      map files. This exposed a **genuine bug**: a declared `kind: map` was ignored
      in favour of extension inference (`.json` → `metrics`). Fixed so a
      **declaration wins over extension inference**; regression test added.
    - **Two further bugs found by validation**: the provenance bundle
      (`configuration.yaml`, `hardware.yaml`, …) was being reported as artifacts
      (fixed in the bookkeeping list), and the inventory root was wrong (it now
      uses the run's working directory rather than the run directory, which holds
      bookkeeping).
    - **Tests**: 42 new (39 `test_artifacts.py`, 3 `test_experiment.py`). Full
      suite **976 passed, 1 failed** — the failure is the pre-existing
      `test_perception_cmd.py` terminal-width artifact, proven unrelated to E1.
    - **Not established (explicitly)**: no deletion/release/teardown by design; no
      artifact store (no CAS, dedup or retention policy); no shared/remote
      destination (only `workstation` and `target_local`); no artifact↔dataset
      hydration; no transfer progress beyond per-file `rsync --partial`; the
      `required:` field parses but is **not enforced**, so a run producing nothing
      reads as zero artifacts rather than a failure; and no persistent-runtime work
      (not started, per instruction).
    - Test deployment removed from `u24-307` after validation. Reference trees
      unchanged.

  - **Phase 7 Stage E3 (Non-ROS Runtime Adapters): COMPLETED.**
    - [Stage E3 Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/stage-e3-report.md)
    - Generalised the E2 observation model beyond ROS 2, using each runtime's own
      **native** interface. Principle unchanged: **caasi asks the runtime for
      state and presents it consistently; the runtime stays authoritative.**
    - **New module** `caasi.core.runtimes` with four adapters plus one shared
      transport primitive (`run_on_target`: local runs directly, SSH joins one
      quoted command). Normalised `RuntimeReport` / `RuntimeItem` across all four.
      | runtime | delegates to |
      |---|---|
      | process | `ps`, falling back to `/proc` |
      | systemd | `systemctl`, `journalctl` |
      | container | `docker`, falling back to `podman` |
      | ros2 | `ros2` CLI (reuses E2 detection rather than duplicating) |
    - **CLI**: `caasi target runtime <target> [--runtime …] [--match …] [--unit …] [--lines N] [--system] [--json]`.
    - **Design decisions recorded**: absence is reported **with a reason**, never as
      an empty success; `systemctl` present is **not** enough (requires
      `/run/systemd/system`, so a container shipping systemctl without systemd is
      correctly reported unavailable); detection is **one round-trip** so a slow
      relay pays once; budgets scale with `ssh_timeout` (Stage D mechanism); the
      adapters **only read** — no start/stop/restart/enable/remove; kernel threads
      are hidden unless `--match` reaches them.
    - **Validated on real workloads, with no OpenMover involvement** (per the
      instruction not to require it):
      * process adapter found a real detached `sleep 900` on `u24-307` by PID/PGID;
      * systemd adapter observed a real user unit (`active`, `running`, MainPID);
      * `journalctl` delegation returned real journal lines from that unit;
      * container adapter observed a real Docker container locally (`running`,
        `alpine`) alongside exited ones — `u24-307` has no container runtime, so it
        was correctly reported unavailable *and why*.
    - **Failure cases**: unknown target rc 1 with **no silent local fallback**;
      unknown runtime rc 1 with the valid list; unreachable target rc 1, bounded
      **20.16 s**, with the transport reason on every runtime.
    - **Tests**: 21 new in `tests/test_runtimes.py`. Full suite **999 passed,
      1 failed** — the failure is the pre-existing `test_perception_cmd.py`
      terminal-width artifact, proven unrelated.
    - **Not established (explicitly)**: no lifecycle operations (observe-only); no
      container logs/inspect; no multi-target aggregation; no polling or history;
      container adapter not validated **remotely** (no reachable target has a
      container runtime); podman covered by test only; no non-systemd init; no
      `caasi monitor` integration; no security posture tested.
    - **Environmental note**: `u24-307` connectivity stayed variable (probe
      round-trips ~325 ms to 1.35 s, several transient SSH drops). This is relay
      variability, **not** an E1 or E3 failure. One drop looked like the relay but
      was a real gotcha: `pkill -f "sleep 900"` matches the SSH command line
      containing that string and kills its own session; the workaround was to match
      on exact process name and inspect `/proc/<pid>/cmdline`.
    - Validation fixtures removed: the systemd unit and workload on `u24-307`, and
      the test container locally. Reference trees unchanged.
    - The documented E1 `required:` limitation was **left as documented**, not
      expanded — E3 did not demonstrate a need for it.

  - **Phase 7 Stage E4 (Persistent Runtime Lifecycle): COMPLETED.**
    - [Stage E4 Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/stage-e4-report.md) |
      [Discovery](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/stage-e4-discovery.md)
    - Answers: *if caasi deploys to a long-lived target such as a robot, how does caasi
      install / configure / enable / verify / manage that deployment over time?*
      Lifecycle: `deploy → install → enable → start → operate → update → verify → rollback`.
    - **Boundary held**: **caasi owns identity, declaration, invocation, verification and
      provenance; systemd owns running the service.** caasi renders a unit from the
      project's declaration, invokes `systemctl`, then *asks systemd* for state. No
      restart loop, no dependency graph, no process table — not a supervisor.
    - **Two declarations, because they are two problems** (this is the central design
      finding). The ROS 1 reference (`install.sh`) established **environment persistence
      only**, via five `~/.bashrc` appends; it never installed a service (grepping it for
      `systemd|rc.local|autostart|cron` returns nothing). Copying that would be wrong:
      shell-specific, not idempotent, not verifiable. So:
      | concern | reference | caasi |
      |---|---|---|
      | environment persistence | `~/.bashrc` appends | declared → systemd `EnvironmentFile` + login shell |
      | service persistence | **not done** | declared entrypoint → unit, enablement delegated to systemd |
    - **New**: `caasi.core.lifecycle`, `caasi runtime install|enable|start|status|verify|update|rollback`.
      `install` writes exactly three things (env fragment, unit, revision marker) and
      deliberately does **not** enable or start, so a partial failure is visible instead
      of half-applied invisibly.
    - **Revision identity**: each install records deployment id, git revision, timestamp
      and the *previous* revision on the target, so rollback has a real target.
    - **Validated on the real target `u24-307`** (fixture = a trivial long-running service;
      this stage proves the *mechanism*, not the robot stack): install → env/unit/marker
      read back; enable → systemd symlink; start → `active (running)` + MainPID; **env
      reaches the process** (`CAASI_E4_MARKER` in `/proc/<pid>/environ`, 0 invalid-assignment
      warnings); status; verify; update A→B (new PID, app reports `revision=rB`, chain
      records previous=A); rollback; drift detection (stopped service → verify fails, rc 1);
      failed update (bad entrypoint → `state=failed`, exit 127, rc 1, names the retained
      previous revision and the recovery command); recovery via rollback.
    - **Four real defects found by real validation** (the substance of the stage):
      1. `deploy` uses `rsync --delete` and **deleted caasi's own runtime state**, silently
         destroying the rollback point. Found by tracing `read previous=None`. Both files
         now excluded; verified the marker survives a deploy.
      2. **Rollback as a marker rewrite was a lie** — measured: marker said r5, files on
         disk were r6, process ran r6. Put to the user as a design fork rather than patched
         silently; decided: **rollback = redeploy the previous revision from the
         workstation**, and `verify` compares the *revision* (a `-dirty` suffix is the same
         content identity) while reporting a changed deployment id as evidence, not drift.
      3. Rollback now **refuses** when content is not honestly restorable (workstation at a
         different revision, or substantive uncommitted changes) and leaves the target
         untouched. Subtlety: `git status` counts caasi's own `.caasi/` bookkeeping as dirt,
         which told the operator to check out the revision they were already on; caasi's
         bookkeeping is now excluded from that judgement.
      4. `update` on a **reinstall** overwrote the rollback point with the revision being
         installed (self-referential marker). Found by a unit test; update now distinguishes
         a genuine update from a reinstall.
      5. Related: systemd's `EnvironmentFile` is **not shell syntax** — `export A=1` was
         logged as "Ignoring invalid environment assignment" and dropped, leaving the
         service running with the variable missing. Only checking `/proc/<pid>/environ`
         caught this; the service *ran* and looked healthy.
    - **NOT claimed** (stated before implementation, still true): **no physical reboot
      recovery** — `Linger=no` on the measured target meant user units did not survive
      logout/reboot; all preconditions were then established and observed (`Linger=yes`,
      `default.target.wants` symlink, `UnitFileState=enabled`) but **the machine was never
      rebooted**, so survival is untested. The lingering probe was reverted afterwards to
      leave the target as found. Also: no physical robot bringup persistence; no claim the
      OpenMover stack runs persistently (its real entrypoint/environment rendering was
      exercised, but not on hardware); system scope untested; only systemd implemented.
    - **Tests**: 55 new in `tests/test_lifecycle.py`. Full suite **1054 passed, 1 failed**
      (the pre-existing `test_perception_cmd.py` terminal-width artifact). One real
      regression was introduced and fixed: `runtime` had to be added to `HELP_PANELS`,
      caught by `test_help_panels_cover_every_root_command`.
    - **Version**: Phase 7 is the **caasi 0.4.0** milestone (*target and control-plane
      capabilities*). `pyproject.toml` + `__version__` set to `0.4.0`; `CHANGELOG.md`
      records remote targets, deployment/execution, observability, result collection and
      the runtime lifecycle under that version.
    - Fixtures removed from `u24-307` (unit stopped/disabled/deleted, deployment root
      removed, lingering reverted) and locally. Reference trees unchanged.
    - **Next, no auto-proceed.** Fleet scheduling and larger control-plane features were
      explicitly out of scope for this bounded stage.

  - **Phase 7 Architecture Gap Assessment: COMPLETED (read-only, no implementation).**
    - [Assessment](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/architecture-gap-assessment.md)
    - Pauses feature work to measure caasi against its stated end goal rather than
      adding capability because it is possible.
    - **Headline finding**: the *target-operation* half of the end goal is complete and
      validated (deploy, build, execute, observe, collect, lifecycle, provenance). The
      *control-plane* half — describe/submit work, **determine an appropriate target**,
      and run the chain as one step — is where the gaps are. The provenance spine already
      carries `target`/`destination`/`deployment_id`/`build_id`/`git_revision`, so
      *linking* is solved; what is missing is *deciding* and *sequencing*.
    - **Five genuine gaps**:
      * **G1 — nothing decides a target.** `find_target` resolves by name/prefix only.
        Yet every ingredient for requirement-driven selection already exists and is
        unconnected: manifest `requires:`, target `discovered_capabilities`/resources,
        and `requirements.satisfies()` with its three-valued verdict where **`None` means
        UNVERIFIED**. It is currently called only from `check.py`, and only for the local
        machine. Largest conceptual gap.
      * **G2 — `check` is local-only**, so incompatibility is found *after* choosing a
        target rather than before.
      * **G3 — the lifecycle is independent commands**, not a sequence; the developer
        hand-carries `deployment_id`/`build_id`/`run_id` between them.
      * **G4 — a legacy `remotes:` shim coexists with `targets:`.** Smaller than it looks:
        `list_targets` already documents it as legacy and *imports* those entries, so this
        is a retirement task, not a duplication.
      * **G5 — no workload object.** `Experiment` is local-only (no target/deployment);
        `RunRecord` is execution-only. Nothing expresses "the work, its requirements and
        its outputs" in a form that can be pointed at a target. This is why G1/G3 are hard.
    - **Recommendation (smallest next step, not yet started)**: a workload declaration plus
      a **read-only, requirement-driven `target select`** that reports a per-target verdict
      including UNVERIFIED — **advisory and inspectable, with execution still taking an
      explicit target**. This reconciles the stated goal ("determine an appropriate
      target") with the standing prohibition on "automatic target selection": selection
      advises and validates, it does not silently choose. Explicitly deferred:
      multi-target execution, queues, scheduling, resource claims.
    - Re-affirmed **not caasi's job** (domain tools own them): systemd, docker/podman,
      colcon/rosdep, ros2/rclpy, Isaac Sim/Lab, nvidia-smi, images/OS, target capability
      discovery. Test applied: *is caasi deciding and recording, or re-implementing?*
    - No code changed; nothing implemented.

  - **Phase 7 Durable Requirements + Workload/Selection Design: COMPLETED (design only).**
    - [Durable Requirements](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/durable-requirements.md) |
      [Workload & Selection Design](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/workload-and-selection-design.md)
    - **Durable requirements preserved (R1–R10)**, so they cannot be lost between sessions:
      R1 workstation as control plane; R2 target-aware existing tools (`caasi rviz2
      --target robot-01` as a *general pattern*, not an RViz subsystem); R3 existing tools
      remain domain owners; R4 target-aware execution; R5 workload abstraction broad enough
      for ROS2/Isaac/GPU-training/robot-deployment/Python, **not** designed around
      OpenMover; R6 requirement-driven inspectable target selection (advisory first, no
      hidden policy); R7 lifecycle composition keeping lower-level commands; R8 future
      multi-target control plane **(defer, do not design yet)**; R9 independent execution
      target vs artifact destination; R10 small **observation-only** web UI, CLI remains the
      control interface, no control buttons. Cross-cutting: the OpenMover-disappears
      architectural test, evidence discipline, explicit absence, nothing destructive on a
      persistent target.
    - **Design key finding (better than expected)**: the matching machinery *already exists
      and is already correct*. `core/check.py` documents the **Check Contract** with the
      exact verdict ladder needed (`compatible`/`untested`/`missing`/`incompatible`) and the
      §57 doctrine that a version outside a range must **not** assert incompatibility.
      Crucially, `CheckEngine` is built as *"one compatibility semantics behind every
      `check`"* and already serves multiple entry points (root `check`, `sim check`,
      `container check`). So the one real work item is not "build a matcher": it is making
      fact detection read from a **target's** discovered environment instead of only
      `config`/`shell.which` (the current, local-machine-only source). `target select`
      becomes the next **entry point of an existing engine**.
    - **Model validated against six generalized cases** (local Isaac Lab; remote CPU ROS2;
      remote GPU sim/training; OpenMover deployment; `rviz2 --target robot-01`; simple
      Python). All are instances of one model: same `requires` field, same `steps`
      vocabulary, differing only in *content*. Only one case uses any ROS-specific concept,
      and only as **data** (`ros2: jazzy` is a requirement value, not a code path). The
      OpenMover case is **not special** — its only distinction is using the E4 lifecycle as
      an *additional step in the same model*.
    - **Proposed model**: `Workload` (name, requires, steps, outputs) is the only genuinely
      new model, and it introduces **no new execution machinery** — `steps` names operations
      caasi already has. `SelectReport` is a pure reporting type. Everything else reuses
      `Target`/`TargetEnvironment`/`TargetResources`, `requirements.satisfies`,
      `manifest.requires:`/`tested:`, `OutputDeclaration`, deployment/build/run records and
      `RuntimeDeclaration`.
    - **Staged plan**: **F1** target-aware facts + `Workload.requires` + advisory read-only
      `caasi target select` (smallest foundational step; G1/G2/G5 in one step, no new
      authority, no second compatibility semantics); **F2** workload `steps`/`outputs` +
      `caasi workload run --target` composing deploy→build→run→collect with existing
      provenance; **F3** target-aware tool invocation (R2). **Explicitly deferred**: R8
      multi-target/queues/scheduling/allocation and R10 web UI — the review shows neither is
      required by F1–F3.
    - **Boundaries stated**: `steps` is a fixed operation vocabulary, **not** a scripting or
      DAG engine; selection advises and refuses to guess, never a hidden scheduler; tool
      wrappers are thin and declarative, never subsystems; composition records the *same*
      provenance as the manual path rather than a parallel model.
    - No code changed; nothing implemented.

  - **Phase 7 Traceability + Stage F1: COMPLETED.**
    - [Traceability](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/traceability.md) |
      [Stage F1 Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/stage-f1-report.md) |
      [Durable Requirements](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/durable-requirements.md) |
      [Design](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/workload-and-selection-design.md)
    - **G1–G5 kept explicitly alive.** G1–G5 are the *architectural gaps*; F1–F3 are the
      *implementation stages*. They are never substituted for one another, and implementing a
      stage does not close a gap. New `traceability.md` records the full chain
      **end-goal requirement (R1–R10) → gap (G1–G5) → stage (F1–F3) → evidence**, and the
      gap assessment is annotated in place so each gap shows its stage and status.
      Mapping: **G1→F1**, **G2→F1**, **G3→F2**, **G4→outstanding cleanup (not F1)**,
      **G5→F1/F2**.
    - **Stage F1 implemented** (G1, G2, first half of G5; R1, R4, R5, R6):
      * `caasi.core.selection` — supplies the missing half of the **Check Contract**: same
        verdict ladder, same §57 caution, same exit policy, but facts sourced from a
        **target's** discovery instead of the local machine. **No new compatibility
        semantics** — `target select` is another entry point of the existing engine.
      * `caasi.core.workload` — **minimal** `Workload` (`name`, `requires`); `steps`/`outputs`
        parse and are recorded but not acted on until F2, so an F2 workload loads today.
      * `caasi target select [WORKLOAD] [--json]` — advisory, read-only, **chooses nothing**.
    - **Three-way honesty enforced**: satisfied → `compatible`; asked-and-absent → `missing`
      (a real absence); **never asked → `untested` (not evidence of absence)**. `unreachable`
      is a transport result, not a verdict.
    - **Two defects found by validating against real targets** (not fixtures):
      1. GPU path reported `untested` "not measured" for `u24-307`, which **has no GPUs** —
         telling an operator "unknown" when the true answer is "none". Fixed by preserving the
         measured empty list and distinguishing it from a missing inspection.
      2. A workload file using the `workload:` block spelling parsed to **empty `requires`**,
         silently reading "this work needs nothing". The parser now accepts that spelling *and*
         **rejects unknown keys**, so a typo is reported instead of quietly weakening the
         requirement set.
    - **Evidence on real targets** (`u24-307` remote Jazzy/no GPU; `local` RTX 3080 10GB):
      `ros2 jazzy` → both `ready`; `ros2 humble` → both `warning` with the out-of-range note and
      **exit 0** (§57 honoured); `isaac_sim >=5.0` → both `incompatible`, exit 3;
      **`gpu count>=1, 8GB` → `u24-307` incompatible ("target reports no GPUs"), `local` ready**;
      `torch >=2.0` (never probed) → `warning`, "not measured", exit 0; unreachable target →
      own verdict with the connect error; unknown workload / no requirements → exit 1.
      The **real OpenMover `requires:`** (`ros2 jazzy`, `isaac_sim>=5.0`, `isaac_lab>=2.0`,
      `nav2`) was evaluated against both targets without modifying the project: `ros2`
      compatible, isaac `missing`, **`nav2` untested** (discovery does not probe ROS packages —
      honestly unmeasured, not a false "missing").
    - **Explicitly NOT done (not claimed)**: no target selection/ranking/automatic pick
      (it reports, never chooses); **no composition** (nothing deploys/builds/runs/collects —
      that is F2); steps/outputs not acted on; no ROS-package probing; **G4 untouched**.
    - **No gap is closed by F1.** G1/G2 stay **open** until this evidence is accepted; G5 stays
      open until F2; G3 and G4 untouched.
    - **Tests**: 39 new in `tests/test_selection.py`. Full suite **1093 passed, 1 failed**
      (the pre-existing `test_perception_cmd.py` terminal-width artifact).
    - **Next: Stage F2** (workload `steps`/`outputs` + lifecycle composition → G3, completes G5),
      then stop for review. Do not auto-proceed.

  - **Phase 7 Heterogeneous Targets + Stage F2 Design: COMPLETED (design/evidence only).**
    - [F2 Design](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/stage-f2-design.md) |
      [Durable Requirements](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/durable-requirements.md) |
      [Stage F1 Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/stage-f1-report.md)
    - **Heterogeneous real targets recorded durably as R4a/R4b.** The two real machines are a
      genuinely heterogeneous pair (measured, not assumed):
      | | **`u24-307`** CPU-only robot | **`local`** (= `u24-z690p`) GPU workstation |
      |---|---|---|
      | Transport | ssh/Tailscale | local |
      | ROS 2 / Python | jazzy / 3.12.3 | jazzy / 3.12.3 |
      | **GPUs** | **0** | **1 (RTX 3080, 10 GB)** |
      | CUDA | **none** | 13.0 |
      | Docker | no | yes |
      | Isaac Sim/Lab | not detected | present |
      `u24-307` stands for the commonly-expected CPU-only robot/target; `local` (= `u24-z690p`)
      for a GPU-capable compute/simulation target.
    - **Decided (via ask): keep `local` as the built-in; do not add a duplicate name.** The
      workstation hostname is `u24-z690p` but caasi already exposes it as `local`; a second
      name for the same machine would make a heterogeneous demo confusing. The config was
      restored to its original state.
    - **R4b recorded**: work starts at the workstation and runs on the target — the developer
      must never need to be interactively logged into the target. This **already holds**
      (remote runs use non-interactive SSH, `BatchMode=yes`) and must remain true under
      composition.
    - **Third F1 defect found using the real pair** (same class as the GPU one): discovery
      reports the workstation's Isaac Sim as `{"status": "ok", ...}` with **no version key**;
      the fact mapping turned that into `None`, which the ladder reads as **absent** — so a
      machine that *has* Isaac Sim was reported as not having it. The Check Contract's own
      convention (`check._isaac_version` → the literal `"installed"`) had been broken. Fixed;
      6 regression tests added. This is the third instance of one rule: **"not measured" and
      "absent" must never be collapsed.**
    - **Validated on the real pair** — every difference comes from measured facts:
      | workload | `u24-307` | `local` |
      |---|---|---|
      | python>=3.10 + ros2 jazzy (CPU-only) | **ready** | **ready** |
      | gpu>=1, 8GB + ros2 jazzy | **incompatible** ("target reports no GPUs") | **ready** |
      | isaac_sim>=5.0 + cuda + ros2 jazzy | incompatible | warning (isaac present, version unrecorded) |
      Architecture demonstrated: `workload → evaluate targets → u24-307 incompatible / local
      ready`. **NOT** demonstrated (correctly): automatic forwarding/allocation (R8, deferred).
    - **F2 design written** (not implemented): `steps` as a **fixed ordered vocabulary of
      existing operations**, not a DAG/scripting engine; unknown steps rejected; compose
      `deploy→build→run→collect→provenance`; **a failing step stops the chain** and reports
      which link failed; **composition records the same provenance** as the manual path (no
      parallel "workflow record"); target is **required** (`--target`), never defaulted or
      forwarded. §6 records explicitly how F2 **does not prevent** later allocation/forwarding/
      queues. Validation plan targets the **two real machines**, not synthetic GPU fixtures.
    - **Full suite: 1099 passed, 1 failed** (pre-existing `test_perception_cmd.py` artifact).
    - **Next: implement F2** → G3, completes G5. Then stop for review.

  - **Phase 7 Stage F2 (Workload Steps + Lifecycle Composition): COMPLETED.**
    - [F2 Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/stage-f2-report.md) |
      [F2 Design](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/stage-f2-design.md) |
      [Traceability](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/traceability.md)
    - **Addresses G3 (closed) and completes G5 (closed)**; R1, R4, R5, R7. G1/G2 remain **open**
      pending explicit acceptance of the F1 evidence; **G4 untouched**.
    - **`steps` is a closed vocabulary** `("deploy","build","run","collect")` of **existing**
      operations — not a DAG, not a scripting engine, no conditionals/loops/retries. Two spellings
      (bare, single-key mapping); **unknown steps rejected at parse time**.
    - **`caasi workload list|inspect|run`**; `--target` is **required**, no default, no forwarding.
      `--dry-run` shows the plan + compatibility verdict and touches nothing.
    - **Composition**: `compose()` runs steps in order through thin wrappers over the *same* core
      functions the CLI uses. A failing step **stops the chain**, names it, and preserves the ids
      already produced. `--skip-check` exists for debugging.
    - **Synchronous composition semantics** (per decision): `start_target_run` stays detached and
      unchanged, but composition **waits for a terminal state**. Only `succeeded` continues;
      `failed` and `stopped` stop the chain. **"Launched" is never confused with "succeeded"**.
    - **Real-machine validation**:
      * CPU-only workload on **`u24-307`**: `deploy → run → collect` succeeded, artifact collected.
      * **Full four-step** `deploy → build → run → collect` on **`u24-307`**: all ✔, rc=0, with
        `build_id`/`deployment_id`/`run_id`/`git_revision` recorded.
      * GPU workload on **`local`**: succeeded, GPU work delegated to `nvidia-smi` (never
        reimplemented); reported `1 artifact(s) already on the workstation (local target, nothing
        to copy)` — honest for a local target.
      * **Workstation-initiated remote execution proven**: the collected artifact reads
        `host=u24-307 rclpy ok, ROS_DISTRO=jazzy`.
      * **Real OpenMover workload**: the gate correctly **refused** it on `u24-307` (project
        requires `isaac_lab`, absent on the CPU-only target) — re-checked that **nothing was
        deployed**.
      * **General workload** (plain Python) carried by the same model → **not OpenMover-specific**.
      * **Failure path**: chain stopped at `run`, `collect` did NOT run, exit 1, and the script's
        own **exit code 7 surfaced**.
    - **Provenance**: composed runs record the **same** records as the manual path — verified by
      reading a composed run back through `caasi run list` and `caasi run artifacts`. No parallel
      workflow record exists.
    - **Defects**:
      1. **Pre-existing, FIXED** (exposed by F2, confirmed identical at HEAD): `runs.effective_status`
         returned **`lost`** for a `target: local` run executing in the deployed sandbox
         (`remote_run_dir` set, `exit_code=0`), so composition **hung**. The discriminator is now the
         **run directory**, not the target name. 3 regression tests.
      2. **F2's own, fixed**: a *launched* run was treated as *succeeded* (detached primitive) —
         fixed by waiting for terminal state.
      3. **F2's own, fixed**: the build step read a non-existent `status` attribute; `BuildResult`
         reports success via **`ok`**, so a *successful* build was reported `unknown` and wrongly
         stopped the chain.
      4. **F2's own, fixed**: `collect` inventoried the run *directory* (caasi bookkeeping) instead
         of the run's **working** directory — the same trap E1 hit once already.
      5. **F2's own, fixed**: workload `outputs` were passed unparsed, so the wrong files were
         collected (the experiment config, not the result).
      6. **Pre-existing, REPORTED NOT FIXED** (per decision): for `target: local`, `build` records
         to the **project root** (`destination_path=str(project_root)` in `build.py`) while `run`
         looks at the **deployment destination**, so `caasi build --target local` + `caasi run
         --target local` **already fails today**. Needs a decision on the intended contract
         (project-root vs destination vs explicit distinction). **No workaround logic added.**
    - **Tests**: 41 new in `tests/test_compose.py`. Full suite **1140 passed, 1 failed** (the
      pre-existing `test_perception_cmd.py` terminal-width artifact). One F1 test updated because
      F2 legitimately replaced its placeholder contract.
    - **Next: F3 NOT started** (per instruction). Carried forward, neither blocking F3: the
      **build/run destination mismatch** for `--target local`, and **G4** (`remotes:` retirement).

  - **Phase 7 F1 Acceptance Review + F3 Design: COMPLETED (review/design only, no implementation).**
    - [F1 Acceptance Review](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/stage-f1-acceptance-review.md) |
      [F3 Design](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/stage-f3-design.md) |
      [Traceability](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/traceability.md)
    - **Gap statuses formally recorded**: **G1 CLOSED**; **G2 CLOSED on capability**
      (with a recorded consolidation item); **G3 CLOSED**; **G4 OPEN / cleanup**;
      **G5 CLOSED**.
    - **G1 closure verified against its agreed definition**, live on the real remote target:
      requirement-driven (merges project + workload `requires:`, matches via
      `requirements.satisfies`), inspectable (every verdict carries required/detected/note),
      **advisory (returns a *set*, never a choice)**, and **no ranking/scoring/preference
      logic exists** — `compose` uses `select_target` only as a *gate* on a named target.
    - **G2 closure verified live on `u24-307`**: §57 out-of-range → `untested` (not
      `incompatible`), `missing`, and `unmeasured` all behave per the Check Contract, with
      facts sourced from the target's own discovery.
    - **One genuine remaining gap REPORTED, not smoothed over** (per instruction): the F1
      *design* said `target select` would be another **entry point of the existing
      CheckEngine**; the implementation instead left `check.py` unchanged and
      **re-implemented the requirement ladder in `selection.py`** (11 verdict constructions
      vs 7 in the contract's equivalent ladder). For default projects the two **agree**, so
      the F1 evidence stands. They are **not identical**: `selection.py` calls
      `summarize(..., strict=False)` unconditionally, so under `check.strict: true`
      `caasi check` reports `incompatible` (exit 3) while `target select` reports only a
      `warning` (exit 0). Recorded as an **open consolidation item**; **not** fixed in a
      review pass, and **does not block F3**.
    - **F1 implementation was NOT changed to make status appear closed.**
    - **F3 design written (NOT implemented)**: *target-aware tool invocation*, principle
      **"caasi supplies context, then gets out of the way."** One generic declarative
      mechanism `caasi <tool> --target <t>` (`rviz2`, `rqt`, `rosbag record` as eventual
      proof cases, chosen to prove generality, not to build a subsystem). Design covers:
      what "target context" is; authoritative-vs-unverified target facts; the
      **domain-ID hazard** (the empty-graph trap — explicit `--domain` > target-reported >
      **refuse, never silently defaulted**); how a *local* GUI tool consumes a *remote* ROS
      graph (caasi's job ends at a correct environment; **cross-machine DDS discovery is the
      DDS implementation's responsibility**); pass-through of unrecognised tool arguments;
      error/exit-code reporting (the tool's own code); and explicit scope boundaries.
    - **F3 explicitly excludes**: automatic selection/forwarding/queues/scheduling/
      multi-target orchestration, new ROS/DDS functionality, an RViz replacement, remote GUI
      management, a web UI, **G4 cleanup**, and daemonising the launched tool.
    - **Honest expectation recorded up front**: for a remote GUI tool across Tailscale, DDS
      discovery **may not work** even with a correct environment; that would be reported as
      a network/DDS fact, **not worked around and not claimed as working**. Negative cases
      (refusals) carry the validation weight, not the positive "a window appeared" case.
    - **F3 NOT started.** No F3 code exists.
    - No implementation changes of any kind in this pass.

  - **Phase 7 Stage F3 (Target-Aware Tool Invocation): COMPLETED.**
    - [F3 Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/stage-f3-report.md) |
      [F3 Design](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/stage-f3-design.md)
    - **Requirement R2.** Principle held: **"caasi supplies context, then gets out of the way."**
      One **generic** mechanism (`caasi rviz2 --target t`, `caasi rosbag --target t record …`,
      `caasi tools list|run`). **No part of rviz2/rqt/rosbag and no part of DDS is implemented.**
    - **A tool is data, not code**: `tools:` config entries (`invoke` + declarative
      `environment`). Verified by adding **new tools purely in configuration** during
      validation — invocable with **no code change**. That is the genericity claim tested.
    - **Target facts are never substituted with local ones**: `rmw=None` on both targets (no
      back-fill); a target asked that sets no domain reports `UNSET` (**measured absence**),
      kept distinct from `None` (never asked). `RMW_IMPLEMENTATION` is omitted rather than
      inheriting the workstation's, which would silently change the target's DDS behaviour.
    - **The domain guard (the empty-graph trap) works**: explicit `--domain` > target-reported
      > **REFUSE**. Refusal (exit 3): *"…does not set ROS_DOMAIN_ID … pass --domain explicitly
      rather than assuming the default (an assumed domain can silently show an empty ROS
      graph)"*. **Never silently defaulted to 0.**
    - **Refusals are first-class evidence**: unreachable (exit 3, transport reason); no ROS 2
      (*"nothing to attach to"*); unknown tool (lists available); missing local binary.
      **The tool's own exit code propagates unmodified** (7 → 7). Argument pass-through verified:
      `record --unknown-flag -x /scan /tf` reached the tool verbatim.
    - **Remote GUI / discovery — the honest result (measured, not assumed)**: a real ROS 2
      `talker` (no hardware, no motion) was run on `u24-307` on domain 42. The target sees its
      own node ✅; **local discovery on the workstation works** (saw `/f3_local_talker` on the
      same domain) ✅; but **`u24-307`'s node is NOT discovered from the workstation** ✗ —
      *despite caasi resolving the context correctly* (`ROS_DISTRO=jazzy`, `ROS_DOMAIN_ID=42`).
      Verified NOT a mismatch caasi could fix within scope: `RMW` unset on **both** sides,
      `ROS_LOCALHOST_ONLY` unset, both routable — but the machines are on **different LANs**
      (target `192.168.31.34` = **100% packet loss**; reachable only via Tailscale ~440 ms).
      **Cause: DDS multicast discovery does not traverse the Tailscale link.** Per the agreed
      boundary this is **recorded, not worked around** — caasi implements no DDS discovery,
      tunnels or relays. Explicitly **not** claimed as working, and "RViz window opens" was
      **not** treated as proof.
    - **Defect found in F3's own code**: `output.fail()` **raises its own `Exit(1)`**, so a
      `raise typer.Exit(3)` after it was unreachable and every refusal exited **1**. Caught
      only by **measuring the exit code** — the printed message was already correct. Fixed.
      (Also re-encountered the `pgrep -f` self-match trap from E3 on the target.)
    - **The F1 consolidation item was NOT fixed and did not block F3** (F3 never evaluates
      project requirements). Still open: `check.strict` divergence between `caasi check` and
      `target select`.
    - **Tests**: 35 new in `tests/test_toolctx.py`. Full suite **1175 passed, 1 failed**
      (pre-existing `test_perception_cmd.py` artifact).
    - **Hygiene**: config byte-identical to original (probe targets/tools removed); probe ROS 2
      node stopped and removed on `u24-307`; local probes removed. Reference trees unchanged.
    - **F3 NOT extended**: no auto-selection/forwarding/scheduling/queues/multi-target, no new
      ROS/DDS functionality, no RViz replacement, no remote GUI management, no web UI, no
      daemonisation, **no G4 cleanup**. **Stopping for F3 review.**

  - **Phase 7 R8 Architecture Review: COMPLETED (review only, no code, no F4).**
    - [R8 Architecture Review](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/r8-architecture-review.md)
    - Questions R8 (future multi-target execution, resource allocation, scheduling) against what
      F1–F3 actually proved, using the two real heterogeneous targets as evidence, without
      hardcoding either machine.
    - **Headline finding: most of R8's preconditions already exist.** Four of the six things a
      scheduler would need are already solved and required **no new state**:
      * what work needs (F1 `requires`), what a target offers (live discovery), does X satisfy Y
        (F1 `target select`), **what is running where** (derivable from existing `RunRecord`s —
        verified: `local` 24 succeeded/3 failed/6 stopped, `u24-307` 5/3/1), where results go
        (E1/R9 per-artifact routing), and provenance across the chain.
      * **The occupancy result matters most**: a scheduling system is usually justified by needing
        to know what is busy — and that fact is *already recorded*. A future allocator can be a
        **query over existing records**, not new state.
      * **So the missing piece is not "a scheduler"** — it is narrow: expressing *"run this where
        it fits"* as an explicit, inspectable decision instead of a hand-typed target name.
    - **Four categories distinguished**:
      1. **Solved by F1–F3**: requirement declaration/merging, live discovery, per-target
         compatibility, the composed chain, independent artifact destinations, provenance,
         target-aware tool invocation.
      2. **Genuinely missing** — **M1: workload identity is absent from provenance.** Verified on a
         real composed run: a run records `kind: workload` and `name: hello2` (the *experiment*),
         but the **workload name appears nowhere** — the first link of the chain is missing, so
         "which workload produced this?" cannot be answered once more than one exists. **Small, a
         correctness gap, and a prerequisite** for anything keying on the chain. **M2**: no way to
         express "run this where it fits" (the gap R8 names — but the answer is a selector, not a
         scheduler). **M3**: occupancy is derivable but not exposed (a presentation gap, not a
         state gap).
      3. **Useful but premature**: capacity *booking* (declared resource constraints already work
         — `gpu: {count, memory_gb}` is implemented and tested; what is missing is reserving
         against totals), concurrency admission control, reservations/leases, submit-and-forget
         (needs a destination to submit *to*).
      4. **Deferred until a real multi-target case requires it**: **queues, scheduling, automatic
         allocation, multi-target execution, resource claims, cross-target aggregation, fleet.**
    - **Why queues specifically are deferrable — argued, not assumed**: a queue solves
      *contention*, and none has been observed (one developer, two targets, ad-hoc runs). The
      input for *detecting* contention already exists, so the cheapest honest answer is a query
      saying "target X is busy with run Y" — strictly less machinery than a queue and strictly
      more honest, since it silently reorders no one's work. A queue without a scheduler is
      meaningless, and a scheduler designed without evidence would be designed against a guess.
    - **Minimum abstraction recommended**: an **explicit, explained `--where` policy**
      (`any` / `idle` / `prefer:<tag>`) over the existing verdict machinery — opt-in, always
      naming the chosen target and the eliminated ones **with reasons**, **no queue, no waiting,
      no new state**, and `--target` unchanged as the default. If nothing satisfies, it **fails
      with reasons; it never enqueues**. This does not breach "automatic target selection" because
      it is a *query the operator asks*, not a *policy applied unbidden*.
    - **Open items: before or after?** **F1 ladder consolidation → BEFORE** (the proposed stage
      extends *selection*, which is exactly the duplicated code; building on the duplicate would
      widen the divergence while `check.strict` remains broken). **F2 local build/run destination
      semantics → BEFORE, or explicitly scoped** (a `--where` policy could select `local`, and
      `local` + a `build` step is currently broken by that pre-existing mismatch; selection must
      not be able to choose a broken path). **G4 → AFTER** (independent cleanup; `list_targets`
      already imports the legacy entries so selection correctness is unaffected). **DDS-over-
      Tailscale → AFTER / probably permanently deferred** (environmental; affects remote GUI tool
      use, not multi-target execution or scheduling; working around it would breach the agreed
      boundary).
    - **Recommended order**: (1) close **M1** workload identity; (2) **consolidate the F1 ladder**
      and **decide the F2 `local` build/run semantics**; (3) implement the minimum `--where`
      abstraction; (4) **do not** implement queues/scheduling/allocation/multi-target execution.
    - **All four open items remain exactly as recorded** — none removed, none treated as solved.
      **No code changed. F4 not implemented.**

  - **Phase 7 `--where` Selection Design: COMPLETED (design only, nothing implemented).**
    - [Design](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/where-selection-design.md) |
      [R8 Review](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/r8-architecture-review.md) |
      [Prerequisites Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/prerequisites-m1-f1-f2-report.md)
    - **The distinction the design protects**: `--where` answers *"which currently suitable target
      should I use?"* — **a query the operator asks**. A scheduler would answer *"when and where
      should this run?"* — **a policy the system applies unbidden**.
    - **Policies**: `--where any` / `idle` / `prefer:<tag>`, plus `--target` unchanged as the
      explicit default. Mutually exclusive; **omitting both is an error** (no implicit default).
    - **Nothing here is new machinery**: `select_all` *already* returns the candidate set of
      reports (ranks nothing), tags already exist on real targets (`cpu-only`, `workstation`,
      `remote`, `gpu`…), and **occupancy is already derivable** from `list_runs` +
      `effective_status`. The new work is a *stated, inspectable decision over an existing
      result*, plus recording it in provenance.
    - **Evaluation**: evaluate all targets → eligible = reachable AND not `incompatible`
      (`warning`-grade is **eligible**, because absence of evidence is not evidence of absence,
      and its note is printed) → order by the policy → choose the first → **if none, FAIL**.
    - **The tie-break is stated, not hidden**: lexicographic on the policy key then **target
      name**, so the choice is predictable and reproducible. There is **no scoring, weighting,
      cost model or load balancing** — `prefer:<tag>` is filter-then-name-order, not a score.
    - **The choice is never silent**: an always-printed report naming the **selected** target,
      every **eliminated** target with its failing requirement and the **measured evidence**
      (e.g. *"reports no GPUs"*), and any **unmeasured** notes. Same content in `--json`.
    - **Failure is the required behaviour when nothing fits**: fail immediately with every
      target's reason, non-zero exit, **nothing deployed, nothing queued, no waiting, no retry,
      no forwarding**. This is the design's most important property — a queue would turn
      "nothing fits now" into "something might happen later", which is exactly the scheduling
      semantics this stage must not add.
    - **Occupancy used only where honest**: `running`/`paused` occupy; terminal states do not;
      **`lost` is an unknown** — not counted as busy, **and reported**, never silently treated as
      either busy or free. Occupancy is a **preference, never a guarantee** — two simultaneous
      submissions can both see a target as idle, and that race is **not** fixed here because
      closing it would require the queue (no reservation exists today; multiple runs per target
      are already the norm).
    - **Validation plan**: 13 cases against the two real targets, weighted toward **refusal and
      explanation** rather than the happy path. Case 4 (**nothing fits**) is the explicit
      anti-scheduler test — it must deploy nothing and leave nothing pending. Case 9 (`--target`
      alone) is the **no-regression guard**. Case 12 records the choice in provenance, which M1
      makes possible.
    - **Explicitly NOT done**: wait for a free target, reserve/hold, retry elsewhere, run on
      several targets, reorder/batch, score/rank/balance, default to a policy, aggregate across
      targets.
    - **Data model**: only a `SelectionDecision` reporting type and two provenance fields — **no
      new persistent state, no registry, no queue table**.
    - **Nothing implemented.** Awaiting review before `--where` implementation.

  - **Phase 7 `--where` Explicit Target Selection: COMPLETED.**
    - [Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/stage-where-report.md) |
      [Design](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/where-selection-design.md)
    - **The boundary held throughout**: `--where` answers *"which currently suitable target
      should I use?"* (**a query the operator asks**). A scheduler answers *"when and where
      should this run?"* (**a policy applied unbidden**). No queue, no reservation, no waiting,
      no retry, no forwarding, no scoring.
    - **Built**: `caasi.core.where` (policies, occupancy, decision + report), a
      `SelectionDecision` **reporting type only**, and two provenance fields. **No new
      persistent state, no registry, no queue table.**
    - **Reused, not rebuilt**: `select_all` (already evaluates all targets, already ranks
      nothing), `list_runs`/`effective_status` (occupancy **derived**, not tracked), real
      `Target.tags`, and the shared Check Contract ladder from the F1 consolidation.
    - **All 13 validation cases passed on the two real targets**, with attention on the refusal
      and regression cases:
      * `--where prefer:gpu` → selected `local`, **eliminated `u24-307` with "target reports no
        GPUs"**;
      * `--where prefer:cpu-only` → **selected `u24-307`** (it carries the tag), ordering
        explained as "matched";
      * `--where any` → **deterministic across 3 runs** (target-name tie-break);
      * **NOTHING FITS → failed, exit 3, per-target evidence, and NO deployment was created**
        (the anti-scheduler property, independently verified);
      * `--where idle` with a real 600s run occupying `local` → **selected `u24-307`** — the
        occupancy preference demonstrably changed the outcome;
      * `--target` alone → **byte-for-byte previous behaviour, no selection block** (the
        no-regression guard);
      * `--target` + `--where` → refused; neither → refused (no implicit default);
      * provenance recorded `selected_by: prefer:workstation` + `selection_reason`;
      * `lost` reported as *"unknown run state (neither busy nor free)"*, never resolved.
    - **Two defects found**:
      1. **F3's trap recurred**: `output.fail()` raises its own `Exit(1)`, so "nothing fits"
         exited 1 instead of 3. Only **measuring the exit code** revealed it (the message was
         already correct). Noted as a recurring hazard in this CLI helper.
      2. **Introduced earlier, found here**: the F1 consolidation made **target** verdicts
         inherit the local check's *"not detected on **this machine**"* — **factually wrong for
         a remote target**. The shared ladder now takes a `scope`, so a target verdict says
         *"not detected on this target"* while `caasi check` keeps *"this machine"*. The ladder
         stays single; only the phrase adapts. Caught by reading real remote output, not tests.
    - **Concurrency (documented, NOT solved)**: two simultaneous submissions can both see a
      target as idle and both select it. Occupancy is an **observation and preference, never a
      reservation**. Fixing that race belongs to a future allocation layer, and would require
      exactly the reservation machinery this stage must not add. Verified no reservation/lock
      exists and multiple runs per target are already normal.
    - **Tests**: 31 new in `tests/test_where.py`, including two structural guards — one inspects
      the **code** (not the docstring) for scoring/weighting/balancing vocabulary, one asserts
      no threading/asyncio/queue/sleep machinery. Full suite **1215 passed, 1 failed**
      (pre-existing `test_perception_cmd.py` artifact).
    - **NOT done**: queue, reservation, resource booking, waiting, retry, automatic forwarding,
      multi-target execution, scheduling, ranking/scoring, fleet, web UI. **G4 untouched.
      DDS-over-Tailscale untouched.** `.trae`/`.reasonix` untouched.
    - **ACCEPTED.** `--where` is complete and matches the agreed R8 boundary. Concurrency
      remains **intentionally unresolved** (occupancy is an observation/preference, never a
      reservation). **R8 is not expanded further.**
    - **R8 status recorded**: **selection DELIVERED**; queues, reservations, waiting, retries,
      automatic forwarding, scoring/ranking, scheduling, fleet management and multi-target
      execution remain **deliberately deferred — not partial work, but assessed and found
      unjustified**.
    - **What would justify revisiting them** (recorded so a future stage is evidence-driven):
      1. **observed contention** — a queue solves contention and none has been observed (one
         developer, two targets, ad-hoc runs). The inputs for *detecting* it already exist
         (`--where idle` reads live occupancy), so the trigger is a real observation rather than
         a design ambition;
      2. **a real second-target use case** — multi-target execution needs work that genuinely
         must span machines.
    - **Observed limitations (open, not worked around)**: the **idle-target race** (by design;
      closing it needs the reservation machinery that is out of scope); **DDS-over-Tailscale**
      (environmental network fact, not a caasi defect); **G4** (`remotes:` shim, untouched).
    - **Traceability updated**: R6 consolidation item marked **resolved**; R8 marked **selection
      delivered / remainder deferred**; new rules recorded that *deferral is not closure*,
      *partial delivery does not close the remainder*, and *a limitation recorded is not a
      limitation solved*.
    - **Next architectural gap identified (not started)**: **M3 — target occupancy is not
      exposed as a query.** Occupancy is computed inside `--where` but an operator cannot ask
      *"what is running where?"* directly — `caasi target list` shows transport/endpoint/tags
      but not live runs, and `occupancy_by_target` has exactly one caller. This is the
      **presentation** gap the R8 review flagged (inputs already exist; only exposure is
      missing), and it is the smallest genuinely-open item. **Not started — stopping here.**

  - **Phase 7 Exit-Code Guard + Evidence-Based Stopping Point: COMPLETED.**
    - [Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/exit-code-guard-report.md)
    - **The next item was a correctness defect, not a new capability.** A survey of the open work
      found every candidate deferred-against-evidence, environmental, or by design — so the
      smallest genuinely-open item was a **defect**.
    - **`output.fail()` exit-code defect — FIXED.** The helper raises its own `Exit(1)`, making a
      following `raise typer.Exit(N)` unreachable: the command exits 1 while the author intended N.
      **The message is correct, which is what made it dangerous** — visible only by *measuring*
      the exit code. The class had now been hit **three times** (F3, `--where`, `workload run`
      incompatible target); the third was found by a **static CLI survey**, not by testing.
      Verified on a real target: a 4-GPU requirement against the workstation's single RTX 3080
      now exits **3**, with the same message.
    - **Scope measured, not assumed**: the survey found **76** unreachable raises, of which only
      **one** was genuinely wrong. The other 75 use `Exit(1)`, matching what `fail()` already
      raises — dead but harmless. **Deliberately left untouched** rather than churned as
      unrelated cleanup.
    - **Durable guard**: a CLI-wide static test catches the class, **verified to actually fail** by
      temporarily reintroducing the defect (test failed with the offending location, passed again
      once restored). *A guard never seen to fail is not evidence of anything.*
    - **Conclusion (agreed phrasing):**
      > **The currently justified capability set is complete for the evidence gathered so far.**
    - **The next expansion must be justified by NEW EVIDENCE** — e.g. a **second real project**
      (proving the model generalises beyond one codebase) or a **genuine multi-target workload**
      (what would justify revisiting the deferred scheduling remainder) — **not** by an
      architectural desire to fill the remaining roadmap. **Development does not continue merely
      to keep moving.**
    - **Remaining roadmap disposition**: R8 scheduling/queues/reservations **deferred** (awaiting
      observed contention, not an implementation gap); R9 third artifact destination **deferred**
      (requirement says *eventually*; no use case); R10 web UI **deferred** by requirement; G4
      `remotes:` shim **cleanup**; DDS-over-Tailscale **environmental**; idle race **by design**.
    - **Tests**: 1 new CLI-wide guard. Full suite **1224 passed, 1 failed** (pre-existing
      `test_perception_cmd.py` terminal-width artifact).
    - **No further capability work started. State preserved as-is. Stopping for review.**

  - **Current State**: Nine threads closed and committed — the three-way equivalence
    chain (**`ROS1 ≈ ROS2-reference ≡ caasi-ROS2`**); **Stage D** (real remote target
    validation against `u24-307`, three defects found and fixed); **Stage E1**
    (result/output collection with the ephemeral-vs-persistent distinction);
    **Stage E2** (remote ROS 2 observability via `caasi ros … --target`); **Stage E3**
    (non-ROS runtime adapters for process, systemd and container, observe-only);
    **Stage E4** (persistent runtime lifecycle: install/enable/start/status/verify/
    update/rollback, with revision identity and an honest rollback); **Stage F1**
    (workload model + advisory, requirement-driven, inspectable `caasi target select`);
    **Stage F2** (workload `steps` and lifecycle composition
    `deploy → build → run → collect`); and **Stage F3** (target-aware tool invocation
    — one generic mechanism, `caasi rviz2 --target <t>`).
    These stages together are the **caasi 0.4.0** milestone (*target and control-plane
    capabilities*).

    **F1, F2 and F3 are all ACCEPTED as complete.**
    * **F1** — accepted with the **G2 consolidation item recorded as an open
      implementation issue** (below), which acceptance does not remove.
    * **F2** — four-step composition validated end to end on the real CPU-only target
      `u24-307`, a GPU workload on `local`, a plain Python workload proving the model
      is not OpenMover-specific, and the real OpenMover workload correctly refused by
      the compatibility gate.
    * **F3** — generic target-aware invocation accepted; the existing tools remain the
      domain owners, arguments and exit codes pass through unchanged, target facts are
      never back-filled from the workstation, domain selection is explicit and safe,
      and refusal cases are first-class.

    **Architectural gap status**: **G1 CLOSED**, **G2 CLOSED on capability**,
    **G3 CLOSED**, **G4 OPEN / cleanup**, **G5 CLOSED**.
    See [traceability](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/traceability.md)
    and the [F1 acceptance review](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-07/stage-f1-acceptance-review.md).

    **Conclusion — the currently justified capability set is complete for the evidence
    gathered so far.** The next meaningful expansion must be justified by **new evidence**
    (a second real project, or a genuine multi-target workload) rather than by an
    architectural desire to fill the remaining roadmap.

    **Open items — recorded, never blocking, never to be "tidied" by expanding scope:**
    * ~~F1 `check.strict` / `target select` consolidation~~ — **RESOLVED**: one shared ladder
      (`check.evaluate_requirement`) now serves both entry points, and `check.strict` is
      propagated rather than hardcoded.
    * ~~F2 local build/run destination mismatch~~ — **RESOLVED**: the contract was decided
      (`local` is a deployed target like any other) and the name-based special case removed.
    * **G4** — the legacy `remotes:` shim retirement (needs a migration path).
    * **DDS-over-Tailscale limitation** — an **environmental** finding, accepted as valid
      rather than a failed implementation: caasi supplies the correct ROS 2 context, but
      DDS multicast discovery does not traverse the Tailscale link between the two
      reference machines (different LANs; target `192.168.31.34` unreachable, ~440 ms via
      Tailscale). **Documented as a limitation, deliberately NOT worked around** — caasi
      implements no DDS discovery, tunnels or multicast relays.

    Next, no auto-proceed. Natural next validations each need something this
    environment lacks: **actual reboot survival** (a target that may be rebooted),
    **system-scope units** (privileges), and **running the real robot stack as a managed
    service** (robot hardware). Optional extensions exist (E1 artifact destinations,
    E3 container logs/inspect, multi-target aggregation) but none are required.
    (Carried-forward reproducibility gap, unrelated to these stages: no committed ROS 1
    Dockerfile for the legacy reference environment.)
