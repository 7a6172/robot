#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 2022-6-24 0.0.0.1A

import symbols
import pygame
import rospy
from openmover_msgs.srv import (playsound_request, playsound_requestRequest,
                       playsound_requestResponse)

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


def service_callback(req):
    global sound_filepath
    global request_updated
    global sound_filename
    global sound_loop_times

    result = code_error

    assert isinstance(req, playsound_requestRequest)

    sound_filename = sound_filepath + req.filename
    sound_loop_times = req.loop_times

    request_updated = True

    result = code_ok

    return playsound_requestResponse(result)


def speaker():
    global sound_filepath
    global request_updated
    global sound_filename
    global sound_loop_times

    rospy.init_node(NODE_NAME, anonymous=True)

    rospy.logout('%s：节点已启动。' % TAG)

    sound_filepath = rospy.get_param('~sound_filepath')

    _ = rospy.Service(
        'openmover/control/playsound/request', playsound_request, service_callback)

    pygame.mixer.init()

    rate = rospy.Rate(5)

    while not rospy.is_shutdown():
        if request_updated:
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()

            rospy.loginfo('%s：开始播放：%s。' % (TAG, sound_filename))

            try:
                if (sound_filename != ''):
                    pygame.mixer.music.load(sound_filename)
                    pygame.mixer.music.play(loops=sound_loop_times)
            except:
                pass

            request_updated = False

        if not rospy.is_shutdown():
            try:
                rate.sleep()
            except rospy.exceptions.ROSException:
                rospy.logwarn('%s：节点即将关闭。' % TAG)
        else:
            break


if __name__ == "__main__":
    speaker()
