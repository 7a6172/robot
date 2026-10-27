#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 2022-6-24 0.0.0.1A

import os
import sys
import time
import threading

_PYGAME_IMPORT_ERROR: str | None = None
try:
    import pygame
except Exception as _exc:  # noqa: BLE001 - any import failure means playback is impossible
    pygame = None
    _PYGAME_IMPORT_ERROR = f"{type(_exc).__name__}: {_exc}"
import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from openmover_msgs.srv import PlaysoundRequest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'hal'))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 平铺安装布局

import symbols

NODE_NAME = 'speaker_handler'
TAG = '机器人扬声器驱动'

code_undef = symbols.cmd_code['undef']
code_start = symbols.cmd_code['start']
code_exit = symbols.cmd_code['finish']
code_cancel = symbols.cmd_code['cancel']
code_ok = symbols.cmd_code['ok']
code_error = symbols.cmd_code['error']

request_updated = False
sound_loop_times = 1


class SpeakerHandler(Node):

    def __init__(self):
        super().__init__(NODE_NAME)

        global sound_filepath

        self.declare_parameter('sound_filepath', '')
        sound_filepath = self.get_parameter('sound_filepath').value

        self.get_logger().info('%s：节点已启动。' % TAG)

        self.service = self.create_service(
            PlaysoundRequest, 'openmover/control/playsound/request',
            self.service_callback)

        # Playback is optional at runtime: report precisely why it is unavailable instead of
        # crashing the node (and, with respawn enabled, looping on the same crash). Service
        # requests then fail visibly rather than being logged as successful.
        if pygame is None:
            self.get_logger().error(
                '%s：音频后端不可用，播放功能禁用（%s）。' % (TAG, _PYGAME_IMPORT_ERROR))
            return
        try:
            pygame.mixer.init()
        except Exception as err:
            self.get_logger().error(
                '%s：无法初始化音频设备，播放功能禁用（%s）。' % (TAG, err))
            return
        self.get_logger().info('%s：音频后端已就绪。' % TAG)

    def service_callback(self, req, res):
        global request_updated
        global sound_filename
        global sound_loop_times

        result = code_error

        assert isinstance(req, PlaysoundRequest.Request)

        sound_filename = sound_filepath + req.filename
        sound_loop_times = req.loop_times

        request_updated = True

        result = code_ok

        res.result = result
        return res


def speaker():
    global request_updated
    global sound_filename
    global sound_loop_times

    rclpy.init()

    node = SpeakerHandler()

    # 后台自旋线程处理服务回调（等效 rospy 的隐式回调处理）
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    spinner = threading.Thread(target=executor.spin, daemon=True)
    spinner.start()

    try:
        while rclpy.ok():
            if request_updated:
                if pygame.mixer.music.get_busy():
                    pygame.mixer.music.stop()

                # Report what actually happened. The previous code logged "starting
                # playback" and then swallowed the failure, so a missing sound file looked
                # like a successful request -- and on the robot the sounds directory does
                # not exist at all.
                if pygame is None:
                    node.get_logger().warn(
                        '%s：音频后端不可用，忽略播放请求：%s' % (TAG, sound_filename))
                elif sound_filename == '':
                    node.get_logger().warn('%s：未指定音频文件，忽略播放请求。' % TAG)
                elif not os.path.isfile(sound_filename):
                    node.get_logger().warn(
                        '%s：音频文件不存在，无法播放：%s' % (TAG, sound_filename))
                else:
                    node.get_logger().info('%s：开始播放：%s。' % (TAG, sound_filename))
                    try:
                        pygame.mixer.music.load(sound_filename)
                        pygame.mixer.music.play(loops=sound_loop_times)
                    except Exception as err:
                        node.get_logger().warn(
                            '%s：播放失败：%s（%s）' % (TAG, sound_filename, err))

                request_updated = False

            try:
                time.sleep(0.2)
            except KeyboardInterrupt:
                node.get_logger().warn('%s：节点即将关闭。' % TAG)
                break
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    speaker()
