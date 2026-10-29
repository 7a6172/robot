# caasi in depth

This chapter follows the way you actually use caasi: first contact with a robot, getting the code
onto it, starting a task, watching it, and what to do when it misbehaves. Each command is shown with
its arguments and a real example, so you can adapt rather than memorise.

It covers what this robot needs; caasi is a general tool with more to it. Its home is
<https://github.com/7a6172/caasi/>, and every command answers `--help` with its own details.

## First contact

You have the robot's address and an account on it. Register it once:

```bash
caasi node enroll swjtumover05 --host 10.212.19.94 --user swjtumover
```

| argument | meaning |
| --- | --- |
| `swjtumover05` | the name you will use afterwards. It is the target's identity |
| `--host` | where the robot answers *today*; it may change later |
| `--user` | the account caasi logs in as |
| `--port` | SSH port, default 22 |
| `--expect-fingerprint` | require a specific host-key fingerprint, if you were given one out of band |

On that first contact caasi records the robot's SSH host keys and some hardware facts. From then on
it refuses a machine whose keys do not match — so a different robot at a recycled address cannot
impersonate yours.

Confirm what it recorded, and that the address still points at the same machine:

```bash
caasi node identity swjtumover05
```

```
name:         swjtumover05
machine_id:   2c7c442a1da846c6b70f5a2d7712d7db   (from /etc/machine-id)
cpu_model:    Intel(R) N150
endpoint:     10.212.19.94:22, verified
```

If the robot moved to a new address, do not re-enrol — follow it:

```bash
caasi node refresh swjtumover05
```

Then see whether the machine is ready for this project at all:

```bash
caasi node check swjtumover05          # reachable, environment sane
caasi node inspect swjtumover05        # what hardware and software it has
caasi target deps swjtumover05 --for bringup
```

`--for` picks the part of the project you are asking about (`bringup`, `build`, `project`, `sim`).
The last command prints a table of the requirements declared in `caasi.yaml` and whether each one is
present **on the robot**:

```
17 installed, 0 missing, 0 incompatible, 0 optional-absent, 0 unknown
```

Anything missing names the package to install.

## Getting the code onto the robot

```bash
caasi deploy swjtumover05
```

The first deploy copies the whole project to `~/caasi/robots/swjtumover`; later ones send only what
changed, which is why it is cheap to run after every edit.

| option | when you want it |
| --- | --- |
| `--status` | show what is currently deployed, without deploying |
| `--dry-run` | preview what would be transferred |
| `--dest <path>` | deploy somewhere else, once |
| `--force` | deploy despite compatibility warnings from the preflight |
| `--list` | the deployment records caasi keeps for this project |

Then compile it there:

```bash
caasi build --target swjtumover05
```

| option | when you want it |
| --- | --- |
| `-p <package>` | build one package, e.g. `-p swjtumover_bringup` |
| `--clean` | discard `build/`, `install/` and `log/` first |
| `-j <n>` | limit parallel workers on a small machine |
| `--continue-on-error` | build the rest even if one package fails |

A build is recorded, so a run can tell you which build it used.

## Starting a task

Every task is one file in `experiments/`. You do not need to remember commands; you point at a file:

```bash
caasi run start experiments/bringup.yaml -t swjtumover05
```

| argument | meaning |
| --- | --- |
| `experiments/bringup.yaml` | which task |
| `-t, --target` | which robot |
| `--name` | give the run your own name instead of the experiment's |
| `--dry-run` | print the command it would run, and start nothing |
| `--json` | machine-readable output, for scripting |

It answers with the run's name, which is what you use from then on:

```
Run 20261029-023042-swjtumover-bringup started in background on target 'swjtumover05'.
  Follow it with: caasi logs 20261029-023042-swjtumover-bringup -f
```

`experiments/` covers bringup, mapping, navigation, the mission, the line follower, the obstacle
guard, teleoperation, the camera, rviz, and starting/stopping the mission. [Commands](commands.md)
maps each task to its file.

## Watching it

```bash
caasi logs 20261029-023042-swjtumover-bringup -f
```

`-f` follows until the task ends; **Ctrl+C stops following, not the task**. Filters that save time:

| option | use |
| --- | --- |
| `-n 50` | only the last 50 lines, instead of following |
| `--stream stderr` | just what went to stderr |
| `--errors` | only lines that look like errors |
| `--component <name>` | only lines tagged with one component |

Anywhere a run name is expected you can also use a shorter form: a unique prefix, or `latest`:

```bash
caasi logs latest -n 20
caasi run status latest
```

For the state rather than the output:

```bash
caasi run status 20261029-023042-swjtumover-bringup
```

which reports whether it is running, stopped or failed, **and which build and deployment it used** —
the fastest way to answer "is the robot running the code I think it is".

`caasi run attach <run>` joins the live output and detaches with Ctrl+C without stopping anything.
`caasi run list` shows recent runs; `caasi run list -n 5 -t swjtumover05` narrows to one robot.

## When something is wrong

Stop the task:

```bash
caasi run stop 20261029-023042-swjtumover-bringup
caasi run stop latest
```

`caasi run restart <run>` starts the same command again as a fresh run, which is quicker than
retyping the experiment path. If several things are running and you want the robot quiet:

```bash
caasi run list                          # what is running
caasi node occupancy                    # what caasi sees running on each target
```

`caasi run artifacts <run>` lists files a task produced, and `caasi run delete <run>` forgets a
finished run without touching the robot.

## Looking at the robot without a session

Two commands cover it. `caasi ros2` answers questions *about the robot's ROS 2 system*, and
`caasi exec` runs anything else there.

```bash
caasi ros2 list topics                 # every topic the robot publishes
caasi ros2 list nodes                  # every node running on it
caasi ros2 topic /scan                 # one topic: type, publishers, subscribers
caasi ros2 node /motor_node            # one node and what it is connected to
caasi ros2 graph                       # the whole picture, as text
caasi ros2 status                      # distro, install path, RMW, topic count
caasi ros2 service list                # services available on the robot
caasi ros2 service call /line_then_home/start std_srvs/srv/Trigger "{}"
caasi ros2 doctor                      # ROS 2's own health check, run there
```

Every one of them takes `--target, -t <name>`, and omits it when you have run
`caasi choose target <name>`. They run *on* the robot, so no local ROS 2 installation, no `ROS_DOMAIN_ID`
matching and no DDS across the network is involved.

`caasi ros` is the same command under its older name; both spellings work.

For a single message rather than a summary, ask for exactly one:

```bash
caasi ros2 topic /motor_state/left --echo --once
caasi ros2 topic /cmd_vel --echo --once
```

An unbounded stream is a *run*, not a query, so caasi stops short of one here. For a rate, or for
anything else the ROS 2 tools do:

```bash
caasi exec --ros -- ros2 topic hz /scan
caasi exec --ros -- ros2 bag record -o /tmp/run1 /scan /odom
caasi exec --ros -- bash -c 'ros2 param list /motor_node'
```

| option | meaning |
| --- | --- |
| `--target, -t` | which robot; unnecessary once chosen |
| `--ros` | source the robot's ROS 2 setup first |
| `--overlay <path>` | also source this project's workspace, when a command needs the project's own packages |
| `--cwd <path>` | run the command in a given directory |
| `--env KEY=VALUE, -e` | set an environment variable, repeatable |
| `--timeout <seconds>` | give up after this long (default 60) |
| `--detach, -d` | run in the background as a managed run; pair with `--name` |

`--ros` matters for a reason worth knowing: a non-interactive SSH session does not read `~/.bashrc`, so
`ros2` is not on the path unless caasi puts it there. That is why `caasi exec -- ros2 …` can fail while
`caasi exec --ros -- ros2 …` works, and why `caasi ros2 …` needs no such care.

## Tools you will reach for eventually

| command | what it tells you |
| --- | --- |
| `caasi doctor` | whether the robotics environment here is in order |
| `caasi info` | caasi's version, Python, and the toolchains it can see |
| `caasi system` | operating system, CPU, memory, processes |
| `caasi monitor` | CPU, memory and GPU while something runs |
| `caasi sensor` | which sensors and SDKs are visible |
| `caasi vision` | the computer-vision stack, e.g. whether OpenCV is usable |
| `caasi audit` | an account of the project and its reproducibility |
| `caasi check` | whether this project can run on this machine |
| `caasi view rviz` | open rviz for a run |
| `caasi view foxglove` | the same data in Foxglove Studio |
| `caasi teleop` | drive a robot, record demonstrations, replay bags |
| `caasi replay` | replay a recorded run without re-running it |
| `caasi ros2 list`, `caasi ros2 graph` | the ROS 2 graph, on this machine or on a chosen robot |

`caasi ros2` runs where you point it: with no target it queries the machine you are sitting at, and
with `-t` (or a chosen target) it queries the robot.

## A whole session, end to end

The remote form, with the machine and robot chosen so neither is repeated:

```bash
caasi choose target swjtumover05                     # from here on, "the robot"
caasi choose robot swjtumover                        # and the software on it
cd <project>
caasi node check swjtumover05                        # is the robot there
caasi target deps swjtumover05 --for bringup         # does it have what we need
caasi deploy                                         # copy the code
caasi build                                          # compile it there
caasi run start experiments/bringup.yaml             # start the drivers
caasi logs -f                                        # watch until satisfied
caasi ros2 topic /odom                               # is odometry arriving
caasi exec --ros -- ros2 topic hz /odom              # and at what rate
caasi run stop latest                                # stop it
```

The local form is the same page with the target set to `local`, or with `caasi exec -t local` for the
one-off checks; the robot's own terminal needs none of it.

## What lives where

| what | where |
| --- | --- |
| the project on the robot | `~/caasi/robots/swjtumover` |
| its deployment record | `~/caasi/robots/swjtumover/.caasi-deployment.json` |
| per-run output on the robot | `<project>/.caasi/runs/<run>/stdout.log`, `stderr.log`, `exit_code` |
| your record of each run | `~/.caasi/runs/<run>/` |
| registered targets, and the chosen one | `~/.config/caasi/config.yaml` |
| known host keys | `~/.caasi/identity/` |
