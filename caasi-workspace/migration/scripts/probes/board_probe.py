#!/usr/bin/env python3
"""Probe the motor controller with a well-formed ZERO-SPEED packet and listen for a reply.

Zero speed is the stop command, so this is the safest possible traffic. It answers one
question: does the board still speak its protocol, or has it stopped responding entirely?
"""
import socket, sys, time

BOARD = ("192.168.100.100", 23)
LEFT, RIGHT = 1, 2

def crc8_maxim(data: bytes) -> int:
    """CRC-8/MAXIM, matching the driver's table-driven implementation."""
    crc = 0x00
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8C if crc & 1 else crc >> 1
    return crc & 0xFF

# sanity-check the CRC against the driver's published table
TABLE_HEAD = [0x00, 0x5e, 0xbc, 0xe2, 0x61, 0x3f, 0xdd, 0x83]
for i, expect in enumerate(TABLE_HEAD):
    got = crc8_maxim(bytes([i]))
    assert got == expect, f"crc mismatch at {i}: {got:#02x} != {expect:#02x}"
print("crc8_maxim verified against the driver table")

def packet(motor_id: int, rpm: int = 0, acc: int = 0) -> bytes:
    body = bytearray(10)
    body[0] = motor_id
    body[1] = 0x64               # command flag, as in the driver
    body[2] = (rpm >> 8) & 0xFF
    body[3] = rpm & 0xFF
    body[4] = 0x00
    body[5] = 0x00
    body[6] = acc
    body[7] = 0x00
    body[8] = 0x00
    body[9] = crc8_maxim(bytes(body[:9]))
    return bytes(body)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(1.0)
replies = 0
end = time.time() + 8
while time.time() < end:
    for motor_id in (LEFT, RIGHT):
        pkt = packet(motor_id)
        sock.sendto(pkt, BOARD)
        print(f"sent id={motor_id} zero-speed {pkt.hex()}")
        try:
            data, addr = sock.recvfrom(64)
            replies += 1
            print(f"  REPLY from {addr}: {data.hex()} ({len(data)} bytes)")
        except socket.timeout:
            print("  no reply")
    time.sleep(0.4)
print(f"\ntotal replies: {replies}")
sock.close()
sys.exit(0 if replies else 1)
