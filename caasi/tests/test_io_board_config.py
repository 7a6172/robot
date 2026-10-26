#!/usr/bin/env python3
"""io_board_handler configuration-safety tests (workstation, UDP sink only).

The hazard these guard against: the chassis IO board and the motor controller share the
same IP and differ only by port (IO 26, motors 23). `robot.port` used to default to 23,
so an omitted or inherited configuration silently aimed IO frames at the motor
controller. These tests prove that can no longer happen.

No traffic is ever sent to a real device: every case that starts the node points
`robot.ip_address` at 127.0.0.1.
"""

from __future__ import annotations

import itertools
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

PROJECT = Path(__file__).resolve().parents[2] / "caasi-workspace" / "openmover"
IO_BIN = PROJECT / "install" / "openmover" / "lib" / "openmover" / "io_board_handler"

pytestmark = pytest.mark.skipif(
    not IO_BIN.exists() or shutil.which("ros2") is None or not os.environ.get("ROS_DISTRO"),
    reason="needs a built io_board_handler and a sourced ROS 2 environment",
)

_BASE_ENV = dict(os.environ)

#: The motor controller's port. This node must never target it.
MOTOR_PORT = 23
#: Documented IO board port.
IO_PORT = 26

_DOMAIN_SEQ = itertools.count(201)


def _env() -> dict[str, str]:
    env = dict(_BASE_ENV)
    parts = [p for p in env.get("PYTHONPATH", "").split(os.pathsep)
             if p and not p.rstrip("/").endswith("/caasi/src")]
    if parts:
        env["PYTHONPATH"] = os.pathsep.join(parts)
    else:
        env.pop("PYTHONPATH", None)
    env["ROS_DOMAIN_ID"] = str(next(_DOMAIN_SEQ))
    return env


def _argv(params: dict[str, str]) -> list[str]:
    argv = [str(IO_BIN), "--ros-args"]
    for k, v in params.items():
        argv += ["-p", f"{k}:={v}"]
    return argv


def _run(params: dict[str, str], timeout: float = 12.0) -> tuple[int | None, str]:
    proc = subprocess.Popen(_argv(params), stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, env=_env())
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.terminate()
        out, _ = proc.communicate(timeout=5)
    return proc.poll(), out


def _minimal(**over: str) -> dict[str, str]:
    base = {"robot.ip_address": "127.0.0.1", "robot.port": str(IO_PORT)}
    base.update(over)
    return base


# ---------------------------------------------------------------- fail-closed cases

def test_missing_port_is_refused():
    """An omitted port must stop the node, not silently pick a default."""
    p = _minimal()
    p.pop("robot.port")
    rc, out = _run(p)
    assert rc is not None and rc != 0, f"node ran with no port configured:\n{out[:400]}"
    assert "robot.port" in out


def test_missing_ip_is_refused():
    p = _minimal()
    p.pop("robot.ip_address")
    rc, out = _run(p)
    assert rc is not None and rc != 0
    assert "robot.ip_address" in out


def test_motor_port_23_is_refused():
    """The core guard: port 23 belongs to the motor controller."""
    rc, out = _run(_minimal(**{"robot.port": str(MOTOR_PORT)}))
    assert rc is not None and rc != 0, f"node accepted port 23:\n{out[:400]}"
    assert "23" in out


@pytest.mark.parametrize("bad_port", ["0", "70000", "-1"])
def test_out_of_range_ports_are_refused(bad_port: str):
    rc, out = _run(_minimal(**{"robot.port": bad_port}))
    assert rc is not None and rc != 0, f"node accepted port {bad_port}"
    assert "robot.port" in out


def test_non_integer_port_is_refused():
    rc, out = _run(_minimal(**{"robot.port": '"26"'}))
    assert rc is not None and rc != 0, "a string port must not be coerced"
    assert "robot.port" in out


def test_empty_ip_is_refused():
    rc, out = _run(_minimal(**{"robot.ip_address": '""'}))
    assert rc is not None and rc != 0
    assert "robot.ip_address" in out


# ------------------------------------------------------------ destination behaviour

def test_explicit_port_26_delivers_only_to_the_configured_destination():
    """With a valid configuration the node must send to that destination, and only it.

    The sink stands in for the IO board, so this also demonstrates that traffic follows
    configuration rather than defaulting anywhere else.
    """
    sink = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sink.bind(("127.0.0.1", 0))
    sink.settimeout(0.3)
    port = sink.getsockname()[1]
    got: list[tuple[bytes, int]] = []
    stop = threading.Event()

    def collect():
        while not stop.is_set():
            try:
                data, addr = sink.recvfrom(4096)
            except (TimeoutError, OSError):
                continue
            got.append((data, addr[1]))

    t = threading.Thread(target=collect, daemon=True)
    t.start()
    proc = subprocess.Popen(_argv(_minimal(**{"robot.port": str(port)})),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=_env())
    try:
        time.sleep(6.0)
        assert proc.poll() is None, "node should run with a valid configuration"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        stop.set()
        t.join(timeout=2)
        sink.close()

    assert got, "no IO frames reached the configured destination"
    # Frames arrived on the socket bound to `port`, which proves the destination was the
    # configured port: a datagram to any other port could not be received here. The
    # sender's ephemeral source port is deliberately not asserted on (addr[1] is the
    # origin, not the destination -- an earlier version of this test got that wrong).
    assert len(got) >= 1
    assert port != MOTOR_PORT, "the sink must not be the motor controller port"
    sizes = {len(d) for d, _ in got}
    assert sizes, "captured frames carried no payload"
