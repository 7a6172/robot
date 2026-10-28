#!/usr/bin/env python3
"""Call one of the mission supervisor's services, as a caasi run.

The ROS 1 workflow used `rosservice call /line_then_home/start`, `…/record_waypoints` and
`…/stop` from a shell. Those are the commands that actually start the robot moving, so they belong
in the same tracked, monitorable place as the launch files rather than in an untracked terminal:

    caasi run start experiments/mission_start.yaml -t swjtumover05
    caasi run start experiments/mission_stop.yaml  -t swjtumover05
    caasi run start experiments/mission_record.yaml -t swjtumover05

Usage: mission_control.py {start|stop|record_waypoints}

Exit codes: 0 the service answered success; 1 it answered failure (the message is printed, and it
is the same message the ROS 1 service returned); 2 the service was not reachable at all.
"""

from __future__ import annotations

import sys

import rclpy
from rclpy.node import Node
from std_srvs.srv import Trigger

SERVICE_PREFIX = '/line_then_home'
VALID = ('start', 'stop', 'record_waypoints')


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in VALID:
        print(__doc__)
        return 2
    action = argv[0]
    name = f'{SERVICE_PREFIX}/{action}'

    rclpy.init()
    node = Node('mission_control')
    client = node.create_client(Trigger, name)
    if not client.wait_for_service(timeout_sec=10.0):
        print(f'{name} is not available -- is the mission launch running?')
        node.destroy_node()
        rclpy.try_shutdown()
        return 2

    future = client.call_async(Trigger.Request())
    rclpy.spin_until_future_complete(node, future, timeout_sec=30.0)
    response = future.result()
    node.destroy_node()
    rclpy.try_shutdown()

    if response is None:
        print(f'{name}: no response within 30 s')
        return 2
    print(f'{name}: success={response.success} message={response.message!r}')
    return 0 if response.success else 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
