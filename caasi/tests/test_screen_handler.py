#!/usr/bin/env python3
"""screen_handler (ROS 2) protocol tests against a UDP sink.

The expected frame was captured from the physical robot's ROS 1 `screen_node` and
hex-dumped from the wire during phase 8, so these assertions are against measured
hardware behaviour rather than against the port's own implementation:

    qrcode.txt="<text>"  followed by three 1-byte 0x00 terminators, sent as four
    separate datagrams, with identical text suppressed.

Workstation only: the sink is a local socket. No traffic is ever sent to the robot's
IO endpoint.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time

import pytest
#: The ROS environment as it was when this module was imported. caasi's conftest
#: installs an autouse fixture that deletes ROS_*/AMENT_PREFIX_PATH from os.environ so
#: the CLI unit tests stay hermetic; a real-ROS integration test therefore cannot read
#: those variables at call time. Snapshotting at import (collection happens before any
#: fixture runs) keeps the launch environment intact for subprocesses while leaving the
#: hermetic behaviour of the rest of the suite untouched.
_BASE_ENV = dict(os.environ)


pytestmark = pytest.mark.skipif(
    shutil.which("ros2") is None or not os.environ.get("ROS_DISTRO"),
    reason="needs a sourced ROS 2 environment",
)

#: Verified ROS 1 payload framing.
TERMINATOR = b"\x00"


def _env(domain: int) -> dict[str, str]:
    env = dict(_BASE_ENV)
    # Strip only the caasi *source* tree (it breaks the ros2 CLI's entry-point
    # discovery). Paths under caasi-workspace/ are the ROS overlay and must stay,
    # otherwise `ros2 run <project package>` cannot resolve.
    parts = [p for p in env.get("PYTHONPATH", "").split(os.pathsep)
             if p and not p.rstrip("/").endswith("/caasi/src")]
    env["PYTHONPATH"] = os.pathsep.join(parts) if parts else ""
    if not parts:
        env.pop("PYTHONPATH", None)
    env["ROS_DOMAIN_ID"] = str(domain)
    return env


class Harness:
    def __init__(self, domain: int) -> None:
        self.domain = domain
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.5)
        self.port = self.sock.getsockname()[1]
        self.proc: subprocess.Popen | None = None

    def __enter__(self) -> "Harness":
        self.log = open("/tmp/caasi_screen_test_node.log", "w+")
        self.proc = subprocess.Popen(
            ["ros2", "run", "openmover", "screen_handler.py", "--ros-args",
             "-p", "screen.ip_address:=127.0.0.1",
             "-p", f"screen.port:={self.port}"],
            stdout=self.log, stderr=subprocess.STDOUT, env=_env(self.domain),
        )
        time.sleep(5.0)
        # Fail loudly rather than letting the publisher wait forever on a node that
        # never came up: a hanging test tells you nothing about the code under test.
        if self.proc.poll() is not None:
            self.log.flush()
            self.log.seek(0)
            raise AssertionError(
                f"screen_handler exited with {self.proc.returncode}:\n{self.log.read()[:1500]}"
            )
        return self

    def __exit__(self, *exc) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.sock.close()
        if getattr(self, "log", None):
            self.log.close()

    def publish(self, text: str, times: int = 5) -> None:
        """Publish a bounded number of messages.

        A kill-based publisher races discovery on a fresh domain and can be killed
        before a single sample is delivered, which makes the assertion vacuous rather
        than failing honestly. ``--times`` returns only after the samples are sent.
        """
        subprocess.run(
            ["ros2", "topic", "pub", "--rate", "10", "--times", str(times),
             "/qrcode_text", "std_msgs/msg/String", f'{{data: "{text}"}}'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=40,
            env=_env(self.domain), check=False,
        )

    def drain(self, seconds: float = 2.0) -> list[bytes]:
        got: list[bytes] = []
        end = time.time() + seconds
        while time.time() < end:
            try:
                got.append(self.sock.recvfrom(2048)[0])
            except (TimeoutError, OSError):
                pass
        return got


def test_payload_matches_the_verified_robot_frame():
    """Byte-exact: payload datagram then three 1-byte terminators."""
    with Harness(161) as h:
        h.publish("PAYLOAD_CHK")
        got = h.drain()
    assert got == [b'qrcode.txt="PAYLOAD_CHK"', TERMINATOR, TERMINATOR, TERMINATOR], got


def test_identical_text_is_suppressed():
    """ROS 1 only re-sends on change; the port must not repeat at loop rate."""
    with Harness(162) as h:
        h.publish("PAYLOAD_CHK")
        first = h.drain()
        assert first, "first publish produced no frame"
        h.publish("PAYLOAD_CHK")
        second = h.drain()
    assert second == [], f"identical text was re-sent: {second}"


def test_changed_text_sends_again():
    """A different string must produce a fresh frame."""
    with Harness(163) as h:
        h.publish("FIRST")
        assert h.drain()
        h.publish("SECOND")
        got = h.drain()
    assert got == [b'qrcode.txt="SECOND"', TERMINATOR, TERMINATOR, TERMINATOR], got
