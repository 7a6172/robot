# Example coverage — every caasi command

**Auditable mapping from each CLI command to the example that demonstrates it.**

Generated from the **live command tree**, not maintained by hand: the current CLI has
**60 root commands and 283 command paths**, and **every one is listed below**. A
command that has no runnable example is still listed, with the reason — nothing is
silently omitted.

> **Re-generated and verified** against the live CLI as part of the 0.4.0 release
> check. If a future change adds a command, the count here must change with it.

---

## How to read the columns

| Column | Meaning |
| :--- | :--- |
| **Example** | which example demonstrates it (`01`–`07`, or `cookbook`) |
| **Execution** | how it is exercised — `runnable`, `read-only`, `GUI`, `Docker`, `ROS 2`, `Isaac`, `ecosystem delegation`, `documented`, `not executed` |
| **Tier** | `CI` (validated automatically) · `opt-in` (auto-skipped without prerequisites) · `manual` (needs a display, a TTY, hardware, or is unsafe) |
| **Notes** | the reason, especially for anything **not executed** |

`CI/opt-in` means the example is CI-validated on the local path and opt-in when a
second target is involved.

---

## Summary

| Tier | Count | Meaning |
| :--- | ---: | :--- |
| **CI** | see table | validated by `tests/test_examples.py` via the existing release workflow |
| **opt-in** | see table | run when the prerequisite exists, skipped otherwise |
| **manual** | see table | needs a display, TTY, hardware, or is unsafe to run |

**Never executed by any example:** `run delete`, `project remove`, `teleop start`,
`teleop record`, `setup`, `nav launch`, `moveit launch`, `motion execute` — and none
of them invents a `--dry-run` that the CLI does not provide.

---

## The full matrix

| Command | Example | Execution | Tier | Notes |
| :--- | :--- | :--- | :--- | :--- |
| `caasi audit` | 01 | runnable | CI |  |
| `caasi benchmark` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi benchmark report` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi benchmark start` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi build` | 07 | runnable | CI/opt-in | chain; SSH target optional |
| `caasi check` | 01 | runnable | CI |  |
| `caasi choose` | 01 | runnable | CI | stores a default; no target needed |
| `caasi choose project` | 01 | runnable | CI |  |
| `caasi choose robot` | 01 | runnable | CI | searches ~/caasi/robots by name |
| `caasi choose show` | 01 | runnable | CI |  |
| `caasi choose target` | 07 | runnable | CI/opt-in | chain; SSH target optional |
| `caasi config` | cookbook | read-only | CI |  |
| `caasi config catalog` | cookbook | read-only | CI |  |
| `caasi config get` | cookbook | read-only | CI |  |
| `caasi config path` | cookbook | read-only | CI |  |
| `caasi config set` | cookbook | read-only | CI |  |
| `caasi config show` | cookbook | read-only | CI |  |
| `caasi config tools` | cookbook | read-only | CI |  |
| `caasi container` | 04 | Docker | CI |  |
| `caasi container check` | 04 | Docker | CI |  |
| `caasi container doctor` | 04 | Docker | CI |  |
| `caasi container list` | 04 | Docker | CI |  |
| `caasi container run` | 04 | Docker | CI |  |
| `caasi container status` | 04 | Docker | CI |  |
| `caasi control` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi control check` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi control doctor` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi control list` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi control status` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi cosmos` | 06 | ecosystem delegation | opt-in | needs the upstream tool + a GPU |
| `caasi cosmos dataset` | 06 | ecosystem delegation | opt-in | needs the upstream tool + a GPU |
| `caasi cosmos run` | 06 | ecosystem delegation | opt-in | needs the upstream tool + a GPU |
| `caasi cosmos status` | 06 | ecosystem delegation | opt-in | needs the upstream tool + a GPU |
| `caasi dataset` | 05 | runnable | manual | needs a display/bag |
| `caasi dataset convert` | 05 | runnable | manual | needs a display/bag |
| `caasi dataset download` | 05 | runnable | manual | needs a display/bag |
| `caasi dataset generate` | 05 | runnable | manual | needs a display/bag |
| `caasi dataset inspect` | 05 | runnable | manual | needs a display/bag |
| `caasi dataset list` | 05 | runnable | manual | needs a display/bag |
| `caasi dataset validate` | 05 | runnable | manual | needs a display/bag |
| `caasi deploy` | 07 | runnable | CI/opt-in | chain; SSH target optional |
| `caasi doctor` | cookbook | read-only | CI |  |
| `caasi env` | 01 | runnable | CI |  |
| `caasi env compare` | 01 | runnable | CI |  |
| `caasi env fingerprint` | 01 | runnable | CI |  |
| `caasi env inspect` | 01 | runnable | CI |  |
| `caasi env lock` | 01 | runnable | CI |  |
| `caasi env show` | 01 | runnable | CI |  |
| `caasi gpu` | cookbook | read-only | CI |  |
| `caasi gpu doctor` | cookbook | read-only | CI |  |
| `caasi gpu info` | cookbook | read-only | CI |  |
| `caasi gpu memory` | cookbook | read-only | CI |  |
| `caasi gpu monitor` | cookbook | read-only | CI |  |
| `caasi gpu status` | cookbook | read-only | CI |  |
| `caasi gpu test` | cookbook | read-only | CI |  |
| `caasi groot` | 06 | ecosystem delegation | opt-in | needs the upstream tool + a GPU |
| `caasi groot evaluate` | 06 | ecosystem delegation | opt-in | needs the upstream tool + a GPU |
| `caasi groot run` | 06 | ecosystem delegation | opt-in | needs the upstream tool + a GPU |
| `caasi groot setup` | 06 | ecosystem delegation | opt-in | needs the upstream tool + a GPU |
| `caasi groot status` | 06 | ecosystem delegation | opt-in | needs the upstream tool + a GPU |
| `caasi groot train` | 06 | ecosystem delegation | opt-in | needs the upstream tool + a GPU |
| `caasi help` | cookbook | read-only | CI |  |
| `caasi info` | cookbook | read-only | CI |  |
| `caasi init` | 01 | runnable | CI |  |
| `caasi isaac-ros` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi isaac-ros doctor` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi isaac-ros launch` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi isaac-ros list` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi isaac-ros status` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi lab` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi lab evaluate` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi lab play` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi lab run` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi lab status` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi logs` | 01 | runnable | CI |  |
| `caasi mapping` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi mapping inspect` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi mapping run` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi mapping status` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi monitor` | cookbook | read-only | CI |  |
| `caasi motion` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi motion benchmark` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi motion execute` | 06 | not executed | manual | PHYSICAL MOTION / bringup |
| `caasi motion plan` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi motion serve` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi motion status` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi moveit` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi moveit doctor` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi moveit launch` | 06 | not executed | manual | PHYSICAL MOTION / bringup |
| `caasi moveit plan` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi moveit status` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi moveit test` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi native` | cookbook | read-only | CI |  |
| `caasi native lab` | cookbook | read-only | CI |  |
| `caasi native ros` | cookbook | read-only | CI |  |
| `caasi native run` | cookbook | read-only | CI |  |
| `caasi native sim` | cookbook | read-only | CI |  |
| `caasi nav` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi nav doctor` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi nav inspect` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi nav launch` | 06 | not executed | manual | PHYSICAL MOTION / bringup |
| `caasi nav status` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi nav test` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi nitros` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi nitros doctor` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi nitros status` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi node` | 02 | runnable | CI | works with local alone |
| `caasi node check` | 02 | runnable | CI | works with local alone |
| `caasi node deps` | 02 | runnable | CI | read-only; works with local alone |
| `caasi node discover` | 02 | runnable | CI/opt-in | bounded scan of configured subnets |
| `caasi node enroll` | 02 | runnable | manual | learns trust; explicit action |
| `caasi node identity` | 02 | runnable | CI | local record; `--no-verify` avoids network |
| `caasi node reenroll` | 02 | runnable | manual | replaces trusted keys; needs the flag |
| `caasi node refresh` | 02 | runnable | CI/opt-in | verify + optional discovery |
| `caasi node inspect` | 02 | runnable | CI | works with local alone |
| `caasi node list` | 02 | runnable | CI | works with local alone |
| `caasi node occupancy` | 02 | runnable | CI | works with local alone |
| `caasi node runtime` | 02 | runnable | CI | works with local alone |
| `caasi node select` | 02 | runnable | CI | works with local alone |
| `caasi perception` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi perception camera` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi perception detect` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi perception inspect` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi perception pose` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi perception segment` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi perception status` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi physics` | cookbook | read-only | CI |  |
| `caasi physics benchmark` | cookbook | read-only | CI |  |
| `caasi physics list` | cookbook | read-only | CI |  |
| `caasi physics run` | cookbook | read-only | CI |  |
| `caasi physics status` | cookbook | read-only | CI |  |
| `caasi pipeline` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi pipeline inspect` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi project` | 01 | runnable | CI |  |
| `caasi project add` | 01 | runnable | CI |  |
| `caasi project add-file` | 01 | runnable | CI |  |
| `caasi project config` | 01 | runnable | CI |  |
| `caasi project config get` | 01 | runnable | CI |  |
| `caasi project config set` | 01 | runnable | CI |  |
| `caasi project config show` | 01 | runnable | CI |  |
| `caasi project info` | 01 | runnable | CI |  |
| `caasi project init` | 01 | runnable | CI |  |
| `caasi project inspect` | 01 | runnable | CI |  |
| `caasi project list` | 01 | runnable | CI |  |
| `caasi project remove` | 01 | not executed | manual | DESTRUCTIVE, no --dry-run |
| `caasi project robot` | 01 | runnable | CI |  |
| `caasi project robot create` | 01 | runnable | CI |  |
| `caasi project robot import` | 01 | runnable | CI |  |
| `caasi project robot info` | 01 | runnable | CI |  |
| `caasi project robot inspect` | 01 | runnable | CI |  |
| `caasi project robot list` | 01 | runnable | CI |  |
| `caasi project robot validate` | 01 | runnable | CI |  |
| `caasi project scene` | 01 | runnable | CI |  |
| `caasi project scene capture` | 01 | runnable | CI |  |
| `caasi project scene create` | 01 | runnable | CI |  |
| `caasi project scene import` | 01 | runnable | CI |  |
| `caasi project scene inspect` | 01 | runnable | CI |  |
| `caasi project scene list` | 01 | runnable | CI |  |
| `caasi project scene reconstruct` | 01 | runnable | CI |  |
| `caasi project scene validate` | 01 | runnable | CI |  |
| `caasi project task` | 01 | runnable | CI |  |
| `caasi project task create` | 01 | runnable | CI |  |
| `caasi project task inspect` | 01 | runnable | CI |  |
| `caasi project task list` | 01 | runnable | CI |  |
| `caasi project validate` | 01 | runnable | CI |  |
| `caasi remote` | 07 | runnable | CI/opt-in | chain; SSH target optional |
| `caasi remote connect` | 07 | runnable | CI/opt-in | chain; SSH target optional |
| `caasi remote list` | 07 | runnable | CI/opt-in | chain; SSH target optional |
| `caasi remote run` | 07 | runnable | CI/opt-in | chain; SSH target optional |
| `caasi replay` | 05 | runnable | manual | needs a display/bag |
| `caasi ros` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi ros doctor` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi ros graph` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi ros launch` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi ros list` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi ros node` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi ros service` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi ros service call` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi ros service info` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi ros service list` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi ros status` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi ros topic` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi ros2` | 03 | ROS 2 | CI | same tree as `caasi ros` |
| `caasi ros2 doctor` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi ros2 graph` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi ros2 launch` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi ros2 list` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi ros2 node` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi ros2 service` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi ros2 service call` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi ros2 service info` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi ros2 service list` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi ros2 status` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi ros2 topic` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi rosbag` | 03 | ROS 2 | CI | canonical demo_nodes_py |
| `caasi rqt` | 05 | GUI | manual | needs a display |
| `caasi run` | 01 | runnable | CI |  |
| `caasi run artifacts` | 01 | runnable | CI |  |
| `caasi run attach` | 01 | documented | manual | needs a TTY |
| `caasi run delete` | 01 | not executed | manual | DESTRUCTIVE, no --dry-run |
| `caasi run inspect` | 01 | runnable | CI |  |
| `caasi run list` | 01 | runnable | CI |  |
| `caasi run logs` | 01 | runnable | CI |  |
| `caasi run pause` | 01 | runnable | CI |  |
| `caasi run restart` | 01 | runnable | CI |  |
| `caasi run resume` | 01 | runnable | CI |  |
| `caasi run start` | 01 | runnable | CI |  |
| `caasi run status` | 01 | runnable | CI |  |
| `caasi run stop` | 01 | runnable | CI |  |
| `caasi runtime` | 07 | runnable | CI/opt-in | chain; SSH target optional |
| `caasi runtime enable` | 07 | runnable | CI/opt-in | chain; SSH target optional |
| `caasi runtime install` | 07 | runnable | CI/opt-in | chain; SSH target optional |
| `caasi runtime rollback` | 07 | runnable | CI/opt-in | chain; SSH target optional |
| `caasi runtime start` | 07 | runnable | CI/opt-in | chain; SSH target optional |
| `caasi runtime status` | 07 | runnable | CI/opt-in | chain; SSH target optional |
| `caasi runtime update` | 07 | runnable | CI/opt-in | chain; SSH target optional |
| `caasi runtime verify` | 07 | runnable | CI/opt-in | chain; SSH target optional |
| `caasi rviz2` | 05 | GUI | manual | needs a display |
| `caasi sensor` | cookbook | read-only | CI |  |
| `caasi sensor inspect` | cookbook | read-only | CI |  |
| `caasi sensor list` | cookbook | read-only | CI |  |
| `caasi sensor test` | cookbook | read-only | CI |  |
| `caasi setup` | cookbook | not executed | manual | modifies the environment |
| `caasi exec` | cookbook | read-only | CI | runs on a target through `caasi exec --target` |
| `caasi shell` | cookbook | read-only | CI |  |
| `caasi sim` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi sim check` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi sim extensions` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi sim headless` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi sim run` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi slam` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi slam benchmark` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi slam launch` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi slam status` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi slam test` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi start` | 01 | runnable | CI |  |
| `caasi system` | cookbook | read-only | CI |  |
| `caasi system doctor` | cookbook | read-only | CI |  |
| `caasi system memory` | cookbook | read-only | CI |  |
| `caasi system processes` | cookbook | read-only | CI |  |
| `caasi system status` | cookbook | read-only | CI |  |
| `caasi target` | 02 | runnable | CI | works with local alone |
| `caasi target check` | 02 | runnable | CI | works with local alone |
| `caasi target deps` | 02 | runnable | CI | read-only; works with local alone |
| `caasi target discover` | 02 | runnable | CI/opt-in | bounded scan of configured subnets |
| `caasi target enroll` | 02 | runnable | manual | learns trust; explicit action |
| `caasi target identity` | 02 | runnable | CI | local record; `--no-verify` avoids network |
| `caasi target reenroll` | 02 | runnable | manual | replaces trusted keys; needs the flag |
| `caasi target refresh` | 02 | runnable | CI/opt-in | verify + optional discovery |
| `caasi target inspect` | 02 | runnable | CI | works with local alone |
| `caasi target list` | 02 | runnable | CI | works with local alone |
| `caasi target occupancy` | 02 | runnable | CI | works with local alone |
| `caasi target runtime` | 02 | runnable | CI | works with local alone |
| `caasi target select` | 02 | runnable | CI | works with local alone |
| `caasi teleop` | cookbook | read-only | CI |  |
| `caasi teleop record` | cookbook | not executed | manual | PHYSICAL MOTION |
| `caasi teleop replay` | 05 | runnable | manual | needs a display/bag |
| `caasi teleop start` | cookbook | not executed | manual | PHYSICAL MOTION |
| `caasi teleop stop` | cookbook | read-only | CI |  |
| `caasi test` | cookbook | read-only | CI |  |
| `caasi tools` | cookbook | read-only | CI |  |
| `caasi tools list` | cookbook | read-only | CI |  |
| `caasi tools run` | cookbook | read-only | CI |  |
| `caasi train` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi version` | cookbook | read-only | CI |  |
| `caasi view` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi view attach` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi view foxglove` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi view open3d` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi view run` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi view rviz` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi vision` | cookbook | read-only | CI |  |
| `caasi vision inspect` | cookbook | read-only | CI |  |
| `caasi vision status` | cookbook | read-only | CI |  |
| `caasi vision test` | cookbook | read-only | CI |  |
| `caasi warp` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi warp benchmark` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi warp status` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi warp test` | 06 | Isaac/Isaac ROS | opt-in | needs GPU + Isaac |
| `caasi workload` | 01 | runnable | CI |  |
| `caasi workload inspect` | 01 | runnable | CI |  |
| `caasi workload list` | 01 | runnable | CI |  |
| `caasi workload run` | 07 | runnable | CI/opt-in | chain; SSH target optional |

