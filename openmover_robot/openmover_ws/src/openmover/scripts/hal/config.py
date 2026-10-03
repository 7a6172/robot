# 2023-6-24 0.0.0.1A

# -*- coding: utf-8 -*-

from geometry_msgs.msg import PoseWithCovarianceStamped
from sensor_msgs.msg import LaserScan
from openmover_msgs.msg import *
from openmover_msgs.srv import *
from symbols import *

config_area_list = ['navigation']
config_area_without_map = []
config_area_localization_sources = {'default': localization_mode['odom'] + localization_mode['map'],
                                    'navigation': localization_mode['odom'] + localization_mode['map']}

config_func_uninit_keepalive = []
config_func_enable_self_test = False
config_func_self_test = ['chassis', 'lidar']
config_func_self_test_checklist = {config_func_self_test[0]: 'openmover/localization/odom',
                                   config_func_self_test[1]: 'openmover/hardware/lidar/scan'}
config_func_self_test_typelist = {config_func_self_test[0]: PoseWithCovarianceStamped,
                                  config_func_self_test[1]: LaserScan}
config_func_self_test_wait_duration = 10.0

config_switch_wait_duration = 1.5
config_service_wait_duration = 10.0
config_server_loop_rate = 20
