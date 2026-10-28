# Getting started

From a robot that has never run this software and a computer that has never heard of caasi, to a
robot doing something. Follow it in order the first time.

Two machines are involved:

* **the robot** — Ubuntu 24.04 with ROS 2 on it, reachable over the network,
* **your computer** — where you type commands. Linux or macOS; Windows works through WSL.

## 1. Prepare the robot

You need a shell on the robot (`ssh <user>@<robot-ip>`). Everything in this step runs there.

### 1a. Enable SSH, if it is not already

```bash
sudo apt update && sudo apt install -y openssh-server
sudo systemctl enable --now ssh
```

### 1b. Install ROS 2 and the packages this project needs

```bash
# ROS 2 Jazzy (Ubuntu 24.04)
sudo apt install -y software-properties-common
sudo add-apt-repository -y universe
sudo apt install -y ros-jazzy-desktop

# the parts of the system swjtumover uses
sudo apt install -y \
  ros-jazzy-navigation2 ros-jazzy-nav2-bringup ros-jazzy-slam-toolbox \
  ros-jazzy-realsense2-camera ros-jazzy-cv-bridge \
  python3-opencv python3-pynput python3-colcon-common-extensions

# so that a new shell knows about ROS 2
echo 'source /opt/ros/jazzy/setup.bash' >> ~/.bashrc
```

The robot's earlier ROS 1 installation used scripts named `1.ros_install.sh`,
`2.realsense_install.sh`, `3.install.sh` and `4.make.sh` for the same purpose: install ROS, the
camera driver, the Python extras, and then build the workspace. The commands above are the ROS 2
equivalent; caasi checks the result for you in step 3.

### 1c. Check that the camera is usable

```bash
sudo usermod -aG video "$USER"      # then log out and back in
```

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

The project lives at <https://github.com/7a6172/caasi/> — its README covers installation options in
more detail, and the issue tracker is where to ask about caasi itself.

## 3. Register the robot with caasi

A machine that caasi may control is called a **target**. Register it once:

```bash
caasi node enroll swjtumover-05 --host 10.212.19.94 --user swjtumover
```

`swjtumover-05` is the name you will use from now on; `--host` is where the robot answers today. On
first contact caasi records the robot's SSH host keys and hardware identity, and it refuses to talk to
a machine whose keys do not match that record later.

Name targets after the machine (`swjtumover-05`, `swjtumover-10`). The software keeps the name
`swjtumover` everywhere, so nothing you type afterwards depends on the robot's number.

Verify it:

```bash
caasi node list                        # your target appears
caasi node identity swjtumover-05      # enrolled keys and hardware, endpoint verified
caasi node check swjtumover-05         # reachable? environment sane?
```

If the robot's address changes, tell caasi rather than re-enrolling:
`caasi node refresh swjtumover-05`.

## 4. Check the robot has what the project needs

```bash
cd <this project>                       # the directory holding caasi.yaml
caasi target deps swjtumover-05 --for bringup
```

It reads the requirements declared in `caasi.yaml` and checks each one **on the robot**, telling you
what is installed, what is missing, and what to install. Example:

```
17 installed, 0 missing, 0 incompatible, 0 optional-absent, 0 unknown
```

Anything missing is a `sudo apt install …` away, and the table names the package.

## 5. Put the software on the robot and build it

```bash
caasi deploy swjtumover-05                 # copy the project to ~/caasi/robots/swjtumover
caasi build  --target swjtumover-05        # compile it there
```

`caasi deploy --status` shows what is deployed and whether it verified. Both commands can be re-run
at any time; only what changed is transferred and rebuilt.

## 6. Run something

```bash
caasi run start experiments/bringup.yaml -t swjtumover-05
```

That starts the robot's drivers. It answers with a run name:

```
Run 20261029-023042-swjtumover-bringup started in background on target 'swjtumover-05'.
  Follow it with: caasi logs 20261029-023042-swjtumover-bringup -f
```

Watch it, then stop it:

```bash
caasi logs 20261029-023042-swjtumover-bringup -f     # live output, Ctrl+C only stops watching
caasi run status 20261029-023042-swjtumover-bringup  # running / stopped / failed
caasi run stop   20261029-023042-swjtumover-bringup  # actually stop it
```

**Ctrl+C when following logs does not stop the task** — use `caasi run stop` for that.

## 7. Confirm it works

With the bringup running, from your computer:

```bash
caasi exec --target swjtumover-05 -- bash -c \
  'source /opt/ros/jazzy/setup.bash; source ~/caasi/robots/swjtumover/install/setup.bash; ros2 topic hz /scan'
```

You should see about 14 readings per second. Then check the wheels' odometry:

```bash
caasi exec --target swjtumover-05 -- bash -c \
  'source /opt/ros/jazzy/setup.bash; source ~/caasi/robots/swjtumover/install/setup.bash; ros2 topic hz /odom'
```

About 50 per second. (Typing that prefix repeatedly is tedious — see the shortcut at the end of
[caasi in depth](caasi.md).)

Stop the bringup when you are done:

```bash
caasi run stop 20261029-023042-swjtumover-bringup
```

## 8. Where next

* **[Commands](commands.md)** — drive it, map the space, navigate, run the mission. Each task has a
  local form and a remote form and a way to check it.
* **[caasi in depth](caasi.md)** — everything caasi can do while you develop.
* **[Troubleshooting](troubleshooting.md)** — when something misbehaves.
* **[Hardware and safety](hardware.md)** — before driving on the floor.
