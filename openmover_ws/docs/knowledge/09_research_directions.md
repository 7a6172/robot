# 09 — Research Directions (what this system is for next)

> Status as of 2026-08: **discussion stage — nothing here is implemented yet.** This file records
> the agreed direction so future sessions can continue without re-deriving it.
>
> **This is the short version.** The full research documentation — program overview, NMTE
> framework, first-paper scope, Isaac Sim strategy, transfer-learning notes, validation plan,
> draft review, and the decisions log — lives in
> [`docs/research/`](../research/00_START_HERE.md). Read that folder for anything beyond a quick
> orientation.

## The goal

The primary reason for the ROS 2 migration is to bring this robot into the **NVIDIA Isaac Sim /
Isaac Lab ecosystem**: use the GPU for photoreal, physics-accurate simulation, synthetic data
generation, and robot learning. The current warehouse setup is the proving ground; the same
pipeline is meant to extend to other robots later.

## Operating model (agreed)

- **Train on the workstation PC, deploy to the robot.** The robot's own PC is weaker than the dev
  PC and cannot run Isaac Sim at all — it is a deployment target only.
- Deployment is **not** limited to tiny onboard models: the workstation can act as a tethered
  brain (ROS 2 DDS over network; robot streams scans/odometry, receives `cmd_vel`; the existing
  cmd_vel watchdog pattern doubles as the deadman). Papers should still report an
  onboard-compressed variant where possible — "works on a laptop-brain robot" is a feature.
- **Environments are disposable.** The current warehouse world is just for testing; new USD
  environments can be generated per experiment (procedural layouts for training, held-out layouts
  for evaluation). The robot + pipeline are the constants.
- Preference for ideas that work with **current components only** (two 2D LiDARs, no camera).

## Hardware reality (as of the discussion)

- Isaac Sim 6.x officially supports **ROS 2 Jazzy on Ubuntu 24.04** (the recommended pairing);
  Isaac Lab 3.0 sits on top (and offers a kit-less Newton-physics mode).
- Dev machine: i7-12700K, **16 GB DDR5**, RTX 3080 10G. Isaac Sim's current minimum spec is
  ~32 GB RAM / RTX 4080-class GPU. Plan: RAM upgrade as needed; LiDAR-only policy training runs
  headless without rendering, which keeps VRAM demands low. Check NVIDIA's compatibility checker
  before installing.
- Install form candidates: pip `isaacsim` package (lightest) or container.

## The research thread: "Where am I? → Where do I go?"

Robust autonomy for a cheap robot, trained entirely in simulation. Two linked projects:

### B — Learned global relocalization from synthetic scans (first)

- Isaac Sim can generate **millions of 2D LiDAR scans with perfect ground-truth poses** across
  procedurally randomized warehouse layouts — supervision reality can never provide.
- Design that leverages the existing `relocalization_toolbox`: keep its RRT/candidate sampling as
  the proposal engine, train a network to **score candidate poses** (scan vs. local map match).
  Hybrid classical-proposal + learned-scoring = robust by construction, small network, natural
  ablations.
- Evaluation: kidnapped-robot recovery rate/error vs particle-filter/MCL baselines and vs the
  current likelihood-field pipeline; zero-shot sim→real, then few-shot real adaptation.

### A — Teacher-student social navigation (second)

- Isaac Lab parallel environments with randomized pedestrian flows, friction, sensor noise,
  latency. Teacher policy with privileged ground truth → distilled student consuming only
  LiDAR + odometry + goal → export ONNX/TensorRT.
- Learned policy runs **inside the existing classical safety envelope** (the perception-based
  pedestrian stop). LiDAR-only observations mean headless training without rendering.

### The interlock (the demo that carries the papers)

Navigation confidence drop (kidnap/disturbance) → stop → B relocalizes → A resumes.
End-to-end: robot navigates among pedestrians, gets deliberately displaced, recovers, continues.

### The "transfer engine" framing

The reusable systems contribution: (1) sim data factory (layouts, randomization, free labels),
(2) train + distill pipelines, (3) deployment abstraction (tethered GPU vs onboard CPU),
(4) identical evaluation harness in sim and real. Paper 1 = B, paper 2 = A, paper 3 = integrated
system. Later robots reuse (1)–(4).

## Supporting ideas (parked, still valid)

- **C — Synthetic-data perception safety**: add a cheap camera; Replicator-randomized warehouse
  scenes for pedestrian/forklift detection; synthetic→real data-efficiency study; fuse into the
  costmap for the safety stop. Needs camera hardware — the one idea that does.
- **D — Real-to-sim digital twin**: rebuild the actual warehouse from the robot's own map in USD;
  orchestrated robustness benchmarks (occlusions, degraded geometry) as evaluation material.
- Isaac ROS (separate product): GPU perception/VSLAM/Nvblox nodes for the real stack — a
  complementary way to use the GPU outside simulation.

## Relevant facts about the current system for this research

- Everything above `openmover/hardware/*` topics is simulator-agnostic → Isaac Sim integration
  means replacing the Gazebo layer with an Isaac bridge, not rewriting the stack.
- Custom `openmover_msgs` never need to cross the simulator bridge (standard topics suffice:
  cmd_vel in; scan/odom/tf out).
- The relocalization toolbox and auto-mapping toolbox are the unique, citable assets no other
  group has — benchmark against them, don't replace them.
- Real-robot experiments are the strongest publishability asset (many competing works are
  sim-only); the real branch still needs its first hardware commissioning (see
  [05_workflows_real_robot.md](05_workflows_real_robot.md)).
