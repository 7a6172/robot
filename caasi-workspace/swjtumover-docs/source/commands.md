# Commands

Every task, in the two places you might run it from:

* **Local** — on the robot itself. Both a plain ROS 2 command and a caasi run are given; they do the
  same thing, caasi adds a record.
* **Remote** — from another machine, through caasi. This is the normal way to operate a deployed
  robot.

`<target>` is the execution target you enrolled in caasi — `swjtumover05` for the robot. Run
`caasi choose target <target>` once and you can leave `-t` off everywhere; every command below works
either way. Each section also names the ROS 1 command it replaces, for comparison.

---

## 1. Bringup

Starts the LiDAR adapter, both state publishers, the motor driver and the screen driver.

**Local**

```bash
# ROS 2
ros2 launch swjtumover_bringup bringup.launch.py

# ROS 2 with rviz, or with the camera, or with a keyboard
ros2 launch swjtumover_bringup bringup.launch.py enable_visualization:=true
ros2 launch swjtumover_bringup bringup.launch.py enable_realsense:=true enable_teleop:=true

# caasi, on the robot
caasi run start experiments/bringup.yaml
```

**Remote**

```bash
caasi run start experiments/bringup.yaml -t <target>
caasi logs 20261029-023042-swjtumover-bringup -f      # follow the output
caasi run status 20261029-023042-swjtumover-bringup
caasi run stop   20261029-023042-swjtumover-bringup
```

**Check it worked**

```bash
ros2 topic hz /scan                        # ~14 Hz
ros2 topic hz /odom                        # ~50 Hz
ros2 topic echo /motor_state/left --once    # fault flags false, rpm ~0 at rest
```

ROS 1: `roslaunch swjtumover_bringup bringup.launch`

---

## 2. Teleoperation

Arrow keys drive and turn: 0.2 m/s and 0.4 rad/s, accelerating at 0.2 / 0.4 per second.

**Local**

```bash
# ROS 2 (a terminal on the robot's desktop)
scripts/run_teleop.sh

# caasi, on the robot
caasi run start experiments/teleop.yaml
```

**Remote**

Teleoperation needs the robot's display, so it is normally started as a run and driven while you
watch the screen through a remote desktop session (see [Remote access](fleet-and-display.md)):

```bash
caasi run start experiments/teleop.yaml -t <target>
caasi logs 20261022-101500-swjtumover-teleop -f
```

**Check it worked**

```bash
ros2 topic echo /cmd_vel     # linear.x reaches ±0.2 while a key is held, 0 when released
```

On a Wayland desktop the keyboard is only received while an X11 window has focus — click the rviz
window first. Without any display the node exits with code 3 and says why.

ROS 1: `rosrun swjtumover_bringup teleop_node.py`

---

## 3. Visualization

**Local**

```bash
# ROS 2
rviz2 -d "$(ros2 pkg prefix swjtumover_bringup)/share/swjtumover_bringup/config/bringup.rviz"

# caasi, on the robot
caasi run start experiments/rviz.yaml
```

**Remote**

```bash
# start rviz with the bringup in one go
caasi run start experiments/bringup_rviz.yaml -t <target>

# or rviz against a bringup that is already running
caasi run start experiments/rviz.yaml -t <target>
caasi logs <the rviz run> -f
```

**Check it worked:** the robot body, `/scan` and the camera image draw with only the bringup running.
The `/map` panel fills once something publishes a map; the two costmap panels need nav2 and are off by
default.

ROS 1: `rosrun rviz rviz -d $(rospack find swjtumover_bringup)/config/bringup.rviz`

---

## 4. Mapping

**Local**

```bash
# ROS 2
ros2 launch swjtumover_bringup slam.launch.py

# caasi, on the robot
caasi run start experiments/slam.yaml
```

**Remote**

```bash
caasi run start experiments/slam.yaml -t <target>
caasi logs <the slam run> -f
```

**Check it worked**

```bash
ros2 lifecycle get /slam_toolbox     # active
ros2 topic hz /map                   # ~0.3 Hz once the robot moves
ros2 run tf2_ros tf2_echo map odom   # the transform exists
```

ROS 1: `roslaunch swjtumover_bringup bringup_gmapping.launch`

---

## 5. Saving a map

The target directory must exist; the service does not create it.

**Local**

```bash
mkdir -p ~/maps
ros2 service call /slam_toolbox/save_map slam_toolbox/srv/SaveMap \
  "{name: {data: '/home/swjtumover/maps/map'}}"
```

**Remote**

```bash
caasi exec --target <target> -- bash -c 'mkdir -p ~/maps && source /opt/ros/jazzy/setup.bash && \
  ros2 service call /slam_toolbox/save_map slam_toolbox/srv/SaveMap \
  "{name: {data: \"/home/swjtumover/maps/map\"}}"' | tail -2
```

`nav2_map_server`'s `map_saver_cli` does not work against slam_toolbox. ROS 1:
`rosrun map_server map_saver -f ~/maps/map`

---

## 6. Navigation

**Local**

```bash
# ROS 2 -- serves the map, localises, plans and drives
ros2 launch swjtumover_bringup navigation.launch.py

# standalone test: let nav2 drive /cmd_vel directly
ros2 launch swjtumover_bringup navigation.launch.py cmd_vel_topic:=/cmd_vel

# caasi, on the robot
caasi run start experiments/navigation.yaml
```

**Remote**

```bash
caasi run start experiments/navigation.yaml -t <target>
```

**Give it a pose** — nav2 waits for one before activating its costmaps (the equivalent of rviz's
"2D Pose Estimate"):

```bash
ros2 topic pub --once /initialpose geometry_msgs/msg/PoseWithCovarianceStamped \
  "{header: {frame_id: map}, pose: {pose: {position: {x: 2.85, y: -2.77, z: 0.0}, orientation: {w: 1.0}}}}"
```

**Send a goal**

```bash
ros2 action send_goal /navigate_to_pose nav2_msgs/action/NavigateToPose \
  "{pose: {header: {frame_id: map}, pose: {position: {x: 2.0, y: -2.0, z: 0.0}, orientation: {w: 1.0}}}}" \
  --feedback
```

**Check it worked**

```bash
for n in map_server amcl planner_server controller_server behavior_server bt_navigator velocity_smoother; do
  printf '%-18s ' "$n"; ros2 lifecycle get "/$n"
done
```

Navigation publishes `/cmd_vel/nav`; the mission node owns `/cmd_vel`. ROS 1:
`roslaunch swjtumover_bringup map_server.launch`, `amcl.launch`, `move_base.launch`

---

## 7. Line-then-home mission

One launch brings up the bringup, all of nav2, the line follower and the mission — 21 nodes.

**Local**

```bash
ros2 launch swjtumover_bringup line_then_home.launch.py
ros2 launch swjtumover_bringup line_then_home.launch.py map:=/path/to/nav.yaml follow_timeout:=60.0
```

**Remote**

```bash
caasi run start experiments/mission.yaml -t <target>
```

**Start, stop and configure it** — the services keep their ROS 1 names.

```bash
# local
ros2 service call /line_then_home/start std_srvs/srv/Trigger "{}"
ros2 service call /line_then_home/record_waypoints std_srvs/srv/Trigger "{}"
ros2 service call /line_then_home/stop std_srvs/srv/Trigger "{}"

# remote
caasi run start experiments/mission_start.yaml -t <target>
caasi run start experiments/mission_record_waypoints.yaml -t <target>
caasi run start experiments/mission_stop.yaml -t <target>
```

The run prints what the service answered:

```
/line_then_home/start: success=True message='task started: following the line'
```

**Check it worked**

```bash
ros2 topic echo /line_then_home/state     # IDLE, FOLLOW, STOP, NAV, DONE, FAILED
```

A successful run reads `FOLLOW → STOP → NAV → DONE` and ends where it started. The mission needs a
pose first: it uses `/amcl_pose` when available and otherwise the `map → base_link` transform.

The follower's image crop and colour range are launch arguments;
`experiments/mission_demo.yaml` carries the values measured for the site's floor.

ROS 1: `roslaunch swjtumover_bringup line_then_home.launch`

---

## 8. Line follower on its own

**Local**

```bash
ros2 run swjtumover_bringup omove_following_feng.py --ros-args \
  -p color_topic:=/camera/camera/color/image_raw \
  -p depth_topic:=/camera/camera/depth/image_rect_raw

# tuned for the site floor
ros2 run swjtumover_bringup omove_following_feng.py --ros-args \
  -p color_topic:=/camera/camera/color/image_raw \
  -p depth_topic:=/camera/camera/depth/image_rect_raw \
  -p roi_bottom_offset:=70
```

**Remote**

```bash
caasi run start experiments/line_follower.yaml -t <target>
```

**Check it worked**

```bash
ros2 topic echo /cmd_vel      # linear.x 0.12 with a steering term while the line is visible
ros2 topic echo /reached_goal --once
```

It stops when the line is lost, when the centre clearance falls below 0.28 m, and when it decides the
line has ended; publishing `true` on `/line_follow/enable` clears that. ROS 1:
`python3 omove_following.py`

---

## 9. Obstacle guard on its own

**Local**

```bash
ros2 run swjtumover_bringup obstacle_rplidar.py
```

**Remote**

```bash
caasi run start experiments/obstacle_guard.yaml -t <target>
caasi logs <the guard run> -f        # 'Go! path clear' then 'Stop! obstacle at ...'
```

Drives forward at 0.2 m/s and stops when the ±10° front sector is closer than 0.85 m. ROS 1:
`python3 obstacle_rplidar.py`

---

## 10. Camera

**Local**

```bash
ros2 launch realsense2_camera rs_launch.py
ros2 topic hz /camera/camera/color/image_raw
```

**Remote**

```bash
caasi run start experiments/camera.yaml -t <target>
```

Start it after nav2 is `active` and before starting the mission. ROS 1:
`roslaunch realsense2_camera rs_camera.launch` (published `/d415/...`)

---

## 11. Deploying and building

**Remote** (caasi's purpose)

```bash
caasi deploy <target>              # copy the project to the robot
caasi deploy <target> --status     # what is deployed, and whether it verified
caasi build --target <target>      # colcon build there, recorded
caasi build --target <target> --clean
```

**Local** (on the robot)

```bash
cd ~/caasi/robots/swjtumover
colcon build --symlink-install
source install/setup.bash
```

**Tests**

```bash
colcon test --packages-select swjtumover_bringup
colcon test-result --result-base build/swjtumover_bringup
```

---

## 12. Inspection

| task | ROS 2 | example |
| --- | --- | --- |
| topic rate | `ros2 topic hz` | `ros2 topic hz /scan` |
| one message | `ros2 topic echo --once` | `ros2 topic echo /motor_state/left --once` |
| node list | `ros2 node list` | `ros2 node list` |
| service call | `ros2 service call` | `ros2 service call /line_then_home/stop std_srvs/srv/Trigger "{}"` |
| record a bag | `ros2 bag record` | `ros2 bag record -o run1 /scan /odom /tf /motor_state/left` |
| transform | `tf2_echo` | `ros2 run tf2_ros tf2_echo base_link lidar_link` |
| lifecycle state | `lifecycle get` | `ros2 lifecycle get /amcl` |
| remote logs | `caasi logs` | `caasi logs <run> -f` |
| remote processes | `caasi run list` | `caasi run list` |
| remote occupancy | `caasi node occupancy` | `caasi node occupancy` |

## 13. Fixing the target and the project

Set once instead of repeating `-t <target>` and `cd <project>`:

| task | command | example |
| --- | --- | --- |
| use this machine from now on | `caasi choose target <name>` | `caasi choose target swjtumover05` |
| use this robot (shipped software) | `caasi choose robot <name>` | `caasi choose robot swjtumover` |
| work on your own code | `caasi choose project <name>` | `caasi choose project maze_run_1` |
| point at a directory outside the tree | `caasi choose project <path>` | `caasi choose project ~/work/hw1` |
| scope a choice to one terminal | `caasi choose --session …` | `eval "$(caasi choose --session target local)"` |
| see what is set | `caasi choose` | `caasi choose` |
| send simulation to a GPU machine | `caasi choose target <name> --role gpu` | `caasi choose target gpu-01 --role gpu` |
| forget it | `caasi choose target --clear` | `caasi choose target --clear` |

A **name** is looked up in caasi's layout (`~/caasi/robots`, `~/caasi/projects`,
`~/caasi/workspaces`) **on the machine you are working on**: the chosen target if one is set, otherwise
this computer, with the notice `no target set, defaulting to local machine`. Nothing found is reported
with the places it looked.

A flag always wins for a single command: `caasi exec -t local -- uptime`. When a command acts on a
chosen target it prints one dim line naming it, so you are never guessing which machine is involved.

## 14. Preparing a new robot

| task | command | example |
| --- | --- | --- |
| copy the project there | `caasi deploy <target>` | `caasi deploy swjtumover05` |
| install ROS 2 and everything else | `caasi run start experiments/provision.yaml -t <target>` | `caasi run start experiments/provision.yaml -t swjtumover05` |
| on the robot instead | `scripts/provision.sh --apply` | `cd ~/caasi/robots/swjtumover && scripts/provision.sh --apply` |
| show what it would do | `scripts/provision.sh` | `scripts/provision.sh --stage ros` |
| give a robot its own ROS domain | `scripts/provision.sh --apply --domain <n>` | `scripts/provision.sh --apply --domain 5` |
| check the result | `caasi target deps <target> --for bringup` | `caasi target deps swjtumover05 --for bringup` |

Provisioning is idempotent and prints each command before running it. See
[Getting started](getting-started.md#5-prepare-the-robot-once) for the stages.

## 15. Remote inspection with caasi

`caasi ros2` asks the robot's own ROS 2 system, so nothing needs to be installed or discovered on your
side of the network.

| task | caasi | example |
| --- | --- | --- |
| topics | `caasi ros2 list topics` | `caasi ros2 list topics -t swjtumover05` |
| nodes | `caasi ros2 list nodes` | `caasi ros2 list nodes` |
| one topic | `caasi ros2 topic <name>` | `caasi ros2 topic /scan` |
| one message | `caasi ros2 topic <name> --echo --once` | `caasi ros2 topic /motor_state/left --echo --once` |
| the graph | `caasi ros2 graph` | `caasi ros2 graph` |
| services | `caasi ros2 service list` | `caasi ros2 service list` |
| start the mission | `caasi ros2 service call …` | `caasi ros2 service call /line_then_home/start std_srvs/srv/Trigger "{}"` |
| ROS 2's own check | `caasi ros2 doctor` | `caasi ros2 doctor` |
| anything else | `caasi exec --ros -- …` | `caasi exec --ros -- ros2 topic hz /odom` |

`caasi ros` and `caasi ros2` are the same command; both spellings work.

## 16. Simulation on a GPU machine

Isaac Sim and Isaac Lab need a GPU; the robot does not have one. These commands run where you point
them, and default to this computer when no `gpu` target has been chosen.

| task | command | example |
| --- | --- | --- |
| name the GPU machine once | `caasi choose target <name> --role gpu` | `caasi choose target gpu-01 --role gpu` |
| run a sim experiment there | `caasi sim run <config> [-t <target>]` | `caasi sim run experiments/scene.yaml` |
| run an Isaac Lab task | `caasi lab run <config> [-t <target>]` | `caasi lab run experiments/warehouse.yaml -t gpu-01` |
| train | `caasi lab train <config> [-t <target>]` | `caasi lab train experiments/warehouse.yaml` |
| replay a checkpoint | `caasi lab play <config> --checkpoint <file>` | `caasi lab play experiments/warehouse.yaml --checkpoint runs/last.pt` |
| see what it would do | `--dry-run` | `caasi lab run experiments/warehouse.yaml --dry-run` |
| register the GPU machine first | `caasi node enroll <name> --host <ip> --user <user>` | `caasi node enroll gpu-01 --host 10.212.19.50 --user dev` |

A role is stored separately from the machine commands normally act on, so choosing the robot does not
move your simulations to it.

### What a simulation task is

An Isaac Sim / Isaac Lab task is an ordinary Python script that Isaac's own launcher runs:

```bash
# what Isaac Lab itself would run on the GPU machine
cd ~/IsaacLab && ./isaaclab.sh -p ~/work/tasks/22_train_nav.py --num_envs 64 --num_steps 2000
```

caasi wraps that in an experiment file, so it becomes one tracked run with a log and an exit code:

```yaml
name: nav-training
backend: lab
script: ../tasks/22_train_nav.py
args:
- --num_envs
- "64"
- --num_steps
- "2000"
description: Point-goal navigation training in Isaac Lab.
```

Two things must be true on the machine that runs it:

```bash
caasi config set tools.isaaclab.path /home/<you>/IsaacLab   # so caasi finds isaaclab.sh
caasi lab status                                            # isaaclab registered and usable?
caasi sim check                                             # the Isaac Sim side, same question
caasi node check gpu-01                                     # the GPU machine is reachable and sane
```

`backend: sim` is the same idea for Isaac Sim, and resolves `tools.isaacsim.path`. A task that needs no
Isaac at all uses `backend: python`.
