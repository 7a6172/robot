#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""warehouse_simulation 配置文件的静态校验（不启动仿真）。"""
import os

import yaml

CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', 'config')


def _load(name):
    with open(os.path.join(CONFIG_DIR, name), 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def test_nav2_params_structure():
    data = _load('nav2_params.yaml')
    # Jazzy navigation_launch.py 需要的节点参数
    for node in ('controller_server', 'planner_server', 'smoother_server',
                 'behavior_server', 'bt_navigator', 'collision_monitor',
                 'docking_server'):
        assert node in data, f'{node} missing in nav2_params.yaml'


def test_nav2_mppi_consistency():
    data = _load('nav2_params.yaml')
    cs = data['controller_server']['ros__parameters']
    follow_path = cs['FollowPath']
    assert follow_path['plugin'] == 'nav2_mppi_controller::MPPIController'
    # MPPI 要求 controller_frequency == 1 / model_dt
    assert abs(cs['controller_frequency'] * follow_path['model_dt'] - 1.0) < 1e-6


def test_nav2_plugin_namespaces():
    # Jazzy 插件名必须使用 :: 分隔命名空间（navfn/behaviors/bt_navigator）
    data = _load('nav2_params.yaml')
    cs = data['controller_server']['ros__parameters']
    assert '::' in cs['FollowPath']['plugin']
    planner = data['planner_server']['ros__parameters']['GridBased']
    assert '::' in planner['plugin']
    bt = data['bt_navigator']['ros__parameters']['navigators']
    for nav in bt:
        assert '::' in data['bt_navigator']['ros__parameters'][nav]['plugin']


def test_slam_toolbox_params():
    data = _load('slam_toolbox.yaml')
    assert 'slam_toolbox' in data
    params = data['slam_toolbox']['ros__parameters']
    assert params.get('use_sim_time') is True
    assert params.get('mode') == 'mapping'


def test_gz_bridge_config():
    data = _load('gz_bridge.yaml')
    # ros_gz_bridge 的 config_file 是一个映射列表
    assert isinstance(data, list) and len(data) >= 5
    topics = [m['ros_topic_name'] for m in data]
    assert '/clock' in topics
    assert '/scan' in topics
    assert '/odom' in topics
    assert '/cmd_vel' in topics
    for m in data:
        assert m['direction'] in ('GZ_TO_ROS', 'ROS_TO_GZ')
        assert m['ros_type_name']
        assert m['gz_type_name']
