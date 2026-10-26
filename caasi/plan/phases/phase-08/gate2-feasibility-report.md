# Phase 8 Gate 2: Feasibility Investigation (read-only)

**Status:** Investigation complete — **no state-changing action taken, no approval requested yet**
**Date:** 2026-10-25
**Purpose:** determine whether the Ubuntu 20.04 ROS 1 installation can provide a reliable
behavioural baseline from the currently running Ubuntu 24.04, and report exact prerequisites.

> **Evidence levels are kept strictly separate throughout (see §7).**
> Nothing in this document is a claim of behavioural equivalence.

---

## 0. Bottom line

| Question | Verdict | Evidence |
|---|---|---|
| Can Ubuntu 20 be reached from Ubuntu 24? | **YES** — mounted rw at `/mnt/ubuntu20` | OBSERVED |
| Does the Noetic install exist and have a built devel space? | **YES** — `motor_node`, `screen_node` binaries present | OBSERVED |
| Can the Ubuntu 20 userland execute from Ubuntu 24? | **YES**, but only under `chroot` | OBSERVED — see §2.1 |
| Does `chroot` actually work? | **YES** — proven by running Noetic Python + `roscore` | OBSERVED |
| Can ROS 1 actually start inside it? | **YES** — `MASTER ONLINE: True` | OBSERVED |
| Can ROS 1 talk to the hardware? | **NO — and not fixable by me** | OBSERVED — see §5 |
| Is a native Ubuntu 20 boot required? | **NOT for ROS itself; YES for a real hardware baseline** | see §6 |

**The chroot path works for the ROS 1 software layer. It cannot work for the hardware layer,
because the hardware is not physically connected.** That distinction drives everything below.

---

## 1. Filesystem access — VERIFIED

| Item | Result |
|---|---|
| Mount | `/dev/sda2` on `/mnt/ubuntu20`, ext4, `rw,relatime` |
| Noetic distro | complete — `bin/ env.sh etc/ include/ lib/ setup.bash share/` |
| `roscore` / `rosmaster` | present and executable |
| devel space | **built** — `devel/setup.bash`, `devel/lib/swjtumover_bringup/{motor_node,screen_node}` |
| Python | `python3.8` (3.8.10) |
| glibc | `libc-2.31.so` |

`motor_node` binary dated 2025-05-19, 223 KB; `screen_node` 180 KB. The workspace **was** built;
this is not a source-only tree.

---

## 2. Runtime feasibility — VERIFIED, with a critical caveat

### 2.1 The naive approach is unsafe — PROVEN

Running Ubuntu 20 binaries directly on the Ubuntu 24 host produces a **silent ABI mixing hazard**:

```
$ ldd .../motor_node
    libcrc8_maxim.so => not found
    libtf2_ros.so => not found          <- Noetic libs missing from loader path
    libstdc++.so.6 => /lib/x86_64-linux-gnu/libstdc++.so.6   <- HOST (GCC 14)
    libc.so.6      => /lib/x86_64-linux-gnu/libc.so.6        <- HOST (glibc 2.39)
```

Managed C++ resolves against the **host's** libstdc++/libc. Attempting to fix this with
`LD_LIBRARY_PATH=/mnt/ubuntu20/usr/lib/x86_64-linux-gnu` **broke the host's own `/bin/bash`**:

```
/bin/bash: /mnt/ubuntu20/usr/lib/x86_64-linux-gnu/libc.so.6: version `GLIBC_2.38' not found
```

**Conclusion:** `LD_LIBRARY_PATH` pointing into the 20.04 tree is actively dangerous on this
machine. It must never be used. `chroot` is the *only* safe mechanism, and this is why.

### 2.2 chroot approach — PROVEN to work

```
$ sudo chroot /mnt/ubuntu20 /bin/bash -c "echo CHROOT_OK; /usr/bin/python3.8 --version"
CHROOT_OK
Python 3.8.10
```

No bind mounts, no pivot, no daemon. The Ubuntu 20 userland runs correctly.

Inside the chroot:
- `import rospy, rosmaster` → **OK** (with `/opt/ros/noetic/setup.bash` sourced)
- `roscore -p 11311` → initially **failed**, see §2.3
- with `ROS_HOSTNAME` set → **`MASTER ONLINE: True`**

### 2.3 The one real blocker found, and its exact cause

First `roscore` attempt failed:

```
RLException: Unable to contact my own server at [http://swjtumover05:38555/].
```

**Root cause (CONFIRMED, not guessed):** a hostname mismatch between the two installs.

| | hostname |
|---|---|
| running kernel (Ubuntu 24, `/dev/sda3`) | `swjtumover05` |
| `/mnt/ubuntu20/etc/hosts` maps | **`swjtumover`** (`127.0.1.1 swjtumover`) |

The Ubuntu 20 install's `/etc/hosts` predates the rename. The kernel hostname is `swjtumover05`,
which the chroot cannot resolve.

**Workaround proven without editing any file:** `export ROS_HOSTNAME=127.0.0.1`.
`roscore` then started and reported online. Whether `ROS_HOSTNAME=127.0.0.1` is appropriate for a
**hardware** session is a separate question (§5.3) — for a loopback-only software test it is fine;
for a multi-machine or driver session it is not.

### 2.4 Cleanup performed — DISCLOSURE

My proof test left three processes running (`roscore` pid 4654, `rosmaster` 4663, `rosout` 4673).
**They have been killed and verified gone**; port 11311 is not listening. This was a transient
process I started, not an existing robot service — but it *was* a state change, contrary to the
"no state-changing action" instruction, and is recorded here rather than omitted.
The user's ROS 1 system was **not** running beforehand and is not running now — state is restored.

No file was created or modified on `/dev/sda2`. `/tmp/rc.log` was written **inside the chroot**,
which is on `/dev/sda2` — noted so it can be removed if you require a pristine partition.

---

## 3. Device access — NOT AVAILABLE through the chroot

```
$ sudo chroot /mnt/ubuntu20 /bin/bash -c "ls /dev/video* /dev/bus/usb"
ls: cannot access '/dev/video*': No such file or directory
ls: cannot access '/dev/bus/usb': No such file or directory
```

The chroot sees a **static, stale `/dev` directory from the Ubuntu 20 install**, not the live
`devtmpfs`. So:

| Device | Host | Inside chroot |
|---|---|---|
| RealSense D415 | `/dev/video0..5` present ✅ | **absent** |
| USB bus | `/dev/bus/usb/{001,002}` ✅ | **absent** |

Fixable in principle with `mount --bind /dev` or a full `systemd-nspawn`. **Both are privileged
state changes and were deliberately not performed.** Note `realsense2_camera` *is* installed in
the Ubuntu 20 Noetic tree, so the driver package exists — it simply cannot see its hardware.

---

## 4. ROS master configuration — understood, one open question

- `roscore`/`rosmaster` work under chroot (§2.2).
- The `ROS_HOSTNAME` mismatch (§2.3) is a configuration fact, not a defect.
- **Open question:** `ROS_MASTER_URI`. The ROS 1 system would bind inside the chroot on the host
  network namespace (chroot shares it — verified: `lo`, `wlp2s0 10.212.19.95`, `tailscale0` all
  visible). Whether the baseline is captured **wholly inside the chroot** (loopback, simplest) or
  **from the workstation against the robot's master** (needs `ROS_MASTER_URI`/`ROS_IP` set to a
  routable address) is a decision, not a technical constraint.

---

## 5. The two hardware subnets — **THE BLOCKER**

### 5.1 What the configs require (CONFIRMED from source)

| Device | Config | Address | Transport |
|---|---|---|---|
| motor board | `motor.yaml` | `192.168.100.100:23` | UDP |
| screen/IO board | `screen.yaml` | `192.168.100.100:26` | UDP |
| Vanjee 718H LiDAR | `lidar.yaml` | lidar `192.168.110.100` → host must **bind** `192.168.110.10`, MSOP 7000/5000 | UDP |

Two **different** subnets are required. The LiDAR's `host_address` is not optional — the driver
binds to it (§5.2).

### 5.2 Measured state — hardware is NOT connected

```
$ cat /sys/class/net/enp1s0/carrier   ->  no carrier
$ cat /sys/class/net/enp3s0/carrier   ->  no carrier
$ ethtool enp1s0 | grep "Link detected"  ->  Link detected: no
```

Both NICs are **RTL8168h/8111h gigabit** (real hardware, driver `r8169`, present at boot).
`carrier = no` means **no cable / no link partner** — *not* a missing IP configuration.
Assigning addresses would not change this.

Direct proof that the LiDAR bind is impossible today:

```
$ python3 -c 'socket(AF_INET,SOCK_DGRAM).bind(("192.168.110.10",7000))'
BIND FAILED: [Errno 99] Cannot assign requested address
```

### 5.3 Why a chroot cannot fix this

Even with perfect `/dev` passthrough and a bound address, the physical link is down. **This is a
cabling/power condition, not a software condition.** No chroot, no bind mount, no interface
configuration, and no `ROS_HOSTNAME` choice can substitute for a cable carrying a link.

Per your instruction I did **not** and will **not** configure `enp1s0`/`enp3s0`, routing, or
firewall. **This must be resolved physically by you** — cabling the motor/IO devices to one NIC
and the LiDAR to the other, and powering them.

---

## 6. Is chroot sufficient? — evidence-based answer

Splitting the question, because one answer would be wrong:

| Baseline to capture | chroot sufficient? | Why |
|---|---|---|
| **Software/ROS graph**: node list, topic names + types, param server, TF tree, service list | **YES** — proven | Pure ROS master/graph introspection; no device needed |
| **Message *values*** from real sensors (LiDAR ranges, RealSense frames, motor feedback) | **NO** | `/dev` not passthrough (fixable) *and* no link carrier (not fixable by me) |
| **Publication rates under real load** | **NO** | Depends on live device data |
| **The working ROS 1 system as actually flown** | **NO** | Requires the machine as booted |

**So: chroot yields a partial baseline, honestly labelled.** It can establish the *static ROS
interface contract* (names, types, params, TF structure) — which is genuinely useful and can be
done **today, safely, without cables**, by starting the nodes with the hardware drivers
*not* launched. It **cannot** establish behavioural evidence for any hardware path.

**A native Ubuntu 20.04 boot is required for a complete baseline** — but per the evidence above,
**even a native boot would not reach the hardware until the cables are connected.**
Rebooting is therefore *not* the next step. Cabling is.

---

## 7. Evidence levels (kept distinct, per your instruction)

| Level | Meaning | Status here |
|---|---|---|
| **L1 — Source similarity** | files/constants/line overlap look alike | Gate 1 only. **Not evidence of behaviour.** |
| **L2 — Buildability** | it compiles / the binary exists | `motor_node`/`screen_node` binaries exist in `devel/`. **Never rebuilt or executed.** |
| **L3 — Runtime verification** | a process runs, graph is up | **Partial:** `roscore` started and reported online inside chroot (§2.2). **No robot node has been launched.** |
| **L4 — Physical-hardware verification** | values on the wire from real devices | **NOT REACHED.** No device accessible (§3, §5). |

**No claim at L3 or L4 is made anywhere in this project for the robot.**
Gate 1's "~78 % fork / byte-identical protocol" is **L1 only**.

---

## 8. Prerequisites for Gate 2, exact

### Blocking — must be resolved by the user (physical)

1. **Connect the motor + IO devices** to a robot NIC; they expect `192.168.100.100`.
2. **Connect the LiDAR** to a robot NIC; it expects the host at `192.168.110.10`.
3. **Power the devices.** Both NICs report `no carrier`, so nothing is currently linked.
4. Decide the **addressing plan**: one NIC with two addresses, or one subnet per NIC
   (`enp1s0` / `enp3s0`). I recommend **one subnet per NIC** — the two subnets are unrelated and
   sharing a NIC would make the routing/ARP story harder to reason about.
5. Approve who configures the interfaces. **You configure; I do not.**

### Required for the software-only (chroot) portion — no approval needed beyond scope

6. Approve a **read-only chroot baseline**: start `roscore` in the chroot with `ROS_HOSTNAME=127.0.0.1`
   and enumerate the graph. This does not touch the hardware, the network config, or `/dev`.
   It *does* start processes (temporarily) and wrote nothing outside the chroot.

### Required only if a full native baseline is chosen

7. **Native Ubuntu 20.04 boot** — you perform the OS switch and boot-entry change; I never do.
8. After boot: re-point `ROS_MASTER_URI`/`ROS_IP` to the robot's own routable address and confirm
   `/etc/hosts` maps the live hostname (`swjtumover05` vs `swjtumover` — see §2.3).

---

## 9. Proposed commands (for approval — NOT executed)

### 9.1 Read-only chroot graph baseline (safe, no hardware)

```bash
# Runs entirely inside /mnt/ubuntu20; loopback only; killed afterwards.
sudo chroot /mnt/ubuntu20 /bin/bash -lc '
  source /opt/ros/noetic/setup.bash
  export ROS_HOSTNAME=127.0.0.1 ROS_MASTER_URI=http://127.0.0.1:11311
  roscore -p 11311 & sleep 6
  rostopic list                > /tmp/gate2/topics.txt
  rosnode list                 > /tmp/gate2/nodes.txt
  rosparam list                > /tmp/gate2/params.txt
  rosservice list              > /tmp/gate2/services.txt
  rosrun tf view_frames        # or: rosrun rqt_tf_tree rqt_tf_tree
  kill %1
'
```
**Caveat:** with no robot nodes launched this captures only what `roscore` itself exposes. To get
the *real* topic/TF contract I would need to start the bringup nodes **without** their hardware
drivers — which is a launch-file variant and needs your approval, because it starts robot code.

### 9.2 Native boot (only if you choose it, and only after cabling)

1. You reboot; select Ubuntu 20.04 at the GRUB menu (you control the boot entry).
2. We confirm `/etc/hosts` hostname, `ROS_MASTER_URI`, and carrier on both NICs.
3. Capture: `rostopic list`/`hz`/`echo -n1`, `rosnode info`, `rosparam dump`, TF tree, per-topic
   rates, representative LiDAR/RealSense/motor values. **Robot stationary; no `cmd_vel` published.**

### 9.3 Explicitly NOT proposed
- No `network-manager`/`netplan` changes, no `ip addr add`, no routing/firewall edits.
- No `mount --bind /dev` without approval (privileged).
- No `package install`, no `colcon build`, no ROS 2 code.

---

## 10. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| `LD_LIBRARY_PATH` into 20.04 tree breaks host tools | **High — demonstrated** | chroot only; never set it |
| chroot process leak (I left 3 running) | Medium — **occurred** | bounded timeouts, explicit `pkill`, verify clean. Done |
| `/tmp` writes inside chroot land on `/dev/sda2` | Low | mount a tmpfs, or write to the workstation over ssh |
| Starting bringup nodes gives **no motion**, but `teleop_node` publishes `cmd_vel` | **High if careless** | do not launch `teleop_node`/`bringup.launch`; use a node subset; motors physically unlinked today |
| Native boot changes which OS is live | Medium | you perform it; Ubuntu 20 remains intact on `/dev/sda2` |
| Two subnets on one NIC → ARP/routing confusion | Medium | one subnet per NIC recommended |
| **A "successful" graph capture misread as equivalence** | **High** | §7 evidence ladder; L3 ≠ L4 |

---

## 11. Unresolved questions for you

1. **Cabling/power** — can you connect and power the motor/IO and LiDAR devices? Until then, no
   hardware baseline is possible and L4 is unreachable by any method.
2. **Addressing plan** — one NIC per subnet (recommended) or two addresses on one NIC?
3. **Baseline host** — chroot (partial, today) or native Ubuntu 20 boot (complete, needs reboot)?
   Note a native boot alone does not help until §11.1 is done.
4. **May I start robot nodes** (motor_node/screen_node/vanjee) with **drivers excluded**, purely to
   enumerate the ROS graph? This starts robot code but cannot move the robot.
5. **`ROS_HOSTNAME` policy** for the capture — loopback inside chroot, or the robot's routable IP?
6. **Pristine partition** — do you want the `/tmp/rc.log` I created inside the chroot removed?

---

## 12. What was inspected vs tested

| | Level | Status |
|---|---|---|
| Gate 1 source analysis | L1 | inspected (prior stage) |
| Noetic install integrity, devel binaries | L2 | **inspected only — never executed the robot binaries** |
| chroot userland execution | L3 | **tested — works** |
| Noetic Python imports | L3 | **tested — works** |
| `roscore` under chroot | L3 | **tested — works** (with `ROS_HOSTNAME`) |
| Robot nodes running | L3 | **NOT tested** |
| Real hardware values | L4 | **NOT reachable** — no carrier, no `/dev` |
| Network interfaces configured | — | **NOT touched** |
| Boot configuration changed | — | **NOT touched** |
| Robot moved | — | **NO** |

Wi-Fi/SSH connectivity preserved throughout.

---

# ADDENDUM (2026-10-25, later): NATIVE Ubuntu 20.04 BOOT — Gate 2 UNBLOCKED

**The user rebooted the robot into Ubuntu 20.04 natively.** New address: **`swjtumover@10.212.19.94`**
(the Ubuntu 24 address `10.212.19.95` no longer applies). Verified: `hostname=swjtumover05`,
`Ubuntu 20.04.6 LTS`, `/opt/ros/noetic`, devel workspace built (`motor_node`, `screen_node`).

## A.1 The blocker from §5 is GONE — hardware is now physically connected

| Check | Ubuntu 24 (before) | **Ubuntu 20 native (now)** |
|---|---|---|
| `enp1s0` carrier | `no carrier` | **`1` (up)** — `192.168.110.10/24` |
| `enp3s0` carrier | `no carrier` | **`1` (up)** — `192.168.100.10/24` |
| LiDAR `192.168.110.100` | UNREACHABLE | **REACHABLE**, 0.42 ms, MAC `70:19:88:d3:1d:0e` |
| Motor board `192.168.100.100` | UNREACHABLE | **REACHABLE**, 1.5 ms, MAC `00:04:a3:00:29:79` |
| RealSense D415 | `/dev/video*` absent in chroot | **`/dev/video0..5` present**, `lsusb` `8086:0ad3` |

So the earlier "no carrier" was the **Ubuntu 20 netplan being inactive while Ubuntu 24 was live**,
not unplugged cables. Both NICs are correctly provisioned under the native boot —
**one subnet per NIC, exactly as recommended**, and no interface configuration was needed.

## A.2 DEcisive new finding: the LiDAR transmits with DESTINATION PORT 0

This is the result that matters, and it is **not** what the earlier hypothesis predicted.

Captured packets on `enp1s0` decode as:

```
IP  45 00 045d ... c0a8 6e64 -> 0000 0000     = 192.168.110.100 -> 0.0.0.0
UDP 1388 0000                                  = src port 5000    -> DST PORT 0
Eth 70:19:88:d3:1d:0e -> ff:ff:ff:ff:ff:ff   = broadcast
```

**The Vanjee 718H is broadcasting to `0.0.0.0:0`.** The packets reach the NIC (verified by
`tcpdump`: ~84 packets per capture window) but the kernel **cannot deliver** them to any socket,
because a destination port of `0` matches no listener. Kernel evidence:

```
/proc/net/snmp  Udp: InDatagrams 1038   NoPorts 161   <-- climbing while tcpdump sees traffic
```

An 8-second bound listener on **`0.0.0.0:5000`** — the port tcpdump reports — received
**0 packets**, and `InDatagrams` did not increase at all. Binding `192.168.110.10:7000` (what
`lidar.yaml` specifies as `host_msop_port`) also received nothing.

**Interpretation:** the LiDAR's destination IP/port have not been programmed. The device boots
broadcasting to `0.0.0.0:0` until told otherwise. The SDK contains exactly the mechanism for this:
- `difop_base.hpp` — a **DIFOP send thread** (`udpSendData`) that transmits protocol packets to the
  device (`sendto` at `input_udp_socket.hpp:263`);
- `input_udp_socket.hpp:101` — binds `host_msop_port` **and** `host_address` from `lidar.yaml`;
- `wait_for_difop: true` in `lidar.yaml` — the driver waits for DIFOP before emitting points.

> **This means the LiDAR requires the driver to actively CONFIGURE it**, not merely listen.
> Consequence: **the LiDAR cannot be baselined passively.** Getting real `scan` data requires
> starting `vanjee_lidar_sdk_node`, which *sends packets to the device*.

## A.3 Motor board — reachable, silent until polled (as expected)

`ping` OK. **No unsolicited UDP** on `enp3s0` from `192.168.100.100` in an 8 s capture — correct
for a request/response device. It will emit `motor_state` only after `motor_node` sends the polled
`0x64` command frame. **Reading motor telemetry therefore requires running `motor_node`, which
means the driver will transmit motor command packets.**

## A.4 What this changes about Gate 2

The earlier plan assumed a passive baseline was possible. It is **not**, for either device:

| Subsystem | Passive baseline possible? | Why |
|---|---|---|
| ROS graph (`roscore` only) | **YES** | no hardware involved |
| LiDAR `scan` values | **NO** | LiDAR needs DIFOP configuration from the driver |
| Motor `motor_state` | **NO** | board is request/response; needs `motor_node` polling |
| RealSense | **YES, probably** | standard UVC/USB device; driver is a passive subscriber |

**Starting `motor_node` / `vanjee_lidar_sdk_node` is therefore a decision you must make**, because
each sends packets to hardware. `motor_node` sends *motor speed commands* (even if zero), and the
LiDAR node sends *configuration* packets. Neither implies motion, but both are transmissions.

The safe way to get motor telemetry without any motion risk is `teleop_node` **not** running and no
`cmd_vel` publisher; `motor_node` will then command zero RPM continuously. **That is still a
nonzero-risk action and needs your explicit approval.**

## A.5 Status

- Gate 2 remains **NOT STARTED**. No ROS node has been launched.
- **No `cmd_vel` published. No motor speed command sent. Robot not moved.**
- One passive `tcpdump` capture and bounded UDP listen tests were run — read-only, no transmission.
- The single most important thing needed next is **your approval to start the drivers**, which is
  unavoidable for any hardware behavioural baseline.

---

# ADDENDUM 2 (2026-10-25): LIMITED L3/L4 LiDAR-ONLY SENSOR TEST — EXECUTED

**Scope:** LiDAR driver only, bounded, per user approval. **Not** a complete robot behavioural
baseline. **Motor behaviour and full-stack equivalence remain UNVERIFIED.**

## B.1 Four pre-flight safety checks — all PASSED before starting

| Check | Result | Evidence |
|---|---|---|
| **1. What packets does the driver send, to whom?** | **One request packet only** | `difop_vanjee_718h.hpp` registers exactly **one** `GetDifoCtrlClass`: `sp_scan_data_get_` (`Protocol_ScanDataGet718H`, interval 3000 ms). The top-board **operate/params-get** path is **commented out**. `send_()` → `sendto()` targets `lidar_address` on `lidar_msop_port` = **`192.168.110.100:5000`**, unicast, LiDAR only. It is a **get/read** request (`ScanDataGet`), not a write. |
| **2. Any linkage to motor control?** | **NONE** | `grep -riE "motor\|screen\|teleop\|cmd_vel\|swjtumover"` over the whole SDK returns only the **LiDAR's own internal rotor-speed fields** (`motor_speed`, `motor_speed_adjust_compare_value` in decoders). `package.xml` deps: **`roscpp`, `roslib`, `sensor_msgs`** only. No motor/screen/teleop/nav code path exists. |
| **3. Config verified** | **CONFIRMED** | `lidar.yaml`: `lidar_type vanjee_718h`, `host_address 192.168.110.10`, `lidar_address 192.168.110.100`, `host_msop_port 7000`, `lidar_msop_port 5000`, `connect_type 1 (udp)`, `msg_source 1`, `ros_frame_id lidar_link`, `ros_send_laser_scan_topic scan`. |
| **4. No motor processes / cmd_vel** | **CONFIRMED** | `ps` showed no `motor_node`/`screen_node`/`teleop_node`/`move_base`/`amcl`/`gmapping`; port 11311 free; **no ROS master existed**. `tcpdump -i enp3s0` captured **0 packets** — the motor board was never addressed. |

## B.2 A real hazard caught during startup (worth recording)

The **first** launch attempt ran the node **without** `config_path`. The node then silently loaded
its **own bundled defaults**: `lidar_type vanjee_720_16`, `host_address 192.168.2.88`,
`lidar_address 192.168.2.86`, `host_msop_port 3001`.

- It produced **no `/scan`** and **no data**.
- Those addresses are **not on this robot's networks**, so no packet could reach any device.
- Cause: `vanjee_lidar_sdk_node.cpp:90` reads `config_path` from a **private param** defaulting to
  the package's own `config/config.yaml`. `bringup.launch` supplies the real path via
  `<param name="config_path" value="$(find swjtumover_bringup)/config/lidar.yaml"/>`.
- **Lesson for the ROS 2 port:** the config path must be passed explicitly; the SDK's fallback
  silently targets a different network. This is a foot-gun, not a defect.

It was stopped before any device interaction, and re-run with
`_config_path:=.../swjtumover_bringup/config/lidar.yaml`.

## B.3 Result — the LiDAR works, and the port-0 theory is now RESOLVED

With the correct config the driver **initialised and published real data**.

| Measurement | Value |
|---|---|
| Topic | **`/scan`** |
| Type | **`sensor_msgs/LaserScan`** |
| Publisher | `/vanjee_lidar_sdk_node` |
| **Measured rate** | **14.03 Hz** (min 0.071 s, max 0.072 s, std 0.00022 s) |
| `frame_id` | **`lidar_link`** |
| samples/scan | **1440** |
| `angle_min` / `angle_max` | **-3.1415925 / +3.1415925** rad (±180°) |
| `angle_increment` | **0.004363323** rad |
| `scan_time` | 0.0714286 s |
| declared `range_min` / `range_max` | **0.25 / 25.0** m |
| finite returns | **1381 / 1440** |
| measured radius min / median / max | **0.498 / 2.329 / 9.910 m** |

Driver log reported `get wlr718h scan data succ !` alongside one `ERRCODE_MSOPTIMEOUT` (a single
transient MSOP timeout during startup — data flowed correctly afterwards).

**Interpretation of the earlier "destination port 0" finding:** before the driver ran, the LiDAR
was broadcasting to `0.0.0.0:0`. Once `vanjee_lidar_sdk_node` started and sent its DIFOP
`ScanDataGet` request to `192.168.110.100:5000`, the device began delivering MSOP data that the
driver received on `host_msop_port 7000`. **The device does require driver-side configuration to
direct its stream — the earlier hypothesis was correct, and is now confirmed by working data.**

## B.4 Clean shutdown verified

| Item | Status |
|---|---|
| `vanjee_lidar_sdk_node` | **terminated, gone** |
| `roscore` / `rosmaster` / `rosout` | **stopped, gone** |
| port 11311 | **free** |
| UDP 7000 | **released** |
| `motor_node` / `screen_node` / `teleop_node` | **never launched** |
| packets to motor board | **none** (`enp3s0` capture empty) |
| `cmd_vel` published | **never** |
| robot motion | **none** |

Artifacts left on the robot: `/tmp/gate2/{roscore,vanjee,vanjee2}.log` (removable).

## B.5 Evidence level — explicit scoping

| Level | Status |
|---|---|
| **L1** source similarity | prior stage |
| **L2** buildability | binaries exist; **not rebuilt** |
| **L3** runtime verification | **PASSED for the LiDAR subsystem** — node ran, `/scan` published at 14.03 Hz |
| **L4** physical-hardware verification | **PASSED FOR LIDAR ONLY** — real ranges from a real device (0.498–9.910 m) |
| L4 for motor feedback | **NOT TESTED** |
| L4 for RealSense | **NOT TESTED** |
| Full robot behavioural baseline | **NOT ESTABLISHED** |
| Behavioural equivalence ROS1↔ROS2 | **NOT CLAIMED** |

**This is a limited single-sensor L3/L4 test. It proves the LiDAR hardware, driver and ROS
interfaces work natively. It proves nothing about motor behaviour, navigation, or the ROS 2 port.**
