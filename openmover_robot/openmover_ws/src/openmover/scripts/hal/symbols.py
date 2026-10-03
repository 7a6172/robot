# 2023-6-24 0.0.0.1A

# -*- coding: utf-8 -*-

# const part
mode_code = {'undef': 'undef', 'create_map': 'create_map', 'nav_to': 'nav_to'}
execute_mode = {'async': 'async', 'sync': 'sync'}
localization_mode = {'odom': 'odom', 'map': 'map'}

func_code = {'save_map': 'save_map', 'load_map': 'load_map'}

cmd_code = {'undef': 'undef', 'start': 'start', 'finish': 'finish', 'cancel': 'cancel', 'ok': 'ok', 'error': 'error', 'busy': 'busy',
            'pass': 'pass', 'timeout': 'timeout', 'exit': 'exit', 'back': 'back', 'pause': 'pause', 'continue': 'continue', 'wait': 'wait'}
nav_cmd_code = {'nav_to': 'nav_to', 'move': 'move',
                'cancel': 'cancel', 'pause': 'pause', 'continue': 'continue'}

nav_state_ret_code = {'running': 'running', 'blocked': 'blocked', 'recovery': 'recovery',
                      'reached': 'reached', 'ready': 'reached', 'pausing': 'pausing', 'error': 'error'}

auto_mapping_cmd_code = {'start': 'start', 'cancel': 'cancel'}
auto_mapping_state_ret_code = {'rotation': 'rotation', 'find_local_frontier_points': 'find_local_frontier_points', 'local_navigation': 'local_navigation',
                               'find_global_frontier_points': 'find_global_frontier_points', 'global_navigation': 'global_navigation', 'back_to_origin_navigation': 'back_to_origin_navigation', 'finish': 'finish'}

code_to_exit = [cmd_code['error'],
                cmd_code['timeout'], nav_state_ret_code['blocked']]

flow_state_code = {'reached': 'reached', 'running': 'running',
                   'pausing': 'pause', 'blocked': 'blocked', 'error': 'error'}
flow_cmd_code = {'get': 'get'}
flow_action_code = {'pause': 'pause', 'continue': 'continue', 'back': 'back'}
