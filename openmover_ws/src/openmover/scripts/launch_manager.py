#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 2026-08-17 0.0.0.1A (Stage 6)
# 'ros2 launch' process manager replacing the ROS 1 roslaunch Python API
# (roslaunch.parent.ROSLaunchParent / roslaunch.scriptapi.ROSLaunch).
# Each LaunchHandle spawns `ros2 launch` in its own process group so that
# stop() reliably terminates all nodes of the launch.

import os
import signal
import subprocess
import time


class LaunchHandle:
    def __init__(self, launch_file, args=None, name=None):
        '''
        launch_file: absolute path to a '*.launch.py' file,
                     or a tuple (package, launch_file_name)
        args:        dict of launch arguments (key := value)
        '''
        self.launch_file = launch_file
        self.args = dict(args) if args else dict()
        self.name = name if name else str(launch_file)
        self.process = None

    def _build_cmd(self, args):
        cmd = ['ros2', 'launch']

        if isinstance(self.launch_file, tuple):
            cmd.extend(list(self.launch_file))
        elif os.path.isfile(str(self.launch_file)):
            cmd.append(self.launch_file)
        elif '/' in str(self.launch_file):
            # 'pkg/file.launch.py' 形式
            pkg, _, file_name = str(self.launch_file).partition('/')
            cmd.extend([pkg, file_name])
        else:
            cmd.append(self.launch_file)

        for key, value in args.items():
            cmd.append('%s:=%s' % (str(key), str(value)))

        return cmd

    def start(self, args=None):
        if self.is_alive():
            return

        launch_args = dict(self.args)
        if args:
            launch_args.update(args)

        self.process = subprocess.Popen(
            self._build_cmd(launch_args),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True)

    def stop(self, grace=5.0):
        if self.process == None:
            return

        if not self.is_alive():
            self.process = None
            return

        pgid = None
        try:
            pgid = os.getpgid(self.process.pid)
        except Exception:
            pass

        try:
            if pgid != None:
                os.killpg(pgid, signal.SIGINT)
            else:
                self.process.send_signal(signal.SIGINT)
        except Exception:
            pass

        try:
            self.process.wait(timeout=grace)
        except Exception:
            try:
                if pgid != None:
                    os.killpg(pgid, signal.SIGKILL)
                else:
                    self.process.kill()
                self.process.wait(timeout=grace)
            except Exception:
                pass

        self.process = None

    def restart(self, args=None):
        self.stop()
        self.start(args=args)

    def is_alive(self):
        if self.process == None:
            return False

        return self.process.poll() == None


# 兼容 ROS 1 roslaunch.parent.ROSLaunchParent 用法
def parent_launch(launch_file, args=None, name=None):
    handle = LaunchHandle(launch_file, args=args, name=name)
    handle.start()
    return handle


# 兼容 ROS 1 roslaunch.scriptapi.ROSLaunch 用法
def script_launch(launch_file, args=None, name=None):
    return LaunchHandle(launch_file, args=args, name=name)
