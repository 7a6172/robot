#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 2023-6-24 0.0.0.1A

import os
import sys
import time
import threading

import rclpy
from geometry_msgs.msg import Twist
# The keyboard backend is optional at import time so the node can explain *why* it cannot
# run instead of dying with a bare import error. Note that pynput raises at import when no
# X server is reachable even though the package is installed, so "import failed" must not be
# reported as "not installed" -- the two need different fixes.
_KEYBOARD_IMPORT_ERROR: str | None = None
try:
    from pynput import keyboard
except Exception as _exc:  # noqa: BLE001 - any import failure has the same meaning
    keyboard = None
    _KEYBOARD_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from openmover_msgs.srv import StopRequest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'hal'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 平铺安装布局

import symbols

NODE_NAME = 'teleop_handler'
TAG = '手动控制'

# 初始化数据
emergency_stop_value = False


class TeleopHandler(Node):

    def __init__(self):
        super().__init__(NODE_NAME)

        self.declare_parameter('teleop.velocity_x', 0.4)
        self.declare_parameter('teleop.velocity_yaw', 0.2)
        self.declare_parameter('teleop.max_x_acc', 1.0)
        self.declare_parameter('teleop.max_yaw_acc', 0.3)

        self.velocity_x = self.get_parameter('teleop.velocity_x').value
        self.velocity_yaw = self.get_parameter('teleop.velocity_yaw').value
        self.max_x_acc = self.get_parameter('teleop.max_x_acc').value
        self.max_yaw_acc = self.get_parameter('teleop.max_yaw_acc').value

        self.get_logger().info('%s：节点已启动。' % TAG)

        # 定义发布器
        self.cmd_vel_pub = self.create_publisher(
            Twist, 'openmover/control/cmd_vel_manual', 2)

        # 定义急停客户端
        self.emergency_stop_client = self.create_client(
            StopRequest, 'openmover/control/stop/request')

        # 初始化数据
        self.twist_data = Twist()
        self.twist_target_data = Twist()

        # 注册键盘监听
        self.listener = keyboard.Listener(
            on_press=self.on_press,
            on_release=self.on_release)
        self.listener.start()

        self.delta_vx = self.max_x_acc / 50.0
        self.delta_vyaw = self.max_yaw_acc / 50.0

    def on_press(self, key):
        global emergency_stop_value

        if key == keyboard.Key.up:
            self.twist_target_data.linear.x = self.velocity_x
        elif key == keyboard.Key.down:
            self.twist_target_data.linear.x = -self.velocity_x

        if key == keyboard.Key.left:
            self.twist_target_data.angular.z = self.velocity_yaw
        elif key == keyboard.Key.right:
            self.twist_target_data.angular.z = -self.velocity_yaw

        if key == keyboard.Key.home:
            self.twist_target_data.linear.x = 0
            self.twist_target_data.angular.z = 0

            try:
                if self.emergency_stop_client.wait_for_service(timeout_sec=1):
                    emergency_stop_value = not emergency_stop_value

                    request = StopRequest.Request()
                    request.enable = emergency_stop_value

                    future = self.emergency_stop_client.call_async(request)

                    # 后台自旋线程处理服务回调，此处轮询结果
                    deadline = time.monotonic() + 3.0
                    while not future.done():
                        if time.monotonic() > deadline:
                            self.get_logger().warn('%s：紧急制动服务未就绪。' % TAG)
                            return
                        time.sleep(0.05)

                    emergency_stop_data = future.result()
                    assert isinstance(emergency_stop_data,
                                      StopRequest.Response)

                    if emergency_stop_data.result == symbols.cmd_code['ok']:
                        if emergency_stop_value:
                            self.get_logger().warn('%s：紧急制动已施加。' % TAG)
                        else:
                            self.get_logger().warn('%s：紧急制动已释放。' % TAG)
                    else:
                        self.get_logger().warn('%s：紧急制动服务未就绪。' % TAG)
                else:
                    self.get_logger().warn('%s：紧急制动服务未就绪。' % TAG)
            except Exception:
                self.get_logger().warn('%s：紧急制动服务未就绪。' % TAG)

    def on_release(self, key):
        if key == keyboard.Key.up or key == keyboard.Key.down:
            self.twist_target_data.linear.x = 0

        if key == keyboard.Key.left or key == keyboard.Key.right:
            self.twist_target_data.angular.z = 0

    def update(self):
        global emergency_stop_value

        if not emergency_stop_value:
            # 线速度加速度控制
            if abs(self.twist_data.linear.x - self.twist_target_data.linear.x) < self.delta_vx:
                self.twist_data.linear.x = self.twist_target_data.linear.x
            elif self.twist_data.linear.x < self.twist_target_data.linear.x:
                self.twist_data.linear.x += self.delta_vx
            elif self.twist_data.linear.x > self.twist_target_data.linear.x:
                self.twist_data.linear.x -= self.delta_vx

            # 角速度加速度控制
            if abs(self.twist_data.angular.z - self.twist_target_data.angular.z) < self.delta_vyaw:
                self.twist_data.angular.z = self.twist_target_data.angular.z
            elif self.twist_data.angular.z < self.twist_target_data.angular.z:
                self.twist_data.angular.z += self.delta_vyaw
            elif self.twist_data.angular.z > self.twist_target_data.angular.z:
                self.twist_data.angular.z -= self.delta_vyaw
        else:
            self.twist_data.linear.x = 0
            self.twist_data.angular.z = 0

        self.cmd_vel_pub.publish(self.twist_data)


def check_keyboard_backend() -> str | None:
    """Return a reason when keyboard input cannot work here, or None when it can.

    Three distinct situations, three distinct messages, because the fixes differ:
    the package is missing (install it), the package is installed but cannot reach a window
    server (run it from an operator session), or the environment simply has no DISPLAY.
    """
    if keyboard is None:
        import importlib.util
        installed = importlib.util.find_spec("pynput") is not None
        if not installed:
            return (
                "the 'pynput' Python module is not installed "
                f"({_KEYBOARD_IMPORT_ERROR}). Install it on the target "
                "(sudo apt install -y python3-pynput), or run without teleoperation "
                "(teleop:=false)."
            )
        return (
            "'pynput' is installed but cannot attach to a window server "
            f"({_KEYBOARD_IMPORT_ERROR}). Teleoperation needs an operator session with "
            "DISPLAY or WAYLAND_DISPLAY set; it is not usable from a headless bringup "
            "(teleop:=false)."
        )
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return (
            "no DISPLAY or WAYLAND_DISPLAY is set, so keyboard capture cannot attach to a "
            "window server. Teleoperation needs an operator session; do not start it from a "
            "headless bringup (teleop:=false)."
        )
    return None


def manual_control():
    reason = check_keyboard_backend()
    if reason is not None:
        print(f"[teleop_handler] cannot start: {reason}", file=sys.stderr, flush=True)
        # 3 = a dependency is missing, 4 = the environment cannot provide input.
        return 3 if keyboard is None else 4

    rclpy.init()

    node = TeleopHandler()

    # 后台自旋线程处理回调（等效 rospy 的隐式回调处理）
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    spinner = threading.Thread(target=executor.spin, daemon=True)
    spinner.start()

    try:
        while rclpy.ok():
            node.update()

            try:
                time.sleep(0.02)
            except KeyboardInterrupt:
                node.get_logger().warn('%s：节点即将关闭。' % TAG)
                break
    finally:
        node.listener.stop()
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(manual_control())
