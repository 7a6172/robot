# Getting started

From a robot that has never run this software and a computer that has never heard of caasi, to a
robot doing something. Follow it in order the first time.

Two machines are involved:

* **the robot** — Ubuntu 24.04, reachable over the network,
* **your computer** — where you type commands. Linux or macOS; Windows works through WSL.

Nothing here assumes you have used caasi before, or ROS 2. Where a step has a local form (run on the
robot itself) and a remote form (run from your computer), both are shown; you only need one.

## 1. Let your computer reach the robot

On the robot, over a keyboard and screen or an existing session:

```bash
sudo apt update && sudo apt install -y openssh-server
sudo systemctl enable --now ssh
```

| command | what it does |
| --- | --- |
| `apt install openssh-server` | installs the SSH server |
| `systemctl enable --now ssh` | starts it now, and again after every reboot |

Then, from your computer, confirm you can log in:

```bash
ssh swjtumover@10.212.19.94       # your user and address
```

Everything else can be done from your computer. You will not need the robot's keyboard again.

## 2. Install caasi on your computer

```bash
pipx install caasi        # recommended: keeps caasi in its own environment
```

If `pipx` is not installed: `sudo apt install pipx` on Ubuntu, `brew install pipx` on macOS.
Alternatives, if you prefer:

```bash
pip install caasi                                            # into the active Python environment
python3 -m venv ~/.venvs/caasi && ~/.venvs/caasi/bin/pip install caasi   # a dedicated environment
```

Check it:

```bash
caasi version
caasi info          # caasi, Python, and the toolchains it can see
```

caasi lives at <https://github.com/7a6172/caasi/>; its README covers installation in more detail.

## 3. Register the robot with caasi

A machine caasi may control is called a **target**. Register it once:

```bash
caasi node enroll swjtumover05 --host 10.212.19.94 --user swjtumover
```

| argument | meaning |
| --- | --- |
| `swjtumover05` | the name you use from now on. It identifies the machine |
| `--host` | where the robot answers today; it may change later |
| `--user` | the account caasi logs in as |

On first contact caasi records the robot's SSH host keys and hardware identity, and later refuses to
talk to a machine whose keys do not match that record.

Name targets after the machine (`swjtumover05`, `swjtumover06`, …). The software keeps the name
`swjtumover` everywhere, so nothing you type afterwards depends on the robot's number.

Verify it:

```bash
caasi node list                        # your target appears
caasi node identity swjtumover05       # enrolled keys and hardware, endpoint verified
caasi node check swjtumover05          # reachable? environment sane?
```

If the robot's address changes, tell caasi rather than re-enrolling: `caasi node refresh swjtumover05`.

## 4. Put the code on the robot

From the project directory — the one holding `caasi.yaml`:

```bash
caasi deploy swjtumover05
```

It copies the project to `~/caasi/robots/swjtumover` on the robot and verifies the copy. This needs
nothing but SSH, so it works on a robot with no ROS 2 at all — which is exactly what step 5 then fixes.

`caasi deploy --status` shows what is deployed and whether it verified. Re-run `caasi deploy` at any
time; only what changed is transferred.

## 5. Prepare the robot once

This is the step the ROS 1 setup scripts (`1.ros_install.sh`, `2.realsense_install.sh`,
`3.install.sh`, `4.make.sh`) used to do by hand. It is now one caasi command, it is re-runnable, and
it prints every command before running it.

```bash
caasi run start experiments/provision.yaml -t swjtumover05
caasi logs -f                                  # watch it work
```

| stage | what it installs or changes |
| --- | --- |
| `ros` | ROS 2 Jazzy and `colcon`, if they are not already there |
| `packages` | the ROS 2 packages this project uses: navigation, mapping, camera, vision, teleop |
| `camera` | the `video` group for the camera, and a note about Intel's `librealsense` repository |
| `shell` | two guarded `source` lines in `~/.bashrc`, so `ros2` works in any new terminal |
| `build` | compiles the project |

Every stage is idempotent: running it a second time changes nothing. The shell lines it adds look
like this, and are why `ros2 topic list` works in a fresh terminal afterwards:

```bash
[ -f /opt/ros/jazzy/setup.bash ] && source /opt/ros/jazzy/setup.bash
[ -f ~/caasi/robots/swjtumover/install/setup.bash ] && source ~/caasi/robots/swjtumover/install/setup.bash
```

**Several robots on one network.** Give each its own ROS domain, so two robots do not see each
other's topics:

```bash
caasi exec -t swjtumover05 -- \
  bash ~/caasi/robots/swjtumover/scripts/provision.sh --apply --domain 5
```

**Local form.** On the robot itself, the same script:

```bash
cd ~/caasi/robots/swjtumover
scripts/provision.sh                        # show what would be installed, change nothing
scripts/provision.sh --apply                # do it
scripts/provision.sh --apply --stage ros    # one stage only
```

If the robot cannot reach the package servers, install ROS 2 by hand and skip the `ros` and
`packages` stages — the list is in the [ROS 2 chapter](ros2.md).

## 6. Check the robot has what the project needs

```bash
caasi target deps swjtumover05 --for bringup
```

It reads the requirements declared in `caasi.yaml` and checks each one **on the robot**:

```
17 installed, 0 missing, 0 incompatible, 0 optional-absent, 0 unknown
```

`--for` selects the part of the project you are asking about (`bringup`, `build`, `project`, `sim`).
Anything missing is named, with the package to install.

## 7. Build

```bash
caasi build --target swjtumover05
```

This runs `colcon build` on the robot and records which build each run used. Step 5 already built it,
so this is normally instant — run it again after you change code.

## 8. Run something

```bash
caasi run start experiments/bringup.yaml -t swjtumover05
```

That starts the robot's drivers. It answers with a run name:

```
Run 20261029-023042-swjtumover-bringup started in background on target 'swjtumover05'.
  Follow it with: caasi logs 20261029-023042-swjtumover-bringup -f
```

Watch it, then stop it:

```bash
caasi logs -f                                        # the newest run; Ctrl+C only stops watching
caasi run status 20261029-023042-swjtumover-bringup  # running / stopped / failed
caasi run stop   20261029-023042-swjtumover-bringup  # actually stop it
```

**Ctrl+C while following logs does not stop the task.** Use `caasi run stop` for that.

### Tired of typing `-t`?

Set the robot once, and the rest of the manual gets shorter:

```bash
caasi choose target swjtumover05
caasi run start experiments/bringup.yaml      # the same command, without -t
caasi ros2 list topics                        # the robot's topics
```

`caasi choose` with no arguments shows what is set and where each answer came from. See
[Concepts](concepts.md#which-robot-am-i-talking-to) for what a project and a target are, and for
`--session`, which scopes a choice to one terminal.

The rest of this page uses the short form, assuming you set the target once.

## 9. Confirm it works

```bash
caasi ros2 list topics
caasi ros2 topic /scan
```

The first lists what the robot publishes; the second prints one topic's type and how many nodes use
it. You should see `/scan`, `/odom`, `/motor_state/*` and the rest. For rates and raw messages:

```bash
caasi exec --ros -- ros2 topic hz /scan         # about 14 per second
caasi exec --ros -- ros2 topic echo /odom --once
caasi exec --ros -- ros2 topic hz /odom         # about 50 per second
```

`--ros` makes caasi source the robot's ROS 2 setup for that one command, which is needed because a
non-interactive SSH session does not read `~/.bashrc`.

Stop the bringup when you are done:

```bash
caasi run stop latest
```

## 10. Where next

* **[Commands](commands.md)** — drive it, map the space, navigate, run the mission. Each task has a
  local form, a remote form, and a way to check it.
* **[Concepts](concepts.md)** — the words, and how project, target and deployment fit together.
* **[caasi in depth](caasi.md)** — everything caasi can do while you develop.
* **[Developing](developing.md)** — write your own node or task, and run it on the robot.
* **[Troubleshooting](troubleshooting.md)** — when something misbehaves.
* **[Hardware and safety](hardware.md)** — before driving on the floor.
