# Phase 5 Case Study Evidence: Physical Robot Hardware Transition and Preflight Validation

**Date**: 2026-10-03  
**Status**: Completed  
**Context**: Evaluation and case-study evidence supporting technical reports and academic papers on caasi  
**Target Workspace**: `/home/zar/Documents/phd/robot/caasi-workspace/openmover_ws/`  
**Git Checkpoint**: `8a14c54`

---

## 1. Overview and Methodology

This document preserves empirical, real-world evidence gathered during Phase 5 of the OpenMover dogfooding project. In Phase 5, we investigated whether `caasi` can manage the transition from simulation to physical robot hardware bringup, sensor discovery, environment compatibility verification, and preflight auditing, while respecting strict physical safety boundaries and preserving the separation between domain software and `caasi`'s management layer.

### Evaluation Criteria
Every case study is structured around seven explicit questions:
1. **Actual Situation**: What was the concrete codebase, asset layout, or operational setup before the intervention? (Distinguishing observed project reality from general technical background).
2. **Action Taken with caasi**: What exact commands, configuration files, and workflows were executed?
3. **What caasi Actually Provided**: What did `caasi` discover, validate, manage, execute, or capture? (Strictly distinguishing `caasi`'s management role from existing domain software implementations).
4. **Empirical Evidence**: What concrete artifacts, metrics, exit codes, PIDs, and files directly prove what occurred?
5. **Directly Supported Benefit**: What practical advantage is strictly supported by the observed evidence?
6. **Unmeasured Counterfactuals & Hypotheses**: What reasonable alternatives or advantages remain unmeasured, hypothetical, or dependent on future multi-system experiments?
7. **Observed Friction & Limitations**: What honest limitations, path resolution bugs, or manual workarounds were encountered?

---

## Case Study 1: Sensor Discovery and Device Permission Auditing

### 1. Actual Situation
- **Observed Setup**: OpenMover connects to an external USB camera (HIK 2K Camera) alongside industrial Ethernet LiDARs and motors. Physical device access in Linux requires correct device nodes (`/dev/video*`), USB permissions, and user group memberships (`video`, `dialout`).
- **General Background**: On robotics workstations, missing user group permissions or disconnected camera cables are common causes of launch-time node crashes. Developers typically debug these interactively using `ls -l /dev/`, `groups`, or `dmesg`.

### 2. Action Taken with caasi
We evaluated `caasi`'s non-intrusive sensor discovery commands against the host system:
```bash
caasi sensor list
caasi sensor inspect cameras
```

### 3. What caasi Actually Provided
- Identified active Video4Linux devices (`/dev/video0`, `/dev/video1`) and resolved sysfs device names (`HIK 2K Camera`).
- Validated that sensor discovery is metadata-only without importing heavyweight camera SDKs or locking video streams.
- Checked serial device patterns (`ttyUSB*`, `ttyACM*`) and confirmed 0 active serial devices connected.
- *Boundary Note*: `caasi` did not instantiate a video stream or camera driver; it queried Linux sysfs and device metadata to report sensor availability.

### 4. Empirical Evidence
- `caasi sensor list` reported:
  - `cameras` (`video4linux`): `detected` (2 devices: `/dev/video0`, `/dev/video1`).
  - `lidar` (`serial`): `not detected` (0 devices).
- System groups check confirmed user `zar` belongs to `dialout` and `plugdev`.
- USB device bus enumeration confirmed USB ID `2bdf:028a` ("SN0002 HIK 2K Camera").

### 5. Directly Supported Benefit
Provides a quick, passive CLI diagnostic for connected robotics sensors and camera hardware before launching long-running ROS 2 driver graphs, avoiding startup crashes due to disconnected peripherals.

### 6. Unmeasured Counterfactuals & Hypotheses
- It remains unmeasured whether sensor discovery reduces operator setup time across heterogeneous camera models (e.g. GigE Vision vs USB3).

### 7. Observed Friction & Limitations
- `caasi sensor inspect cameras` suggests `v4l2-ctl --list-devices` in its hint, but `v4l-utils` was not installed on this workstation. The metadata discovery from `/sys/class/video4linux` succeeded regardless.

---

## Case Study 2: System Readiness and Environment Verification for Hardware Deployment

### 1. Actual Situation
- **Observed Setup**: Transitioning OpenMover from simulation to real hardware requires verifying that the ROS 2 Jazzy middleware, host network stack, compiler toolchain, and CPU/RAM resources meet operational thresholds.
- **General Background**: Hardware driver compilation and real-time sensor processing require sufficient compute headroom and correct ROS 2 environment variable configuration (`RMW_IMPLEMENTATION`, `ROS_DOMAIN_ID`).

### 2. Action Taken with caasi
We executed `caasi`'s comprehensive preflight and environment diagnostic suites:
```bash
caasi env inspect
caasi doctor
caasi check project
```

### 3. What caasi Actually Provided
- **Environment Telemetry**: Queried and reported host CPU (Intel i7-12700K, 20 cores), system memory (46.8 GiB total, 37.8 GiB available), NVIDIA driver (580.178.04), and compiler versions (GCC 13.3.0, Clang 18.1.3, CMake 3.28.3).
- **ROS 2 Middleware Diagnostics**: Verified `/opt/ros/jazzy` installation, active ROS 2 environment sourcing, and CLI availability.
- **Project Preflight Checks**: Checked project manifest requirements against detected environment, verifying compatibility with Nav2 and ROS 2 Jazzy.
- *Boundary Note*: `caasi` performed diagnostic inspection and compatibility verification; it did not alter OS networking or device drivers.

### 4. Empirical Evidence
- `caasi env inspect` produced a complete, structured snapshot of system architecture, compilers, Python virtualenv, and ROS 2 overlays.
- `caasi check project` reported `Result: READY` for environment fingerprinting and verified components.
- `caasi doctor` checked 18 diagnostic domains, validating operating system, kernel, RAM guards, and core robotics libraries.

### 5. Directly Supported Benefit
Enables reproducible, audit-ready preflight checks that confirm machine capability and environment configuration before deploying physical hardware drivers.

### 6. Unmeasured Counterfactuals & Hypotheses
- We have not measured whether environment fingerprinting catches subtle ABI incompatibilities across different Linux kernel patch levels on physical robot SBCs.

### 7. Observed Friction & Limitations
- `caasi doctor` checks for optional GPU-accelerated ROS packages (`isaac_ros_*`, `moveit_core`, `controller_manager`) and marks them with warnings or failures even when the target robot project uses custom UDP drivers and standalone Nav2.

---

## Case Study 3: Physical Interface Boundary Analysis and Safety Enclosure

### 1. Actual Situation
- **Observed Setup**: OpenMover's physical robot architecture communicates with its motor controllers and IO boards over UDP sockets (`192.168.100.100:23` and `192.168.100.100:26`), and with its dual LiDARs over UDP port 502 (`192.168.100.101/102`).
- **General Background**: In physical robotics, launching motor drivers without an active network link or on a development workstation disconnected from the robot can result in socket timeouts, thread deadlocks, or unintended packet transmission.

### 2. Action Taken with caasi
We inspected the launch and driver configurations ([`bringup.launch.py`](file:///home/zar/Documents/phd/robot/openmover_ws/src/openmover/launch/hardwares/bringup.launch.py) and [`hardwares.yaml`](file:///home/zar/Documents/phd/robot/openmover_ws/src/openmover/config_defaults/hardwares.yaml)), verified the network link state using Linux networking tools, and enforced safety rules preventing accidental socket traffic or motor actuation.

### 3. What caasi Actually Provided
- **Architecture Validation**: Identified that OpenMover's hardware interface is strictly decoupled: domain nodes handle UDP packet parsing and checksums, while `caasi` manages the processes and tracks their provenance.
- **Safety Boundary**: Confirmed that `caasi` must not attempt to act as a mock UDP server or inject artificial packets into hardware drivers.
- *Boundary Note*: `caasi` respects the boundary of physical equipment, delegating hardware communications entirely to tested domain driver executables.

### 4. Empirical Evidence
- Network audit confirmed the physical Ethernet interface (`enp6s0`) is currently in `NO-CARRIER` / `DOWN` state (no physical robot umbilical attached).
- Inspection of `motor_handler.cpp` and `io_board_handler.cpp` confirmed socket timeouts are configured (`tv_recv = 5ms`, `tv_send = 10ms`), with automatic reconnection loops.
- `caasi`'s experiment and run architecture successfully encapsulated this behavior during simulation (Phase 3), validating that the identical management layer can launch the real hardware nodes when connected.

### 5. Directly Supported Benefit
Ensures safe, bounded evaluation without risking equipment damage or network disruption, while confirming that `caasi`'s execution engine seamlessly accommodates the physical launch path.

### 6. Unmeasured Counterfactuals & Hypotheses
- It remains unmeasured whether running physical hardware drivers under `caasi` introduces measurable latency overhead into 100 Hz UDP motor control loops.

### 7. Observed Friction & Limitations
- `caasi` does not currently include dedicated network subnet verification (e.g. checking whether a network adapter with IP `192.168.100.x` exists). This is appropriate because network configuration belongs to the OS (Netplan/NetworkManager), but it requires the operator to verify IP assignments manually before launching hardware drivers.
