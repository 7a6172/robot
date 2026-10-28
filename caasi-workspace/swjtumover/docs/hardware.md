# Hardware and safety

Read this before driving the robot.

## Interfaces

| what | where |
| --- | --- |
| motor / IO board | `192.168.100.100`, TCP/UDP **23** (motors) and UDP **26** (display) |
| Vanjee 718H LiDAR | `192.168.110.100`, UDP **7000** on the host and `5000` on the LiDAR |
| host addresses | `192.168.100.10` (motor network), `192.168.110.10` (LiDAR network) |

The motor protocol is the board's own: 10-byte datagrams, CRC8-Maxim in the last byte, motor id
`0x01` left / `0x02` right, speed as a signed RPM. Only the motor driver should talk to port 23.

## Safety model

| layer | behaviour |
| --- | --- |
| command watchdog | `motor.cmd_vel_timeout` (0.5 s): no new `/cmd_vel` means zero speed |
| feedback watchdog | `motor.motor_feedback_timeout` (0.5 s): lost telemetry means zero speed, and the driver stays off until restarted |
| fault latch | any board fault flag (over-temperature, stall, phase overcurrent, overcurrent, sensor) latches the driver off |
| body-aware guard | the line follower holds zero when the centre clearance falls below 0.28 m |
| navigation | nav2's footprint critic rejects trajectories that would put the body into an obstacle |

A latched driver stays off deliberately: it means something real happened. Restart it after fixing
the cause.

## Geometry

The body is 0.32 × 0.30 m and the LiDAR is at its centre, so every range reading is measured to the
centre while the body extends 0.16 m further forward. The line follower stops at 0.28 m of centre
clearance (0.16 m body plus 0.12 m margin); nav2 uses the body footprint with
`footprint_padding: 0.06`.

A single-line LiDAR sweeps one plane at 0.141 m. Objects shorter than that plane are not seen.

## Before driving

1. **Check the supply.** The motor board goes quiet when the battery sags — it still answers ping
   while the protocol replies decay. If replies fall below roughly 95 %, charge it.
2. **Start the LiDAR first.** Whichever process binds UDP 7000 keeps it; if the motor driver wins,
   there is no `/scan`.
3. **Never leave a publisher running.** Every script here publishes a final zero and the watchdog
   covers the rest, but do not walk away from a live publisher.
4. **Set a pose before navigating.** nav2 activates its global costmap only once `map → base_link`
   exists.

## Health checks

```bash
ping -c3 192.168.100.100                    # board reachable
ros2 topic hz /scan                         # ~14 Hz
ros2 topic hz /odom                         # ~50 Hz
ros2 topic echo /motor_state/left --once    # fault flags false, rpm ~0 at rest
ros2 run tf2_ros tf2_echo base_link lidar_link   # z = 0.14114 m, roll = 1.500°
```

## If something does not work

| symptom | cause | action |
| --- | --- | --- |
| no `/scan` | another process holds UDP 7000 | restart with the bringup, which orders it correctly |
| no `/odom`, driver logs a feedback timeout then latches | board silent: supply, cabling | charge or repair, then restart the driver |
| nav2 nodes stay `inactive` | no `map → base_link` | publish `/initialpose` |
| `map_server` fails to configure | map yaml path wrong | `image:` in the yaml must be relative |
| the robot does not move although `/cmd_vel` carries values | driver latched, or the controller is publishing to `/cmd_vel/nav` | restart the driver; check `cmd_vel_topic` |
| keyboard teleoperation does nothing | no X11 focus on a Wayland desktop | click the rviz window, then use the arrow keys |
