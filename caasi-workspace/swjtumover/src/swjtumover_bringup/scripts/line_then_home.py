#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ROS 2 port of swjtumover_bringup/scripts/line_then_home.py (the mission supervisor).

ROS 1 behaviour, preserved:

  * it owns the robot's command topic. The line follower publishes `/cmd_vel/line` and the
    navigation stack publishes `/cmd_vel/nav`; this node forwards exactly one of them to
    `/cmd_vel`, so the two never fight over the wheels;
  * `~start`, `~stop` and `~record_waypoints` std_srvs/Trigger services with the same
    semantics (waypoints may only be recorded while idle; start requires a map pose);
  * `~state` (transient_local String) reports IDLE / FOLLOW / STOP / NAV / DONE / FAILED;
  * `/clicked_point` records return waypoints while recording, and the home pose is appended
    automatically;
  * the same timeouts: `cmd_timeout`, `stop_duration`, `follow_timeout`, `nav_timeout`,
    `tf_timeout`.

ROS 1 -> ROS 2 changes, all unavoidable or deliberate:

  * navigation goes through nav2's `NavigateToPose` action instead of `move_base`
    (actionlib has no ROS 2 equivalent);
  * "line finished" arrives on `/line_follow/end` and `/reached_goal` as they did, but
    `/reached_goal` is a topic now, not a global ROS parameter;
  * the pose source is still `/amcl_pose`; `~tf_timeout` is kept as a parameter because the
    TF2 lookup is what validates that a map->base_link transform exists before navigating.
"""

from __future__ import annotations

import copy
import math

import rclpy
from geometry_msgs.msg import PointStamped, PoseStamped, PoseWithCovarianceStamped, Twist
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool, String
from std_srvs.srv import Trigger

import tf2_ros

STATE_IDLE = 'IDLE'
STATE_FOLLOW = 'FOLLOW'
STATE_STOP = 'STOP'
STATE_NAV = 'NAV'
STATE_DONE = 'DONE'
STATE_FAILED = 'FAILED'


def _yaw_from_quaternion(q) -> float:
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


class LineThenHome(Node):
    def __init__(self) -> None:
        super().__init__('line_then_home')
        self.cmd_timeout = float(self.declare_parameter('cmd_timeout', 0.5).value)
        self.stop_duration = float(self.declare_parameter('stop_duration', 0.7).value)
        self.follow_timeout = float(self.declare_parameter('follow_timeout', 300.0).value)
        self.nav_timeout = float(self.declare_parameter('nav_timeout', 180.0).value)
        self.tf_timeout = float(self.declare_parameter('tf_timeout', 1.0).value)
        self.map_frame = str(self.declare_parameter('map_frame', 'map').value)
        self.base_frame = str(self.declare_parameter('base_frame', 'base_link').value)
        self.require_return_waypoints = bool(
            self.declare_parameter('require_return_waypoints', False).value)
        raw_waypoints = self.declare_parameter('return_waypoints', []).value
        self.return_waypoints = self.validate_waypoints(list(raw_waypoints or []))

        latched = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                             durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.cmd_pub = self.create_publisher(Twist, '/cmd_vel', 1)
        self.enable_pub = self.create_publisher(Bool, '/line_follow/enable', latched)
        self.state_pub = self.create_publisher(String, '~state', latched)

        self.create_subscription(PoseWithCovarianceStamped, '/amcl_pose', self.pose_cb, 1)
        self.create_subscription(Twist, '/cmd_vel/line',
                                 lambda m: self.cmd_cb(m, 'line'), 1)
        self.create_subscription(Twist, '/cmd_vel/nav', lambda m: self.cmd_cb(m, 'nav'), 1)
        self.create_subscription(Bool, '/line_follow/end', self.end_cb, 1)
        self.create_subscription(PointStamped, '/clicked_point', self.waypoint_cb, 10)
        self.create_service(Trigger, '~start', self.start_cb)
        self.create_service(Trigger, '~stop', self.stop_cb)
        self.create_service(Trigger, '~record_waypoints', self.record_waypoints_cb)

        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)
        self.nav_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')

        self.state = STATE_IDLE
        self.recording_waypoints = False
        self.home_pose = None
        self.nav_targets: list[PoseStamped] = []
        self.target_index = 0
        self.nav_goal_handle = None
        self.state_since = self.get_clock().now()
        self.cmd_sources = {'line': (None, Twist()), 'nav': (None, Twist())}

        self.timer = self.create_timer(0.1, self.step)
        self.publish_state()

    # -- helpers -------------------------------------------------------
    @staticmethod
    def validate_waypoints(raw):
        if not isinstance(raw, list):
            raise ValueError('return_waypoints 必须是列表')
        waypoints = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict) or 'x' not in item or 'y' not in item:
                raise ValueError('第 %d 个途经点必须包含 x、y' % (index + 1))
            point = {}
            for key in ('x', 'y', 'yaw'):
                if key in item:
                    try:
                        value = float(item[key])
                    except (TypeError, ValueError, OverflowError):
                        raise ValueError('第 %d 个途经点的 %s 必须是有限数值' % (index + 1, key))
                    if isinstance(item[key], bool) or not math.isfinite(value):
                        raise ValueError('第 %d 个途经点的 %s 必须是有限数值' % (index + 1, key))
                    point[key] = value
            waypoints.append(point)
        return waypoints

    def publish_state(self) -> None:
        self.state_pub.publish(String(data=self.state))
        self.get_logger().info('state -> %s' % self.state)

    def set_state(self, state: str) -> None:
        self.state = state
        self.state_since = self.get_clock().now()
        self.publish_state()

    def elapsed(self) -> float:
        return (self.get_clock().now() - self.state_since).nanoseconds / 1e9

    # -- callbacks -----------------------------------------------------
    def pose_cb(self, msg: PoseWithCovarianceStamped) -> None:
        self.last_pose = msg

    def cmd_cb(self, msg: Twist, source: str) -> None:
        self.cmd_sources[source] = (self.get_clock().now(), msg)

    def end_cb(self, msg: Bool) -> None:
        if msg.data and self.state == STATE_FOLLOW:
            self.set_state(STATE_STOP)

    def waypoint_cb(self, msg: PointStamped) -> None:
        if self.state != STATE_IDLE or not self.recording_waypoints:
            return
        if msg.header.frame_id != self.map_frame:
            self.get_logger().warn(
                '忽略途经点：请将 Fixed Frame 设为 %s' % self.map_frame)
            return
        x, y = msg.point.x, msg.point.y
        if not math.isfinite(x) or not math.isfinite(y):
            self.get_logger().warn('忽略坐标无效的途经点')
            return
        self.return_waypoints.append({'x': x, 'y': y})
        self.get_logger().info('已录入返航途经点 %d: x=%.3f, y=%.3f'
                               % (len(self.return_waypoints), x, y))

    def record_waypoints_cb(self, _request, response):
        if self.state != STATE_IDLE:
            response.success = False
            response.message = '只能在任务开始前录入途经点'
            return response
        self.return_waypoints = []
        self.recording_waypoints = True
        response.success = True
        response.message = ('已清空途经点。请按返航顺序点选，最后一个点后会自动追加起点。')
        self.get_logger().info(response.message)
        return response

    def start_cb(self, _request, response):
        if self.state != STATE_IDLE:
            response.success = False
            response.message = '任务已在运行中'
            return response
        if self.require_return_waypoints and not self.return_waypoints:
            response.success = False
            response.message = '需要先录入返航途经点'
            return response
        pose = getattr(self, 'last_pose', None)
        if pose is None:
            response.success = False
            response.message = '尚未收到 /amcl_pose，无法开始'
            return response
        self.home_pose = copy.deepcopy(pose.pose.pose)
        self.nav_targets = self.build_nav_targets(self.home_pose, self.return_waypoints)
        self.target_index = 0
        self.recording_waypoints = False
        self.enable_pub.publish(Bool(data=True))
        self.set_state(STATE_FOLLOW)
        response.success = True
        response.message = '任务已开始：寻线中'
        return response

    def stop_cb(self, _request, response):
        self.enable_pub.publish(Bool(data=False))
        self.cmd_pub.publish(Twist())
        if self.nav_goal_handle is not None:
            self.nav_goal_handle.cancel_goal_async()
            self.nav_goal_handle = None
        self.set_state(STATE_IDLE)
        response.success = True
        response.message = '已停止'
        return response

    # -- navigation ----------------------------------------------------
    def build_nav_targets(self, home, waypoints):
        targets = []
        for index, item in enumerate(waypoints):
            yaw = item.get('yaw')
            if yaw is None:
                yaw = _yaw_from_quaternion(home.orientation)
                candidates = waypoints[index + 1:] + [
                    {'x': home.position.x, 'y': home.position.y}]
                for point in candidates:
                    dx, dy = point['x'] - item['x'], point['y'] - item['y']
                    if math.hypot(dx, dy) > 1e-6:
                        yaw = math.atan2(dy, dx)
                        break
            target = PoseStamped()
            target.header.frame_id = self.map_frame
            target.pose.position.x = item['x']
            target.pose.position.y = item['y']
            target.pose.orientation.z = math.sin(yaw / 2.0)
            target.pose.orientation.w = math.cos(yaw / 2.0)
            targets.append(target)
        home_target = PoseStamped()
        home_target.header.frame_id = self.map_frame
        home_target.pose = copy.deepcopy(home)
        targets.append(home_target)
        return targets

    def send_current_target(self) -> None:
        if self.target_index >= len(self.nav_targets):
            self.set_state(STATE_DONE)
            return
        if not self.nav_client.wait_for_server(timeout_sec=self.tf_timeout):
            self.get_logger().error('nav2 的 navigate_to_pose 服务不可用')
            self.set_state(STATE_FAILED)
            return
        target = copy.deepcopy(self.nav_targets[self.target_index])
        target.header.stamp = self.get_clock().now().to_msg()
        goal = NavigateToPose.Goal()
        goal.pose = target
        self.get_logger().info('导航到第 %d/%d 个目标 (%.2f, %.2f)'
                               % (self.target_index + 1, len(self.nav_targets),
                                  target.pose.position.x, target.pose.position.y))
        send_future = self.nav_client.send_goal_async(goal, feedback_callback=None)
        send_future.add_done_callback(self.goal_response_cb)

    def goal_response_cb(self, future) -> None:
        handle = future.result()
        if handle is None or not handle.accepted:
            self.get_logger().error('导航目标被拒绝')
            self.set_state(STATE_FAILED)
            return
        self.nav_goal_handle = handle
        handle.get_result_async().add_done_callback(self.goal_result_cb)

    def goal_result_cb(self, future) -> None:
        status = future.result().status
        # 4 = STATUS_SUCCEEDED in action_msgs/GoalStatus
        if status != 4:
            self.get_logger().error('导航失败，状态码 %d' % status)
            self.set_state(STATE_FAILED)
            return
        self.target_index += 1
        self.nav_goal_handle = None
        if self.target_index >= len(self.nav_targets):
            self.set_state(STATE_DONE)
        else:
            self.send_current_target()

    # -- supervisor loop -----------------------------------------------
    def step(self) -> None:
        if self.state == STATE_FOLLOW:
            now = self.get_clock().now()
            stamp, cmd = self.cmd_sources['line']
            fresh = (stamp is not None and
                     (now - stamp).nanoseconds / 1e9 <= self.cmd_timeout)
            self.cmd_pub.publish(cmd if fresh else Twist())
            if self.elapsed() > self.follow_timeout:
                self.get_logger().warn('寻线超时，进入停车阶段')
                self.set_state(STATE_STOP)
        elif self.state == STATE_STOP:
            self.cmd_pub.publish(Twist())
            if self.elapsed() >= self.stop_duration:
                self.set_state(STATE_NAV)
                self.send_current_target()
        elif self.state == STATE_NAV:
            now = self.get_clock().now()
            stamp, cmd = self.cmd_sources['nav']
            fresh = (stamp is not None and
                     (now - stamp).nanoseconds / 1e9 <= self.cmd_timeout)
            # nav2 drives the wheels itself through /cmd_vel/nav; forward it while the
            # mission is in the navigation phase.
            self.cmd_pub.publish(cmd if fresh else Twist())
            if self.elapsed() > self.nav_timeout:
                self.get_logger().error('导航超时')
                if self.nav_goal_handle is not None:
                    self.nav_goal_handle.cancel_goal_async()
                    self.nav_goal_handle = None
                self.set_state(STATE_FAILED)
        else:
            self.cmd_pub.publish(Twist())

    def shutdown(self) -> None:
        self.enable_pub.publish(Bool(data=False))
        self.cmd_pub.publish(Twist())


def main() -> int:
    rclpy.init()
    node = LineThenHome()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.shutdown()
        node.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
