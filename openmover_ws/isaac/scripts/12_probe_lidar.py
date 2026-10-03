"""Step 1.2 probe v2 — RTX 2D LiDAR data pipeline (static scene, no robot).

Fixes over v1:
  - enable_motion_bvh=True  (silences 'multi-tick without motion BVH' warning,
    which otherwise yields incorrect point clouds)
  - tick_rate matched to scanRateBaseHz (15 Hz) to silence the mismatch warning
  - NO validStart/EndAzimuth restriction: capture the full 360 deg so we can
    establish the native azimuth behaviour, then filter/rebin to the bluesea2
    +/-90 deg window in software.

GMO format (confirmed in v1): SPHERICAL, SENSOR frame ->
    x = azimuth (deg), y = elevation (deg), z = range (m)

Scene: lidar at z=0.5 facing +x, three thin walls at 4 m:
    front @ +x -> azimuth ~ 0, left @ +y -> +90, right @ -y -> -90

Run: ~/isaacsim/python.sh openmover_ws/isaac/scripts/12_probe_lidar.py
"""

import time

import numpy as np

from common import preflight

preflight("lidar_probe")

T0 = time.time()
from isaacsim import SimulationApp  # noqa: E402

simulation_app = SimulationApp({"headless": True, "enable_motion_bvh": True})
print(f"[probe] app up in {time.time() - T0:.1f} s", flush=True)

import omni  # noqa: E402
from isaacsim.core.experimental.objects import Cube  # noqa: E402
from isaacsim.sensors.experimental.rtx import (  # noqa: E402
    Lidar,
    LidarSensor,
    parse_generic_model_output_data,
)

# --- scene: three walls within the forward hemisphere ----------------------
Cube("/World/wall_front", positions=np.array([4.0, 0.0, 1.0]),
     scales=np.array([0.2, 8.0, 2.0]))
Cube("/World/wall_left", positions=np.array([0.0, 4.0, 1.0]),
     scales=np.array([8.0, 0.2, 2.0]))
Cube("/World/wall_right", positions=np.array([0.0, -4.0, 1.0]),
     scales=np.array([8.0, 0.2, 2.0]))
print("[probe] scene: 3 walls at 4 m (front/left/right)", flush=True)

# --- lidar: full 360 deg, bluesea2 range + rate ----------------------------
lidar = Lidar.create(
    "/World/lidar_probe",
    config="Example_Rotary_2D",
    translations=np.array([0.0, 0.0, 0.5]),
    tick_rate=15,
    attributes={
        "omni:sensor:Core:nearRangeM": 0.22,
        "omni:sensor:Core:farRangeM": 10.0,
        "omni:sensor:Core:scanRateBaseHz": 15,
        "omni:sensor:Core:outputFrameOfReference": "SENSOR",
    },
)
prim = lidar.prims[0]
print(f"[probe] lidar prim: {lidar.paths[0]}", flush=True)
for key in ("omni:sensor:Core:nearRangeM", "omni:sensor:Core:farRangeM",
            "omni:sensor:Core:scanRateBaseHz", "omni:sensor:tickRate",
            "omni:sensor:Core:validStartAzimuthDeg",
            "omni:sensor:Core:validEndAzimuthDeg"):
    attr = prim.GetAttribute(key)
    val = attr.Get() if attr and attr.IsValid() else "<missing>"
    print(f"    {key} = {val}", flush=True)

sensor = LidarSensor(lidar, annotators=["generic-model-output"])

# --- collect ---------------------------------------------------------------
timeline = omni.timeline.get_timeline_interface()
timeline.play()

xs, ys, zs = [], [], []
per_frame = []  # (az_min, az_max) per frame
n_frames = 60
frames_with_data = 0
t_collect = time.time()
for i in range(n_frames):
    simulation_app.update()
    data, _info = sensor.get_data("generic-model-output")
    if data is None:
        continue
    gmo = parse_generic_model_output_data(data)
    if gmo.numElements == 0:
        continue
    frames_with_data += 1
    if frames_with_data == 1:
        print(f"[probe] GMO coord type   = {gmo.elementsCoordsType}", flush=True)
        print(f"[probe] GMO frame of ref = {gmo.frameOfReference}", flush=True)
    _x = np.asarray(gmo.x)
    per_frame.append((float(_x.min()), float(_x.max())))
    xs.append(_x)
    ys.append(np.asarray(gmo.y))
    zs.append(np.asarray(gmo.z))
    if time.time() - t_collect > 180:
        print("[probe] wall-clock cap hit", flush=True)
        break
timeline.stop()
print(f"[probe] frames with data: {frames_with_data}/{n_frames} "
      f"in {time.time() - t_collect:.1f} s", flush=True)

if not xs:
    print("[probe] RESULT: NO DATA", flush=True)
    simulation_app.close()
    raise SystemExit(1)

az = np.concatenate(xs)          # azimuth deg (SPHERICAL)
el = np.concatenate(ys)          # elevation deg
rng = np.concatenate(zs)         # range m
print(f"[probe] total points: {az.size}", flush=True)
print(f"[probe] azimuth   : {az.min():.2f} .. {az.max():.2f} deg", flush=True)
print(f"[probe] elevation : {el.min():.2f} .. {el.max():.2f} deg", flush=True)
print(f"[probe] range     : {rng.min():.3f} .. {rng.max():.3f} m", flush=True)
print(f"[probe] range=0 pts: {int((rng == 0).sum())} | "
      f"r<0.22: {int((rng < 0.22).sum())} | r>=10: {int((rng >= 10).sum())}",
      flush=True)
pf = np.asarray(per_frame)
if pf.size:
    lo, hi = pf[:, 0], pf[:, 1]
    print(f"[probe] per-frame az window: min={lo.min():.1f}..{lo.max():.1f}, "
          f"max={hi.min():.1f}..{hi.max():.1f} "
          f"(span {float((hi - lo).mean()):.1f} deg avg)", flush=True)
    uniq = np.unique(np.round(pf, 1), axis=0)
    print(f"[probe] distinct frame windows: {uniq.shape[0]} "
          f"({'phase-locked' if uniq.shape[0] <= 2 else 'drifting'})", flush=True)

# --- azimuth coverage histogram (15 deg bins) ------------------------------
bins = np.arange(-180, 181, 15)
hist, _ = np.histogram(az, bins=bins)
print("[probe] azimuth histogram (15 deg bins):", flush=True)
for h, b0, b1 in zip(hist, bins[:-1], bins[1:]):
    bar = "#" * min(60, h // max(1, hist.max() // 60))
    print(f"    [{b0:5.0f},{b1:5.0f}) {h:9d} {bar}", flush=True)

# --- Cartesian cross-check (front wall should be at x_cart ~ +4) ---------
el_r = np.radians(el)
az_r = np.radians(az)
xc = rng * np.cos(el_r) * np.cos(az_r)
yc = rng * np.cos(el_r) * np.sin(az_r)
front = (np.abs(az) < 20) & (rng > 1.0)
print(f"[probe] points near azimuth 0 (|az|<20, r>1): {front.sum()}", flush=True)
if front.sum():
    print(f"[probe]   mean Cartesian x = {xc[front].mean():.2f} m (expect ~ +4)",
          flush=True)
left = (np.abs(az - 90) < 20) & (rng > 1.0)
if left.sum():
    print(f"[probe] points near az +90: {left.sum()}, mean y = {yc[left].mean():.2f} "
          f"(expect ~ +4)", flush=True)
right = (np.abs(az + 90) < 20) & (rng > 1.0)
if right.sum():
    print(f"[probe] points near az -90: {right.sum()}, mean y = {yc[right].mean():.2f} "
          f"(expect ~ -4)", flush=True)

# --- rebin to bluesea2 spec: 600 samples over [-90, +90] ------------------
N = 600
az_min, az_max = -90.0, 90.0
edges = np.linspace(az_min, az_max, N + 1)
centers = 0.5 * (edges[:-1] + edges[1:])
win = (az >= az_min) & (az <= az_max) & (rng > 0.0)
ranges = np.full(N, np.nan)
idx = np.clip(np.digitize(az[win], edges) - 1, 0, N - 1)
# nearest return per bin (min range = closest obstacle, like a real lidar)
np.minimum.at(np.where(np.isnan(ranges), np.inf, ranges), idx, rng[win])
_tmp = np.full(N, np.inf)
np.minimum.at(_tmp, idx, rng[win])
ranges = np.where(np.isinf(_tmp), np.nan, _tmp)
valid = (~np.isnan(ranges)).sum()
print(f"[probe] rebinned scan: {N} bins over +/-90 deg, "
      f"{valid} bins filled ({100.0 * valid / N:.0f}%)", flush=True)
filled = ranges[~np.isnan(ranges)]
if filled.size:
    print(f"[probe] rebinned range: {filled.min():.3f} .. {filled.max():.3f} m",
          flush=True)

ok = frames_with_data > 0 and win.sum() > 0 and valid > 100
print(f"[probe] {'PASSED' if ok else 'NEEDS WORK'}: usable scan data "
      f"({'can' if ok else 'cannot'} build a 600-sample flat scan)", flush=True)
simulation_app.close()
