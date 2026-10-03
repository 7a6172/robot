# Phase 7 — Execution Targets, Remote Deployment & Fleet Orchestration

## Stage A Report: Target Model & Capability Discovery

**Status:** Completed & Empirically Verified  
**Date:** October 2026  
**Scope:** Stage A only (Target Abstraction, Capability Discovery, and Mismatch Detection)

---

### 1. Summary of Stage A Deliverables

Phase 7 Stage A establishes a first-class, project-agnostic execution target model in `caasi`. Execution targets (development workstations, remote robots, edge computers such as Jetson Orin, or compute clusters) are modeled explicitly by identity, transport, capabilities, and hardware resources.

The architecture enforces strict separation between:
1. **Configured Target Facts:** Declared statically by developers in `caasi.yaml` or global configuration (`targets:` section).
2. **Discovered Target Facts:** Empirically probed at runtime from the live target.
3. **Compatibility & Mismatch Engine:** Rigorously verifies declared versus discovered realities (e.g. CPU architecture, GPU presence, ROS 2 distribution, CUDA version, sensor capabilities).

---

### 2. Architecture & Implementation

#### 2.1 Core Target Abstraction (`caasi.core.targets`)
- **`Target`**: Configured representation specifying `name`, `transport` (`local` | `ssh`), `host`, `user`, `port`, `identity`, `deployment_root`, `tags`, `declared_capabilities`, and `declared_resources`.
  - Built-in default: `local` target is always available automatically with zero required user configuration.
  - Backward compatibility: Legacy `remotes:` entries are automatically imported as SSH targets.
- **`TargetResources`**: Discovered hardware metrics (`cpu_model`, `cpu_count`, `memory_total_kib`, `memory_available_kib`, `gpus`).
- **`TargetEnvironment`**: Discovered software environment (`os`, `kernel`, `arch`, `hostname`, `python_version`, `ros_distro`, `ros_root`, `rmw`, `cuda_version`, `nvidia_driver`, `isaac_sim`, `isaac_lab`, `docker`).
- **`TargetInspection`**: Unifies reachability, round-trip latency (`latency_ms`), status (`online`, `unreachable`, `error`), discovered capabilities, and detected mismatches.

#### 2.2 Discovery Engine
- **Local Target**: Evaluated in-process via `caasi.core.environment.collect(config)` in ~300-500ms without subprocess overhead.
- **Remote Target**:
  - Non-blocking socket preflight (`check_socket_reachable`) with bounded timeout (default 1.5s) to guarantee `caasi` never hangs when remote targets are offline or unreachable.
  - Compact standard-library Python probe script executed over SSH (`python3 -c "..."`). Does **not** require `caasi` or third-party packages to be preinstalled on the remote target prior to first discovery.
  - Measures TCP latency and captures full hardware and OS state in a single round-trip.

#### 2.3 Mismatch & Validation Engine
- Evaluates declared vs discovered facts across:
  - Architecture (`decl_arch != detected_arch`)
  - Accelerators (`decl_gpu == True` when 0 GPUs detected)
  - CUDA drivers and runtime
  - ROS 2 distribution match
  - Sensor and domain capabilities (`declared_capabilities` missing from `discovered_capabilities`)

#### 2.4 CLI Interface (`caasi target ...` with alias `caasi node ...`)
- `caasi target list [--check] [--json]`: Lists all targets with transport, endpoint, deployment root, tags, and optional live reachability/latency.
- `caasi target inspect <name> [--json]`: Comprehensive discovery report detailing hardware resources, environment, detected simulators, declared vs discovered capabilities, and compatibility status.
- `caasi target check <name> [--json]`: Fast connectivity and capability verification tool returning exit code `0` on success and `1` on mismatch or unreachable target.

---

### 3. Verification & Empirical Results

#### 3.1 Unit Test Coverage
19 new unit tests in `caasi/tests/test_targets.py`:
- Target defaults and serialization
- Automatic `local` default target injection
- Config-driven `targets:` loading
- Legacy `remotes:` backward-compatibility import
- Target query resolution (exact and prefix matching)
- Capability and resource mismatch detection (matching vs discrepancy cases)
- Local target discovery
- Unreachable socket handling without hanging
- Unreachable remote target handling
- Remote discovery over SSH with mocked JSON responses
- SSH command construction (`target_ssh_prefix`)
- CLI commands: `target list`, `target list --json`, `node list` (alias), `target inspect local`, `target check local`, and error handling for missing/unreachable targets.

#### 3.2 Live Dogfooding on Workstation
Executed directly from `/home/zar/Documents/phd/robot/caasi-workspace/openmover`:
- `caasi target list`:
  Successfully listed `local` target (`transport: local`, `deployment_root: .`, `tags: [local, workstation]`).
- `caasi target inspect local`:
  - Discovered CPU: 12th Gen Intel(R) Core(TM) i7-12700K (20 cores)
  - Discovered Memory: 46.8 GiB total (36.2 GiB available)
  - Discovered GPU: NVIDIA GeForce RTX 3080 (10240.0 MiB, driver 580.178.04)
  - Discovered Platform: Ubuntu 24.04.5 LTS, kernel 6.8.0-142-generic, arch x86_64
  - Discovered Ecosystem: ROS 2 Jazzy (/opt/ros/jazzy), CUDA 13.0, Docker available
  - Discovered Simulators: Isaac Sim 6.0 (`/home/zar/isaacsim`), Isaac Lab 3.0.0 (`/home/zar/isaaclab`)
  - Discovered Capabilities: `cuda, docker, gpu, isaac_lab, isaac_sim, ros2, ros2:jazzy`
  - Mismatches: 0 (All declared facts compatible)
- `caasi target check local`:
  Returned exit code `0` with online confirmation.
- Negative & Mismatch Testing:
  - Offline target (`192.0.2.1:2222`): Returned exit code `1` immediately with clean error `Target 'robot-offline' is unreachable: Could not connect to 192.0.2.1:2222`.
  - Mismatch target (declared `arch: aarch64`, declared capability `nonexistent_cap`): Returned exit code `1` immediately with clear diagnostics.

#### 3.3 Stage A Refinements & Semantic Corrections
1. **Timing Semantics Disambiguation**:
   - The ~305ms metric originally reported for the local target was the discovery probe duration (in-process inspection of hardware, compilers, drivers, ROS, and simulators), not network latency.
   - Disambiguated in `TargetInspection`:
     - `ping_ms`: Network round-trip latency (0.0 ms for local transport; TCP socket connect time for SSH targets).
     - `probe_duration_ms`: Execution time spent collecting and evaluating target facts.
     - `latency_ms`: Retained as alias to `ping_ms` for backward compatibility.
   - CLI display updated to explicitly distinguish transport and discovery duration:
     - Local: `Status: ONLINE (transport: local | discovery probe: 305.2ms)`
     - Remote: `Status: ONLINE (network ping: 2.5ms | discovery probe: 410.0ms)`

2. **CUDA Version Semantics Disambiguation**:
   - Discovered that `nvidia-smi` reports the driver-supported maximum runtime version (e.g. `13.0`), while `nvcc` reports the installed compiler toolkit version (e.g. `13.4`).
   - Disambiguated in `TargetEnvironment`:
     - `cuda_driver_max`: Maximum CUDA version supported by the NVIDIA display driver (from `nvidia-smi`).
     - `cuda_toolkit`: Installed CUDA compiler/toolkit version (from `nvcc --version`).
     - `cuda_version`: Effective CUDA version (prefers toolkit, fallback to driver max).
   - CLI inspect output updated:
     - `CUDA: 13.4 (toolkit: nvcc) | driver max: 13.0`

---

## Stage B Report: Deployment Foundation & Synchronization Engine

**Status:** Completed & Empirically Verified  
**Date:** October 2026  
**Scope:** Stage B (Deployment Abstraction, Incremental Synchronization, Preflight Verification, Provenance)

---

### 1. What Was Implemented

1. **Deployment Core Abstraction (`caasi.core.deploy`)**:
   - `DeploymentSpec`: Represents what project content to deploy, where to deploy it, and on which target (`project_root`, `project_name`, `project_version`, `git_revision`, `target`, `destination_path`, `include_paths`, `exclude_patterns`).
   - `DeploymentRecord`: Comprehensive provenance record capturing `deployment_id` (`deploy-<project>-<timestamp>-<short_rev>`), git commit SHA, target environment snapshot, file counts, transfer volume, duration, itemized changed files list, verification status, and diagnostics.
2. **Project Content vs Deployment Content Separation**:
   - Project content to deploy: `caasi.yaml`, `caasi.lock`, `src/` (ROS 2 packages), `config/` (parameters), `assets/` (models/URDF), `sim/`, `lab/`, `experiments/`.
   - Excluded development content: `build/`, `install/`, `log/`, `.colcon/`, `.git/`, `tests/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.caasi/runs/`, `.caasi/deployments/`.
   - Declarative override support via `deployment:` block in `caasi.yaml`.
3. **Incremental Synchronization Engine**:
   - Orchestrates `rsync` over local filesystem or SSH with `--delete`, `--stats`, and `-i` (itemized changes).
   - Bounded timeouts (120s) and non-blocking directory creation.
   - Unchanged projects transfer 0 regular file payload on subsequent synchronizations.
4. **Target Preflight & Compatibility Enforcement**:
   - Validates target reachability and capability compatibility against `project.requires` prior to file transfer.
   - Halts deployment cleanly if target is unreachable or incompatible (overridable via `--force`).
5. **Deployment Materialization & Provenance**:
   - Writes `<destination>/.caasi-deployment.json` directly on target.
   - Persists deployment records in host project under `.caasi/deployments/<target>/<deployment_id>.json`.
   - Post-deployment verification confirms integrity of `caasi.yaml`, source packages, and deployment metadata on target.
6. **CLI Interface (`caasi deploy`)**:
   - `caasi deploy <target> [--dry-run] [--force] [--dest <path>] [--json]`
   - `caasi deploy <target> --status [--json]`
   - `caasi deploy --list [--json]`

---

### 2. What Was Actually Deployed

Tested on the canonical OpenMover project at `/home/zar/Documents/phd/robot/caasi-workspace/openmover`:
- **Files**: 833 project files synchronized.
- **Payload Size**: 40.4 MiB total project source and assets.
- **Included Tree**:
  - `caasi.yaml` & `caasi.lock` (manifests)
  - `src/` (all 9 ROS 2 packages: `openmover_base`, `openmover_msgs`, `openmover_navigation`, `openmover_description`, `openmover_bringup`, `relocalization_toolbox`, `relocalization_toolbox_msgs`, `laserscan_multi_merger`, `warehouse_simulation`)
  - `config/` (navigation parameters, RViz profiles, slam configurations)
  - `assets/` (robot meshes, world definitions)
  - `sim/` & `lab/` (simulation bridges, Isaac Lab Gym tasks)
  - `experiments/` (declarative test manifests)
- **Excluded**:
  - Host build directories: `build/` (93.4 MiB), `install/` (14.2 MiB), `log/` (2.4 MiB)
  - Git repository: `.git/` (1.2 GiB object history)
  - Test caches: `.pytest_cache/`, `tests/`
  - Host execution artifacts: `.caasi/runs/`, `.caasi/deployments/`

---

### 3. What the Target Received

The target destination received a clean, self-contained project workspace containing:
1. All project source code, configurations, and assets needed for compilation and execution.
2. The root manifest `caasi.yaml` and lockfile `caasi.lock`.
3. The deployment descriptor `.caasi-deployment.json`:
   ```json
   {
     "deployment_id": "deploy-openmover-20261003-173059-9330b08f",
     "project_name": "openmover",
     "project_version": "0.4.0",
     "git_revision": "9330b08ff24bd0ac35ff10ed8ca96507bd9b56d2-dirty",
     "target_name": "local",
     "target_transport": "local",
     "destination_path": "/tmp/openmover-deploy-test",
     "deployed_at": "20261003-173059",
     "status": "verified",
     "file_count": 833,
     "total_bytes": 42362880,
     "transferred_bytes": 42362880,
     "duration_seconds": 0.63
   }
   ```
4. Zero host architecture pollution: host `build/` and `install/` binaries were never copied to the target.

---

### 4. How Deployment Identity Was Recorded

Deployment identity is recorded with two-sided provenance:
1. **On Target**: At `<destination>/.caasi-deployment.json`. This allows any tool or process running on the target to inspect what revision, project version, and deployment ID is currently active.
2. **On Host**: At `<project_root>/.caasi/deployments/<target>/<deployment_id>.json`. This provides an auditable history of all deployments made to every target from the development workstation.
3. Both records store identical metadata: unique deployment ID, git commit SHA, ISO timestamp, target environment snapshot, file counts, and verification status.

---

### 5. What Failed or Was Awkward

1. **Initial Status Timing Bug**:
   - `DeploymentRecord` was initially serialized to JSON before `verify_deployment()` completed, resulting in `.caasi-deployment.json` recording `"active"` instead of `"verified"`. Corrected so the verified state is recorded and persisted.
2. **Local Sync Destination Ambiguity**:
   - When deploying to target `local` without an explicit `--dest`, defaulting to `.` would attempt to sync the project onto itself. Resolved by resolving the default local destination to `~/.caasi/deployments/local/<project_name>`, establishing a clean sandbox.
3. **Deployment Metadata Recursion**:
   - The first incremental sync test showed that local deployment records saved in `.caasi/deployments/` were being detected as project changes. Resolved by adding `.caasi/deployments` to default synchronization exclude patterns.

---

### 6. What OpenMover Exposed as a General Caasi Requirement

1. **Build Artifacts Must Never Cross Architectures**:
   - OpenMover contains C++ CMake nodes (`laserscan_multi_merger`, `relocalization_toolbox`) and Python packages. If `build/` or `install/` were synced to an aarch64 target (such as Jetson Orin), host x86_64 `.so` libraries would break target builds. Rigid exclusion of host build/install trees is a non-negotiable general rule.
2. **Incremental Speed is Essential for Robotics**:
   - With 833 files (40.4 MiB), initial sync took 0.63s. On the second run with zero changes, incremental sync took 0.60s and transferred **0 regular file bytes** (only updating the small metadata manifest). For real wireless robot links (Wi-Fi 6 or 5G), transferring only changed files is mandatory.
3. **Target Verification Must Be Structural, Not Just Network Status**:
   - Verifying that rsync succeeded is necessary but insufficient. The deployment engine must structurally verify that `caasi.yaml` and source trees exist and that deployment metadata is readable on the target.

---

### 7. What Should Become Stage C

Stage B establishes safe, verified materialization of project content onto execution targets.
**Stage C should focus on: Target-Native Build & Transparent Remote Execution**:
1. **Target-Native Build (`caasi build --target <name>`)**:
   - Orchestrate compilation on the target (via SSH invocation of `colcon build`) using target CPU and memory capacity.
2. **Remote Run Execution (`caasi run start --target <name> <manifest>`)**:
   - Launch and supervise processes on the target, streaming stdout/stderr back to the workstation.
3. **Remote Run Tracking & Lifecycle (`caasi run list / stop / inspect --target <name>`)**:
   - Manage remote processes using the existing caasi process group lifecycle without orphaned nodes.
