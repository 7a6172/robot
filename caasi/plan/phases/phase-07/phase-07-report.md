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
