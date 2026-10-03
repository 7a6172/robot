# 2022-5-13 0.0.0.7A

# -*- coding: utf-8 -*-

import os

import colorama
from colorama import Back, Fore, Style

import utils

# const part
log_level_code = {'INFO': 'INFO', 'WARN': 'WARN',
                  'ERROR': 'ERROR', 'DEBUG': 'DEBUG'}

log_initialize_template = 'openmover Python CLI'
log_uninitialize_template = 'openmover Python CLI uninitialized.'
log_saving_log_template = 'Saving to log file [%s]...'
log_normal_template = '[%s][%s][%s]: %s'
log_filepath = os.path.expanduser(
    '~') + '/openmover_robot/logs/'
log_filename_template = 'openmover_cli_%s.log'


def initialize():
    global log_file
    try:
        colorama.init()
    except:
        pass


def log(log_level=log_level_code['INFO'], handler=None, text=None):
    global log_file

    if log_level in log_level_code and handler != None and text != None:
        log_text = log_normal_template % (
            log_level, str(utils.current_sys_timestamp()), handler, text)
        if log_level == log_level_code['INFO']:
            print(Fore.WHITE + log_text + Style.RESET_ALL)
        elif log_level == log_level_code['WARN']:
            print(Fore.YELLOW + log_text + Style.RESET_ALL)
        elif log_level == log_level_code['ERROR']:
            print(Fore.RED + log_text + Style.RESET_ALL)
        elif log_level == log_level_code['DEBUG']:
            print(Fore.GREEN + log_text + Style.RESET_ALL)

        try:
            log_file.write(log_text + '\n')
            log_file.flush()
        except:
            pass


def loginfo(handler=None, text=None):
    log(log_level=log_level_code['INFO'], handler=handler, text=text)


def logwarn(handler=None, text=None):
    log(log_level=log_level_code['WARN'], handler=handler, text=text)


def logerror(handler=None, text=None):
    log(log_level=log_level_code['ERROR'], handler=handler, text=text)


def logdebug(handler=None, text=None):
    log(log_level=log_level_code['DEBUG'], handler=handler, text=text)


def log_sys_init():
    global log_file

    log_filename = log_filename_template % str(
        int(round(utils.current_sys_timestamp() * 1000, 0)))

    if not os.path.exists(log_filepath):
        os.makedirs(log_filepath)

    log_file = open(log_filepath + log_filename, 'a')

    print(Fore.BLACK + Back.WHITE + log_initialize_template + Style.RESET_ALL)
    log_file.write(log_initialize_template + '\n')

    print(log_saving_log_template % (log_filepath + log_filename))
    log_file.write(log_saving_log_template %
                   (log_filepath + log_filename) + '\n')

    log_file.flush()


def log_sys_uninit():
    print(Fore.BLACK + Back.WHITE + log_uninitialize_template + Style.RESET_ALL)

    try:
        log_file.write(log_uninitialize_template + '\n')
        log_file.flush()
        log_file.close()
    except:
        pass
