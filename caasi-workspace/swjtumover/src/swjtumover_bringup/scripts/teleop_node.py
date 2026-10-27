#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ROS 2 port of swjtumover_bringup/scripts/teleop_node.py.

Behaviour is preserved from ROS 1: same 50 Hz loop, same acceleration ramp, same
brake-on-direction-flip, same release debounce and zero-flush sequence, same parameters
(teleop.*) and the same command topic (/cmd_vel).

Two deliberate improvements over ROS 1:

* the keyboard backend is checked before starting, so a headless robot reports why
  teleoperation cannot run instead of throwing a traceback (this robot has no DISPLAY);
* the loop is a wall timer, so a stalled keyboard listener cannot stop the zero-flush, and
  the node always leaves a zero command behind on shutdown.
"""

from __future__ import annotations

import math
import os
import sys
import threading

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node

NODE_NAME = "teleop_node"
TAG = "键盘手动控制"

_KEYBOARD_IMPORT_ERROR: str | None = None
try:  # pynput raises at import when no X server is reachable, even though it is installed
    from pynput import keyboard
except Exception as exc:  # noqa: BLE001 - every import failure means the same thing here
    keyboard = None
    _KEYBOARD_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


def check_keyboard_backend() -> str | None:
    """Return a reason when keyboard input cannot work here, or None when it can.

    Three distinct situations, three distinct messages, because the fixes differ: the package
    is missing, the package is installed but cannot reach a window server, or the environment
    has no DISPLAY at all.
    """
    if keyboard is None:
        import importlib.util
        if importlib.util.find_spec("pynput") is None:
            return (
                "the 'pynput' Python module is not installed "
                f"({_KEYBOARD_IMPORT_ERROR}). Install it on the target "
                "(sudo apt install -y python3-pynput), or run without teleoperation."
            )
        return (
            "'pynput' is installed but cannot attach to a window server "
            f"({_KEYBOARD_IMPORT_ERROR}). Teleoperation needs an operator session with "
            "DISPLAY or WAYLAND_DISPLAY set."
        )
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return (
            "no DISPLAY or WAYLAND_DISPLAY is set, so keyboard capture cannot attach to a "
            "window server. Teleoperation needs an operator session."
        )
    return None


class TeleopNode(Node):
    def __init__(self) -> None:
        super().__init__(NODE_NAME)
        self.velocity_x = self.declare_parameter("teleop.velocity_x", 0.4).value
        self.velocity_yaw = self.declare_parameter("teleop.velocity_yaw", 0.8).value
        max_x_acc = self.declare_parameter("teleop.max_x_acc", 0.5).value
        max_yaw_acc = self.declare_parameter("teleop.max_yaw_acc", 1.57).value
        self.zero_flush_sec = self.declare_parameter("teleop.zero_flush_sec", 0.15).value
        self.release_debounce_sec = self.declare_parameter(
            "teleop.release_debounce_sec", 0.08).value
        self.brake_on_flip = self.declare_parameter("teleop.brake_on_flip", True).value
        self.brake_on_flip_yaw = self.declare_parameter("teleop.brake_on_flip_yaw", True).value

        self.hz = 50.0
        self.delta_vx = max_x_acc / self.hz
        self.delta_vyaw = max_yaw_acc / self.hz
        self.zero_flush_ticks_total = max(1, int(self.zero_flush_sec * self.hz))

        self.cmd_vel_pub = self.create_publisher(Twist, "cmd_vel", 2)
        self.twist = Twist()
        self.target = Twist()
        self.last_nonzero = Twist()

        self.pressed: set = set()
        self.lock = threading.Lock()
        self.zero_flush_ticks = 0
        self.waiting_debounce = False
        self.last_all_release = self.get_clock().now()

        self.key_up = keyboard.Key.up
        self.key_down = keyboard.Key.down
        self.key_left = keyboard.Key.left
        self.key_right = keyboard.Key.right

        self.listener = keyboard.Listener(
            on_press=self.on_press, on_release=self.on_release)
        self.listener.start()

        self.timer = self.create_timer(1.0 / self.hz, self.tick)
        self.get_logger().info("%s：节点已启动。" % TAG)

    # -- keyboard ------------------------------------------------------
    def _recompute_target(self) -> None:
        vx = 0.0
        wz = 0.0
        if self.key_up in self.pressed and self.key_down not in self.pressed:
            vx += self.velocity_x
        if self.key_down in self.pressed and self.key_up not in self.pressed:
            vx -= self.velocity_x
        if self.key_left in self.pressed and self.key_right not in self.pressed:
            wz += self.velocity_yaw
        if self.key_right in self.pressed and self.key_left not in self.pressed:
            wz -= self.velocity_yaw
        self.target.linear.x = vx
        self.target.angular.z = wz

    def on_press(self, key) -> None:
        with self.lock:
            if key in (self.key_up, self.key_down, self.key_left, self.key_right):
                self.pressed.add(key)
            self._recompute_target()
            self.zero_flush_ticks = 0
            self.waiting_debounce = False

    def on_release(self, key) -> None:
        with self.lock:
            if key in (self.key_up, self.key_down, self.key_left, self.key_right):
                self.pressed.discard(key)
                self._recompute_target()
                if not self.pressed:
                    self.last_all_release = self.get_clock().now()
                    self.waiting_debounce = True

    # -- control loop --------------------------------------------------
    def tick(self) -> None:
        now = self.get_clock().now()
        with self.lock:
            has_pressed = len(self.pressed) > 0
            in_waiting = self.waiting_debounce
            target_vx = self.target.linear.x
            target_wz = self.target.angular.z
            local_zero_flush = self.zero_flush_ticks
            last_release = self.last_all_release

        if has_pressed:
            if self.brake_on_flip and (self.twist.linear.x * target_vx < 0):
                self.twist.linear.x = 0.0
            if self.brake_on_flip_yaw and (self.twist.angular.z * target_wz < 0):
                self.twist.angular.z = 0.0

            self.twist.linear.x = self._ramp(self.twist.linear.x, target_vx, self.delta_vx)
            self.twist.angular.z = self._ramp(self.twist.angular.z, target_wz, self.delta_vyaw)
            self.cmd_vel_pub.publish(self.twist)

            if abs(self.twist.linear.x) > 1e-6 or abs(self.twist.angular.z) > 1e-6:
                self.last_nonzero = Twist()
                self.last_nonzero.linear.x = self.twist.linear.x
                self.last_nonzero.angular.z = self.twist.angular.z

            with self.lock:
                self.zero_flush_ticks = 0
                self.waiting_debounce = False

        elif in_waiting:
            self.cmd_vel_pub.publish(self.last_nonzero)
            if (now - last_release).nanoseconds / 1e9 >= self.release_debounce_sec:
                with self.lock:
                    self.waiting_debounce = False
                    self.zero_flush_ticks = self.zero_flush_ticks_total
        elif local_zero_flush > 0:
            with self.lock:
                self.zero_flush_ticks -= 1
            self.cmd_vel_pub.publish(Twist())

    @staticmethod
    def _ramp(current: float, target: float, delta: float) -> float:
        if abs(current - target) < delta:
            return target
        return current + delta if current < target else current - delta

    def shutdown(self) -> None:
        # Always leave a zero command behind: a stopped process must not leave a motion
        # command in effect on a controller that keeps the last value.
        for _ in range(3):
            self.cmd_vel_pub.publish(Twist())
        try:
            self.listener.stop()
        except Exception:  # noqa: BLE001 - stopping a listener is best effort
            pass


def main() -> int:
    reason = check_keyboard_backend()
    if reason is not None:
        print(f"[teleop_node] cannot start: {reason}", file=sys.stderr, flush=True)
        return 3 if keyboard is None else 4

    rclpy.init()
    node = TeleopNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.shutdown()
        node.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
