# Implementation Plan - Phase 7: Multi-Node Lifecycle, Target-Aware Deployment & Remote Execution

Phase 6 established that the entire OpenMover project natively lives inside `caasi-workspace/openmover/` with bit-for-bit mathematical reproduction, automatic project overlay chaining, and unified CLI management.

The next major objective is to transform `caasi` from a single-machine workspace tool into the **project-level control and execution layer for the entire robotics lifecycle**, with the developer workstation serving as the primary control point orchestrating physical robots, simulation servers, and GPU compute clusters.

---

## 1. Architectural Vision & Conceptual Model

```text
                     DEVELOPER WORKSTATION
                   (development & caasi control)
                                 │
                   ┌─────────────┴─────────────┐
                   ▼                           ▼
        TARGET NODES (Physical)      TARGET NODES (Compute)
          ┌─────────────────┐         ┌─────────────────────┐
          │    robot-01     │         │       gpu-01        │
          │ (OpenMover PC)  │         │ (Isaac Sim/Lab RL)  │
          └─────────────────┘         └─────────────────────┘
          ┌─────────────────┐         ┌─────────────────────┐
          │    robot-02     │         │  simulation-server  │
          │ (Manipulator)   │         │ (Multi-Run Headless)│
          └─────────────────┘         └─────────────────────┘
                   │                           │
                   └─────────────┬─────────────┘
                                 │ execution
                                 ▼
                   CONFIGURABLE ARTIFACT ROUTING
              ┌──────────────────┬──────────────────┐
              ▼                  ▼                  ▼
       Workstation Logs     Remote Storage     Provenance
       (Metrics, Summaries) (Models, Datasets) (Audit Bundles)
```

### Generalization Principle
OpenMover serves as the demanding dogfooding case, **not the architectural definition of caasi**. The design must generalize across:
1. **ROS 2 Mobile Robots** (differential, omni, Ackermann)
2. **Isaac Sim / Isaac Lab Reinforcement Learning Clusters**
3. **ROS 2 Manipulators** with MoveIt 2 and `ros2_control`
4. **Simulation-Only Projects**
5. **Physical Robots without Isaac**
6. **Multi-Robot Fleets**

---

## 2. Core Architectural Pillars

### 2.1 Generalized Node Model (`NodeRegistry`)
Each target machine (local workstation, remote robot, GPU server) is modeled as an execution node with declarative configuration and live capability discovery:

```yaml
# caasi.yaml or ~/.caasi/nodes.yaml
nodes:
  local:
    role: control
    transport: local
    capabilities: [build, sim, lab, ros]

  robot-01:
    role: robot
    transport: ssh
    host: 192.168.100.10
    user: zar
    auth: ssh_key
    arch: x86_64
    capabilities: [hardware, ros]
    deployment_root: ~/deploy/openmover
    tags: [openmover, physical, warehouse]

  gpu-01:
    role: compute
    transport: ssh
    host: 10.0.0.50
    user: zar
    capabilities: [cuda, sim, lab]
    deployment_root: /data/caasi/workspaces/openmover
    resources:
      gpus: 4
      gpu_model: RTX_4090
      ram_gb: 128
```

Discoverable attributes queryable via `caasi node inspect <node>`:
- System fingerprint: OS, architecture, kernel, CPU cores, physical RAM.
- GPU & CUDA: driver version, compute capability, VRAM.
- Middleware: ROS distribution, installed underlays, RMW implementation.
- Simulators: Isaac Sim path/version, Isaac Lab installation.
- Operational Status: `online`, `idle`, `busy` (running job), `offline`, `unreachable`.

### 2.2 Target-Aware Deployment Engine (`DeploymentEngine`)
Deploying a robotics project to a target machine requires target-filtered preparation rather than blind source copying:

$$\text{Project Workspace} \xrightarrow[\text{filters}]{\text{target profile}} \text{Deployment Payload} \xrightarrow{\text{sync}} \text{Target Node} \xrightarrow[\text{if needed}]{\text{remote build}} \text{Active Deployment}$$

1. **Target Profiles**:
   - **`robot` profile**: Synchronizes `install/` (or compiled binaries), `config/`, `assets/`, `launch/` without transferring developer artifacts (`.git`, test fixtures, temporary raw logs).
   - **`compute` profile**: Synchronizes `src/`, `lab/`, `experiments/`, `assets/scenes/`, `models/` for remote simulation/RL training.
2. **Smart Build Strategy**:
   - Architecture match: If workstation and robot share architecture/glibc and toolchains match, pre-compiled overlay can be transferred directly.
   - Architecture mismatch or native preference: `caasi` triggers `colcon build` on the target node wrapped in target's ROS environment.
3. **Content-Addressed / Incremental Sync**:
   - Leverages SSH/rsync layer to transfer only modified files, minimizing wireless transfer time to robots.

### 2.3 Transparent Remote Execution (`RemoteRunExecutor`)
The developer remains on the workstation. Running a job on a target node behaves identically to a local run:

```bash
# Launch physical bringup on robot-01
caasi ros launch sim/bridges/16_stack_b.launch.py --target robot-01 --name real-robot-bringup

# Launch 56-map evaluation campaign on gpu-01
caasi run start experiments/lab_campaign.yaml --target gpu-01 --name remote-campaign

# Check unified execution status across nodes
caasi run list
caasi logs real-robot-bringup -f
caasi run stop real-robot-bringup
```

- **Remote Wrapper**: Automatically discovers and sources target's `/opt/ros/...` and target deployment's `install/setup.bash`.
- **Run Tracking**: The remote run produces a standard `RunRecord` with PID on the target node, streaming stdout/stderr back to workstation cache.
- **Detached Lifecycle**: Network disconnections do not terminate remote robot execution; runs continue detached and re-attach when connectivity resumes.

### 2.4 Multi-Node Resource State & Job Scheduling
To manage multiple robots and servers:
- **Node State Tracking**: `caasi` tracks active runs per node. If `gpu-01` is executing a 4-hour RL training job, `caasi run --target gpu-01` warns the user that GPU resources are occupied or queues the job.
- **Target Selection**: If `--target` is omitted, `caasi` can resolve the default target matching the workload backend (`sim` $\rightarrow$ GPU node, `hardware` $\rightarrow$ robot node, `test` $\rightarrow$ local).

### 2.5 Configurable Artifact & Result Routing
Different nodes produce different output categories that require distinct routing:

```yaml
# In experiment manifest or caasi.yaml
artifacts:
  routing:
    logs:
      target: retain_local_summary  # Full logs on robot, summary to workstation
    metrics:
      target: fetch_to_workstation   # Pull aggregate.json to workstation
    checkpoints:
      target: retain_on_remote      # Keep heavy model weights on GPU server
    provenance:
      target: fetch_to_workstation   # Always pull manifest and audit metadata
```

### 2.6 GUI Workload Handling
Robotics frequently involves visualization (RViz, Isaac Sim GUI, rqt):
1. **Headless by Default**: All background runs, campaigns, and robot deployments operate headless.
2. **Decoupled GUI via DDS / Network Topics**: Run robot or simulation headlessly on the remote target, and run RViz locally on the developer workstation connected to the same ROS 2 domain (`ROS_DOMAIN_ID`). This avoids sluggish X11/VNC network latency while keeping native GPU acceleration on the workstation display.
3. **Omniverse WebRTC Streaming**: For Isaac Sim remote GUI, support WebRTC live-streaming flags (`--livestream`) connecting via browser from workstation.

---

## 3. Existing Caasi Reuse vs Genuine Gaps

| Capability Area | Existing Caasi Infrastructure | Genuine Gap to Implement |
| :--- | :--- | :--- |
| **Node Registry** | `caasi.core.config.Config`, basic `RemoteConfig` | Generalized `Node` dataclass, `nodes.yaml` schema, capability discovery |
| **System Inspection** | `caasi.core.check`, `caasi.core.doctor`, system fingerprints | Remote inspection over SSH (`caasi node check / inspect`) |
| **Workspace Build** | `caasi.core.build` (RAM-safe colcon orchestrator) | Remote build trigger on target node (`caasi build --target <node>`) |
| **Run Management** | `caasi.core.runs` (manifest, lifecycle, PID tracking) | Target-tagged `RunRecord` and remote process supervision |
| **Remote Transport** | `caasi.core.remote` (basic SSH execution helper) | Workspace sync engine (`rsync` wrapper with target profiles) |
| **Provenance** | `caasi.core.provenance` (Level 6 local bundle capture) | Multi-node provenance merging (capturing target node hardware + local controller git state) |

---

## 4. Phase 7 Scope: The Smallest Coherent Next Phase

To maintain validation-first discipline and avoid speculative over-engineering, Phase 7 will implement the **Target Node Management, Workspace Deployment & Remote Execution Core**:

### Stage A: Node Management & Capability Discovery (`caasi node`)
- Implement `Node` and `NodeRegistry` in `caasi.core.nodes`.
- Support `caasi node list`, `caasi node check <node>`, and `caasi node inspect <node>`.
- Remotely discover OS, architecture, RAM, GPU/CUDA, ROS distro, Isaac paths, and connectivity latency.

### Stage B: Target-Aware Deployment Engine (`caasi deploy`)
- Implement `DeploymentEngine` with target deployment profiles (`robot`, `compute`).
- Synchronize filtered project workspace to target nodes via incremental rsync.
- Provide `caasi build --target <node>` to execute RAM-safe builds directly on the target machine.

### Stage C: Transparent Remote Run Execution (`caasi run --target`)
- Extend `caasi run start`, `caasi sim run`, and `caasi ros launch` with `--target <node>`.
- Launch runs inside the remote target's properly sourced environment.
- Stream logs, track remote PID lifecycle, and handle graceful stops (`caasi run stop`).

### Stage D: End-to-End Multi-Node Validation (Dogfooding)
- Validate local workstation $\leftrightarrow$ target node workflows.
- Verify remote log streaming, detached process resilience, and multi-node provenance capture.

---

## 5. Verification Plan

### Automated Unit Tests
- `tests/test_nodes.py`: Node configuration, schema parsing, capability discovery serialization.
- `tests/test_deploy.py`: Target profile filtering, payload generation, sync dry-run.
- `tests/test_remote_run.py`: Remote run lifecycle, target tagging, environment wrapping.

### Real Multi-Node Validation
1. Register local workstation and configured remote node.
2. `caasi node inspect <node>`: verify remote hardware and toolchain detection.
3. `caasi deploy <node>`: deploy filtered OpenMover workspace.
4. `caasi run start ... --target <node>`: execute and verify remote tracking.
5. Verify zero lingering processes on target node after `caasi run stop`.
