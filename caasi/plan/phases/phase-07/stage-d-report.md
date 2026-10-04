# Phase 7 — Stage D Report: Real Remote Target Validation

**Status:** Completed & Empirically Verified
**Date:** October 2026
**Scope:** Stage D only (real separate machine over SSH/Tailscale; full target lifecycle)

---

## 1. Objective

Prove the complete target lifecycle against a **genuinely separate machine**, not a
local container:

```text
Workstation / control plane          Independent execution target
u24-z690p                            u24-307
      │
      │  SSH over Tailscale
      ▼
      ├── caasi target check
      ├── caasi deploy
      ├── caasi build --target
      ├── caasi run start   (detached)
      ├── caasi run status / logs / inspect
      └── caasi run stop
```

Stage D validates the **remote execution infrastructure**. It does not test GPU
or simulation compatibility, and the CPU-only smoke workload used here must not
be described as an Isaac Sim / OpenMover simulation test.

---

## 2. Target and environment

| | Workstation (control plane) | Target |
| :--- | :--- | :--- |
| Hostname | `u24-z690p` | **`u24-307`** |
| OS | Ubuntu 24.04.5 LTS | Ubuntu 24.04.4 LTS |
| Kernel | 6.8.0-142-generic | **6.8.0-139-generic** |
| CPU | Intel i7-12700K (20 cores) | **Intel Xeon E5-2630 v2 (12 cores)** |
| RAM | 46.8 GiB | **62.7 GiB** |
| GPU | NVIDIA RTX 3080 | **none** |
| Docker | available | **not installed** |
| ROS 2 | Jazzy | Jazzy (`/opt/ros/jazzy`) |
| Reachability | — | Tailscale `100.111.167.124`, **relay "hkg"** |

The two machines are genuinely independent: distinct hostname, kernel, CPU
model and core count. Discovery reads the target's own facts (see §4).

**Network characteristic that matters.** `u24-307` is reached through a
Tailscale **relay**, so an SSH round-trip costs **~5–6 s** while TCP connect is
only ~0.35 s:

```text
TCP preflight to :22         ~350 ms
SSH handshake + probe        ~5-6 s
```

This is normal for a real WAN/VPN-reached target and is the direct cause of the
two latency-related gaps in §3.

**Remote caasi installation was left untouched.** `u24-307` has the released
PyPI `caasi 0.3.0` via pipx (`~/.local/bin/caasi`), unchanged before and after
Stage D. The workstation's development checkout remains the controller. The
target is used purely as a deployment/build/run destination.

---

## 3. Gaps exposed and fixed

Stage D is the first stage to use a genuinely separate machine, and it exposed
**three real caasi defects**. Each was documented before being fixed, and each
fix is the smallest general change that addresses the root cause. Full write-ups:

- [`stage-d-gap-ssh-timeout.md`](stage-d-gap-ssh-timeout.md)
- [`stage-d-gap-run-timeouts.md`](stage-d-gap-run-timeouts.md)
- [`stage-d-gap-deploy-status.md`](stage-d-gap-deploy-status.md)

### G1 — SSH probe/connect timeout too small for real links

`caasi target check u24-307` failed outright:

```console
Error: Target 'u24-307' discovery error: Remote probe timed out after 3.0s
```

The SSH probe timeout (3.0 s) and `ConnectTimeout` (3 s) were hardcoded, sized
for a local container. Diagnosis: TCP preflight 350 ms (passes), SSH probe
~5–6 s (fails).

**Fix:** one optional per-target field `ssh_timeout` (default 3.0, preserving
existing behaviour), threaded through the SSH prefix and the discovery probe.
All four existing `discover_target` call sites inherit it. The timeout error now
distinguishes *unreachable* from *too slow* and names the setting to raise.

### G2 — Remote run control budgets too small, causing a false `lost`

`caasi run stop` timed out and reported the run as `lost`, even though the kill
had in fact succeeded — verified on the target: all three tested PIDs were gone
and the process group was empty.

`caasi.core.runs` hardcoded 12 subprocess timeouts (5 s and 10 s) across the
remote paths. Every step of `remote_stop_run` is one SSH round-trip, so each
could individually exceed its budget.

**Fix:** per-call budgets derived from `target.ssh_timeout` with the previous
values kept as floors, so targets that do not set the field behave exactly as
before. Additionally, a delivered signal now records the run as **stopped**
rather than `lost`; "kill sent" and "state confirmed" are treated as different
facts, and the return value distinguishes *confirmed* from *signalled,
unconfirmed*. A transport timeout is no longer converted into a false terminal
state.

### G3 — `deploy --status` could not find a deployment it had just created

Immediately after a verified deployment, `--status` reported:

```console
No active caasi deployment found on target 'u24-307'.
```

while the target held a `verified` `.caasi-deployment.json` that was in active
use. Cause: the **write** path appended the project name
(`resolve_deployment_destination` → `<root>/<project_name>`) but the **read**
path used the bare `deployment_root`. With no `--dest`, it looked one directory
too high. Confirmed by supplying `--dest`, which found it immediately.

**Fix:** the read path now uses the same resolver as the write path, deriving
the project name from the manifest, with the bare-root fallback preserved when
no project is discoverable.

**Severity note.** G3 is not latency-related and affects the documented default
destination layout generally, on any target. G1/G2 are the same class of defect
(fixed budgets ignoring target latency) and were fixed consistently.

---

## 4. Lifecycle evidence

Commands were run from `/home/zar/Documents/phd/robot/caasi-workspace/openmover`
using the development controller
`/home/zar/Documents/phd/robot/caasi/.venv/bin/caasi`.

### 4.1 `caasi target check u24-307` — PASS

```console
✔ Target 'u24-307' is ONLINE (ping: 335.4ms | probe: 4691.4ms) and fully COMPATIBLE.
  Capabilities: ros2, ros2:jazzy
```

The readout makes the G1 diagnosis explicit: TCP 335 ms, probe 4.69 s.

### 4.2 Independent target identity — PASS

`caasi target inspect u24-307` reports facts read **from the remote machine**,
all distinct from the workstation:

```text
CPU:     Intel(R) Xeon(R) CPU E5-2630 v2 @ 2.60GHz (12 cores)
Memory:  62.7 GiB total (60.6 GiB available)
GPUs:    None detected
OS:      Linux-6.8.0-139-generic-x86_64-with-glibc2.39
Host:    x86_64 (u24-307)
ROS 2:   jazzy (/opt/ros/jazzy)
Docker:  Not installed
```

### 4.3 `caasi deploy u24-307` — VERIFIED

```console
Total Project Files: 835 (40.4 MiB)
Changed Files:       169
✔ Deployment deploy-openmover-20261004-100729-8c304a34 materialization complete.
  Status:       VERIFIED
```

Transfer took 78.63 s — consistent with a relayed WAN link, versus 0.77 s to a
local container in Stage B.

**On-target verification:**

```text
  absent (correct):    build, install, log, .git, tests
  present (correct):   caasi.yaml, caasi.lock, src, config, assets, experiments
  43M  /home/zar/caasi-deployments/openmover   665 files
```

**Target-side deployment metadata** records the target's own identity:

```text
deployment_id : deploy-openmover-20261004-100729-8c304a34
git_revision  : 8c304a349784bfb03f24e1a9af329a4b7805ce7b-dirty
target_name   : u24-307 (ssh)
hostname      : u24-307
kernel        : 6.8.0-139-generic
cuda_version  : None        isaac_sim: None      docker: False
```

### 4.4 `caasi build --target u24-307` — PASS, built on the target

```console
Build completed successfully in 185.83s.
Target-native build artifacts remain on u24-307: /home/zar/caasi-deployments/openmover
```

**Proof the compilation happened on `u24-307`:**

| Evidence | Observation |
| :--- | :--- |
| Compile paths in the build log | `/home/zar/caasi-deployments/openmover/src/...` — **target** paths |
| `build/`, `install/`, `log/` | exist **only** on the target (184M / 13M / 4.3M) |
| Built executables | present on the target (`install/openmover/lib/openmover/*`) |
| Workstation | **no** `/home/zar/caasi-deployments/openmover` — no target binaries leaked back |
| Worker count | **10**, derived from u24-307's own 62.7 GiB / 12 cores (`min(12, (62.7-2)/6)`), distinct from the workstation's 7 |
| Target-side provenance | `build-u24-307-1791108950-c26895`, `target_name: u24-307` |

Dependencies had to be installed on the target first (`nav2_costmap_2d`,
`nav2_util`, `nav2_msgs`, `octomap*`, `osqp_vendor`). This is ordinary target
provisioning — the target's own independent ROS 2 install, not a caasi change.

### 4.5 `caasi run start --target u24-307` — detached run on the target

Workload: the project's existing CPU-only smoke experiment,
`experiments/target_smoke.yaml` → `target_smoke_test.py` (verifies ROS 2 imports,
detached PGID, and child-process lifecycle). No new workload was invented for
Stage D.

```console
Run 20261004-182108-target-smoke started in background on target 'u24-307'.
```

**On-target process tree:**

```text
    PID    PPID    PGID STAT CMD
  77787       1   77787 Ss   bash .../run.sh python3 .../target_smoke_test.py
  77810   77787   77787 Sl    \_ python3 .../target_smoke_test.py
  77814   77810   77787 S         \_ sleep 120
```

`PPID 1` confirms the run is reparented to init and detached from any session.
Run directory, `pid`, `pgid`, `run.sh`, `stdout.log`, `stderr.log` all present on
the target.

### 4.6 SSH disconnect survival — **TESTED** (not merely claimed)

A dedicated SSH session was opened, the run inspected from inside it, then the
**local SSH client was killed with SIGKILL** while the run was active;
afterwards no ssh process to the target remained on the workstation.

| Check | Result |
| :--- | :--- |
| Session host inside test session | `u24-307` |
| Run visible from that session | PID 77787, PGID 77787 |
| SSH client after `kill -9` | **terminated** |
| Local ssh processes to target afterwards | **0** |
| Run after reconnect | **same PID 77787, still alive, elapsed 01:52** |
| Heartbeat progress across the disconnect | **step 20 → step 110** |

The run continued independently of the initiating session and completed
naturally. Note this strengthens the Stage C2 claim: the run does not depend on
*any* live SSH session, because the launching invocation had already exited
before the disconnect test began.

### 4.7 `status` / `logs` / `inspect` from a fresh invocation — PASS

A **new** caasi process (not the launching one) read the state from the target:

```console
$ caasi run status 20261004-182108-target-smoke
  Status           succeeded
  Target           u24-307 (ssh)
  PID              77787      PGID  77787
  Deployment       deploy-openmover-20261004-100729-8c304a34
  Build            build-u24-307-1791108950-c26895
```

`caasi run logs` returned the full stream ending in `[SMOKE] Finished naturally`.
`caasi run inspect` listed the run inventory (`exit_code`, `manifest.yaml`,
`pgid`, `pid`, `run.sh`, `stderr.log`, `stdout.log`) from the target.

### 4.8 `caasi run stop` — reports `stopped`, tested tree gone

A second run (`20261004-183747-target-smoke-stop2`) was started specifically to
be stopped while live, so `stop` was exercised against a running process.

```console
$ caasi run stop 20261004-183747-target-smoke-stop2
Run 20261004-183747-target-smoke-stop2 stopped.          # 21.95 s
$ caasi run status 20261004-183747-target-smoke-stop2
  Status           stopped
```

**Tested process tree before stop:** `79032` (launcher), `79054` (python),
`79058` (`sleep`), all in PGID `79032`.

**After stop, verified on the target:**

```text
  gone:        79032
  gone:        79054
  gone:        79058
  processes remaining in tested group: 0
  no process matches the tested run.sh
  target-side manifest: stopped: true
```

> **Scope of this cleanup claim.** This is evidence about the **tested process
> group and its spawned child only**. It is not a universal guarantee for
> arbitrary workloads.

### 4.9 Two-sided provenance — PASS

Host and target records agree and form a complete chain:

```text
deployment_id  deploy-openmover-20261004-100729-8c304a34
      ↓
build_id       build-u24-307-1791108950-c26895   (workers 10, 185.83 s)
      ↓
run            20261004-183747-target-smoke-stop2  (pid 79032, pgid 79032, stopped)
```

| Location | Artifacts |
| :--- | :--- |
| Target | `<dest>/.caasi-deployment.json`, `<dest>/.caasi-build.json`, `<dest>/.caasi/runs/<run_id>/manifest.yaml` |
| Workstation | `.caasi/deployments/u24-307/*.json`, `.caasi/builds/u24-307/*.json`, `~/.caasi/runs/<run_id>/manifest.yaml` |

### 4.10 Offline target — bounded failure, no hang

A target pointing at TEST-NET-1 (RFC 5737, guaranteed non-routable) was
registered and every operation timed:

| Operation | Result | Elapsed |
| :--- | :--- | :--- |
| `target check` | `unreachable`, exit 1 | **2.13 s** |
| `deploy` | `unreachable`, exit 1 | **2.14 s** |
| `build --target` | `unreachable`, exit 1 | **2.15 s** |
| `run start --target` | `unreachable`, exit 1 | **2.13 s** |

All fail bounded and fast with clear messages. Note that a large `ssh_timeout`
(20 s) did **not** cause a 20 s stall: the TCP preflight detects unreachability
first and short-circuits.

### 4.11 Connectivity restored — target usable again

After removing the offline test target, `caasi target check u24-307` returned
ONLINE/COMPATIBLE, and `caasi deploy u24-307 --status` reported the verified
deployment (this last check is exactly what exposed and then confirmed the fix
for G3).

---

## 5. Tests added

| Test | File | Purpose |
| :--- | :--- | :--- |
| `test_target_ssh_prefix_defaults_to_three_second_connect_timeout` | `test_targets.py` | Default budget unchanged (3 s) |
| `test_target_ssh_prefix_honours_slow_link_budget` | `test_targets.py` | G1: configurable budget reaches `ConnectTimeout` |
| `test_ssh_timeout_parsed_from_config` | `test_targets.py` | G1: `ssh_timeout` parsed; default preserved |
| `test_discover_target_uses_target_timeout_when_none_given` | `test_targets.py` | G1: discovery budgets from the target |
| `test_discover_target_explicit_timeout_still_wins` | `test_targets.py` | G1: explicit timeout overrides |
| `test_remote_stop_uses_target_ssh_budget` | `test_target_run.py` | G2: every SSH call gets the target budget |
| `test_remote_stop_records_stopped_when_confirmation_times_out` | `test_target_run.py` | G2: never mis-report `lost` |
| `test_deployment_status_resolves_default_destination` | `test_deploy.py` | G3: read path matches write path |
| `test_deployment_status_missing_deployment_returns_none` | `test_deploy.py` | G3: absent deployment reports absent, never raises |

Target-related suites: **125 passing** (`test_deploy`, `test_targets`,
`test_target_run`, `test_target_build`, `test_build`, `test_runs`,
`test_run_cmd`, `test_project`).

Full suite: **928 passed, 1 failed**. The single failure is
`test_perception_cmd.py::test_perception_segment_dry_run_passes_extra_args`,
which is **pre-existing and unrelated to Stage D**: it fails identically on the
unmodified commit (verified by stashing the Stage D changes and re-running), it
concerns Isaac ROS perception (untouched by this stage), and its cause is
terminal-width line wrapping splitting `launch.py model:=unet` across two output
lines. It is recorded here rather than fixed, as it is outside Stage D scope.

---

## 6. What Stage D did and did not establish

**Established (with direct evidence):**

1. `caasi target check` works against a genuinely separate machine over
   SSH/Tailscale, reading the target's own hardware and software facts.
2. `caasi deploy` materializes the project on the real target with development
   artifacts excluded, and records two-sided deployment provenance.
3. `caasi build --target` compiles **on the target**, with worker sizing derived
   from the target's own CPU/RAM, and no target binaries returning to the
   workstation.
4. Detached remote runs start, produce logs, and survive **tested** SSH client
   termination.
5. `status`, `logs` and `inspect` work from a **fresh** caasi invocation,
   proving run state is not tied to the launching CLI process.
6. `caasi run stop` terminates the **tested** process group and its child; the
   target-side manifest records `stopped`.
7. Provenance links deployment → build → run on both sides.
8. Unreachable targets fail **bounded** (~2.1 s), never hanging.
9. Connectivity recovery restores normal operation.

**Not established:**

- **No GPU / simulation compatibility claim.** The target has no NVIDIA GPU and
  was never used for Isaac Sim / Isaac Lab. The workload is CPU-only.
- **No physical-robot claim.** No motor, actuator or hardware bringup.
- **No fleet/scheduling claim.** Single target only: no multi-target execution,
  no automatic target selection, no queues.
- **No universal process-cleanup guarantee** — only the tested process tree.
- **No ROS 1 involvement.** The earlier Docker/ROS 1 discussion concerned a
  separate legacy reference environment and is unrelated to this stage.

---

## 7. Stage C2 claim corrections carried forward

As required before closing C2, and now consistent with direct evidence:

- The Stage C2 detached-supervision claim is **upgraded**: SSH-disconnect
  survival is no longer merely asserted from `setsid` semantics — it was tested
  by SIGKILLing the SSH client mid-run (§4.6).
- Process cleanup is reported as **the tested process group and its spawned
  child, with no remaining processes from the tested run**, not as a universal
  zero-orphan guarantee.
- Worker sizing is described as a **conservative limit derived from discovered
  target CPU and RAM capacity**, not as OOM prevention.

---

## 8. Next step

Stage D is complete. **Do not auto-proceed.** Candidates for the next stage,
each now justified by observed evidence rather than speculation:

1. **Fleet / resource orchestration** — Stage D validated exactly one target;
   multi-target scheduling remains untested and unbuilt.
2. **Artifact management** — Stage D produced build outputs and logs on the
   target with no routing story back to the workstation beyond provenance.
3. **Container orchestration as a first-class transport** — the earlier
   containerized experiment showed caasi currently cannot express mounts,
   `--network host` or `--shm-size` for a container target. This is a genuine
   capability question, deliberately not introduced into Stage D.

Recommendation: decide between (1) and (2) after reviewing this evidence.
