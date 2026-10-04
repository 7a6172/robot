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
  - **Phase 7 Stage D (Real Remote Target Validation): PAUSED, not cancelled.** Containerized
    remote-target validation over SSH had been partially exercised before this equivalence
    study was requested (target identity/discovery, project deployment with dev-artifact
    exclusion verified, target-native build, detached run lifecycle, remote logs/status/
    inspect, remote stop + process cleanup, and unreachable/bad-auth/undeployed failure
    cases). Two genuine `caasi` bugs it exposed were fixed and committed separately
    (`99fc43c`): the remote discovery probe was broken on any real SSH target
    (`python3 -c` argv was re-parsed by the remote shell → `SyntaxError`; now base64 +
    `shlex.quote`), and SSH identity selection is now bounded via `-o IdentitiesOnly=yes`.
    Remaining Stage D work (SSH-client-termination resilience evidence, A–G evidence matrix,
    Stage D report section) is **not yet done**. The Stage D container
    (`remote-target-01`) is stopped but retained; its scaffolding is parked at
    `/tmp/stage-d-parked/`. Per instruction, Stage D does **not** proceed until the user
    decides based on this equivalence evidence.
  - **Current State**: ROS 1 → ROS 2 functional equivalence validation complete and committed.
    Awaiting user decision on whether to resume Phase 7 Stage D, or to pursue another
    capability first.
