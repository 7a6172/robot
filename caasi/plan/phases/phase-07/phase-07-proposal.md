# Phase 7 Architectural Proposal: Target-Aware Deployment, Capability-Driven Remote Execution & Multi-Node Lifecycle

**Status**: Proposal / Architecture Design Only (Implementation Deferred)  
**Date**: 2026-10-04  
**Primary Testbed**: OpenMover Canonical Workspace (`caasi-workspace/openmover`)  
**Design Mandate**: Strictly generalized robotics project abstraction; OpenMover is a concrete validation vehicle, not the architectural definition of caasi.

---

## 1. Architectural Vision & Three-Tier Generalization

The long-term goal is for `caasi` to serve as the **project-level control and execution layer for the entire robotics lifecycle**, with the developer workstation as the primary control point managing physical robots, simulation clusters, and GPU compute servers.

To prevent baking OpenMover assumptions into core abstractions, all architectural components are organized into three strictly separated tiers:

```text
┌────────────────────────────────────────────────────────────────────────┐
│ 1. GENERAL CAASI CORE LAYER (Project-Agnostic Engine)                  │
│    - Capability-Driven Target Model (Architecture, Resources, State)   │
│    - Deployment Pipeline (Filter, Package, Transfer, Target Build)     │
│    - Transparent Remote Process Supervisor (Environment Wrap, Runs)    │
│    - Configurable Artifact & Result Router                             │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ instantiates
┌──────────────────────────────────▼─────────────────────────────────────┐
│ 2. PROJECT CONFIGURATION LAYER (Declarative Project Manifest)          │
│    - Workspace Structure & Toolchain Requirements (caasi.yaml)         │
│    - Deployment Profiles & Target Capability Match Constraints         │
│    - Artifact Routing Rules & Experiment Declarations                  │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ configures
┌──────────────────────────────────▼─────────────────────────────────────┐
│ 3. DOMAIN / HARDWARE INTEGRATION LAYER (Project-Specific Payload)      │
│    - Concrete ROS 2 Nodes / Drivers / MoveIt / Nav2 Stacks             │
│    - Specific Sensors (LiDARs, Cameras, IMUs, CAN/Serial buses)        │
│    - Specific Simulators & RL Environments (Isaac Sim/Lab, Gazebo)     │
└────────────────────────────────────────────────────────────────────────┘
```

### Universal Applicability Across Robotics Archetypes
The design must remain valid without alteration across diverse robotics project types:
1. **ROS 2 Mobile Robots** (differential drive, omni-directional, Ackermann steering; Nav2, SLAM).
2. **Robotic Manipulators** (multi-DoF arms; MoveIt 2, `ros2_control`, trajectory controllers).
3. **Isaac Sim / Isaac Lab RL Research Projects** (GPU server training, policy evaluation, procedurally generated terrains).
4. **Simulation-Only Projects** (headless testing, continuous integration simulation without physical robots).
5. **Physical Robots without Isaac** (embedded compute, field robotics, hardware-in-the-loop without GPU simulation).
6. **Multi-Robot Fleets** (heterogeneous mobile bases and arms coordinated over DDS).

---

## 2. Fundamental Target & Execution Model

The fundamental abstraction is capability- and resource-driven rather than hardcoded around rigid machine roles:

```text
Project
  ↓
Deployment
  ↓
Target
  ↓
Capabilities + Resources + State
  ↓
Build / Package / Execute
  ↓
Run
  ↓
Artifacts / Results / Provenance
```

### 2.1 Capability-Driven Target Specification
Rather than categorizing nodes merely as "robot" or "compute", each target declares its physical resources, supported capabilities, and operational state:

```yaml
# ~/.caasi/nodes.yaml or project target declarations
targets:
  workstation:
    transport: local
    architecture: x86_64
    os: linux
    resources:
      cpus: 20
      ram_gb: 46.8
      gpus:
        - model: RTX_3080
          vram_gb: 10
          cuda: "13.0"
    capabilities:
      - ros2: jazzy
      - colcon: build
      - isaac_sim: "6.0"
      - isaac_lab: "3.0.0"

  robot-01:
    transport: ssh
    host: 192.168.100.10
    user: zar
    auth: ssh_key
    architecture: x86_64
    os: linux
    resources:
      cpus: 8
      ram_gb: 16.0
      gpus: []
    capabilities:
      - ros2: jazzy
      - hardware: [ethernet_udp, v4l2, serial]
    deployment_root: /opt/openmover/runtime

  gpu-server-01:
    transport: ssh
    host: 10.0.0.50
    user: zar
    auth: ssh_key
    architecture: x86_64
    os: linux
    resources:
      cpus: 64
      ram_gb: 256.0
      gpus:
        - model: RTX_4090
          vram_gb: 24
          cuda: "12.4"
          count: 4
    capabilities:
      - cuda
      - isaac_sim: "6.0"
      - isaac_lab: "3.0.0"
      - colcon: build
    deployment_root: /data/caasi/deployments/openmover
```

### 2.2 Live State Discovery
Target nodes report dynamic operational status:
- **`online / idle`**: Ready to accept build, test, or run workloads.
- **`busy`**: Actively executing a job (tracking active Run IDs, allocated CPU/GPU resources).
- **`capacity_limited`**: Partial resources available (e.g. 2 of 4 GPUs occupied).
- **`offline / unreachable`**: Target unreachable over network transport.

---

## 3. Target-Aware Deployment Engine

Deployment is the process of preparing, transferring, and installing a project onto a target node based on **capability match and deployment policy**, rather than blind file copying:

$$\text{Project Workspace} \xrightarrow[\text{policy}]{\text{target profile requirements}} \text{Payload Filters} \xrightarrow[\text{rsync / transport}]{\text{incremental transfer}} \text{Target Node} \xrightarrow[\text{if required}]{\text{target build}} \text{Active Deployment}$$

### 3.1 Policy-Driven Deployment Profiles
Projects declare deployment profiles in `caasi.yaml` matching workload requirements:

```yaml
# In caasi.yaml
deployment_profiles:
  runtime_minimal:
    # Intended for physical robot controllers or resource-constrained nodes
    require_capabilities: [ros2]
    exclude:
      - .git/
      - "**/*.pyc"
      - tests/
      - lab/tasks/
      - docs/
      - assets/scenes/
    include:
      - install/
      - config/
      - launch/
      - assets/robots/
    build_on_target: false  # Transfer pre-built overlay if arch/toolchain matches

  compute_training:
    # Intended for GPU simulation/training servers
    require_capabilities: [cuda, isaac_lab]
    exclude:
      - .git/
      - "**/*.pyc"
      - build/
      - install/
    include:
      - src/
      - lab/
      - config/
      - experiments/
      - assets/
    build_on_target: true   # Compile natively on compute node
```

### 3.2 Target Build Strategy
- **Binary Transfer**: If workstation and target share binary compatibility (matching CPU architecture, kernel ABI, glibc, and ROS distribution), `caasi` can transfer the compiled `install/` directory directly.
- **Target-Native Build**: If architectures differ, or if the profile specifies `build_on_target: true`, `caasi` triggers `caasi build` directly on the target machine wrapped in the target's native ROS environment, enforcing target-side RAM-budget heuristics.

---

## 4. Transparent Remote Execution & Unified Process Supervision

The developer operates from the workstation. Remote execution mirrors local execution semantics:

```bash
# Execute hardware launch on robot-01
caasi ros launch openmover bringup.launch.py --target robot-01 --name robot-bringup

# Execute 56-map training campaign on gpu-server-01
caasi run start experiments/lab_campaign.yaml --target gpu-server-01 --name remote-campaign

# Unified status across local and remote runs
caasi run list
caasi logs robot-bringup -f
caasi run stop robot-bringup
```

### Key Remote Execution Invariants:
1. **Remote Environment Wrapping**: The target-side runner automatically discovers and chain-sources the target node's system underlay (`/opt/ros/...`) and target deployment overlay (`<deployment_root>/install/setup.bash`).
2. **Detached Process Resilience**: Remote jobs run detached under a target-side wrapper script (`run.sh`). Disconnecting the workstation network or closing the terminal does not interrupt the robot or training run.
3. **Unified Run Records**: The workstation receives and tracks a first-class `RunRecord` containing the target node identifier, remote PID, exit code, and streamed stdout/stderr logs.
4. **Graceful Multi-Process Termination**: `caasi run stop` sends targeted SIGINT/SIGTERM process-group signals on the remote machine, ensuring simulators and hardware drivers terminate without orphaned processes.

---

## 5. Configurable Artifact & Result Routing

Execution target and artifact destination are decoupled:

```yaml
# In experiment manifest or caasi.yaml
artifact_routing:
  telemetry:
    # Send scalar metrics, norms, and run status to workstation
    destination: workstation
  logs:
    # Keep full high-bandwidth sensor dumps on target node; stream summaries
    destination: target_local
    stream_summary: true
  model_checkpoints:
    # Store heavy neural network weights on shared storage / compute server
    destination: target_local
  provenance:
    # Level 6 audit bundle always captured and returned to workstation
    destination: workstation
```

---

## 6. GUI Workload Strategy

Robotics workflows regularly require visualization tools (RViz, rqt, Isaac Sim viewport):
1. **Headless by Default**: All background experiment runs, robot controllers, training jobs, and bridges execute headlessly.
2. **Peered Network Visualization (Decoupled GUI)**: The robot or simulation server runs headlessly on the remote target, publishing ROS 2 topics over the network DDS domain (`ROS_DOMAIN_ID`). The developer runs RViz locally on the workstation GPU, avoiding network rendering lag while viewing live robot sensor data.
3. **WebRTC Viewport Streaming**: For Isaac Sim remote GUI, support WebRTC livestreaming (`--livestream`) connecting via browser from the workstation.

---

## 7. Existing Caasi Reuse vs Genuine Gaps

| Capability Area | Existing Caasi Infrastructure | Genuine Gap to Implement |
| :--- | :--- | :--- |
| **Node Registry** | `caasi.core.config.Config`, basic `RemoteConfig` | Generalized `Target` dataclass, `nodes.yaml` schema, capability matcher |
| **Capability Discovery** | `caasi.core.check`, `caasi.core.doctor`, system fingerprints | Remote inspection over SSH (`caasi node check / inspect`) |
| **Workspace Build** | `caasi.core.build` (RAM-safe colcon orchestrator) | Remote build trigger on target node (`caasi build --target <target>`) |
| **Run Management** | `caasi.core.runs` (manifest, lifecycle, PID tracking) | Target-tagged `RunRecord` and remote process supervision |
| **Transport** | `caasi.core.remote` (basic SSH execution helper) | Profile-filtered workspace sync engine (`rsync` wrapper) |
| **Provenance** | `caasi.core.provenance` (Level 6 local bundle capture) | Multi-node provenance merging (target hardware + controller git state) |
| **Project Data Assets** | Basic `assets/` directory scanning | Formal support for site-specific environmental data (e.g. SLAM maps, calibration bags) |

---

## 8. Implementation Staging (Next Phase)

*Note: In accordance with instructions, implementation is deferred until full design review and approval.*

- **Stage A (Target Discovery Core)**: Implement target data models and remote capability discovery (`caasi node list`, `caasi node inspect <target>`).
- **Stage B (Deployment Engine)**: Implement profile-filtered workspace sync and target-native build triggers (`caasi deploy <target>`, `caasi build --target <target>`).
- **Stage C (Transparent Remote Runs)**: Implement `--target` execution on `caasi run start`, `caasi sim run`, and `caasi ros launch` with detached remote process supervision and log streaming.
- **Stage D (Multi-Node Validation)**: Validate workstation $\leftrightarrow$ target workflows across real local and remote Linux/robot targets.
