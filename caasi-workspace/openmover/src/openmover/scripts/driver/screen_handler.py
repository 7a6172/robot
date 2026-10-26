#!/usr/bin/env python3
"""Chassis IO display node (ROS 2) -- port of the physical robot's screen_node.

The physical robot exposes a small status display behind a plain UDP protocol on the
same board as the motors (default 192.168.100.100:26). No upstream package implements
it, so this is the one component in the migration that is genuinely new code rather
than configuration.

Protocol, verified on the real robot at L4 during phase 8 (payload hex-dumped from the
wire, not inferred):

    <text>\\0\\0\\0        sent as four separate datagrams:
                          one payload datagram, then three 1-byte terminators

with the text being `qrcode.txt="<value>"`. Identical text is suppressed -- the ROS 1
implementation only sends when the string changes, and that behaviour is preserved so
a display update is not repeated at loop rate.

Deliberately scoped to this protocol only: it is not a general IO framework and does
not attempt to cover the lab's io_board_handler surface (battery, lift, e-stop).
"""

from __future__ import annotations

import socket

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

#: Terminator byte sent three times after each payload, matching the ROS 1 framer.
COMM_TAIL = b"\x00"


class ScreenHandler(Node):
    """Sends `qrcode.txt` display updates over UDP."""

    def __init__(self) -> None:
        super().__init__("screen_handler")

        # Defaults mirror the robot's screen.yaml so an unconfigured run still aims at
        # the real device rather than somewhere arbitrary.
        self.declare_parameter("screen.ip_address", "192.168.100.100")
        self.declare_parameter("screen.port", 26)
        self.declare_parameter("screen.control_freq", 5.0)

        self._ip = str(self.get_parameter("screen.ip_address").value)
        self._port = int(self.get_parameter("screen.port").value)
        self._freq = float(self.get_parameter("screen.control_freq").value)

        self._last_text: str | None = None
        self._sock: socket.socket | None = None

        self._sock = self._open_socket()

        self.create_subscription(String, "qrcode_text", self._on_qrcode_text, 1)

        # Idle loop kept from ROS 1 so the node has the same liveness/rate behaviour.
        if self._freq > 0.0:
            self.create_timer(1.0 / self._freq, self._tick)

        self.get_logger().info(
            f"screen_handler ready -> {self._ip}:{self._port} at {self._freq} Hz "
            f"(socket {'ok' if self._sock else 'unavailable'})"
        )

    def _open_socket(self) -> socket.socket | None:
        try:
            # No send timeout is set: SO_SNDTIMEO needs a packed timeval and a UDP
            # sendto does not block meaningfully anyway.
            return socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        except OSError as exc:  # pragma: no cover - environment dependent
            self.get_logger().error(f"screen socket unavailable: {exc}")
            return None

    def _tick(self) -> None:
        # Nothing periodic is sent: the display only updates on change. The timer exists
        # to preserve the ROS 1 node's loop rate and to keep the executor responsive.
        return

    def _on_qrcode_text(self, msg: String) -> None:
        if msg.data == self._last_text:
            return  # ROS 1 suppresses duplicates; repeated identical text is a no-op
        self._last_text = msg.data
        payload = f'qrcode.txt="{msg.data}"'.encode()
        self._send(payload)

    def _send(self, payload: bytes) -> None:
        if self._sock is None:
            self._sock = self._open_socket()
            if self._sock is None:
                return
        try:
            # Four datagrams, exactly as the ROS 1 framer does it.
            self._sock.sendto(payload, (self._ip, self._port))
            for _ in range(3):
                self._sock.sendto(COMM_TAIL, (self._ip, self._port))
        except OSError as exc:
            self.get_logger().error(f"screen send failed: {exc}")
            try:
                self._sock.close()
            finally:
                self._sock = None

    def destroy_node(self) -> bool:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
        return super().destroy_node()


def main(args: list[str] | None = None) -> int:
    rclpy.init(args=args)
    node = ScreenHandler()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
