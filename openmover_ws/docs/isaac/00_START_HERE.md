# Isaac Sim Integration — Start Here

This folder is the machine-readable description of the **Isaac Sim bring-up** of the OpenMover
robot, written so an AI model (or a new engineer) can understand and extend it **without
re-deriving the sessions that produced it**. If you are an AI assistant reading this: consume
the files in order below, then verify against the scripts in `openmover_ws/isaac/scripts/`
before changing anything.

Companion docs: the AI-facing knowledge base for the ROS 2 stacks is `docs/knowledge/`;
the research context (including `04_isaac_sim_strategy.md` and the decisions log) is
`docs/research/`. Human-facing HTML for this topic: `docs/isaac/index.html`.

## What this is (30 seconds)

Isaac Sim 6.0 (headless) now drives the OpenMover robot stacks **over ROS 2 Jazzy topics,
unmodified**. Isaac plays the role Gazebo used to play: it receives velocity commands and
publishes `/clock`, odometry and two bluesea2-style 2D LiDAR scans. Two integrations exist:

1. **Stack B** (`warehouse_simulation`: slam_toolbox + Nav2) — bare topics `/scan /cmd_vel
   /odom /tf`. Bridge: `isaac/scripts/16_bridge_ros.py`, launch `16_stack_b.launch.py`.
   Teleop and Nav2 gates PASSED.
2. **Stack A** (`openmover`, the real product stack) — product topics
   `openmover/control/cmd_vel_sim` in; `openmover/hardware/odom_sim` + 2 scans + `/clock` out.
   Bridge: `isaac/scripts/17_bridge_openmover.py`. One launch arg added ROS-side
   (`launch_gazebo`, default 1) to skip Gazebo itself. Teleop gate PASSED;
   **navigation gate PASSED** (cartographer localization + the product's own navigation
   controller drove the robot to goal (1.0, 0.0) in Isaac).

## Reading order

| # | File | Contents |
|---|---|---|
| 1 | [01_environment.md](01_environment.md) | Machine, Isaac install, how scripts run, RAM guard |
| 2 | [02_codebase.md](02_codebase.md) | `openmover_ws/isaac/` tree, every script and module, scenes/assets |
| 3 | [03_bridges.md](03_bridges.md) | The two bridge contracts (topics, QoS, TF ownership), sim-loop mechanics |
| 4 | [04_runbooks.md](04_runbooks.md) | Exact commands: Stack B teleop/Nav2, Stack A teleop, shutdown order |
| 5 | [05_lessons_learned.md](05_lessons_learned.md) | Bugs found, tuning values, caveats, follow-ups |
| 6 | [06_results.md](06_results.md) | Results ledger: baselines, training runs, transfer evidence (D24) |

## Quick orientation facts

- Isaac Sim: `6.0.1-rc.7` at `~/isaacsim`. Scripts run **inside Isaac's bundled Python**:
  `~/isaacsim/python.sh <script>` (Python 3.12), after `source /opt/ros/jazzy/setup.bash`
  if the script uses ROS.
- Workspace: `/home/zar/Documents/phd/robot/openmover_ws`; Isaac work in `isaac/`,
  docs here in `docs/isaac/`. ROS packages in `src/` — **untouched except** the approved
  `launch_gazebo` change in `openmover/launch/hardwares/bringup.launch.py` and
  `openmover/launch/bootloader.launch.py` (both symlink-installed; no rebuild needed).
- rclpy runs **inside Isaac's Python process**; there is no external `ros_gz_bridge`-style
  process. `rclpy` has **no `spin_some`** — the bridges use `rclpy.spin_once(node, timeout_sec=0)`.
- Sim loop: physics dt ≈ 0.0167 s (60 Hz), LiDAR scan tick 1/15 s (15 Hz, both lidars).
  Rendering is gated to the scan tick and the loop is paced to real time.
- **Machine constraint:** 16 GiB RAM (this machine has hard-frozen under load). Every Isaac
  script calls `common.preflight()` first: abort below 8 GiB MemAvailable, warn below 12.5,
  one simulator at a time.
- Standing convention from the plan: Steps 1.0–1.6 (smoke test → robot → LiDAR → bridge core →
  scenes → stack integration → this documentation). Steps 1.0–1.5 are complete with all gates
  passed, and the Stack A navigation gate (cartographer + product navigation controller)
  passed afterwards; see [05_lessons_learned.md](05_lessons_learned.md) for the gate evidence.
