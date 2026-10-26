# openmover_vanjee

Thin ROS 2 adapter that publishes `sensor_msgs/msg/LaserScan` from a Vanjee 718H LiDAR.

## Why a thin adapter

The vendor driver (`external/vanjee_driver`) is ROS-independent: it receives UDP, decodes
DIFOP and scan data, and hands back a `ScanData`. This package configures it from ROS
parameters and converts `ScanData` to `LaserScan`. It does not fork the driver, does not
build the vendor's shared library, and does not need `vanjee_lidar_msg` (which the vendor's
ROS wrapper requires only for point-cloud/packet publishing).

The driver headers are used directly, which is why the vendor source ships under
`external/` as an unmodified copy rather than inside `src/`.

## Contract

Taken from the ROS 1 baseline measured on the robot, not invented:

| Property | Value |
| --- | --- |
| Topic | `/scan` |
| Type | `sensor_msgs/msg/LaserScan` |
| Frame | `lidar_link` |
| Rate | ~14.03 Hz |
| Samples | 1440 |
| Angle | `-pi` .. `+pi`, increment 0.004363323 rad |
| Range | 0.25 .. 25.0 m |
| No return | `NaN`, as in ROS 1 |
| Timestamps | wall clock (`use_lidar_clock:=false`) |

QoS is reliable, depth 10: ROS 1 had no such distinction and downstream consumers
subscribe reliably. `SensorDataQoS` (best effort) here silently drops every message for
such a subscriber.

## Parameters

`lidar_type`, `host_address`, `lidar_address`, `host_msop_port`, `lidar_msop_port`,
`frame_id`, `topic`, `min_distance`, `max_distance`, `use_lidar_clock`.
Defaults are the values verified on the robot.

## Requirements

The driver's default `DISABLE_PCAP_PARSE=ON` is applied here, so libpcap is not needed.

```bash
ros2 run openmover_vanjee vanjee_scan_node
```
