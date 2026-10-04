#!/usr/bin/env python3
"""Definitive message/service field-level A/B: ROS 1 (live) vs ROS 2 (port).

IMPORTANT METHODOLOGY NOTE
--------------------------
`rosmsg show` EXPANDS nested message types (a `std_msgs/Header` field is printed
as its three subfields seq/stamp/frame_id). Comparing that expanded output
against the ROS 2 .msg source text would fabricate differences that do not
exist. To compare like with like, both sides are reduced to their DECLARED
top-level fields:

  ROS 1: `rosmsg show -r` gives the non-recursive (raw) definition.
  ROS 2: the .msg source, which is already a top-level declaration.

Field names are compared exactly; type references are normalized for
ROS1->ROS2 naming conventions. Order is compared.
"""
import json
import pathlib
import re

ROOT = pathlib.Path("/home/zar/Documents/phd/robot")
ROS2_MSGS = ROOT / "openmover_ws/src/openmover_msgs/msg"
ROS2_SRVS = ROOT / "openmover_ws/src/openmover_msgs/srv"


def norm_name(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def norm_type(t):
    arr = ""
    m = re.match(r"^(.*?)\[(\d*)\]$", t)
    if m:
        t, n = m.group(1), m.group(2)
        arr = "[]" if n == "" else f"[{n}]"
    if "/" in t:
        pkg, base = t.split("/", 1)
        t = f"{pkg}/{norm_name(base)}"
    return t + arr


def parse_fields(lines):
    """Top-level (type, name) pairs, skipping comments, blanks and --- markers."""
    out = []
    for ln in lines:
        s = ln.split("#")[0].strip()
        if not s or s.startswith("---"):
            continue
        parts = s.split()
        if len(parts) >= 2:
            out.append((norm_type(parts[0]), parts[1]))
    return out


def load_ros1():
    txt = pathlib.Path("/tmp/ros1_msgdefs_raw.txt").read_text()
    m = re.search(r"RAW_MSGS=(\{.*\})", txt, re.S)
    msgs = {k.split("/")[1]: parse_fields(v.splitlines())
            for k, v in json.loads(m.group(1)).items()}

    txt2 = pathlib.Path("/tmp/ros1_srvdefs.txt").read_text()
    m2 = re.search(r"SRV_DEFS=(\{.*\})", txt2, re.S)
    srvs = {pathlib.Path(k).stem: v.splitlines()
            for k, v in json.loads(m2.group(1)).items()}
    return msgs, srvs


def load_ros2():
    msgs = {f.stem: parse_fields(f.read_text().splitlines())
            for f in sorted(ROS2_MSGS.glob("*.msg"))}
    srvs = {f.stem: f.read_text().splitlines()
            for f in sorted(ROS2_SRVS.glob("*.srv"))}
    return msgs, srvs


m1, s1 = load_ros1()
m2, s2 = load_ros2()

print("=" * 78)
print("MESSAGE field-level A/B (ROS 1 live, raw defs vs ROS 2 port sources)")
print("=" * 78)
mm = md = 0
for key in sorted(set(norm_name(k) for k in m1) & set(norm_name(k) for k in m2)):
    k1 = next(k for k in m1 if norm_name(k) == key)
    k2 = next(k for k in m2 if norm_name(k) == key)
    f1, f2 = m1[k1], m2[k2]
    if f1 == f2:
        mm += 1
        print(f"  MATCH  {k1:16} -> {k2:18} ({len(f1)} fields, name+type+order)")
    else:
        md += 1
        print(f"  DIFF   {k1:16} -> {k2:18}")
        print(f"         ROS1: {f1}")
        print(f"         ROS2: {f2}")
print(f"\n  messages matching: {mm}   differing: {md}")


def split_srv(lines):
    req, resp, cur = [], [], None
    cur = req
    for ln in lines:
        if ln.strip().startswith("---"):
            cur = resp
            continue
        cur.append(ln)
    return parse_fields(req), parse_fields(resp)


print()
print("=" * 78)
print("SERVICE field-level A/B (request + response)")
print("=" * 78)
sm = sd = 0
for key in sorted(set(norm_name(k) for k in s1) & set(norm_name(k) for k in s2)):
    k1 = next(k for k in s1 if norm_name(k) == key)
    k2 = next(k for k in s2 if norm_name(k) == key)
    r1, p1 = split_srv(s1[k1])
    r2, p2 = split_srv(s2[k2])
    if r1 == r2 and p1 == p2:
        sm += 1
        print(f"  MATCH  {k1:26} -> {k2:24} req={len(r1)} resp={len(p1)}")
    else:
        sd += 1
        print(f"  DIFF   {k1:26} -> {k2:24}")
        if r1 != r2:
            print(f"         req  ROS1: {r1}")
            print(f"         req  ROS2: {r2}")
        if p1 != p2:
            print(f"         resp ROS1: {p1}")
            print(f"         resp ROS2: {p2}")
print(f"\n  services matching: {sm}   differing: {sd}")
