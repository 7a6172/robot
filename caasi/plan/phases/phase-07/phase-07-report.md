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
2. **Incremental Synchronization Minimizes Transferred Content**:
   - In the local dogfood test (833 files, 40.4 MiB), the initial local sync completed in 0.63s, while a subsequent sync of the unchanged project completed in 0.60s and transferred **0 regular file payload bytes** (updating only the deployment descriptor). Performance over wireless robot links was not measured.
3. **Target Verification Must Be Structural, Not Just Network Status**:
   - Verifying that rsync succeeded is necessary but insufficient. The deployment engine must structurally verify that `caasi.yaml` and source trees exist and that deployment metadata is readable on the target.

---

### 7. What Should Become Stage C

Stage B establishes safe, verified materialization of project content onto execution targets.
**Stage C is partitioned into two focused stages**:
1. **Stage C1 (Target-Native Build)**: Orchestrate compilation natively on the execution target via `caasi build --target <name>`, sizing worker parallelism to target CPU/RAM capacity, ensuring host architectures never cross, and tracking build provenance.
2. **Stage C2 (Target-Native Remote Run Execution)**: Launch and supervise processes on the target via `caasi run start --target <name> <manifest>`, streaming stdout/stderr back to the workstation with complete process group lifecycle control.

---

## Stage C1 Report: Target-Native Build

### 1. Stage C1 Objectives & Core Accomplishments

Stage C1 validates the architectural principle: **the workstation acts as the unified control and orchestration plane, while execution targets own their own architecture-specific build environment and native compilation resources.**

Key accomplishments:
1. **Target-Aware Build Interface**: Extended `caasi build` with `--target <name>` / `-t <name>`. Local workstation build behavior is preserved identically with zero regressions.
2. **Target Resource Sizing (`derive_target_workers`)**: RAM-safe compilation parallelism is derived directly from target hardware capacity (`memory_total_kib` and `cpu_count` discovered in Stage A) using conservative default heuristic policies ($\text{RAM\_PER\_WORKER} = 6.0\text{ GiB}$, $\text{SYSTEM\_RESERVED} = 2.0\text{ GiB}$), providing a conservative worker limit derived from the target's discovered CPU and RAM capacity.
3. **Verified Deployment Preflight**: Builds on remote/deployed targets enforce prerequisite deployment verification via `deploy.get_deployment_status`. If no active deployment exists, the build fails fast with actionable guidance.
4. **Target-Native Underlay & Colcon Wrapping**: Remote execution sources the target's native ROS 2 underlay (e.g. `/opt/ros/{distro}/setup.bash`), executes `colcon build` in the target's deployed root directory, and streams live output back to the workstation terminal.
5. **Strict Artifact Retention on Target**: Architecture-specific binaries (`build/`, `install/`, `log/`) remain entirely on the target. They are never copied to the workstation, preventing architecture pollution between x86_64 and aarch64.
6. **Two-Sided Build Provenance**: Build outcomes, timings, return codes, worker allocations, and error logs are saved both on the target (`<destination>/.caasi-build.json`) and in the workstation project repository (`.caasi/builds/<target>/<build_id>.json`).
7. **Test Coverage**: Added 10 dedicated unit tests in `caasi/tests/test_target_build.py`. All 912 tests pass across the entire caasi suite.

---

### 2. Implementation Details

#### Target Worker Parallelism Derivation
In `caasi/src/caasi/core/build.py`:
```python
def derive_target_workers(
    resources: TargetResources | None = None,
    requested_jobs: int | None = None,
) -> int:
    if requested_jobs is not None and requested_jobs > 0:
        return requested_jobs

    if resources and resources.memory_total_kib and resources.cpu_count:
        ram_gb = resources.memory_total_kib / (1024 * 1024)
        usable_ram = max(0.0, ram_gb - SYSTEM_RESERVED_RAM_GB)
        ram_workers = max(1, int(usable_ram / RAM_PER_WORKER_GB))
        return max(1, min(resources.cpu_count, ram_workers))

    return default_parallel_workers()
```

#### Remote Build Assembly
When executing over SSH:
```python
steps = [f"cd {dest}"]
if clean:
    steps.append("rm -rf build install log")
steps.append(f"test -f {ros_setup} && . {ros_setup}")
steps.append(shlex.join(colcon_cmd))
remote_sh = " && ".join(steps)
remote_exec = ssh_prefix + [f"bash -c {shlex.quote(remote_sh)}"]
```
Output lines are captured via `subprocess.Popen` and streamed in real-time to the workstation console or JSON accumulator.

#### Build Provenance Data Model
`TargetBuildRecord` records:
- `build_id`: Unique identifier (e.g. `build-test-sandbox-1791049711-805239`)
- `project_name` & `git_revision`: Identifies exact source code revision built
- `target_name` & `target_transport`: Execution destination
- `destination_path`: Target workspace path where compilation occurred
- `built_at`: UTC ISO timestamp
- `status`: `"success"` or `"failed"`
- `returncode`: Exit status from colcon
- `duration_seconds`: Build execution wall-clock time
- `workers`: Parallel compilation processes allocated
- `command`: Arguments passed to colcon
- `deployment_id`: Linked deployment identifier providing complete end-to-end traceability
- `output`: Stderr/failure excerpt if build was unsuccessful

---

### 3. Empirical Dogfooding Results (Canonical OpenMover)

Dogfooding was conducted from `/home/zar/Documents/phd/robot/caasi-workspace/openmover`:

1. **Local Build Preservation**:
   ```bash
   caasi build --target local --packages-select openmover
   ```
   - Parallel workers: 7
   - Duration: 0.70s
   - Exit code: 0
   - Provenance record saved: `.caasi/builds/local/build-local-1791049640-42db94.json`

2. **Unregistered Target Rejection**:
   ```bash
   caasi build --target robot-orin
   ```
   - Result: Failed fast with `Error: No target matching 'robot-orin' (configured: local).`
   - Exit code: 1

3. **Undeployed Target Verification**:
   - Configured target `test-sandbox` (`transport: local`, `deployment_root: /tmp/caasi-test-deploy`)
   ```bash
   caasi build --target test-sandbox
   ```
   - Result: Failed fast with `Error: No active deployment found on target 'test-sandbox' at '/tmp/caasi-test-deploy/openmover'. Run 'caasi deploy test-sandbox' first.`
   - Exit code: 1

4. **Target Materialization & Intentional Failure Handling Validation**:
   - Deployed project: `caasi deploy test-sandbox` (838 files, 40.4 MiB synced in 0.64s).
   - Intentionally tested partial build without prerequisites to validate failure handling and non-zero exit code capture:
     ```bash
     caasi build --target test-sandbox --packages-select openmover
     ```
     - Colcon exited with code 1 as expected because CMake dependencies (`auto_mapping_toolbox_msgs`, `openmover_msgs`, `bluesea2`, etc.) had not yet been compiled on this fresh target.
     - Failure was captured cleanly, exit code 1 was preserved, and detailed failure stderr was written to provenance record `.caasi/builds/test-sandbox/build-test-sandbox-1791049703-db5de2.json`.

5. **Full Native Target Build**:
   ```bash
   caasi build --target test-sandbox --packages-up-to openmover
   ```
   - Packages built: 6 packages (`openmover_msgs`, `auto_mapping_toolbox_msgs`, `relocalization_toolbox_msgs`, `bluesea2`, `ira_laser_tools`, `openmover`)
   - Parallel workers: 7
   - Compilation duration: 61.4s
   - Exit code: 0
   - Output message: `Target-native build artifacts remain on test-sandbox: /tmp/caasi-test-deploy/openmover`
   - Target inspection: Verified `build/`, `install/`, `log/`, and `.caasi-build.json` were created exclusively on the target workspace, with zero host workstation leakage.

---

### 4. What Failed or Was Awkward

1. **Subprocess Quoting Redundancy**:
   - Initially, remote shell paths were individually single-quoted (`cd '{dest}'`) before the full script was escaped with `shlex.quote`. This created nested `\'"\'"\'` escaping sequences. Resolved by cleaning up inner path interpolation and allowing `shlex.quote` to handle the outer command boundary cleanly.
2. **Missing Builds Directory in Exclude Patterns**:
   - During local deployment, `.caasi/builds/` was initially synchronized to the target because it was not listed in `DEFAULT_EXCLUDE_PATTERNS`. Resolved by adding `.caasi/builds` and `.caasi-build.json` to exclude patterns, ensuring host and target build histories remain decoupled.
3. **Failure Provenance Truncation**:
   - High-volume build logs during compilation failures could produce excessively large JSON records if unconstrained. Added a 2,000-character truncation budget for output captured in `TargetBuildRecord`.

---

### 5. What OpenMover Exposed as a General Caasi Requirement

1. **Colcon Package Prerequisite Chains Must Be Respected on Fresh Targets**:
   - Unlike the workstation where artifacts may have been previously compiled, fresh execution targets start from zero build state. Commands specifying `--packages-select` will fail if workspace dependencies are not already built on the target. Developers should use `--packages-up-to` or full workspace builds when deploying to fresh targets.
2. **Deployment ID Binding is Mandatory for Build Provenance**:
   - Linking each target build record to its corresponding `deployment_id` provides complete traceability: developers can inspect a built robot node and immediately identify which exact rsync transfer and Git commit materialized the source tree.

---

### 6. Next Step

Stage C1 is complete and verified.
**Proceed to Stage C2: Target-Native Remote Run Execution & Lifecycle Management**:
1. Implement `caasi run start --target <name> <manifest>` to launch supervised processes on targets.
2. Stream remote stdout/stderr to the workstation control plane.
3. Manage target process groups via `caasi run stop / inspect / list --target <name>`.


---

# Stage C2 Report: Target-Native Remote Run Execution & Lifecycle Management

**Status**: Completed & Verified  
**Date**: October 4, 2026  
**Scope**: Target-Native Remote Run Execution & Lifecycle Management (`caasi run start --target`, `caasi run status`, `caasi run logs`, `caasi run inspect`, `caasi run stop`, `caasi run list`)  

---

### 1. Executive Summary

Phase 7 Stage C2 establishes target-native remote execution and process lifecycle management across the Caasi control plane. Prior to Stage C2, running simulation or robotic tasks required direct local workstation execution or manual SSH sessions into target machines. With Stage C2:

1. **Target-Aware Run Execution**: Developers launch tracked runs on configured targets via `caasi run start --target <name> <manifest>` directly from the workstation control plane without manual SSH coordination.
2. **Deterministic Preflight Verification**: Enforces target reachability, active deployment verification (`get_deployment_status`), and target-native build verification (`get_last_build_status`) before executing remote processes.
3. **Detached Process Supervision**: Wraps remote target execution in detached sessions (`setsid`) designed to decouple from the initiating terminal session, recording both process PID and session PGID.
4. **Complete Process Group Termination**: Eliminates dangling child processes by addressing process group trees (`kill -TERM -<pgid>`, falling back to `kill -KILL -<pgid>`), ensuring multi-node ROS 2 and simulator child processes in the tested tree are reaped.
5. **Remote Log Streaming & Inspection**: Enables retrieving trailing log lines (`caasi run logs`), live remote streaming (`caasi run logs -f`), and target run directory inventory auditing (`caasi run inspect`).
6. **Two-Sided Run Provenance**: Connects the complete provenance chain on both host and target (`project -> deployment_id -> build_id -> target -> git_revision -> run_id`).

---

### 2. Core Model & Target-Aware Run Architecture

Caasi's run architecture treats target runs as first-class citizens alongside local runs, maintaining a unified data model:

```text
Workstation Control Plane (Host)
  caasi run start --target <name> <manifest>
          ↓
  [Preflight Checks]
    ├─ Target Reachability Probe
    ├─ Deployment Verification (destination, status: active)
    └─ Build Verification (.caasi-build.json on target, status: success)
          ↓
  [Path Translation & Script Synthesis]
    ├─ Translate host paths to target-relative paths rooted at destination
    ├─ Generate target execution wrapper: <destination>/.caasi/runs/<run_id>/run.sh
    │   ├─ Sourcing: /opt/ros/<distro>/setup.bash
    │   ├─ Sourcing: <destination>/install/setup.bash
    │   ├─ Environment: CAASI_PROJECT_ROOT, CAASI_EXPERIMENT, manifest env vars
    │   └─ Exit code capture: echo "$ec" > "$RUN_DIR/exit_code"
    └─ Launch detached session via nohup setsid
          ↓
  [Two-Sided Provenance Materialization]
    ├─ Target: <destination>/.caasi/runs/<run_id>/manifest.yaml
    └─ Host: ~/.caasi/runs/<run_id>/manifest.yaml + Level 6 Provenance Bundle
```

#### RunRecord Model Extensions (`caasi.core.runs`)

`RunRecord` was augmented with target-native execution metadata:
* `target: str` — Execution target name (`"local"` or configured target name).
* `target_transport: str` — Transport protocol (`"local"` or `"ssh"`).
* `pgid: int | None` — Process Group ID assigned on target.
* `destination: str | None` — Target-side deployment path.
* `deployment_id: str | None` — Lineage ID of deployment that materialized the code.
* `build_id: str | None` — Lineage ID of target-native build.
* `git_revision: str | None` — Git commit SHA and dirty status.
* `project: str | None` — Project name.
* `remote_run_dir: str | None` — Directory on target holding run assets and logs.

---

### 3. CLI Interface & Flags

Caasi's run CLI commands were generalized to support target-native execution while preserving local behavior identically:

* `caasi run start --target <name> [-t <name>] <config>`:
  Launches the experiment on the specified target. Validates backend, preflight checks, resolves target paths, and initiates execution.
* `caasi run list [--target <name>]`:
  Displays running and historical runs, adding a dedicated `Target` column showing target name and transport.
* `caasi run status <query>`:
  Shows real-time status of local or remote runs, querying target-side exit code or process group liveness over SSH or local sandbox.
* `caasi run logs <query> [-n <lines>] [-f] [-s stdout|stderr]`:
  Reads trailing logs or streams live stdout/stderr from the target over SSH tail or local sandbox file handles.
* `caasi run inspect <query>`:
  Audits target run artifacts (`run.sh`, `pid`, `pgid`, `stdout.log`, `stderr.log`, `exit_code`, `manifest.yaml`) and displays file sizes.
* `caasi run stop <query>`:
  Signals the target process group (`SIGTERM` followed by `SIGKILL` on timeout), ensuring complete termination of parent and child processes.

---

### 4. Target Preflight & Verification Engine

Before issuing execution commands on the target, `start_target_run` performs deterministic preflight verification:

1. **Reachability Check**:
   Invokes `targets_core.discover_target(target)`. If the target is offline or SSH handshake fails, execution halts immediately with a clear diagnostics error.
2. **Project Resolution**:
   Resolves root Caasi project from caller directory or path ancestry, ensuring project manifest (`caasi.yaml`) and lockfile exist.
3. **Deployment Verification**:
   Resolves deployment destination path via `deploy_core.resolve_deployment_destination(target, proj_name)` and queries `get_deployment_status(target, dest, config)`. Halts with actionable advice (`Run 'caasi deploy <target>' first.`) if no active deployment is found.
4. **Target-Native Build Verification**:
   For projects containing ROS 2 components or `src/` packages, queries `build_core.get_last_build_status(target, dest, config)`. Verifies that `.caasi-build.json` exists on the target itself at `dest`, and verifies `status == "success"`. Halts if unbuilt or if the previous compilation failed.

---

### 5. Remote Process Lifecycle & Detached Supervision

Processes executed on remote targets must not terminate if the developer's workstation drops SSH connection:

1. **Detached Invocation**:
   Remote runs are launched using:
   ```bash
   nohup setsid '<run_dir>/run.sh' "$@" > '<run_dir>/stdout.log' 2> '<run_dir>/stderr.log' </dev/null &
   PID=$!
   echo $PID > '<run_dir>/pid'
   ps -o pgid= -p $PID | tr -d ' ' > '<run_dir>/pgid'
   ```
2. **Session Decoupling**:
   `setsid` allocates a new session and process group where `PGID == PID`, detaching stdin from any controlling terminal. This session decoupling isolates the process group from controlling terminal hangup signals.
3. **Exit Code Persistence**:
   The wrapper traps or captures command exit status:
   ```bash
   "$@"
   ec=$?
   echo "$ec" > "$RUN_DIR/exit_code"
   exit "$ec"
   ```
4. **Status Probe Engine**:
   Remote status checks query the target with a single atomic probe:
   - If `<run_dir>/exit_code` exists: exit code 0 maps to `succeeded`, non-zero to `failed`.
   - If PID is alive (`kill -0 <pid>`): maps to `running`.
   - If dead without exit code: maps to `stopped` if user stopped it, or `lost`.
   - If SSH connection drops: maps to `unreachable` rather than falsely reporting dead.

---

### 6. Process Group Signaling & Orphan Prevention

Robotics applications routinely spawn complex multi-process trees (ROS 2 daemon, launch wrappers, Python nodes, sensor drivers, simulator processes). Terminating only the root PID leaves orphaned child processes running.

Stage C2 implements process-group-level lifecycle control:
1. **Target-Side Process Group ID Tracking**:
   The wrapper records `pgid` at launch time.
2. **Negative PGID Signaling**:
   `stop_run` dispatches `SIGTERM` to the entire process group:
   - SSH targets: `kill -TERM -<pgid> 2>/dev/null || kill -TERM <pid>`
   - Local sandbox targets: `os.killpg(pgid, signal.SIGTERM)`
3. **Bounded Wait & SIGKILL Escalation**:
   Monitors process group liveness for a configurable timeout (default 5.0s). If processes remain active, delivers `SIGKILL` to `-<pgid>`.
4. **Reaping & Zombie Prevention**:
   In local test sandboxes, invokes `os.waitpid(pid, os.WNOHANG)` across polling loops, preventing defunct zombie processes from skewing liveness checks.

---

### 7. Workstation Log Retrieval & Streaming

1. **Log Ingestion**:
   `runs.read_run_log(record, config, stream, lines)` retrieves trailing lines over SSH (`tail -n <lines>`) or local file handles.
2. **Filtering & Severity Attribution**:
   Reuses Caasi's standard log parser convention (`[HH:MM:SS] [component] message`) to support `--component`, `--since`, and `--errors` filtering on target runs.
3. **Live Streaming (`-f / --follow`)**:
   - For SSH targets: executes a non-blocking `tail -n 0 -f` over SSH subprocess pipe, streaming incoming lines directly to the workstation terminal until interrupted via Ctrl+C.
   - For local sandboxes: uses direct file handle polling, terminating automatically when the run reaches a terminal state.

---

### 8. Target Run Inspection & File Accounting

`caasi run inspect <run_id>` performs remote run inventory auditing:
* Local sandbox runs: recursively traverses `<remote_run_dir>` collecting relative paths and byte sizes.
* Remote SSH runs: executes `find '<run_dir>' -maxdepth 2 -type f -exec stat -c '%n %s' {} +` over SSH in a single call.
* Audited artifacts include: `run.sh` (synthesized wrapper), `pid`, `pgid`, `stdout.log`, `stderr.log`, `exit_code`, and `manifest.yaml`.

---

### 9. Two-Sided Run Provenance & Metadata Schema

Every target run records full lineage linking workstation and target state:

```yaml
id: 20261004-021616-target-smoke
name: target-smoke
backend: python
kind: experiment
command:
  - python3
  - /tmp/caasi-test-deploy/openmover/experiments/target_smoke_test.py
cwd: /tmp/caasi-test-deploy/openmover
created: '2026-10-04T02:16:16+08:00'
pid: 645497
pgid: 645497
target: test-sandbox
target_transport: local
destination: /tmp/caasi-test-deploy/openmover
deployment_id: deploy-openmover-20261003-181609-1818b63f
build_id: build-test-sandbox-1791051254-396f85
git_revision: 1818b63f01
project: openmover
remote_run_dir: /tmp/caasi-test-deploy/openmover/.caasi/runs/20261004-021616-target-smoke
paused: false
stopped: true
extra:
  experiment: experiments/target_smoke.yaml
  headless: true
```

* **Workstation Host**: Written to `~/.caasi/runs/<run_id>/manifest.yaml` accompanied by the standard Level 6 provenance bundle (`configuration.yaml`, `dependencies.yaml`, `environment.yaml`, `hardware.yaml`, `git.json`, `processes.json`).
* **Execution Target**: Written to `<remote_run_dir>/manifest.yaml` alongside runtime execution artifacts.

---

### 10. Empirical Dogfooding Results (Canonical OpenMover)

Dogfooding was executed from `/home/zar/Documents/phd/robot/caasi-workspace/openmover` against a deployed target sandbox (`test-sandbox`, `deployment_root: /tmp/caasi-test-deploy`):

1. **Preflight Rejection of Undeployed Target**:
   ```bash
   caasi run start --target test-sandbox experiments/smoke_test.yaml
   ```
   - Result: Failed fast with:
     `Error: No active deployment found on target 'test-sandbox' at '/tmp/caasi-test-deploy/openmover'. Run 'caasi deploy test-sandbox' first.`
   - Exit code: 1.

2. **Preflight Rejection of Unbuilt Target**:
   - Deployed fresh workspace: `caasi deploy test-sandbox` (833 files, 40.4 MiB synced in 0.64s).
   - Attempted run before compiling:
     ```bash
     caasi run start --target test-sandbox experiments/sim_warehouse_bridge.yaml
     ```
   - Result: Failed fast with:
     `Error: No completed build found on target 'test-sandbox' at '/tmp/caasi-test-deploy/openmover'. Run 'caasi build --target test-sandbox' first.`
   - Exit code: 1.

3. **Target Compilation**:
   ```bash
   caasi build --target test-sandbox --packages-up-to openmover
   ```
   - Result: Successfully compiled 6 packages (`openmover_msgs`, `auto_mapping_toolbox_msgs`, `relocalization_toolbox_msgs`, `bluesea2`, `ira_laser_tools`, `openmover`) in 60.61s. Native build metadata recorded in `/tmp/caasi-test-deploy/openmover/.caasi-build.json`.

4. **Remote Run Launch & Sourcing Verification**:
   - Synchronized safe smoke experiment (`experiments/target_smoke.yaml`, `experiments/target_smoke_test.py`).
   ```bash
   caasi run start --target test-sandbox experiments/target_smoke.yaml
   ```
   - Result:
     `Run 20261004-021616-target-smoke started in background on target 'test-sandbox'.`
   - Verified process group: PID 645497, PGID 645497.

5. **Log Retrieval & Sourcing Verification**:
   ```bash
   caasi run logs 20261004-021616-target-smoke
   ```
   - Log output captured:
     ```text
     [SMOKE] Starting target smoke test...
     [SMOKE] PID: 645578, PGID: 645497
     [SMOKE] CAASI_PROJECT_ROOT: /tmp/caasi-test-deploy/openmover
     [SMOKE] ROS_DISTRO: jazzy
     [SMOKE] rclpy import successful
     [SMOKE] openmover_msgs import successful
     [SMOKE] CHILD_PID: 645588
     [SMOKE] Heartbeat step 0/120 (PID 645578, child 645588)
     [SMOKE] Heartbeat step 5/120 (PID 645578, child 645588)
     ```
   - Verified that `/opt/ros/jazzy` and `/tmp/caasi-test-deploy/openmover/install` were sourced automatically, enabling target-native `openmover_msgs` import.

6. **Target Run Inspection**:
   ```bash
   caasi run inspect 20261004-021616-target-smoke
   ```
   - Output displayed target remote directory, target name (`test-sandbox (local)`), status (`running`), and complete inventory of run files:
     * `manifest.yaml` (734 B)
     * `pgid` (6 B)
     * `pid` (6 B)
     * `run.sh` (519 B)
     * `stderr.log` (0 B)
     * `stdout.log` (484 B)

7. **Process Tree & Zero-Orphan Stop Verification**:
   - Inspected OS process tree prior to stop:
     ```text
         PID    PGID CMD
      645497  645497 bash /tmp/caasi-test-deploy/openmover/.caasi/runs/20261004-021616-target-smoke/run.sh
      645578  645497  \_ python3 /tmp/caasi-test-deploy/openmover/experiments/target_smoke_test.py
      645588  645497      \_ sleep 120
     ```
   - Issued stop command:
     ```bash
     caasi run stop 20261004-021616-target-smoke
     ```
     `Run 20261004-021616-target-smoke stopped.`
   - Checked OS process table for all 3 PIDs (`ps -fp 645497,645578,645588`):
     Returned empty — the tested process group and its spawned child were terminated, with no remaining processes from the tested run.
   - Verified `caasi run status 20261004-021616-target-smoke` transitioned to `stopped`.

---

### 11. What Failed, What Was Awkward, and How It Was Resolved

1. **Host Build Record Fallback Masking Unbuilt Target State**:
   - *Issue*: `get_last_build_status` fell back to `project_root` host build records when querying target build status. If a target had been built previously in an older directory, redeploying to a fresh destination bypassed the build preflight check even though `install/` was absent.
   - *Resolution*: Updated `start_target_run` to query `get_last_build_status(target, dest, config)` strictly against the target destination without host project fallback. The target destination must contain its own `.caasi-build.json`.
2. **Zombie Process Reaping in Local Test Sandboxes**:
   - *Issue*: In local sandboxes running under the same parent process during tests, terminated processes remained as zombie entries (`<defunct>`), causing `pid_alive(pid)` (`os.kill(pid, 0)`) to return `True` and `sandbox_stop_run` to time out.
   - *Resolution*: Integrated `_reap(pid)` (`os.waitpid(pid, os.WNOHANG)`) into `sandbox_stop_run` and `sandbox_effective_status` loops, properly reaping child processes without affecting detached non-child processes.
3. **Experiment Script Path Translation Anchoring**:
   - *Issue*: Experiment configs specifying relative script paths (e.g. `script: ../scripts/test.py` relative to `experiments/`) resolved relative to the experiment directory on the host. Passing unnormalized paths caused `dest / rel_script` misalignments.
   - *Resolution*: Normalized `exp.script_path` and `exp.work_dir` against `proj_root` before prepending target destination root, ensuring portable execution regardless of directory nesting.

---

### 12. What OpenMover Exposed as a General Caasi Requirement

1. **Overlay Sourcing in Target Launch Wrappers is Mandatory**:
   - Robotics targets do not inherit the developer's interactive `.bashrc`. Sourcing `/opt/ros/<distro>/setup.bash` alone is insufficient when projects rely on custom message definitions or workspace packages. Automatically injecting `[ -f "<dest>/install/setup.bash" ] && . "<dest>/install/setup.bash"` into target execution wrappers guarantees custom interfaces (`openmover_msgs`) are available to all launched nodes without manual environment configuration.
2. **Session PGID Decoupling is Crucial for Multi-Node Tasks**:
   - In distributed robotics, stopping an experiment must never leave background nodes (e.g. LiDAR drivers, camera pipelines, navigation servers) spinning and locking hardware ports or GPU memory. Tracking PGID and delivering signals to `-pgid` is a fundamental requirement for reliable robotics supervision.

---

### 13. Test Suite Status

* 8 dedicated unit tests added in `caasi/tests/test_target_run.py`:
  - `test_target_run_unreachable_target`
  - `test_target_run_missing_deployment`
  - `test_target_run_missing_or_failed_build`
  - `test_target_run_ssh_launch_and_provenance`
  - `test_remote_effective_status_and_ssh_probe`
  - `test_remote_stop_run_process_group`
  - `test_local_sandbox_lifecycle_and_process_group_cleanup`
  - `test_cli_run_target_commands`
* Full target suite passing: **50 target tests** (`test_target_run.py`, `test_target_build.py`, `test_targets.py`, `test_deploy.py`).
* Full regression test suite passing: **912 tests** across the entire Caasi repository.

