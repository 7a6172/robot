"""Step 1.3 gate — bridge core: cmd_vel in, odom/tf out, drive verification.

Manoeuvres:
    A) straight:  v = 0.3 m/s, w = 0          for 2.0 s
    B) turn:      v = 0,       w = 0.5 rad/s  for 3.0 s

Checks (physics-limited, so absolute tracking of the command is NOT the
criterion — caster friction bounds the in-place turn):
    A1: displacement dx ~ v*t and |dy| small
    B1: steady yaw rate reached, stable, and turning
    B2: small positional drift while turning
    C : encoder odom twist matches ground-truth pose derivative (the real
        mirror check — nav sees /odom, so /odom must describe reality)

Run: ~/isaacsim/python.sh openmover_ws/isaac/scripts/13_bridge_core.py
"""

import math
import os
import time

import numpy as np

from common import ASSETS_DIR, preflight

USD_PATH = os.path.join(ASSETS_DIR, "pioneer3dx", "pioneer3dx", "pioneer3dx.usda")

preflight("bridge_core")
assert os.path.isfile(USD_PATH), f"missing {USD_PATH} — run 10_import_urdf.py first"

T0 = time.time()
from isaacsim import SimulationApp  # noqa: E402

simulation_app = SimulationApp({"headless": True})
print(f"[bridge] app up in {time.time() - T0:.1f} s", flush=True)

from isaacsim.core.api import World  # noqa: E402
from isaacsim.core.prims import Articulation  # noqa: E402
from isaacsim.core.utils.stage import add_reference_to_stage  # noqa: E402

from bridge_core import BridgeCore  # noqa: E402

world = World(stage_units_in_meters=1.0)
world.scene.add_default_ground_plane()
add_reference_to_stage(USD_PATH, "/World/pioneer3dx")
robot = Articulation("/World/pioneer3dx", name="pioneer3dx")
world.reset()
robot.initialize()
bridge = BridgeCore(world, robot)


def yaw_of(q) -> float:
    w, x, y, z = q
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


dt = world.get_physics_dt()
ODOM_EVERY = max(1, int(round(0.1 / dt)))  # sample odom at ~10 Hz


def drive(v: float, w: float, seconds: float, label: str) -> dict:
    bridge.set_cmd_vel(v, w)
    n = int(seconds / dt)
    path = []  # (x, y, yaw, vx_enc, wz_enc) at ~10 Hz
    for i in range(n):
        bridge.step(render=False)
        if i % ODOM_EVERY == 0:
            o = bridge.get_odom()
            path.append((float(o["position"][0]), float(o["position"][1]),
                         yaw_of(o["orientation"]),
                         float(o["linear"][0]), float(o["angular"][2])))
    o = bridge.get_odom()
    print(f"[bridge] {label}: end pose x={o['position'][0]:.3f} "
          f"y={o['position'][1]:.3f} yaw={yaw_of(o['orientation']):+.3f} rad | "
          f"v_enc={o['linear'][0]:.3f} w_enc={o['angular'][2]:+.3f}",
          flush=True)
    return {"odom": o, "path": path}


def twist_consistency(path: list, dt_sample: float, check: str) -> tuple[float, bool]:
    """Compare encoder twist against finite-difference of ground-truth pose."""
    errs = []
    for i in range(1, len(path)):
        x0, y0, y0w, vx0, wz0 = path[i - 1]
        x1, y1, y1w, vx1, wz1 = path[i]
        if check == "vx":
            truth = (x1 - x0) / dt_sample
            errs.append(abs((vx0 + vx1) / 2.0 - truth))
        elif check == "wz":
            truth = (y1w - y0w) / dt_sample
            errs.append(abs((wz0 + wz1) / 2.0 - truth))
    mae = float(np.mean(errs)) if errs else float("nan")
    return mae, mae < 0.05


o0 = bridge.get_odom()
p0, yaw0 = o0["position"], yaw_of(o0["orientation"])
print(f"[bridge] start pose: x={p0[0]:.3f} y={p0[1]:.3f} yaw={yaw0:+.3f}",
      flush=True)

dt_sample = ODOM_EVERY * dt

res_a = drive(0.3, 0.0, 2.0, "A straight")
pa = res_a["odom"]["position"]
dx = float(pa[0] - p0[0])
dy = float(pa[1] - p0[1])
ok_a = abs(dx - 0.60) < 0.08 and abs(dy) < 0.05
print(f"[bridge] A1: dx={dx:.3f} (expect ~0.60), dy={dy:.3f} (expect ~0) "
      f"-> {'OK' if ok_a else 'FAIL'}", flush=True)
mae_a, ok_c_a = twist_consistency(res_a["path"], dt_sample, "vx")
print(f"[bridge] C(A): vx encoder vs truth MAE={mae_a:.4f} m/s "
      f"-> {'OK' if ok_c_a else 'FAIL'}", flush=True)

res_b = drive(0.0, 0.5, 3.0, "B turn")
pb = res_b["odom"]["position"]
drift = math.hypot(float(pb[0] - pa[0]), float(pb[1] - pa[1]))
# steady yaw rate: finite differences over the second half of phase B
rates = [(res_b["path"][i][2] - res_b["path"][i - 1][2]) / dt_sample
         for i in range(len(res_b["path"]) // 2, len(res_b["path"]))]
w_ss = float(np.mean(rates))
w_std = float(np.std(rates))
ok_b = w_ss > 0.25 and w_std < 0.05 and drift < 0.08
print(f"[bridge] B1: steady yaw rate {w_ss:+.3f} rad/s "
      f"(std {w_std:.3f}) for cmd +0.5 (friction-limited) "
      f"-> {'OK' if ok_b else 'FAIL'}", flush=True)
print(f"[bridge] B2: drift={drift:.3f} m (expect ~0) "
      f"-> {'OK' if drift < 0.08 else 'FAIL'}", flush=True)
mae_b, ok_c_b = twist_consistency(res_b["path"], dt_sample, "wz")
print(f"[bridge] C(B): wz encoder vs truth MAE={mae_b:.4f} rad/s "
      f"-> {'OK' if ok_c_b else 'FAIL'}", flush=True)

ok = ok_a and ok_b and ok_c_a and ok_c_b
print(f"[bridge] {'PASSED' if ok else 'FAILED'}: bridge core "
      f"(cmd_vel -> wheels -> physics -> odom/tf)", flush=True)
simulation_app.close()
if not ok:
    raise SystemExit(1)
