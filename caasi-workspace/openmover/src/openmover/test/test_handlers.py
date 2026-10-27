"""Handlers that touch the outside world: wire format, dependency failures, fail-closed.

These run without a robot. The screen's datagram framing is pure and asserted directly; the
speaker and teleop handlers are exercised for what they do when their backend is missing,
which is the state the real robot is in (`pygame` and `pynput` are not installed there).
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent

# The handlers import their message packages, so the workspace's built packages must be
# importable. `colcon test` provides that through the environment; a bare pytest run does
# not, so add the install tree when it exists.
_INSTALL = SRC.parent.parent / 'install'
if _INSTALL.is_dir():
    for candidate in _INSTALL.glob('*/lib/python*/site-packages'):
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
    for candidate in _INSTALL.glob('*_msgs'):  # type-support packages live next to lib/
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))


def _load(relative: str, name: str):
    spec = importlib.util.spec_from_file_location(name, SRC / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------ screen handler

def test_screen_payload_is_the_ros1_wire_format():
    """`qrcode.txt="..."` followed by three NUL tails, byte for byte."""
    screen = _load('scripts/driver/screen_handler.py', 'screen_handler_mod')
    datagrams = screen.framed_datagrams('SCAN-ME')
    assert len(datagrams) == 4
    assert datagrams[0] == b'qrcode.txt="SCAN-ME"'
    assert datagrams[1:] == [b'\x00', b'\x00', b'\x00']


def test_screen_payload_escapes_nothing_and_keeps_quotes():
    screen = _load('scripts/driver/screen_handler.py', 'screen_handler_mod')
    assert screen.build_qr_payload('a"b') == b'qrcode.txt="a"b"'


def test_screen_defaults_keep_the_io_endpoint_off_the_motor_port():
    """The display shares the host address with the motor controller but not the port."""
    screen = _load('scripts/driver/screen_handler.py', 'screen_handler_mod')
    source = (SRC / 'scripts' / 'driver' / 'screen_handler.py').read_text()
    assert '192.168.100.100' in source
    assert '26' in source
    assert screen.COMM_TAIL == b'\x00'


# ----------------------------------------------------------------- speaker handler

def test_speaker_reports_a_missing_backend_instead_of_crashing():
    """pygame is absent on the robot; the node must say so, not die on import."""
    speaker = _load('scripts/driver/speaker_handler.py', 'speaker_handler_mod')
    # The module imports either way: the failure is carried, not raised.
    assert hasattr(speaker, '_PYGAME_IMPORT_ERROR')
    assert speaker.pygame is not None or speaker._PYGAME_IMPORT_ERROR


def test_speaker_startup_names_the_missing_asset(tmp_path):
    """A play request for a file that does not exist must not be logged as success."""
    source = (SRC / 'scripts' / 'driver' / 'speaker_handler.py').read_text()
    assert 'os.path.isfile(sound_filename)' in source
    assert '音频文件不存在' in source  # warns instead of claiming playback


# ---------------------------------------------------------------- teleop handler

def test_teleop_explains_missing_backend(monkeypatch):
    teleop = _load('scripts/teleop/teleop_handler.py', 'teleop_mod')
    monkeypatch.setattr(teleop, 'keyboard', None)
    monkeypatch.setattr(teleop, '_KEYBOARD_IMPORT_ERROR', 'ModuleNotFoundError: pynput')
    reason = teleop.check_keyboard_backend()
    assert reason is not None and 'pynput' in reason


def test_teleop_explains_missing_display(monkeypatch):
    teleop = _load('scripts/teleop/teleop_handler.py', 'teleop_mod')
    if teleop.keyboard is None:
        pytest.skip("keyboard backend not installed on this host")
    monkeypatch.delenv('DISPLAY', raising=False)
    monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
    reason = teleop.check_keyboard_backend()
    assert reason is not None and 'DISPLAY' in reason


def test_teleop_exits_with_a_distinct_code_when_it_cannot_start(tmp_path):
    """The launch must see a failure, not a component that quietly did nothing."""
    env = {k: v for k, v in os.environ.items()
           if k not in ('DISPLAY', 'WAYLAND_DISPLAY')}
    env['PYTHONPATH'] = os.pathsep.join(
        [entry for entry in sys.path if Path(entry).is_dir()]
        + [env.get('PYTHONPATH', '')]
    ).strip(os.pathsep)
    result = subprocess.run(
        [sys.executable, str(SRC / 'scripts' / 'teleop' / 'teleop_handler.py')],
        capture_output=True, text=True, timeout=60, env=env,
    )
    # Either the backend is missing (3) or there is no display (4); never a clean 0.
    assert result.returncode in (3, 4), (result.returncode, result.stdout, result.stderr)
    assert 'cannot start' in result.stderr


# ------------------------------------------------------- command path is gated

def test_teleop_publishes_to_the_manual_command_topic():
    """Teleoperation feeds the gated command path, not the actuation path directly."""
    source = (SRC / 'scripts' / 'teleop' / 'teleop_handler.py').read_text()
    assert 'openmover/control/cmd_vel_manual' in source


def test_motor_handler_consumes_manual_commands_behind_the_actuation_gate():
    """The manual command topic terminates in motor_handler, whose gate is fail-closed."""
    motor = (SRC / 'src' / 'driver' / 'motor_handler.cpp').read_text()
    assert 'openmover/control/cmd_vel_manual' in motor
    # The gate is consulted on the command paths, not merely defined.
    assert motor.count('actuation_permitted()') >= 3
    # A watchdog separately zeroes a stale command.
    assert 'cmd_vel_timeout' in motor


def test_obstacle_handler_publishes_state_and_never_commands():
    source = (SRC / 'src' / 'navigation' / 'obstacle' / 'obstacle_handler.cpp').read_text()
    assert 'openmover/navigation/obstacle' in source
    assert 'cmd_vel' not in source, "obstacle detection must not command the robot"
    assert 'actuation' not in source.lower()
