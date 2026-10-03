"""Step 1.0 — Isaac Sim 6.0.1 headless smoke test.

Verifies that SimulationApp starts headless on this machine (16 GB RAM,
RTX 3080 10G), creates an empty stage with a ground plane, steps the
physics loop, and reports timing + peak RSS. No ROS, no assets yet.

Run: ~/isaacsim/python.sh openmover_ws/isaac/scripts/00_smoke_test.py
"""

import resource
import time

T0 = time.time()
print(f"[smoke] launching SimulationApp (headless)... t={T0:.1f}", flush=True)

from isaacsim import SimulationApp  # noqa: E402

simulation_app = SimulationApp({"headless": True})
T1 = time.time()
print(f"[smoke] SimulationApp up in {T1 - T0:.1f} s", flush=True)

from isaacsim.core.api import World  # noqa: E402

world = World(stage_units_in_meters=1.0)
world.scene.add_default_ground_plane()
print("[smoke] stage created, ground plane added", flush=True)

world.reset()
N = 60
T2 = time.time()
for _ in range(N):
    world.step(render=False)
T3 = time.time()
print(f"[smoke] {N} physics steps in {T3 - T2:.2f} s "
      f"({N / (T3 - T2):.1f} steps/s)", flush=True)

peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
print(f"[smoke] peak RSS: {peak_mb:.0f} MB", flush=True)

simulation_app.close()
print(f"[smoke] OK — total {time.time() - T0:.1f} s", flush=True)
