#!/usr/bin/env python3
"""Semantically normalized comparison of ROS 1 vs ROS 2 launch parameters.

Raw extraction shows differences that are purely syntactic (XML needs
'true'/'3', Python needs True/3.0, and quoted strings). This script normalizes
both sides to comparable primitives and re-reports, so remaining differences
are genuine.
"""
import pathlib
import re

ROOT = pathlib.Path("/home/zar/Documents/phd/robot")
R1 = ROOT / "openmover_robot/openmover_ws/src/openmover/launch"
R2 = ROOT / "openmover_ws/src/openmover/launch"

KEYS = [
    "destination_frame", "cloud_destination_topic", "scan_destination_topic",
    "laserscan_topics", "angle_min", "angle_max", "angle_increment",
    "scan_time", "range_min", "range_max", "topic", "frame_id",
    "min_dist", "max_dist", "zero_shift", "from_zero", "output_scan",
    "output_cloud", "output_360", "with_checksum", "inverted", "reversed",
    "hard_resample", "soft_resample", "with_angle_filter", "error_circle",
    "error_scale", "type", "lidar_port", "local_port", "lidar_ip",
    "group_listener", "group_ip", "uuid", "rpm", "resample_res",
    "with_smooth", "with_deshadow", "alarm_msg", "direction",
]


def normalize(raw: str):
    """Strip Python quotes, normalize bools and numeric formatting."""
    s = raw.strip()
    # strip a single layer of matching quotes
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        s = s[1:-1]
    if s in ("true", "True"):
        return "true"
    if s in ("false", "False"):
        return "false"
    try:
        f = float(s)
        # render integral floats without a trailing .0 so 0 == 0.0 and -1 == -1.0
        return str(int(f)) if f == int(f) else repr(f)
    except ValueError:
        return s


def extract(path: pathlib.Path, python: bool):
    out = {k: set() for k in KEYS}
    txt = path.read_text(errors="replace")
    if not python:
        for m in re.finditer(r'<param\s+name="([^"]+)"\s+value\s*=\s*"([^"]*)"', txt):
            if m.group(1) in out:
                out[m.group(1)].add(normalize(m.group(2)))
    else:
        for m in re.finditer(r"'([A-Za-z_][A-Za-z0-9_]*)'\s*:\s*([^,\n}]+)", txt):
            if m.group(1) in out:
                out[m.group(1)].add(normalize(m.group(2)))
    return out


a = extract(R1 / "hardwares/bringup.launch", python=False)
b = extract(R2 / "hardwares/bringup.launch.py", python=True)

print("=" * 78)
print("bringup: ROS1 vs ROS2 launch params (semantically normalized)")
print("=" * 78)
same = differ = 0
diffs = []
for k in KEYS:
    va, vb = a[k], b[k]
    if not va and not vb:
        continue
    if va == vb:
        same += 1
        print(f"MATCH   {k:26} {sorted(va)}")
    else:
        # ROS2 builds driver params per-instance via a helper function, so the
        # literal values appear as variable names at the call site.
        placeholder = bool(vb) and all(not re.search(r"\d", x) for x in vb) \
            and any(x in ("topic", "frame_id", "local_port", "lidar_ip") for x in vb)
        tag = "PER-INSTANCE (arg passed at call site)" if placeholder else "DIFFER"
        if placeholder:
            print(f"{tag} {k:26} ROS1={sorted(va)}  ROS2=variable")
        else:
            differ += 1
            diffs.append(k)
            print(f"DIFFER  {k:26} ROS1={sorted(va)}  ROS2={sorted(vb)}")

print()
print(f"matching (normalized): {same}   genuine differences: {differ} {diffs}")
