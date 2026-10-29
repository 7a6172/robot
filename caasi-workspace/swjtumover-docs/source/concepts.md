# Concepts

Short definitions of everything the rest of the manual assumes. Skip what you already know.

## ROS 2 in ten lines

ROS 2 is the framework the robot's programs are built on. Programs are **nodes**; they talk to each
other over named channels.

| word | meaning |
| --- | --- |
| **node** | one program doing one job, e.g. `motor_node` talks to the motor board |
| **topic** | a named stream of messages, e.g. `/scan` carries LiDAR readings 14 times a second |
| **message** | the data on a topic: a LiDAR scan, an odometry pose, a velocity command |
| **service** | a request/response call, e.g. "start the mission" and its answer |
| **action** | a long-running request with progress, e.g. "navigate to this point" |
| **launch file** | a script that starts several nodes with the right settings |
| **parameter** | a named setting a node reads at start-up, e.g. wheel radius |
| **TF** | the tree of coordinate frames; it lets a LiDAR reading be placed in the map |
| **lifecycle** | a node that must be *activated* before it works (navigation and mapping nodes) |
| **bag** | a recording of topics, so you can replay exactly what happened |

Commands you will use:

```bash
ros2 node list                     # what is running
ros2 topic list                    # what channels exist
ros2 topic hz /scan                # how often a topic publishes
ros2 topic echo /odom --once       # print one message
ros2 service call <name> <type> "{}"   # call a service
ros2 launch swjtumover_bringup bringup.launch.py
```

Coming from ROS 1, the names simply gained `ros2`:

| ROS 1 | ROS 2 |
| --- | --- |
| `roslaunch pkg file.launch` | `ros2 launch pkg file.launch.py` |
| `rosrun pkg node` | `ros2 run pkg node` |
| `rostopic` / `rosservice` / `rosnode` / `rosbag` | `ros2 topic` / `ros2 service` / `ros2 node` / `ros2 bag` |
| `rosparam` | parameters are per node: `ros2 param get` |
| parameter server | no global server; settings live with each node |
| `tf_echo` (from `tf`) | `tf2_echo` (from `tf2_ros`) |

## caasi in ten lines

caasi is the tool that puts the software on a robot and runs it from your computer.

| word | meaning |
| --- | --- |
| **project** | this repository. caasi reads `caasi.yaml` to learn what it needs |
| **target** | a machine caasi can reach: the robot, or a workstation. You create one with `caasi node enroll` |
| **deployment** | a copy of the project on the target, under `~/caasi/robots/<project>` |
| **build** | running `colcon build` on the target, recorded so runs know which build they used |
| **run** | one task started through caasi, with a name, a log, and an exit code |
| **exec** | a one-off command on the target, for quick checks |
| **scope** (`--for bringup`) | which part of the project you are asking about when checking dependencies |

A run is the thing you watch: `caasi run status <run>`, `caasi logs <run> -f`, `caasi run stop <run>`.

## Which robot am I talking to?

Three different things are easy to confuse, because one machine carries two of their names.

| question | answer | example |
| --- | --- | --- |
| **Which machine?** | the **target** — a registered `user@host` caasi can reach, or `local` | `swjtumover05` |
| **Which robot?** | the **robot** — the shipped software that drives its hardware | `swjtumover` |
| **Whose work?** | the **project** — your own algorithm, task or homework, which *uses* that robot | `maze_run_1` |

caasi keeps the two apart on every machine it manages, so temporary work cannot damage the robot's own
code:

```
~/caasi/
├── robots/<robot>/        the shipped robot: its code and deployed environment. You do not edit this
├── projects/<project>/     your own work: algorithms, tasks, homework. It uses the robot's topics
├── workspaces/<name>/      a source checkout
├── data/                  run logs, datasets, recordings, results
└── artifacts/  cache/     build outputs, and scratch space that is safe to clear
```

So `swjtumover` (robot) is the program that talks to motors, LiDAR and camera; `maze_run_1` (project)
is your code that subscribes to `/scan` and publishes to `/cmd_vel`. Same robot, your files in your
own directory.

### Three machines, one tool

The same distinction applies to *where* things run. A laptop may have no GPU and no robot attached:

| role | what runs there | caasi target |
| --- | --- | --- |
| **your dev machine** | editing, small tests, nothing physical | `local` (reserved name) |
| **the robot** | the hardware: motors, sensors, navigation | `swjtumover05` |
| **a GPU server** | Isaac Sim / Isaac Lab simulation, training | e.g. `gpu-01` |

All three are just **targets** to caasi; the difference is what you run on them. A robot has no GPU, so
simulation goes to a GPU target — which may be your own machine if it has one, or a server elsewhere.

### Simulation and the GPU

`caasi sim`, `caasi lab` and `caasi train` run Isaac Sim / Isaac Lab, which needs a real GPU. They take
`--target` like everything else:

```bash
caasi lab run experiments/warehouse.yaml -t gpu-01
caasi lab train experiments/warehouse.yaml -t gpu-01
caasi sim run experiments/scene.yaml -t gpu-01
```

and, more usually, you name the GPU machine once:

```bash
caasi choose target gpu-01 --role gpu     # everything sim/lab/train now goes there
caasi choose                              # the "gpu work" row shows where that is
```

A role never follows the machine you happen to be on. If no `gpu` target has been chosen, the work runs
**on this computer** and says so — which is the right answer when your machine has the GPU, and an
honest failure when it does not:

```
Error: Backend 'lab' needs a registered isaaclab install. Register one with
'caasi config set tools.isaaclab...' or use backend 'python'.
```

That is caasi's whole point on this robot: the hardware work goes to the robot, the simulation goes to
whatever machine has the GPU, and neither has to be the laptop you are typing on.

### Name it once: `caasi choose`

Typing `-t swjtumover05` on every command, in every terminal, is the part caasi can hold for you:

```bash
caasi choose target swjtumover05     # which machine
caasi choose robot swjtumover        # which robot on it
caasi choose project maze_run_1      # whose work
caasi choose                         # what is set, and where each answer came from
```

A **name is enough**. caasi looks in the layout above, on the machine you are working on:

* a target is set → it searches **there**: `ssh swjtumover05 'test -f ~/caasi/robots/swjtumover/caasi.yaml'`
* no target is set → it says `no target set, defaulting to local machine`, and searches here
* nothing there → it names the places it looked:
  `No project called 'maze_run_1' on 'swjtumover05'. Looked in ~/caasi/projects/maze_run_1, ~/caasi/workspaces/maze_run_1.`

A path still works for anything outside that tree: `caasi choose project ~/work/hw1`.

Everything afterwards follows the choice:

```bash
caasi run start experiments/bringup.yaml    # on swjtumover05, no -t needed
caasi ros2 list topics                      # the robot's topics
caasi deploy                                # the chosen machine
caasi logs                                  # the most recent run
```

Rules worth knowing:

* **A flag always wins.** `caasi exec -t local -- uptime` acts on your own machine once, without
  changing the choice.
* **One terminal only.** `eval "$(caasi choose --session target local)"` scopes a choice to the shell
  you run it in; close that shell and the remembered default returns.
* **You are told which machine.** A command acting on a chosen target prints one dim line first, for
  example `target: swjtumover05 (from selection)`. Nothing chosen is also said out loud — silently
  acting on the wrong machine is the mistake a remembered default makes possible.
* **Forget it** with `caasi choose target --clear`, `caasi choose robot --clear` or
  `caasi choose project --clear`.

The choices live in `~/.config/caasi/config.yaml` under `defaults:`, so `caasi config show` always
prints exactly what will happen.

## Does `ros2` work in a new terminal?

Yes, once the robot has been provisioned — that is one command, described in
[Getting started](getting-started.md). It adds two guarded lines to the robot's `~/.bashrc`:

```bash
[ -f /opt/ros/jazzy/setup.bash ] && source /opt/ros/jazzy/setup.bash
[ -f ~/caasi/robots/swjtumover/install/setup.bash ] && source ~/caasi/robots/swjtumover/install/setup.bash
```

The guards mean a shell still opens when the workspace has not been built yet. With them in place you
open a terminal and type `ros2 topic list` directly, as you would have typed `rostopic list` in ROS 1.
You never need caasi to use ROS 2 — caasi is what saves you from doing it *remotely*, which ROS 2 on
its own does not do well.

## Words used in this manual

* **bringup** — starting the robot's basic drivers: motors, screen, LiDAR.
* **mapping** — driving around to build a map of the space.
* **navigation** — telling the robot to go to a point on that map.
* **mission** — the whole task: follow the line, stop, then navigate back to where it started.
* **odometry** — the robot's estimate of how far it has moved, from wheel rotation.
* **localisation** — working out where the robot is on the map.
* **costmap** — a grid navigation uses to know what is free, blocked and risky.
