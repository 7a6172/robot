# Bridge Contracts & Sim-Loop Mechanics

Both bridges wrap `bridge_core.BridgeCore` in an rclpy node inside Isaac's Python process and
run the same scene (warehouse collision boxes + visual workcell mesh + pioneer3dx at
`(0, 0, 0.01)`). They differ only in the topic contract.

## Stack B contract — `16_bridge_ros.py`

Mirrors the gz half of `warehouse_simulation`'s gz_bridge.yaml:

| Dir | Topic | Type | Notes |
|---|---|---|---|
| in | `/cmd_vel` | geometry_msgs/Twist | reliable |
| out | `/clock` | rosgraph_msgs/Clock | every physics step |
| out | `/odom` | nav_msgs/Odometry | ground-truth pose + encoder twist |
| out | `/tf` | tf2_msgs/TFMessage | `odom→base_link` |
| out | `/tf_static` | tf2_msgs/TFMessage | `base_link→lidar_{forward,rear}_link`, transient-local |
| out | `/openmover/hardware/lidar_{forward,rear}/scan` | sensor_msgs/LaserScan | real-robot topic names so the unmodified `laserscan_multi_merger` consumes them and remaps output to `/scan` |

## Stack A contract — `17_bridge_openmover.py`

Mirrors `openmover/config_defaults/gz_bridge.yaml` **exactly** (Isaac replaces gz;
`simulation_handler` runs unmodified in the stack and plays `motor_handler`'s role):

| Dir | Topic | Type | Notes |
|---|---|---|---|
| in | `/openmover/control/cmd_vel_sim` | geometry_msgs/Twist | published by `simulation_handler` (forwards `cmd_vel` or, by default at boot, `cmd_vel_manual` → teleop path) |
| out | `/clock` | rosgraph_msgs/Clock | every physics step; the stack runs `use_sim_time:=true` on this |
| out | `/openmover/hardware/odom_sim` | nav_msgs/Odometry | frame `odom` / child `base_link`; consumed by `simulation_handler` → re-stamped to `openmover/hardware/odom` + `twist` |
| out | `/openmover/hardware/lidar_{forward,rear}/scan` | sensor_msgs/LaserScan | frames `lidar_forward_link` / `lidar_rear_link` |

**No TF from Isaac.** Like the real gz chain (`publishOdomTF=false`), `odom→base_link` is
broadcast by `localization_handler`, and the static lidar frames come from
`robot_state_publisher` / the stack's static TF publisher.

All publishers are reliable keep-last depth 10 (the rclcpp subscribers use plain depth-N
subscriptions; ros_gz_bridge published reliable too). `/tf_static` (Stack B only) is
transient-local.

## Scan re-binning

The RTX 2D LiDAR (`Example_Rotary_2D` config) emits spherical sweeps in the sensor frame
(x=azimuth°, z=range m), phase-locked to about ±155° per 15 Hz tick. Each tick's sweeps are
accumulated and re-binned into 600 bins over ±90°, min-per-bin; empty bins → 0.0 (the
bluesea2 driver convention for invalid returns). Known asset bias: measured ranges read
~0.1 m short of geometric truth (optical-origin offset of the example config).

## Sim-loop mechanics (both bridges)

```python
DT = world.get_physics_dt()   # ≈ 0.0167 s (60 Hz physics)
TICK = 1.0 / 15.0             # scan rate
```

1. **Render gating.** RTX rendering is the dominant cost; scans are only needed at TICK
   rate. `render = sim_t + DT >= next_tick` → `bridge.step(render=render)`; sensor reads are
   gated the same way. Effect on RTF: 0.57 (render every step) → ~12 (gated, unpaced).
2. **Real-time pacing.** Unpaced, the gated loop runs ~10× faster than real time — unusable
   for teleop and wrong for stacks expecting real-time sensors:
   `lag = wall_t0 + sim_t - time.monotonic(); if lag > 0: time.sleep(lag)`.
   Paced RTF ≈ 0.87 alone, ≈ 0.6 with the full stack running.
3. **Callback pumping.** `rclpy` has **no `spin_some`** (that is rclcpp-only); the loop uses
   `rclpy.spin_once(node, timeout_sec=0)` each iteration — non-blocking, pumps pending
   subscriptions.
4. **Scan tick.** At `sim_t >= next_tick`, publish one LaserScan per sensor from the
   accumulated sweeps, reset accumulators. If the loop fell behind, resync
   (`next_tick = sim_t + TICK`) instead of bursting.
5. **Settle.** 60 rendered steps before exposing the robot to ROS (it drops ~1 cm onto the
   floor).
6. **Instrumentation.** Loop-entry/exit markers, 5 s heartbeat with position and scan count,
   full traceback on any exception. These repeatedly paid for themselves; keep them.

## Loop exit conditions

`while not simulation_app.is_exiting() and rclpy.ok()` — note `is_running()` is False in
headless script mode (the script *is* the main loop); `is_exiting()` flips only after
`close()`.
