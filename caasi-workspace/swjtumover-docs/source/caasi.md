# caasi in depth

This chapter follows the way you actually use caasi: first contact with a robot, getting the code
onto it, starting a task, watching it, and what to do when it misbehaves. Each command is shown with
its arguments and a real example, so you can adapt rather than memorise.

It covers what this robot needs; caasi is a general tool with more to it. Its home is
<https://github.com/7a6172/caasi/>, and every command answers `--help` with its own details.

## First contact

You have the robot's address and an account on it. Register it once:

```bash
caasi node enroll swjtumover-05 --host 10.212.19.94 --user swjtumover
```

| argument | meaning |
| --- | --- |
| `swjtumover-05` | the name you will use afterwards. It is the target's identity |
| `--host` | where the robot answers *today*; it may change later |
| `--user` | the account caasi logs in as |
| `--port` | SSH port, default 22 |
| `--expect-fingerprint` | require a specific host-key fingerprint, if you were given one out of band |

On that first contact caasi records the robot's SSH host keys and some hardware facts. From then on
it refuses a machine whose keys do not match — so a different robot at a recycled address cannot
impersonate yours.

Confirm what it recorded, and that the address still points at the same machine:

```bash
caasi node identity swjtumover-05
```

```
name:         swjtumover-05
machine_id:   2c7c442a1da846c6b70f5a2d7712d7db   (from /etc/machine-id)
cpu_model:    Intel(R) N150
endpoint:     10.212.19.94:22, verified
```

If the robot moved to a new address, do not re-enrol — follow it:

```bash
caasi node refresh swjtumover-05
```

Then see whether the machine is ready for this project at all:

```bash
caasi node check swjtumover-05          # reachable, environment sane
caasi node inspect swjtumover-05        # what hardware and software it has
caasi target deps swjtumover-05 --for bringup
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
caasi deploy swjtumover-05
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
caasi build --target swjtumover-05
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
caasi run start experiments/bringup.yaml -t swjtumover-05
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
Run 20261029-023042-swjtumover-bringup started in background on target 'swjtumover-05'.
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
`caasi run list` shows recent runs; `caasi run list -n 5 -t swjtumover-05` narrows to one robot.

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

`caasi exec` runs one command on the robot and prints the result:

```bash
caasi exec --target swjtumover-05 -- uptime
```

For anything ROS 2, let caasi prepare the environment instead of sourcing it yourself:

```bash
caasi exec --target swjtumover-05 \
  --ros --overlay '~/caasi/robots/swjtumover/install/setup.bash' \
  -- ros2 topic hz /scan
```

| option | meaning |
| --- | --- |
| `--target, -t` | which robot |
| `--ros` | source the robot's ROS 2 setup first |
| `--overlay <path>` | also source this project's workspace |
| `--cwd <path>` | run the command in a given directory |
| `--env KEY=VALUE, -e` | set an environment variable, repeatable |
| `--timeout <seconds>` | give up after this long (default 60) |
| `--detach, -d` | run in the background as a managed run; pair with `--name` |

Because that prefix is long, put a function in your `~/.bashrc`:

```bash
swj() { caasi exec --target swjtumover-05 --ros \
          --overlay '~/caasi/robots/swjtumover/install/setup.bash' -- bash -c "$*"; }
```

```bash
swj ros2 topic echo /motor_state/left --once
swj ros2 service call /line_then_home/start std_srvs/srv/Trigger "{}"
swj ros2 bag record -o /tmp/run1 /scan /odom
```

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
| `caasi ros list`, `caasi ros graph` | the ROS 2 graph on the machine you are sitting at |

`caasi ros` acts locally. On the robot, use `caasi exec --ros`.

## A whole session, end to end

```bash
cd <project>
caasi node check swjtumover-05                        # is the robot there
caasi target deps swjtumover-05 --for bringup         # does it have what we need
caasi deploy swjtumover-05                            # copy the code
caasi build --target swjtumover-05                    # compile
caasi run start experiments/bringup.yaml -t swjtumover-05
caasi logs latest -f                                  # watch until satisfied
caasi exec --target swjtumover-05 --ros \
  --overlay '~/caasi/robots/swjtumover/install/setup.bash' -- ros2 topic hz /odom
caasi run stop latest
```

## What lives where

| what | where |
| --- | --- |
| the project on the robot | `~/caasi/robots/swjtumover` |
| its deployment record | `~/caasi/robots/swjtumover/.caasi-deployment.json` |
| per-run output on the robot | `<project>/.caasi/runs/<run>/stdout.log`, `stderr.log`, `exit_code` |
| your record of each run | `~/.caasi/runs/<run>/` |
| registered targets | `~/.config/caasi/config.yaml` |
| known host keys | `~/.caasi/identity/` |
