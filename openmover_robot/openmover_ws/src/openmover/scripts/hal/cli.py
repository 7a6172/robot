# -*- coding: utf-8 -*-
import hal
import rospy
import symbols
from openmover_msgs.msg import *
from utils import *
import config

# 常量
none = None
true = True
false = False

# 模式
mapping = symbols.mode_code['create_map']
navigation = symbols.mode_code['nav_to']

# 定位源
odom = symbols.localization_mode['odom']
map = symbols.localization_mode['map']

# 执行方式
syn = symbols.execute_mode['sync']
asyn = symbols.execute_mode['async']

# 启动停止常量
on = symbols.cmd_code['start']
off = symbols.cmd_code['finish']

# 导航常量
nav_state_running = symbols.nav_state_ret_code['running']
nav_state_blocked = symbols.nav_state_ret_code['blocked']
nav_state_recoery = symbols.nav_state_ret_code['recovery']
nav_state_reached = symbols.nav_state_ret_code['reached']
nav_state_pausing = symbols.nav_state_ret_code['pausing']
nav_state_error = symbols.nav_state_ret_code['error']


def sleep(sec):
    try:
        rospy.sleep(sec)
    except Exception:
        pass


def read(filename):
    with open(filename, 'r') as fs:
        data = fs.read()
    return data


def readlines(filename):
    with open(filename, 'r') as fs:
        data = fs.readlines()
    return data


def back_tag(tag):
    return hal.set_back_tag(tag)


def join():
    return hal.join()


def param(name, default):
    return hal.param(name=name, default=default)


def init(mode=navigation, area=config.config_area_list[0], reloc=true, initpose=none, initpose_x=0, initpose_y=0, initpose_yaw=0, back_tag=none):
    command = hal.if_to_continue(hal.initialize(mode=mode,
                                                area=area,
                                                try_relocalization=reloc,
                                                init_pose_name=initpose,
                                                init_pose_x=initpose_x, init_pose_y=initpose_y, init_pose_yaw=initpose_yaw, inner=true), latch=true, inner=true)

    if command == hal.cmd_code['back']:
        hal.back(back_tag)


def uninit(error=false, exit=true):
    return hal.uninitialize(error=error, inner=not exit)


def get_value(key=none, back_tag=none):
    result = hal.get_value_from_host(key=key, inner=true)

    command = hal.__wait_for_command__(latch=true, inner=true)

    if command == hal.cmd_code['back']:
        hal.back(back_tag)

    return result


def get_nav_state(disp=false):
    return hal.get_navigation_state(inner=(not disp))


def get_loc_state(locsrc=map, disp=false):
    return hal.get_localization_state(localization_source=locsrc, inner=(not disp))


def get_pose_point(name='pose', disp=false):
    if name in hal.pose_point_dict:
        pose = hal.pose_point_dict[name]
        assert isinstance(pose, hal.PoseWithCovarianceStamped)
        ret = dict()
        ret['x'] = pose.pose.pose.position.x
        ret['y'] = pose.pose.pose.position.y
        ret['yaw'] = rad_from_deg(
            yaw_from_quaternion(pose.pose.pose.orientation))

        if disp:
            print(str(ret))
        else:
            return ret


def create_pose(name='pose', x=none, y=none, yaw=none):
    return hal.create_pose_point(name=name, x=x, y=y, yaw=yaw)


def create_map(name=config.config_area_list[0]):
    return hal.create_map(name=name)


def create_path(name='path', path=none, frame=map, delete=false):
    return hal.create_planned_path(name=name, planned_path=path, path_frame=frame, delete=delete)


def call(name=none, action=on, back_tag=none):
    command = hal.if_to_continue(hal.call_robot_function(
        name=name, action=action, inner=true), latch=true, inner=true)

    if command == hal.cmd_code['back']:
        hal.back(back_tag)


def reloc():
    command = hal.if_to_continue(hal.call_relocalization(
        inner=true), latch=true, inner=true)

    if command == hal.cmd_code['back']:
        hal.back(back_tag)


def apply_pose(pose=none, x=0, y=0, yaw=0, cov_xx=0.25, cov_yy=0.25, cov_aa=0.06853):
    command = hal.if_to_continue(
        hal.apply_pose_point(name=pose, x=x, y=y, yaw=yaw, cov_xx=cov_xx, cov_yy=cov_yy, cov_aa=cov_aa, inner=true), latch=true, inner=true)

    if command == hal.cmd_code['back']:
        hal.back(back_tag)


def plan(from_pose=none, to_pose=none,
         from_x=none, from_y=none, from_yaw=none,
         to_x=none, to_y=none, to_yaw=none):
    return hal.call_plan_path(current_pose_name=from_pose, target_pose_name=to_pose,
                              current_pose_x=from_x, current_pose_y=from_y, current_pose_yaw=from_yaw,
                              target_pose_x=to_x, target_pose_y=to_y, target_pose_yaw=to_yaw)


def navto(pose=none, x=none, y=none, yaw=none,
          vxmax=none, vyawmax=none,
          area=none, locsrc=none,
          ignore=false,
          sdist=none, tdist=none,
          tolexy=none, toleyaw=none,
          plan=true,
          planned=true,
          button=false,
          path=none,
          path_data=none,
          initpose=none, initpose_x=none, initpose_y=none, initpose_yaw=none,
          execmode=syn, timeout=240, pubfreq=2, back_tag=none):
    command = hal.if_to_continue(hal.call_nav_to(target_pose_name=pose, target_pose_x=x, target_pose_y=y, target_pose_yaw=yaw,
                                                 vx_max=vxmax, vyaw_max=vyawmax,
                                                 area=area, localization_sources=locsrc,
                                                 ignore_obstacle=ignore,
                                                 strighting_stop_distance=sdist,
                                                 turning_stop_distance=tdist,
                                                 xy_tolerance=tolexy,
                                                 yaw_tolerance=toleyaw,
                                                 use_global_planner=plan,
                                                 use_planned_path=planned,
                                                 button_required=button,
                                                 planned_path_name=path,
                                                 planned_path=path_data,
                                                 init_pose_name=initpose, init_pose_x=initpose_x, init_pose_y=initpose_y, init_pose_yaw=initpose_yaw,
                                                 execution_mode=execmode, timeout=timeout, publish_freq=pubfreq, back_tag=back_tag, inner=true), latch=true, inner=true)

    if command == hal.cmd_code['back']:
        hal.back(back_tag)


def move(dist=0, angle=0,
         vxmax=none, vyawmax=none,
         locsrc=odom,
         ignore=false,
         sdist=none, tdist=none,
         button=false,
         execmode=syn, timeout=240, pubfreq=2, back_tag=none):
    command = hal.if_to_continue(hal.call_move(dist=dist, angle=angle,
                                               vx_max=vxmax, vyaw_max=vyawmax,
                                               localization_sources=locsrc,
                                               ignore_obstacle=ignore,
                                               strighting_stop_distance=sdist,
                                               turning_stop_distance=tdist,
                                               button_required=button,
                                               execution_mode=execmode, timeout=timeout, publish_freq=pubfreq, back_tag=back_tag, inner=true), latch=true, inner=true)

    if command == hal.cmd_code['back']:
        hal.back(back_tag)


def cancel():
    command = hal.if_to_continue(hal.call_cancel(
        inner=true), latch=true, inner=true)

    if command == hal.cmd_code['back']:
        hal.back(back_tag)


def auto_mapping(retracing=false, execmode=syn, pubfreq=1, back_tag=none):
    ret = hal.call_auto_mapping(enable_waypoint_retracing=retracing,
                                execution_mode=execmode, publish_freq=pubfreq, back_tag=back_tag,
                                inner=true)
    command = hal.if_to_continue(ret, latch=true, inner=true)

    if command == hal.cmd_code['back']:
        hal.back(back_tag)

    return ret


def cancel_auto_mapping():
    ret = hal.call_cancel_auto_mapping(inner=true)
    command = hal.if_to_continue(ret, latch=true, inner=true)

    if command == hal.cmd_code['back']:
        hal.back(back_tag)

    return ret


def playsound(name=none, loop=1):
    hal.call_playsound(filename=name, loop_times=loop, inner=true)
