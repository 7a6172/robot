#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""openmover_msgs 接口完整性测试：所有消息/服务均可导入并实例化。"""
import openmover_msgs.msg as msg_mod
import openmover_msgs.srv as srv_mod

MSG_TYPES = [
    'BmsData',
    'FlowState',
    'MotorState',
    'NavToSimple',
    'NavToState',
    'Obstacle',
    'Pose',
    'Twist',
]

SRV_TYPES = [
    'CmdVelModeRequest',
    'DirectRequest',
    'FlowAction',
    'FlowCmd',
    'NavToRequest',
    'NavToSimpleRequest',
    'PlaysoundRequest',
    'SelfTestReportRequest',
    'StopRequest',
    'WorkModeRequest',
]


def test_all_msgs_instantiate():
    for name in MSG_TYPES:
        cls = getattr(msg_mod, name, None)
        assert cls is not None, f'openmover_msgs.msg.{name} 不存在'
        instance = cls()
        assert instance is not None


def test_all_srvs_have_request_response():
    for name in SRV_TYPES:
        cls = getattr(srv_mod, name, None)
        assert cls is not None, f'openmover_msgs.srv.{name} 不存在'
        assert hasattr(cls, 'Request'), f'{name}.Request 缺失'
        assert hasattr(cls, 'Response'), f'{name}.Response 缺失'
        cls.Request()
        cls.Response()
