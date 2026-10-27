#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""先寻线，再依次导航经过返航途经点，最后返回出发位姿。"""

import copy
import math
import threading

import actionlib
import rospy
import tf2_ros
from actionlib_msgs.msg import GoalStatus
from geometry_msgs.msg import PointStamped, Pose, PoseWithCovarianceStamped, Twist
from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal
from std_msgs.msg import Bool, String
from std_srvs.srv import Trigger, TriggerResponse


class LineThenHome:
    def __init__(self):
        self.lock = threading.RLock()
        self.state = 'IDLE'
        self.home = None
        self.localized = False
        self.endpoint_seen = False
        self.commands = {}
        self.phase_started = rospy.Time.now()
        self.cmd_timeout = float(rospy.get_param('~cmd_timeout', 0.5))
        self.stop_duration = float(rospy.get_param('~stop_duration', 0.7))
        self.follow_timeout = float(rospy.get_param('~follow_timeout', 300.0))
        self.nav_timeout = float(rospy.get_param('~nav_timeout', 180.0))
        self.tf_timeout = float(rospy.get_param('~tf_timeout', 1.0))
        self.map_frame = rospy.get_param('~map_frame', 'map')
        self.base_frame = rospy.get_param('~base_frame', 'base_link')
        self.require_return_waypoints = rospy.get_param('~require_return_waypoints', False)
        self.return_waypoints = self.validate_waypoints(rospy.get_param('~return_waypoints', []))
        self.recording_waypoints = False
        self.nav_targets = []
        self.target_index = 0

        self.tf_buffer = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer)
        self.client = actionlib.SimpleActionClient('/move_base', MoveBaseAction)
        self.cmd_pub = rospy.Publisher('/cmd_vel', Twist, queue_size=1)
        self.enable_pub = rospy.Publisher('/line_follow/enable', Bool, queue_size=1, latch=True)
        self.state_pub = rospy.Publisher('~state', String, queue_size=1, latch=True)
        self.enable_pub.publish(Bool(data=False))
        self.state_pub.publish(String(data=self.state))

        rospy.Subscriber('/amcl_pose', PoseWithCovarianceStamped, self.pose_cb, queue_size=1)
        rospy.Subscriber('/cmd_vel/line', Twist, self.cmd_cb, callback_args='line', queue_size=1)
        rospy.Subscriber('/cmd_vel/nav', Twist, self.cmd_cb, callback_args='nav', queue_size=1)
        rospy.Subscriber('/line_follow/end', Bool, self.end_cb, queue_size=1)
        rospy.Subscriber('/clicked_point', PointStamped, self.waypoint_cb, queue_size=10)
        self.start_service = rospy.Service('~start', Trigger, self.start_cb)
        self.stop_service = rospy.Service('~stop', Trigger, self.stop_cb)
        self.record_service = rospy.Service('~record_waypoints', Trigger, self.record_waypoints_cb)
        rospy.on_shutdown(self.shutdown)

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

    def record_waypoints_cb(self, _request):
        with self.lock:
            if self.state != 'IDLE':
                return TriggerResponse(success=False, message='只能在任务开始前录入途经点')
            self.return_waypoints = []
            rospy.set_param('~return_waypoints', [])
            self.recording_waypoints = True
            message = '已清空途经点。请在 RViz 用 Publish Point 按返航顺序点选，最后一个点后会自动追加起点。'
            rospy.loginfo('%s', message)
            return TriggerResponse(success=True, message=message)

    def waypoint_cb(self, msg):
        with self.lock:
            if self.state != 'IDLE' or not self.recording_waypoints:
                return
            if msg.header.frame_id != self.map_frame:
                rospy.logwarn('忽略途经点：请将 RViz Fixed Frame 设为 %s', self.map_frame)
                return
            x, y = msg.point.x, msg.point.y
            if not math.isfinite(x) or not math.isfinite(y):
                rospy.logwarn('忽略坐标无效的途经点')
                return
            self.return_waypoints.append({'x': x, 'y': y})
            rospy.set_param('~return_waypoints', copy.deepcopy(self.return_waypoints))
            rospy.loginfo('已录入返航途经点 %d: x=%.3f, y=%.3f', len(self.return_waypoints), x, y)

    def build_nav_targets(self, home, waypoints):
        targets = []
        for index, item in enumerate(waypoints):
            target = Pose()
            target.position.x, target.position.y = item['x'], item['y']
            # 未单独配置 yaw 时，到达该点后的朝向取后续第一个不同位置的点。
            yaw = item.get('yaw')
            if yaw is None:
                yaw = math.atan2(2.0 * home.orientation.w * home.orientation.z,
                                 1.0 - 2.0 * home.orientation.z ** 2)
                candidates = waypoints[index + 1:] + [
                    {'x': home.position.x, 'y': home.position.y}]
                for point in candidates:
                    dx, dy = point['x'] - item['x'], point['y'] - item['y']
                    if math.hypot(dx, dy) > 1e-6:
                        yaw = math.atan2(dy, dx)
                        break
            target.orientation.z = math.sin(yaw / 2.0)
            target.orientation.w = math.cos(yaw / 2.0)
            targets.append(target)
        targets.append(copy.deepcopy(home))
        return targets

    def send_current_target(self, now):
        goal = MoveBaseGoal()
        goal.target_pose.header.frame_id = self.map_frame
        goal.target_pose.header.stamp = now
        goal.target_pose.pose = copy.deepcopy(self.nav_targets[self.target_index])
        self.commands.clear()
        self.phase_started = now  # 每个目标单独计时。
        self.client.send_goal(goal)
        rospy.loginfo('导航目标 %d/%d: x=%.3f, y=%.3f%s',
                      self.target_index + 1, len(self.nav_targets),
                      goal.target_pose.pose.position.x, goal.target_pose.pose.position.y,
                      '（起点）' if self.target_index == len(self.nav_targets) - 1 else '')

    def pose_cb(self, msg):
        if msg.header.frame_id == self.map_frame:
            with self.lock:
                self.localized = True

    def cmd_cb(self, msg, source):
        with self.lock:
            self.commands[source] = (msg, rospy.Time.now())

    def end_cb(self, msg):
        with self.lock:
            if self.state == 'FOLLOW_LINE' and msg.data:
                self.endpoint_seen = True

    def current_map_pose(self):
        transform = self.tf_buffer.lookup_transform(
            self.map_frame, self.base_frame, rospy.Time(0))
        age = (rospy.Time.now() - transform.header.stamp).to_sec()
        if age > self.tf_timeout or age < -self.tf_timeout:
            raise ValueError('map 到 base_link 的定位变换已过期')
        pose = Pose()
        pose.position.x = transform.transform.translation.x
        pose.position.y = transform.transform.translation.y
        # 平面导航只保留偏航角。
        q = transform.transform.rotation
        yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                         1.0 - 2.0 * (q.y * q.y + q.z * q.z))
        pose.orientation.z = math.sin(yaw / 2.0)
        pose.orientation.w = math.cos(yaw / 2.0)
        return pose

    def transition(self, state):
        self.state = state
        self.phase_started = rospy.Time.now()
        self.commands.clear()
        self.enable_pub.publish(Bool(data=state == 'FOLLOW_LINE'))
        self.state_pub.publish(String(data=state))
        rospy.loginfo('任务阶段: %s', state)

    def fail(self, reason):
        if self.state == 'RETURN_HOME':
            self.client.cancel_goal()
        self.transition('ERROR')
        self.cmd_pub.publish(Twist())
        rospy.logerr('%s', reason)

    def start_cb(self, _request):
        if not self.client.wait_for_server(rospy.Duration(1.0)):
            return TriggerResponse(success=False, message='move_base 尚未启动')
        with self.lock:
            if self.state != 'IDLE':
                return TriggerResponse(success=False, message='任务已开始；重新试验请重启此 launch')
            if not self.localized:
                return TriggerResponse(success=False, message='尚未收到 /amcl_pose，请先完成初始定位')
            try:
                waypoints = self.validate_waypoints(rospy.get_param('~return_waypoints', self.return_waypoints))
                if self.require_return_waypoints and not waypoints:
                    return TriggerResponse(success=False, message='环路任务需要返航途经点，请先调用 record_waypoints 并点选路线')
                home = self.current_map_pose()
                targets = self.build_nav_targets(home, waypoints)
            except (tf2_ros.TransformException, ValueError) as exc:
                return TriggerResponse(success=False, message=str(exc))
            self.home = home
            self.return_waypoints = waypoints
            self.nav_targets = targets
            self.target_index = 0
            self.recording_waypoints = False
            # 此组合任务独占 move_base；清除可能遗留的 RViz 导航目标。
            self.client.cancel_all_goals()
            self.endpoint_seen = False
            rospy.set_param('/reached_goal', False)
            self.transition('FOLLOW_LINE')
            message = '已记录起点 x=%.3f, y=%.3f，返航途经点 %d 个，开始寻线' % (
                self.home.position.x, self.home.position.y, len(waypoints))
            rospy.loginfo('%s', message)
            return TriggerResponse(success=True, message=message)

    def stop_cb(self, _request):
        with self.lock:
            self.fail('用户停止任务')
        return TriggerResponse(success=True, message='任务停止，速度输出置零')

    def selected_command(self, source, now):
        item = self.commands.get(source)
        if item is not None:
            msg, received = item
            age = (now - received).to_sec()
            if 0 <= age <= self.cmd_timeout:
                values = (msg.linear.x, msg.linear.y, msg.linear.z,
                          msg.angular.x, msg.angular.y, msg.angular.z)
                if all(math.isfinite(value) for value in values):
                    return msg
        return Twist()

    def tick(self):
        with self.lock:
            now = rospy.Time.now()
            elapsed = (now - self.phase_started).to_sec()
            output = Twist()
            if self.state in ('FOLLOW_LINE', 'RETURN_HOME', 'STOPPING'):
                try:
                    self.current_map_pose()
                except (tf2_ros.TransformException, ValueError) as exc:
                    self.fail('定位失效: %s' % exc)

            if self.state == 'FOLLOW_LINE':
                if self.endpoint_seen:
                    self.transition('STOPPING')
                elif elapsed > self.follow_timeout:
                    self.fail('寻线超时；未检测到终点标记')
                else:
                    output = self.selected_command('line', now)
            elif self.state == 'STOPPING' and elapsed >= self.stop_duration:
                self.transition('RETURN_HOME')
                self.send_current_target(now)
            elif self.state == 'RETURN_HOME':
                status = self.client.get_state()
                if status == GoalStatus.SUCCEEDED:
                    self.target_index += 1
                    if self.target_index < len(self.nav_targets):
                        self.send_current_target(now)
                    else:
                        self.transition('DONE')
                        rospy.loginfo('已经过全部途经点并返回起点，任务完成')
                elif status in (GoalStatus.ABORTED, GoalStatus.REJECTED,
                                GoalStatus.PREEMPTED, GoalStatus.RECALLED, GoalStatus.LOST):
                    self.fail('返航目标 %d/%d 失败: %s' % (
                        self.target_index + 1, len(self.nav_targets), self.client.get_goal_status_text()))
                elif elapsed > self.nav_timeout:
                    self.fail('返航目标 %d/%d 超时' % (self.target_index + 1, len(self.nav_targets)))
                else:
                    output = self.selected_command('nav', now)
            self.cmd_pub.publish(output)

    def shutdown(self):
        with self.lock:
            self.enable_pub.publish(Bool(data=False))
            if self.state == 'RETURN_HOME':
                self.client.cancel_goal()
            self.cmd_pub.publish(Twist())

    def run(self):
        rospy.loginfo('先用 RViz 完成定位，再调用 /line_then_home/start 开始任务')
        rate = rospy.Rate(20)
        while not rospy.is_shutdown():
            self.tick()
            rate.sleep()


if __name__ == '__main__':
    rospy.init_node('line_then_home')
    try:
        LineThenHome().run()
    except rospy.ROSInterruptException:
        pass

