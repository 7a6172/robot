# 04 — Isaac Sim Strategy

Everything gathered about NVIDIA's simulation stack, our hardware reality, and how to integrate
it phase by phase. Facts checked as of August 2026 (via NVIDIA docs/forums/Isaac Lab releases);
re-verify version numbers before installation.

## Why Isaac Sim for this program

- The migration to ROS 2 was driven by Isaac Sim in the first place: the robot works as a
  ROS 2 node, Isaac Sim publishes LiDAR/odometry, the robot consumes them and publishes `cmd_vel`.
  Same as today's Gazebo pipeline — the ROS 2 stack is already Isaac-ready at the interface level.
- Simpler first: the robot only needs `sensor_msgs/LaserScan` + `cmd_vel`, and the stack uses only
  standard message types — a property deliberately preserved during migration because **custom
  messages don't cross the ROS bridge**.
- GPU-parallel RL training (Isaac Lab) is the realistic path for the learned artifacts; the CPU
  machine would be hopeless at that scale.

## Version facts (re-verify before installing)

- **Isaac Sim 6.0.x** is the current release; supported host: Ubuntu 24.04 LTS (recommended),
  **ROS 2 Jazzy is supported**. Isaac Sim's internal Python is 3.12 — matching Jazzy's Python 3.12,
  so extensions are compatible.
- Isaac Sim 5.1/6.0 **minimum spec** quoted by NVIDIA: 32 GB RAM, RTX 4080 / 16 GB VRAM
  (4.5-generation minimum was RTX 3070/8 GB + 32 GB RAM).
- **Isaac Lab 3.0** (RL framework): kit-less Newton-based mode available; NVIDIA's own hardware
  guide for Lab recommends 32 GB RAM / 16 GB VRAM. For our use case: **LiDAR-only training is
  headless with no rendering**, so the 10 GB RTX 3080 can run many parallel environments.
- **Isaac ROS 4.x** (GPU perception: VSLAM, Nvblox) runs on the robot stack itself and requires
  native Ubuntu 24.04 — complementary, later-stage, not needed for paper 1.

## Our hardware reality (honest)

| Component | Spec | Impact |
|---|---|---|
| GPU | RTX 3080, 10 GB VRAM | Below recommended 16 GB, above old-generation minimums. Headless/LiDAR-only training viable; rendering-heavy scenes must stay small |
| RAM | 16 GB DDR5 | **The bottleneck.** NVIDIA's minimum is 32 GB. The machine froze twice under heavy parallel work. **A RAM upgrade to 32 GB is the single biggest unlock.** Without it: pip/container installs, headless only, low scene counts |
| CPU | i7-12700K, 20 threads | Fine |
| Driver | 580.65.06 (within 580-series family) | Compatible |
| Disk | ~50 GB available | Tight (Isaac Sim can take tens of GB); plan cleanup |

Standing rule: never launch heavy parallel builds/simulations unattended; `-j2` build convention;
kill stray `gz sim`/`ruby` before launching GPU simulators.

## Installation options

- **pip install** — lightest footprint, easiest RAM management; preferred given 16 GB RAM.
- **Container** — clean isolation; second choice.
- Full Omniverse Launcher install — heaviest; avoid on this machine.

## The operating model

**Train on the PC, deploy on the robot.** Isaac Sim/Lab runs entirely on the development PC; the
robot connects as a ROS 2 node over DDS (later: WiFi or cable — open question). During paper 1,
everything is sim-to-sim anyway; the tethered deployment model is exercised later and is described
in `05_transfer_learning_notes.md`.

## Task tiers (from simplest to most ambitious)

| Tier | Task | Needs |
|---|---|---|
| A | Reproduce current teleop + SLAM + navigation pipeline in Isaac Sim | Isaac Sim + ROS bridge only |
| B | Synthetic perception data generation (Replicator, SDG labels) | Isaac Sim |
| C | RL policy training (teacher-student nav / dynamics learning) | Isaac Lab, headless |
| D | Multi-robot fleet / optimization (CuOpt) | Later |
| E | Isaac ROS GPU perception on the real robot | Native Ubuntu 24.04 robot, later |

## Phased integration plan

1. **Phase 0 — characterization first** (no Isaac involved): measure the physical robot, per
   `06_validation_plan.md`. Everything downstream depends on it.
2. **Phase 1 — Tier A**: install Isaac Sim (pip), import the robot (pioneer3dx URDF → USD, once,
   reused forever), RTX 2D LiDAR sensor configured to match the real LiDAR, recreate the warehouse
   scene; run the existing ROS 2 stack against it. *Proof that the interface contract holds.*
3. **Phase 2 — environment factory**: procedural source domains + the railway yard USD scene.
4. **Phase 3 — Tier C**: Isaac Lab headless training of the engine artifacts (Koopman + student).
5. **De-risking rule:** the method nodes (policy inference, CBF-QP, DOB) are written
   **simulator-agnostic** — plain ROS 2 nodes consuming `/scan`, publishing `/cmd_vel`. They are
   developed against the *already working* Gazebo stack while Isaac matures; then the same nodes
   point at Isaac Sim for scale training. **The paper never blocks on Isaac setup**: Isaac is the
   training engine, Gazebo the early testbed, the real robot the later revision.

## Notes & caveats

- The Gazebo Harmonic world (`openmover_gazebo.sdf`) is system-validation ground truth during
  migration; research experiments use purpose-built Isaac scenes.
- The existing `warehouse_simulation` world is the template for the depot/yard layout vocabulary.
- Isaac Lab crowd/pedestrian agents: scripted or random-walk agents are sufficient for paper 1
  (no learned pedestrian model needed).
