# Phase 8 — Fleet Design and caasi Provisioning Workflow (proposal)

**Date:** 2026-10-26
**Status:** Proposal only. No caasi source changed, nothing installed, nothing applied.

**Governing constraint:** do **not** build a second target-management architecture. This document
starts from what `caasi.core.targets` already does and proposes the smallest extensions that a
10-robot lab needs.

---

## 1. What caasi already supports (inspected, not assumed)

`Target` (`core/targets.py:152`) already carries:

| Field | Purpose |
|---|---|
| `name`, `transport` (`local`/`ssh`), `host`, `user`, `port`, `identity` | identity + connection |
| `deployment_root`, `ssh_timeout` | where code lands, how patient to be |
| `tags`, `declared_capabilities`, `declared_resources` | declared expectations |

`TargetEnvironment` / `TargetResources` / `TargetInspection` hold *discovered* facts (OS, kernel,
arch, hostname, python, ROS distro/root, RMW, CUDA, Isaac, docker, CPU/RAM/GPU). `list_targets()`
merges declared targets, auto-adds `local`, and imports legacy `remotes:`.

Operational surface already target-aware: `deploy`, `build --target`, `run start/status/logs/stop/
inspect --target`, `run artifacts`, `ros … --target`, `target runtime`, `target select`,
`--where`, `tools run --target`, `runtime install/enable/update/rollback`.

**Conclusion: the abstraction is sound and sufficient in kind.** A fleet needs *scale*, not a
redesign.

---

## 2. The four real gaps for a lab of 10 robots

| # | Gap | Why it hurts at 10 robots | Smallest fix |
|---|---|---|---|
| **F1** | No shared defaults / per-target overrides | Every robot must repeat `user`, `identity`, `deployment_root`, `ssh_timeout`. Ten near-identical blocks, ten places to make one mistake. | A `target_defaults:` block merged under each target, plus native YAML anchors for per-robot overrides. Config-only — no new model. |
| **F2** | One endpoint per target | The robot's address changes between boots (`10.212.19.94` on Ubuntu 20, `10.212.19.95` on Ubuntu 24); the Tailscale name `swjtumover05-u24` is stable. Today a target holds a single `host`. | Allow `hosts: [primary, fallback…]` tried in order, with the winner recorded in provenance. `host` stays valid as a one-element list. |
| **F3** | No group operations | `target select` is advisory and `--where` picks **one**. "Deploy to every robot tagged `swjtumover`" means ten invocations. | A `--all`/`--tag <t>` selector on the existing commands, reusing `select_all` — no new execution path. |
| **F4** | No link from target → project hardware profile | The project now has `hardware:=swjtumover`; the target knows `tags`/`capabilities`. Nothing connects them, so the wrong profile can be launched on the wrong robot. | A `hardware_profile` field on `Target`, checked by the existing `check`/`select` ladder, and passed through to launch. |

Deliberately **not** proposed: a separate fleet registry, a database, a scheduler, per-robot
credential stores beyond what SSH already provides (`identity` + agent), or a second config file
format. Credentials stay with SSH: key path in config, passphrase in the agent. Nothing secret is
written into caasi state.

---

## 3. Proposed fleet configuration sketch

```yaml
# one place for everything shared
target_defaults:
  user: swjtumover
  identity: ~/.ssh/id_robot
  deployment_root: ~/caasi-deployments/openmover
  ssh_timeout: 10.0

targets:
  swjtumover05:
    hosts: [10.212.19.95, swjtumover05-u24]   # tried in order; Tailscale as fallback
    tags: [robot, swjtumover, wifi, jazzy]
    hardware_profile: swjtumover
  swjtumover06:
    hosts: [10.212.19.96]
    tags: [robot, swjtumover, wifi, jazzy]
    hardware_profile: swjtumover
  # per-robot override, everything else inherited:
  swjtumover07:
    hosts: [10.212.19.97]
    tags: [robot, swjtumover, wifi, humble]
    hardware_profile: swjtumover
    ssh_timeout: 20.0        # slow link on this one
```

`local` keeps being auto-added, so a workstation remains `local` and a robot is just another target.

---

## 4. Provisioning workflow (mapped to commands that exist today)

| Step | Command | Exists? |
|---|---|---|
| 1. Register a robot | edit `targets:` (or `caasi target list` to confirm) | ✅ |
| 2. Connect over an approved transport | `caasi target check <name>` (TCP preflight + SSH probe) | ✅ |
| 3. Inspect OS / packages / hardware | `caasi target inspect <name>`, `caasi env inspect`, `caasi sensor list` | ✅ |
| 4. Identify missing deps / config | `caasi check project --target` (**today `check` is local-only — F5 below**), `caasi audit` | ⚠️ partial |
| 5. Present exact system changes | **no capability** — see F5 | ❌ |
| 6. Apply approved changes | **no capability** — deliberately | ❌ |
| 7. Validate + register capabilities | `caasi target inspect` → discovered capabilities; `caasi target select` | ✅ |
| 8. Ongoing operations | `deploy`, `build --target`, `run`, `ros --target`, `runtime` | ✅ |

### F5 — the gap that matters most for provisioning, and the most careful one

Steps 4–6 are where the lab currently burns time by hand (as we just did: missing packages,
unset addresses). caasi should help. But installing packages and writing network configuration on
a robot are the two most consequential operations in this whole project.

Proposal, deliberately narrow:

- **`caasi target deps <name>`** — *read-only*. Inspects the target and reports missing ROS packages
  / launch-critical dependencies as a list, with the exact `apt install` line it *would* run. **Does
  not run it.** This alone removes the guesswork we just did manually.
- **Nothing is proposed for step 6 yet.** Package installation, network configuration and reboot are
  exactly the operations that must not be automated behind a convenience flag until the fleet-level
  safety story exists (staged rollout, per-robot confirmation, dry-run diff, rollback). Flagged as a
  future decision, not implemented.

This keeps caasi's role: *decide and report*, with the human applying consequential changes.

---

## 5. Acceptance criteria — the distinctions to demonstrate

Each of these is a **separate** claim; passing one does not imply the next:

| Level | Claim | How it will be shown |
|---|---|---|
| L0 | **Registered** | `caasi target list` shows the robot |
| L1 | **Reachable** | `caasi target check <name>` succeeds (TCP + SSH), with measured latency |
| L2 | **Discovered** | `caasi target inspect <name>` reports OS, ROS distro, deps, and discovered capabilities from the real machine |
| L3 | **ROS 2 works through caasi** | `caasi ros status --target <name>` / `graph` / `topic` against a real runtime on the robot |
| L4 | **Hardware validated** | measured sensor/motor values matching the ROS 1 baseline (14.03 Hz scan, 1440 samples, motor rpm scaling) — *not* merely "the node started" |
| L5 | **Fleet operation** | one command acting on ≥2 targets, with per-target outcome recorded |

Today: L0–L2 achievable once the NICs/netplan are approved; L3 needs a ROS 2 runtime on the robot;
L4 needs the LiDAR reachable; **L5 needs a second robot that does not exist yet** — so L5 must be
demonstrated by a *second simulated target* (e.g. the workstation registered twice with different
names/tags) and that limitation stated plainly, not glossed.

---

## 6. Open questions for the user

1. **Subnet topology — isolated or shared per robot?** Both the LiDAR (`192.168.110.100`) and the
   motor/IO board (`192.168.100.100`) use *fixed device addresses*. If ten robots share one physical
   network, those addresses collide. If each robot has its own isolated pair of links (direct cable,
   no switch), the same addresses can be reused safely on every robot — which is what the current
   10-per-robot addressing assumes and what makes the fleet config uniform.
   **Which is it?** This decides whether the fleet needs per-robot address blocks
   (`192.168.11X.10`) or one shared template.
2. **Second robot for L5** — is one available, or should I demonstrate the fleet selector against
   two synthetic targets and label it as such?
3. **`caasi target deps`** — approve the read-only dependency report as the first provisioning
   capability (F5 first half), so the manual package-hunting we just did becomes one command?

---

## 7. Netplan applied and device isolation verified (2026-10-26)

Applied with the user's approval (`/etc/netplan/60-robot-devices.yaml` on the robot):

| Interface | Address | State |
|---|---|---|
| `enp1s0` | 192.168.110.10/24 | **up** |
| `enp3s0` | 192.168.100.10/24 | **up** |
| `wlp2s0` | 10.212.19.95/24 | up, **still the default route** (`default via 10.212.19.229`) |

No gateway and no DNS on either device link, so external traffic stays on Wi-Fi — verified with
`ip route` rather than assumed.

### Both devices reachable on Ubuntu 24

| Device | Address | RTT |
|---|---|---|
| Vanjee 718H | 192.168.110.100 | 0.91 ms avg |
| Motor + IO board | 192.168.100.100 | 1.42 ms avg |

### Isolation: verified for this robot, with the right caveat

Method: ARP table inspection plus a subnet sweep, not inference from code.

```
ip neigh dev enp1s0 -> 192.168.110.100  lladdr 70:19:88:d3:1d:0e   (only entry)
ip neigh dev enp3s0 -> 192.168.100.100  lladdr 00:04:a3:00:29:79   (only entry)
sweep of .110.1/2/50/100/101/102 and .100.1/2/50/101/102/110 -> only the two expected devices
```

Evidence supporting **per-robot isolated links**:
1. **Exactly one peer per interface**, with a vendor MAC each (Vanjee, motor board) and no other host
   answering anywhere on either subnet.
2. **No gateway on either link** — nothing routes into or out of these subnets.
3. Both devices are **onboard** the robot (cabled to it), and the robot's only external path is
   Wi-Fi at a DHCP address that differs per boot (`.94` on Ubuntu 20, `.95` here).
4. The robot code binds **by IP only, never by interface name** (`lidar.yaml` `host_address`
   `192.168.110.10`; `motor.yaml` `192.168.100.100`), so the same addresses are intended to be
   valid on every robot that runs the same code.

**Not proven:** that no two robots are ever plugged into one switch. That is a physical/topology
fact I cannot observe from inside one robot. If the lab ever puts several robots on a shared device
network, the fixed `.100.100` / `.110.100` addresses will collide and per-robot ranges become
necessary — which is why the fleet config keeps the network profile parameterised rather than
hardcoding one shared template.

**Decision taken:** the standard profile (`.110.10` and `.100.10`, no gateway) is used for this
robot and is the fleet default, because the evidence points to isolated onboard links. The
parameterisation remains for the shared case.
