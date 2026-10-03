#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cmd_vel watchdog: publishes a zero Twist if no cmd_vel arrives within `timeout` seconds.

gz-sim's DiffDrive holds the last velocity command forever (no cmd_vel timeout),
and keyboard teleops only publish on keypress, so the robot would keep driving
after key release. This watchdog restores the "release keys -> robot stops"
behaviour. It is safe with Nav2: Nav2 commands continuously, so the watchdog
never fires while autonomous navigation is active.
"""
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist


class CmdVelWatchdog(Node):
    def __init__(self):
        super().__init__('cmd_vel_watchdog')
        self.declare_parameter('timeout', 0.4)
        self.timeout = self.get_parameter('timeout').value
        self.last_cmd = self.get_clock().now()
        self.create_subscription(Twist, 'cmd_vel', self.on_cmd_vel, 10)
        self.pub = self.create_publisher(Twist, 'cmd_vel', 10)
        self.create_timer(0.1, self.check)

    def on_cmd_vel(self, _msg):
        self.last_cmd = self.get_clock().now()

    def check(self):
        elapsed = (self.get_clock().now() - self.last_cmd).nanoseconds / 1e9
        if elapsed > self.timeout:
            self.pub.publish(Twist())
            self.last_cmd = self.get_clock().now()


def main():
    rclpy.init()
    node = CmdVelWatchdog()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
