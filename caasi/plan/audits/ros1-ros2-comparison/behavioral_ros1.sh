#!/bin/bash
# ============================================================================
# BEHAVIORAL TEST A/B/C (ROS 1 SIDE): simulation_handler + obstacle_handler
#
# These two nodes are PURE ROS message-transform nodes with no simulator
# dependency, so identical inputs can be driven into them on both stacks.
#
#   Test A  cmd_vel response : /openmover/control/cmd_vel (and _manual)
#                              -> /openmover/control/cmd_vel_sim
#                              gated by /openmover/control/cmd_vel_mode/request
#                              and emergency /openmover/control/stop/request
#   Test B  odometry/twist    : /openmover/hardware/odom_sim (nav_msgs/Odometry)
#                              -> /openmover/hardware/odom  (PoseWithCovarianceStamped)
#                              -> /openmover/hardware/twist (TwistWithCovarianceStamped)
#   Test C  obstacle grid     : /openmover/hardware/lidar/scan/obstacle (LaserScan)
#                              -> /openmover/navigation/obstacle (openmover_msgs/obstacle)
#
# NO hardware is touched. NO simulator is started. Values are emitted as JSON so
# the ROS 2 side can be compared numerically.
# ============================================================================
set -o pipefail
export DISABLE_ROS1_EOL_WARNINGS=1
source /opt/ros/noetic/setup.bash
source /root/openmover_robot/cartographer_ws/install_isolated/setup.bash
source /root/openmover_robot/openmover_ws/devel/setup.bash
export PYTHONPATH=$PYTHONPATH:/root/openmover_robot/openmover_ws/src/openmover/scripts/hal

pkill -f roscore >/dev/null 2>&1; pkill -f simulation_handler >/dev/null 2>&1
pkill -f obstacle_handler >/dev/null 2>&1
sleep 2
roscore > /tmp/roscore.log 2>&1 &
sleep 5

# --- param setup must match the ROS 1 config files exactly -----------------
# obstacle_handler reads ~/obstacle/* (i.e. /obstacle_handler/obstacle/*) and ~/footprint,
# loaded from the project's own config files exactly as bringup.launch does.
python3 - <<'PY'
import rospy, yaml
rospy.init_node('param_setup', anonymous=True, disable_signals=True)
mods = yaml.safe_load(open('/root/openmover_robot/config/modules/modules.yaml'))
hws  = yaml.safe_load(open('/root/openmover_robot/config/hardwares/hardwares.yaml'))
rospy.set_param('/obstacle_handler/obstacle', mods['obstacle'])
rospy.set_param('/obstacle_handler/footprint', hws['footprint'])
rospy.set_param('/simulation_handler/simulation', mods.get('teleop', {}))
print("obstacle params:", rospy.get_param('/obstacle_handler/obstacle'))
print("footprint:", rospy.get_param('/obstacle_handler/footprint'))
PY

# --- publish the static base->lidar transform (bringup.launch does this) ---
# obstacle_handler blocks on lookupTransform(base_link, lidar_link) at startup,
# so the transform must exist first.
rosrun tf2_ros static_transform_publisher 0 0 0 0 0 0 base_link lidar_link \
  > /tmp/static_tf.log 2>&1 &
sleep 3

# --- start the two pure nodes ---------------------------------------------
rosrun openmover simulation_handler > /tmp/sim_handler.log 2>&1 &
rosrun openmover obstacle_handler   > /tmp/obs_handler.log  2>&1 &
sleep 8

echo "=== nodes up ==="
rosnode list 2>&1 | sort

echo
echo "=== TEST A/B/C results (JSON) ==="
python3 - <<'PY'
import json, math, time, rospy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from geometry_msgs.msg import PoseWithCovarianceStamped, TwistWithCovarianceStamped
from openmover_msgs.msg import obstacle as ObstacleMsg
from openmover_msgs.srv import cmd_vel_mode_request, cmd_vel_mode_requestRequest
from openmover_msgs.srv import stop_request, stop_requestRequest

rospy.init_node('equiv_probe_ros1', anonymous=True, disable_signals=True)
results = {}

# ---------------- capture helpers ----------------
got = {}
def mk(topic, typ):
    def cb(m):
        got.setdefault(topic, []).append(m)
    return rospy.Subscriber(topic, typ, cb)

sub_cmd_sim   = mk('/openmover/control/cmd_vel_sim', Twist)
sub_odom      = mk('/openmover/hardware/odom', PoseWithCovarianceStamped)
sub_twist     = mk('/openmover/hardware/twist', TwistWithCovarianceStamped)
sub_obstacle  = mk('/openmover/navigation/obstacle', ObstacleMsg)

pub_cmd    = rospy.Publisher('/openmover/control/cmd_vel', Twist, queue_size=10)
pub_manual = rospy.Publisher('/openmover/control/cmd_vel_manual', Twist, queue_size=10)
pub_odom   = rospy.Publisher('/openmover/hardware/odom_sim', Odometry, queue_size=10)
pub_scan   = rospy.Publisher('/openmover/hardware/lidar/scan/obstacle', LaserScan, queue_size=2)

def wait(service):
    for _ in range(50):
        try:
            rospy.wait_for_service(service, timeout=0.2); return True
        except Exception: pass
    return False

def twist(vx, vy, vz, wx, wy, wz):
    t = Twist()
    t.linear.x, t.linear.y, t.linear.z = vx, vy, vz
    t.angular.x, t.angular.y, t.angular.z = wx, wy, wz
    return t

# ============ TEST A: cmd_vel response ============
# Node starts with cmd_vel_manual_mode = true (per source).
set_mode = rospy.ServiceProxy('/openmover/control/cmd_vel_mode/request', cmd_vel_mode_request)
stop_srv = rospy.ServiceProxy('/openmover/control/stop/request', stop_request)
ok_mode = wait('/openmover/control/cmd_vel_mode/request')
ok_stop = wait('/openmover/control/stop/request')

rospy.sleep(1.0)

A = {"services_available": {"cmd_vel_mode": ok_mode, "stop": ok_stop}, "cases": []}

def emit_case(name, chan, msg, expect):
    """Publish, then check whether cmd_vel_sim received the value."""
    got.pop('/openmover/control/cmd_vel_sim', None)
    (pub_manual if chan == 'manual' else pub_cmd).publish(msg)
    rospy.sleep(0.45)
    recv = got.get('/openmover/control/cmd_vel_sim', [])
    last = recv[-1] if recv else None
    A["cases"].append({
        "name": name,
        "channel": chan,
        "manual_mode": None,   # filled by caller
        "input": {"vx": msg.linear.x, "wz": msg.angular.z},
        "expected": expect,
        "published": last is not None,
        "output": ({"vx": last.linear.x, "wz": last.angular.z} if last else None),
    })
    return last

# initial state: manual_mode == True
A["initial_manual_mode"] = True
emit_case("manual_mode=True, auto channel", "auto", twist(0.11,0,0,0,0,0.22),
          "suppressed (manual mode ignores auto channel)")
emit_case("manual_mode=True, manual channel", "manual", twist(0.33,0,0,0,0,0.44),
          "forwarded")

# switch to auto mode (manual=false)
r1 = set_mode(False)
rospy.sleep(0.5)
A["mode_service_response_manual_false"] = str(r1.result)
emit_case("manual_mode=False, auto channel", "auto", twist(0.55,0,0,0,0,0.66),
          "forwarded")
emit_case("manual_mode=False, manual channel", "manual", twist(0.77,0,0,0,0,0.88),
          "suppressed")
A["cases"][-2]["manual_mode"] = False
A["cases"][-1]["manual_mode"] = False

# emergency enable -> outputs forced to zero while still publishing
r2 = stop_srv(True)
rospy.sleep(0.5)
A["stop_service_response_enable_true"] = str(r2.result)
emit_case("emergency=True, auto channel", "auto", twist(0.99,0,0,0,0,0.99),
          "published but zeroed")
A["cases"][-1]["manual_mode"] = False

# clear emergency
r3 = stop_srv(False)
rospy.sleep(0.5)
A["stop_service_response_enable_false"] = str(r3.result)
emit_case("emergency=False, auto channel", "auto", twist(0.12,0,0,0,0,0.34),
          "forwarded again")
A["cases"][-1]["manual_mode"] = False

results["test_A_cmd_vel"] = A

# ============ TEST B: odometry / twist transform ============
got.pop('/openmover/hardware/odom', None); got.pop('/openmover/hardware/twist', None)
od = Odometry()
od.header.frame_id = "odom"; od.child_frame_id = "base_link"
od.pose.pose.position.x = 1.25
od.pose.pose.position.y = -2.5
od.pose.pose.position.z = 0.125
od.pose.pose.orientation.w = 1.0
od.twist.twist.linear.x = 0.4
od.twist.twist.angular.z = -0.15
pub_odom.publish(od)
rospy.sleep(0.6)

B = {"input": {"x": 1.25, "y": -2.5, "z": 0.125, "lin_x": 0.4, "ang_z": -0.15}}
for topic, key in (('/openmover/hardware/odom','odom'), ('/openmover/hardware/twist','twist')):
    recv = got.get(topic, [])
    if recv:
        m = recv[-1]
        if key == 'odom':
            B[key] = {"frame_id": m.header.frame_id,
                      "x": m.pose.pose.position.x, "y": m.pose.pose.position.y,
                      "z": m.pose.pose.position.z}
        else:
            B[key] = {"frame_id": m.header.frame_id,
                      "lin_x": m.twist.twist.linear.x,
                      "ang_z": m.twist.twist.angular.z}
    else:
        B[key] = None
results["test_B_odom"] = B

# ============ TEST C: obstacle grid ============
got.pop('/openmover/navigation/obstacle', None)
# Deterministic synthetic scan: 360 samples, one obstacle at a known bearing.
sc = LaserScan()
sc.header.frame_id = "lidar_link"
sc.angle_min = -math.pi
sc.angle_max =  math.pi
sc.angle_increment = 2*math.pi/360.0
sc.range_min = 0.05
sc.range_max = 20.0
sc.scan_time = 0.1
sc.time_increment = 0.0
ranges = [float('inf')]*360
ranges[0]   = 1.0    # forward
ranges[90]  = 0.5    # left
ranges[180] = 2.0    # rear
ranges[270] = 0.75   # right
sc.ranges = ranges
pub_scan.publish(sc)
rospy.sleep(1.2)
recv = got.get('/openmover/navigation/obstacle', [])
C = {"input": {"frame_id": "lidar_link", "num_ranges": 360,
               "obstacles": {"forward_0deg": 1.0, "left_90deg": 0.5,
                             "rear_180deg": 2.0, "right_270deg": 0.75}}}
if recv:
    m = recv[-1]
    C["output"] = {
        "size": int(m.size),
        "obstacle_forward": list(m.obstacle_forward),
        "obstacle_backward": list(m.obstacle_backward),
        "obstacle_left": list(m.obstacle_left),
        "obstacle_right": list(m.obstacle_right),
    }
else:
    C["output"] = None
results["test_C_obstacle"] = C

results["_meta"] = {"ros_distro": "noetic", "source": "live ROS 1 container"}
print("###JSON_START###")
print(json.dumps(results, indent=2))
print("###JSON_END###")
PY
