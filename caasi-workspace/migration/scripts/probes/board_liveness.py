#!/usr/bin/env python3
"""Is the board's *application* alive on any port, or only its network stack?

Ping answers, so the NIC is powered. This checks whether anything speaks on the ports the
system uses, without commanding motion (all payloads are zero-speed frames).
"""
import socket, time

BOARD = "192.168.100.100"
print("--- TCP port 23 ---")
for port in (23, 1234, 8000):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2.0)
    try:
        s.connect((BOARD, port))
        print(f"  tcp/{port}: CONNECTED")
        s.close()
    except Exception as exc:
        print(f"  tcp/{port}: {type(exc).__name__}")
        s.close()

print("--- UDP listen for any unsolicited datagrams (5 s) ---")
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("192.168.100.10", 23))
    print("  bound 192.168.100.10:23, listening")
except OSError as exc:
    print(f"  cannot bind :23 ({exc}); listening on an ephemeral port instead")
    s.bind(("192.168.100.10", 0))
print(f"  local: {s.getsockname()}")
s.settimeout(1.0)
seen = 0
end = time.time() + 5
while time.time() < end:
    try:
        data, addr = s.recvfrom(128)
        seen += 1
        print(f"  datagram from {addr}: {data.hex()}")
    except socket.timeout:
        pass
print(f"  unsolicited datagrams: {seen}")
s.close()

print("--- ARP entry for the board ---")
import subprocess
out = subprocess.run(["ip", "neigh", "show", BOARD], capture_output=True, text=True).stdout
print("  " + out.strip())
