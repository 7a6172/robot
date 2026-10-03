# Caasi v0.3.0 Capability Audit

## 1. Executive Summary

Caasi v0.3.0 is a lightweight, CLI-first orchestration layer for NVIDIA Isaac Sim, Isaac Lab, ROS 2, and the broader robotics ecosystem. It is **not a greenfield project**; it possesses a mature internal architecture designed across seven layers (§1–7 of the Caasi specification) and implemented in Python 3.10+ using `typer`, `rich`, and `pyyaml`.

This audit evaluates the actual, implemented capabilities in `src/caasi` and documents their exact mechanisms to answer the question: **"Can the existing Caasi already do this?"**

---

## 2. Detailed Capability Analysis by Domain

### 2.1 Project Management (`caasi project`, `init`, `caasi.yaml`)
- **Implemented Mechanism**:
  - `core/manifest.py`: Flat `caasi.yaml` manifest (`schema: 1`, `name`, `version`, `components`, `requires`, `tested`).
  - `core/project.py`: Standard directories initialized via `project init`: `robots/`, `scenes/`, `tasks/`, `experiments/`, `datasets/`, `runs/`, `artifacts/`, `logs/`, `.caasi/`.
  - Component model (`core/components.py`): Subtrees registered via `caasi project add <component>`:
    - `isaac_sim`: `isaac/sim/scenes`, `isaac/sim/configs`, `isaac/sim/extensions`
    - `isaac_lab`: `isaac/lab/tasks`, `isaac/lab/environments`, `isaac/lab/configs`
    - `ros2`: `ros/launch`, `ros/config`, `ros/params`
    - `nav2`: `nav/maps`, `nav/params`, `nav/launch`
    - `moveit`: `moveit/config`, `moveit/launch`
    - `robot`: `robot/urdf`, `robot/meshes`, `robot/usd`
    - `navigation`: `navigation/configs`, `navigation/launch`
    - `manipulation`: `manipulation/configs`, `manipulation/launch`
  - Definition files: Declarative YAML files in `robots/<name>.yaml`, `scenes/<name>.yaml`, `tasks/<name>.yaml` inspectable without starting simulation.
- **Can Caasi already do this?**: **YES**. It provides a structured project model and component registry.

### 2.2 Environment Discovery & Fingerprinting (`caasi env`, `gpu`, `system`)
- **Implemented Mechanism**:
  - `core/fingerprint.py`: Captures complete environment state into `.caasi/fingerprint.json` (OS, kernel, CPU, RAM, NVIDIA driver, GPU, CUDA, Vulkan, Python, ROS 2, Isaac Sim/Lab).
  - `core/nvidia.py`: Direct `nvidia-smi` parser capturing device count, name, driver version, CUDA capability, VRAM total/used/free, temperature, power, utilization.
  - `cli/gpu.py`, `cli/system.py`: Live and snapshot reporting of compute, memory, and running processes.
- **Can Caasi already do this?**: **YES**. Machine discovery, GPU topology, and drift tracking are fully implemented.

### 2.3 Compatibility & Preflight Engine (`caasi check`, `doctor`)
- **Implemented Mechanism**:
  - `core/check.py`: Implements the §16 Check Contract. Scopes include `sim`, `lab`, `ros`, `nav`, `moveit`, `control`, `container`, `hardware`, `project`, `dependencies`.
  - 4-level compatibility ladder: `compatible`, `untested`, `missing`, `incompatible`.
  - Folded results: `ready` (exit 0), `warning` (exit 0), `incompatible` (exit 3).
  - `checks/`: Machine-wide probe registry for Isaac Sim, Isaac Lab, ROS 2 distros, CUDA, Vulkan, display servers, python environments, storage.
- **Can Caasi already do this?**: **YES**. Preflight checks evaluate hardware, driver, VRAM, and package dependencies before runs.

### 2.4 Run Management (`caasi run`, `start`, `logs`, `replay`, `view`)
- **Implemented Mechanism**:
  - `core/runs.py`: Runs are first-class, detached background processes in `~/.caasi/runs/<run-id>/` (or project-configured `paths.runs`).
  - Contains: `manifest.yaml` (metadata, PID, timestamps), `run.sh` (bash exit-code wrapper), `stdout.log`, `stderr.log`, `exit_code`.
  - Status derivation: Checked via PID liveness (`os.kill(pid, 0)`) and exit code file. States: `running`, `paused`, `stopped`, `succeeded`, `failed`, `lost`.
  - `caasi run logs -f <id>`: Live tail of stdout/stderr.
  - `caasi run stop <id>`: Clean termination via SIGTERM then SIGKILL.
- **Can Caasi already do this?**: **YES**. Robust process detachment, log capture, and status tracking are fully implemented.

### 2.5 Provenance & Reproducibility (`core/provenance.py`, `caasi audit`)
- **Implemented Mechanism**:
  - Layer 6 provenance bundle written automatically to every run directory upon start:
    - `manifest.yaml`: Run and project metadata, Caasi version.
    - `environment.yaml`: Snapshot of OS, Python, ROS, Isaac Sim/Lab environment.
    - `hardware.yaml`: Snapshot of CPU, memory, GPU at launch.
    - `dependencies.yaml`: Required, resolved, and verified package versions (`caasi.lock` format).
    - `configuration.yaml`: Effective Caasi config + experiment YAML (secrets redacted).
    - `git.json`: Commit hash, branch, dirty status, remotes.
    - `processes.json`: Top processes by RSS memory at launch.
  - `caasi audit`: Audits 6 scopes (`project`, `dependencies`, `environment`, `files`, `runs`, `reproducibility`).
- **Can Caasi already do this?**: **YES**. State provenance and auditability are core strengths.

### 2.6 ROS 2 Integration (`caasi ros`, `nav`, `control`, `moveit`)
- **Implemented Mechanism**:
  - `core/ros.py`: Discovers ROS distro via `$ROS_DISTRO` or `/opt/ros/*`, wraps commands with `rosenv.py` so unsourced shells work.
  - CLI delegation: Delegates to standard `ros2` binary (`ros2 topic`, `node`, `service`, `param`, `launch`).
  - `caasi ros launch <file>`: Automatically wraps ROS launch processes as tracked Caasi runs.
  - `caasi nav status/launch/inspect`: Delegates to `nav2_bringup`.
- **Can Caasi already do this?**: **YES**. Orchestrates ROS 2 without importing `rclpy` in the CLI host.

### 2.7 Simulation & Isaac Lab Integration (`caasi sim`, `lab`, `train`)
- **Implemented Mechanism**:
  - `core/experiment.py`: Declarative experiment YAML:
    ```yaml
    name: exp1
    backend: sim  # sim | lab | python
    script: script.py
    args: ["--arg", "val"]
    env: { KEY: "VAL" }
    headless: true
    ```
  - Backend resolution: `sim` resolves to `<isaacsim>/python.sh`; `lab` resolves to `<isaaclab>/isaaclab.sh`.
  - `caasi lab play --checkpoint <path>`: Automates evaluation of trained policies.
- **Can Caasi already do this?**: **YES**. Handles headless execution, script dispatch, and Isaac toolchain resolution.

### 2.8 Remote Execution (`caasi remote`)
- **Implemented Mechanism**:
  - `core/remotes.py`: Configures remote machines in `caasi.yaml` (`host`, `user`, `port`, `path`, `python`, `ssh_key`).
  - `caasi remote run <machine> <command>`: Dispatches commands over SSH as tracked runs.
- **Can Caasi already do this?**: **YES**, for SSH execution. (Advanced scheduling/queuing or file sync is minimal).

### 2.9 Container Support (`caasi container`)
- **Implemented Mechanism**:
  - `core/containers.py`: Detects Docker/Podman, verifies NVIDIA container runtime (`nvidia-ctk`), catalogs known Isaac Sim container images.
- **Can Caasi already do this?**: **YES**. Validates container environments and builds run commands.

### 2.10 Resource Monitoring (`caasi monitor`, `gpu monitor`)
- **Implemented Mechanism**:
  - `core/monitor.py`: Real-time sampling of CPU, system RAM, GPU %, VRAM used/total, simulation throughput (steps/s), and top memory processes.
- **Can Caasi already do this?**: **YES**. Tracks live resource consumption.

### 2.11 Datasets & Assets (`caasi dataset`)
- **Implemented Mechanism**:
  - `core/dataset.py`: Manages datasets under `~/.caasi/datasets/` or project `datasets/`. Generates datasets via experiment configs, tracks metadata, file counts, and byte sizes.
- **Can Caasi already do this?**: **YES**, for standard file/episode collections.

---

## 3. Summary Assessment of Existing Caasi

| Subsystem | Implemented Status | Readiness for OpenMover |
|---|---|---|
| Project Structure & Manifest | Mature (schema: 1) | Ready to represent OpenMover packages & components |
| Environment & Preflight Checks | Complete (§16 ladder) | Ready to validate ROS 2 Jazzy, Isaac Sim 6.0, RTX 3080 |
| Run Tracking & Logging | Complete | Ready to capture logs & exit codes of simulations & launches |
| Provenance Bundling | Complete (Layer 6) | Ready to record git commits, hardware, and dependency snapshots |
| ROS 2 Orchestration | Complete delegation | Ready to launch ROS 2 bringup and monitor topics |
| Isaac Sim / Lab Launcher | Complete | Ready to invoke `python.sh` / `isaaclab.sh` headlessly |
| Remote Execution | Basic SSH | Ready for remote server execution; sync/queuing to be assessed |
| Live Resource Monitoring | Complete | Ready to watch RAM / VRAM during simulation runs |
