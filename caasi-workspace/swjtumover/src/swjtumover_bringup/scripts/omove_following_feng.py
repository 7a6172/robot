#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ROS 2 port of swjtumover_bringup/scripts/omove_following_feng.py (the line follower).

The vision pipeline is unchanged: the same crop, the same BGR thresholds, the same moments
centroid, the same `yaw = (x - width/2)/320`, the same Hough-lines end-of-line detection with
the same confirmation counter, and the same 0.12 m/s command with `-yaw * 0.6` steering.

Topics are unchanged too: /cmd_vel (remapped to /cmd_vel/line when the mission node is
supervising), /lane_image, /line_follow/enable and /line_follow/end.

Deliberate differences:
  * **the OpenCV windows are optional** (`gui`, default false). ROS 1 always created a window
    and called imshow/waitKey, which cannot work on a headless robot; with `gui:=true` the
    original behaviour including the mouse BGR probe is preserved;
  * ROS 1 signalled "line finished" through the global ROS param `/reached_goal`. ROS 2 has no
    global parameter store, so this node publishes the same information on `/reached_goal`
    (transient-local Bool), which the mission node consumes;
  * the depth image is used for the blocked flag exactly as before, but missing depth simply
    leaves it unchanged instead of silently doing nothing;
  * a zero command is published on shutdown.
"""

from __future__ import annotations

import math

import rclpy
from cv_bridge import CvBridge
from geometry_msgs.msg import Twist
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Image, LaserScan
# --- obstacle stop ---------------------------------------------------------------
# ROS 1's follower had no obstacle check at all: its only stop conditions were "line lost" and
# "end of line". The LiDAR sits at the robot's CENTRE (link origin x=0, y=0), so the range it
# reports is the distance to the centre -- the body still extends 0.16 m ahead of that. A guard
# that stops at a raw 0.22 m is therefore only 6 cm from contact, which is how the robot crept
# into a wall boundary during verification. Stop when the CENTRE clearance is less than the body
# half-length plus a margin.
BODY_HALF_LENGTH = 0.16      # from the URDF: base_link spans x -0.16..+0.16
OBSTACLE_MARGIN = 0.12       # deliberate clearance on top of the body
OBSTACLE_STOP_DISTANCE = BODY_HALF_LENGTH + OBSTACLE_MARGIN
OBSTACLE_SECTOR_DEG = 30     # half-width of the protected sector

from std_msgs.msg import Bool

import cv2
import numpy as np

NODE_NAME = 'omove_following'


class OmoveFollowing(Node):
    def __init__(self) -> None:
        super().__init__(NODE_NAME)
        self.bridge = CvBridge()

        self.image_topic = self.declare_parameter(
            'color_topic', '/d415/color/image_raw').value
        self.depth_topic = self.declare_parameter(
            'depth_topic', '/d415/depth/image_rect_raw').value
        self.enabled = bool(self.declare_parameter('enabled', True).value)
        self.end_confirm_frames = max(
            1, int(self.declare_parameter('end_confirm_frames', 1).value))
        self.image_timeout = float(self.declare_parameter('image_timeout', 0.5).value)
        self.gui = bool(self.declare_parameter('gui', False).value)

        self.cmd_pub = self.create_publisher(Twist, '/cmd_vel', 10)
        self.lane_img_pub = self.create_publisher(Image, '/lane_image', 5)
        latched = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                             durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.end_pub = self.create_publisher(Bool, '/line_follow/end', latched)
        self.reached_pub = self.create_publisher(Bool, '/reached_goal', latched)
        self.end_pub.publish(Bool(data=False))
        self.reached_pub.publish(Bool(data=False))

        self.yaw = 0.0
        self.flag = 0
        self.blocked = False
        self.obstacle_stop = False
        self.last_scan = None
        self.reached_goal = False
        self.line_detected = True
        self.end_frames = 0
        self.last_image_time = None

        self.image_window_img = None
        self.mouse = {'x': 0, 'y': 0, 'b': 0, 'g': 0, 'r': 0, 'window': ''}

        if self.gui:
            cv2.namedWindow('Image window', cv2.WINDOW_NORMAL)
            cv2.setMouseCallback('Image window', self.mouse_callback)
            cv2.startWindowThread()

        image_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        scan_qos = QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT)
        self.create_subscription(Bool, '/line_follow/enable', self.enable_cb, 1)
        self.create_subscription(Image, self.image_topic, self.color_img_cb, image_qos)
        self.create_subscription(Image, self.depth_topic, self.depth_img_cb, image_qos)
        self.create_subscription(LaserScan, '/scan', self.scan_cb, scan_qos)
        self.create_timer(0.05, self.control_step)   # 20 Hz, as in ROS 1

    # -- enable / reached-goal signalling ------------------------------
    def enable_cb(self, msg: Bool) -> None:
        if msg.data and not self.enabled:
            self.reached_goal = False
            self.flag = 0
            self.end_frames = 0
            self.line_detected = False
            self.last_image_time = None
            self.reached_pub.publish(Bool(data=False))
            self.end_pub.publish(Bool(data=False))
        self.enabled = msg.data

    # -- control loop --------------------------------------------------
    def control_step(self) -> None:
        cmd = Twist()
        if self.enabled and self.flag and not self.reached_goal:
            self.reached_goal = True
            self.reached_pub.publish(Bool(data=True))
            self.end_pub.publish(Bool(data=True))

        image_fresh = (self.last_image_time is not None and
                       (self.get_clock().now() - self.last_image_time).nanoseconds / 1e9
                       < self.image_timeout)

        clearance = self.front_clearance()
        if clearance < OBSTACLE_STOP_DISTANCE:
            if not self.obstacle_stop:
                self.obstacle_stop = True
                self.get_logger().warn(
                    'obstacle stop: centre clearance %.2f m < %.2f m (body half-length %.2f m '
                    'plus %.2f m margin) -- holding zero'
                    % (clearance, OBSTACLE_STOP_DISTANCE, BODY_HALF_LENGTH, OBSTACLE_MARGIN))
        elif clearance > OBSTACLE_STOP_DISTANCE + 0.05:
            self.obstacle_stop = False

        if not self.enabled or not image_fresh or self.reached_goal or self.blocked \
                or not self.line_detected or self.obstacle_stop:
            cmd.linear.x = 0.0
            cmd.angular.z = 0.0
        else:
            cmd.linear.x = 0.12
            cmd.angular.z = -self.yaw * 0.6
        self.cmd_pub.publish(cmd)

    # -- obstacle stop --------------------------------------------------
    def scan_cb(self, msg: LaserScan) -> None:
        self.last_scan = msg

    def front_clearance(self) -> float:
        """Nearest return inside the protected sector, or inf when nothing is seen."""
        scan = self.last_scan
        if scan is None:
            return float('inf')
        limit = math.radians(OBSTACLE_SECTOR_DEG)
        best = float('inf')
        for index, distance in enumerate(scan.ranges):
            if not math.isfinite(distance):
                continue
            if distance < scan.range_min or distance > scan.range_max:
                continue
            angle = scan.angle_min + index * scan.angle_increment
            angle = math.atan2(math.sin(angle), math.cos(angle))
            if -limit <= angle <= limit:
                best = min(best, distance)
        return best

    # -- vision --------------------------------------------------------
    def mouse_callback(self, event, x, y, flags, param) -> None:
        if self.image_window_img is None:
            return
        height, width = self.image_window_img.shape[:2]
        if x < 0 or x >= width or y < 0 or y >= height:
            return
        b, g, r = self.image_window_img[y, x]
        self.mouse = {'x': x, 'y': y, 'b': int(b), 'g': int(g), 'r': int(r),
                      'window': 'Image window'}
        if event == cv2.EVENT_LBUTTONDOWN:
            self.get_logger().info(
                '[image window] click: x=%d, y=%d, BGR=(%d, %d, %d)'
                % (x, y, self.mouse['b'], self.mouse['g'], self.mouse['r']))

    def _draw_bgr_text(self, img):
        out = img.copy()
        if self.mouse['window'] != 'Image window':
            return out
        cv2.rectangle(out, (10, 10), (430, 115), (0, 0, 0), -1)
        for index, text in enumerate([
                'Window: Image window',
                'x=%d, y=%d' % (self.mouse['x'], self.mouse['y']),
                'BGR=(%d, %d, %d)' % (self.mouse['b'], self.mouse['g'], self.mouse['r'])]):
            cv2.putText(out, text, (20, 40 + 35 * index), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (0, 255, 0), 2)
        return out

    def color_img_cb(self, data: Image) -> None:
        try:
            cv_img = self.bridge.imgmsg_to_cv2(data, 'bgr8')
        except Exception as exc:  # noqa: BLE001 - conversion failure is reported, not fatal
            self.get_logger().error('colour image conversion failed: %s' % exc)
            return

        self.last_image_time = self.get_clock().now()
        height, width, _ = cv_img.shape
        crop_img = cv_img[height // 2 + 100:height, 1:width]
        if crop_img.size == 0:
            return

        lower = np.array([10, 20, 10], dtype='uint8')
        upper = np.array([40, 50, 40], dtype='uint8')
        mask = cv2.inRange(crop_img, lower, upper)
        extraction = cv2.bitwise_and(crop_img, crop_img, mask=mask)

        moments = cv2.moments(mask, False)
        if moments['m00'] > 0:
            self.line_detected = True
            x = moments['m10'] / moments['m00']
            y = moments['m01'] / moments['m00']
            self.yaw = (x - width / 2) / 320.0
        else:
            self.line_detected = False
            x = width / 2
            y = crop_img.shape[0] / 2
            self.yaw = 0.0

        cv2.circle(extraction, (int(x), int(y)), 2, (0, 255, 0), 3)
        gray = cv2.cvtColor(extraction, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100,
                                minLineLength=100, maxLineGap=10)

        terminal_seen = False
        if lines is not None:
            for line in lines:
                x1, y1, x2, y2 = line[0]
                slope = abs((y2 - y1) / (x2 - x1 + 1e-6))
                if abs(slope) < 0.2:
                    terminal_seen = True
                    cv2.line(extraction, (x1, y1), (x2, y2), (0, 0, 255), 2)

        if self.enabled and terminal_seen:
            self.end_frames += 1
        else:
            self.end_frames = 0
        self.flag = int(self.end_frames >= self.end_confirm_frames)

        show_img = np.hstack([crop_img, extraction])
        self.image_window_img = show_img.copy()
        try:
            self.lane_img_pub.publish(self.bridge.cv2_to_imgmsg(show_img, 'bgr8'))
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error('publishing the debug image failed: %s' % exc)

        if self.gui:
            cv2.imshow('Image window', self._draw_bgr_text(show_img))
            cv2.waitKey(1)

    def depth_img_cb(self, data: Image) -> None:
        try:
            depth_img = self.bridge.imgmsg_to_cv2(data, '16UC1')
        except Exception as exc:  # noqa: BLE001
            self.get_logger().error('depth image conversion failed: %s' % exc)
            return
        height, width = depth_img.shape
        if height > 400:
            for distance in depth_img[400:401, 0:width][0]:
                if 300 < distance < 350:
                    self.blocked = False
                    break

    def shutdown(self) -> None:
        self.cmd_pub.publish(Twist())   # a stopped process must not leave a command in effect
        if self.gui:
            cv2.destroyAllWindows()


def main() -> int:
    rclpy.init()
    node = OmoveFollowing()
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
