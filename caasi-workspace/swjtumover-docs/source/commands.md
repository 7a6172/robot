# Commands

Every task, in the two places you might run it from:

* **Local** — on the robot itself. Both a plain ROS 2 command and a caasi run are given; they do the
  same thing, caasi adds a record.
* **Remote** — from another machine, through caasi. This is the normal way to operate a deployed
  robot.

`<target>` is the execution target you enrolled in caasi. Each section also names the ROS 1 command
it replaces, for comparison.

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
