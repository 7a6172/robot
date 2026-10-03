"""Shared helpers for the Isaac Sim bring-up scripts.

Preflight guards exist because this machine has 16 GB RAM and has hard-frozen
twice under heavy load. Every Isaac script must call preflight() before
launching SimulationApp.

Standing rules enforced here (see docs/research/04_isaac_sim_strategy.md):
- never launch heavy simulation unattended
- no stray gz sim / ruby / other Kit processes while Isaac runs
- one simulator at a time
"""

import os
import subprocess
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SIM_DIR = os.path.dirname(SCRIPTS_DIR)  # isaac/sim
WS_ROOT = os.path.dirname(os.path.dirname(SIM_DIR))  # caasi-workspace/openmover_ws
ASSETS_DIR = os.path.join(WS_ROOT, "robot", "usd")
SCENES_DIR = os.path.join(SIM_DIR, "scenes")

# Peak RSS of the empty headless sim was 12.3 GB (Step 1.0 smoke test).
# 24 GB swap is the real backstop; abort only when RAM is truly critical.
MIN_AVAILABLE_GIB = 8.0    # abort below this
WARN_AVAILABLE_GIB = 12.5  # warn below this


def available_ram_gib() -> float:
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / (1024 * 1024)
    return 0.0


def stray_simulators() -> list[str]:
    """Processes that would fight Isaac for GPU/RAM (one simulator at a time)."""
    patterns = ["gz sim", "ruby ", "gz sim", "omni.kit", "isaac-sim.sh"]
    found = []
    try:
        out = subprocess.run(["ps", "-eo", "pid,comm,args"], capture_output=True,
                             text=True, timeout=10).stdout
    except Exception:
        return found
    my_pid = os.getpid()
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3 or not parts[0].isdigit():
            continue
        pid, _, args = int(parts[0]), parts[1], parts[2]
        if pid == my_pid:
            continue
        if any(p in args for p in patterns):
            found.append(f"  pid {pid}: {args[:100]}")
    return found


def preflight(label: str) -> None:
    """Abort early instead of freezing the machine. Call before SimulationApp()."""
    ram = available_ram_gib()
    print(f"[preflight:{label}] MemAvailable = {ram:.1f} GiB", flush=True)
    if ram < MIN_AVAILABLE_GIB:
        sys.exit(f"[preflight:{label}] ABORT: only {ram:.1f} GiB available "
                 f"(< {MIN_AVAILABLE_GIB} required). Free memory first.")
    if ram < WARN_AVAILABLE_GIB:
        print(f"[preflight:{label}] WARNING: below {WARN_AVAILABLE_GIB} GiB — "
              "watch RAM while this runs.", flush=True)

    strays = stray_simulators()
    if strays:
        print(f"[preflight:{label}] WARNING: possible stray simulator processes:\n"
              + "\n".join(strays) +
              "\n  Kill them first if they are simulators (one simulator at a time).",
              flush=True)
