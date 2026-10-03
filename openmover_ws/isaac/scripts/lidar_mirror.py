"""Shared RTX 2D LiDAR mirror of the real bluesea2 chain (Step 1.2 output).

Specs mirrored from the bluesea2 ROS config; validated in 12_probe_lidar.py:
- GMO is SPHERICAL in SENSOR frame: x=azimuth deg, y=elevation deg, z=range m
- native sweep phase-locked at ~+/-155 deg per 15 Hz tick -> re-bin to +/-90
- invalid returns carry range 0 -> filter r >= nearRange
- known asset bias: measured ranges read ~0.1 m SHORT of geometric truth
  (Example_Rotary_2D optical-origin offset); characterise in Step 1.5

Used by: 12_lidar_setup.py (gate), 14_scene_room.py, warehouse gate.
"""

import numpy as np

# NOTE: no top-level isaacsim imports here — this module is imported before
# SimulationApp starts; the sensor extension only exists after app startup.

# bluesea2 chain spec
N_SAMPLES = 600
AZ_MIN, AZ_MAX = -90.0, 90.0      # FOV (deg)
NEAR, FAR = 0.22, 10.0            # range (m)
RATE = 15.0                       # scan rate (Hz)

# Real mount poses relative to base_link
MOUNTS = {
    "front": {"translation": np.array([0.22015, 0.0, 0.07513]),
              "orientation": np.array([1.0, 0.0, 0.0, 0.0])},
    "rear":  {"translation": np.array([-0.22015, 0.0, 0.07513]),
              "orientation": np.array([0.0, 0.0, 0.0, 1.0])},  # yaw pi
}


def mount_bluesea2_pair(base_link_path: str) -> dict:
    """Create the two bluesea2-mirror LiDARs under the given base_link prim.

    Returns {name: LidarSensor}. Requires enable_motion_bvh=True in
    SimulationApp options when the robot moves.
    """
    from isaacsim.sensors.experimental.rtx import Lidar, LidarSensor

    sensors = {}
    for name, mount in MOUNTS.items():
        path = f"{base_link_path}/bluesea2_{name}"
        lidar = Lidar.create(
            path,
            config="Example_Rotary_2D",
            translations=mount["translation"].reshape(1, 3),
            orientations=mount["orientation"].reshape(1, 4),
            tick_rate=int(RATE),
            attributes={
                "omni:sensor:Core:nearRangeM": NEAR,
                "omni:sensor:Core:farRangeM": FAR,
                "omni:sensor:Core:scanRateBaseHz": RATE,
                "omni:sensor:Core:rangeAccuracyM": 0.01,
                "omni:sensor:Core:outputFrameOfReference": "SENSOR",
            },
        )
        sensors[name] = LidarSensor(lidar, annotators=["generic-model-output"])
    return sensors


def collect_scan(sensor, world, seconds: float,
                 parse_generic_model_output_data) -> dict:
    """Collect sweeps for one sensor while stepping physics+render.

    Returns {"frames": n, "scan": np.ndarray(600)} with the scan re-binned to
    N_SAMPLES closest returns over [AZ_MIN, AZ_MAX]; empty bins are NaN.
    """
    dt = world.get_physics_dt()
    n = int(seconds / dt)
    azs, rngs = [], []
    frames = 0
    for _ in range(n):
        world.step(render=True)
        data, _ = sensor.get_data("generic-model-output")
        if data is None:
            continue
        gmo = parse_generic_model_output_data(data)
        if gmo.numElements == 0:
            continue
        frames += 1
        azs.append(np.asarray(gmo.x))
        rngs.append(np.asarray(gmo.z))
    scan = np.full(N_SAMPLES, np.nan)
    if azs:
        az = np.concatenate(azs)
        rng = np.concatenate(rngs)
        win = (az >= AZ_MIN) & (az <= AZ_MAX) & (rng >= NEAR)
        edges = np.linspace(AZ_MIN, AZ_MAX, N_SAMPLES + 1)
        idx = np.clip(np.digitize(az[win], edges) - 1, 0, N_SAMPLES - 1)
        acc = np.full(N_SAMPLES, np.inf)
        np.minimum.at(acc, idx, rng[win])
        scan = np.where(np.isinf(acc), np.nan, acc)
    return {"frames": frames, "scan": scan}
