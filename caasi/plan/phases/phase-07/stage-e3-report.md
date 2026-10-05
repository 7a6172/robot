# Phase 7 Stage E3 Report: Non-ROS Runtime Adapters

**Status:** Completed & Empirically Verified
**Date:** October 2026
**Parents:** [`stage-e2-report.md`](stage-e2-report.md) (the ROS 2 observation model being generalised), [`stage-e-observability-addendum.md`](stage-e-observability-addendum.md)

---

## 1. Objective

Generalise the E2 observation model beyond ROS 2, using each runtime's own native
interface — without building a second runtime implementation inside caasi.

The principle, unchanged from E2:

> **caasi asks the target/runtime for state and presents it consistently; the
> underlying runtime remains authoritative.**

---

## 2. What was implemented

### 2.1 `caasi.core.runtimes` (new module)

One adapter per runtime, plus a shared transport primitive:

| Runtime | Delegates to | Notes |
| :--- | :--- | :--- |
| `process` | `ps`, falling back to `/proc` | Finds bare processes and workloads by match |
| `systemd` | `systemctl`, `journalctl` | User scope by default (`--user`) |
| `container` | `docker`, falling back to `podman` | Not bound to one implementation |
| `ros2` | `ros2` CLI | Reuses E2's detection rather than duplicating it |

Normalised across all four:

```text
RuntimeReport{runtime, target, available, tool, items[], error, detail}
RuntimeItem{name, state, detail{}}
```

**`run_on_target`** is the single transport primitive: local runs the argv
directly; SSH joins one quoted command through the existing SSH prefix. Every
adapter uses it, so the transport story lives in one place.

### 2.2 `caasi target runtime` (new command)

```bash
caasi target runtime <target>                      # every detected runtime
caasi target runtime <target> --runtime process --match <text>
caasi target runtime <target> --runtime systemd --unit <name>
caasi target runtime <target> --runtime systemd --unit <name> --lines 20
caasi target runtime <target> --runtime container
caasi target runtime <target> --json
```

---

## 3. Design decisions

Recorded because they are the substance of the stage:

1. **Absence is reported, not guessed.** A runtime that is missing yields
   `available: false` **with a reason** ("no docker or podman on PATH"), never an
   empty-but-successful result. A caller should never have to infer absence from
   an empty list.

2. **`systemctl` existing is not enough.** A container commonly ships `systemctl`
   without systemd as PID 1. The adapter requires `/run/systemd/system` to exist
   as well, and reports *"systemd not running (not PID 1 / container)"* otherwise.
   Claiming the runtime works there would be wrong.

3. **Detection is one round-trip.** All tools are probed in a single SSH call, so
   a slow relayed target is not penalised once per runtime.

4. **Budgets scale with the link**, reusing the `ssh_timeout` mechanism from
   Stage D — a relayed target must not be given a LAN-sized budget.

5. **Nothing is mutated.** Adapters only *read* state. There is no start, stop,
   restart, enable or remove operation. Lifecycle belongs to the execution
   lifecycle; enablement belongs to a later stage.

6. **Kernel threads are hidden unless matched.** They dominate a bare process
   listing and are almost never what an operator wants. Detected via `ps`'s
   bracketed command (`[kthreadd]`), which is a reliable signal; an explicit
   `--match` still reaches them.

---

## 4. Validation

Per the instruction to use simple workloads and not require OpenMover, validation
used a trivial `sleep` workload, a minimal systemd user unit, and a real Docker
container. **OpenMover was not involved** and was not needed.

Targets: the real remote machine `u24-307` (has systemd + `/proc`, **no**
container runtime) and the local workstation (has Docker, no relevance to the
remote path).

### 4.1 Availability detection — PASS

```console
$ caasi target runtime u24-307 --lines 6
Runtimes on u24-307
  Transport: ssh
  ● process (ps)            systemd, systemd-journal, systemd-udevd, …
  ● systemd (systemctl)     at-spi-dbus-bus.service, dbus.service, …
  ○ container - no docker or podman on PATH
  ● ros2 (/opt/ros/jazzy/bin/ros2)
```

All four runtimes surfaced in one command, with the container runtime correctly
reported as unavailable *and why* — on a target that genuinely has no container
runtime. This is the honest-absence behaviour working on real hardware.

### 4.2 Process adapter — PASS (real workload)

Started `sleep 900` detached on `u24-307`, then located it through caasi:

```console
$ caasi target runtime u24-307 --runtime process --match "sleep 900"
  ● process (ps)
      sleep [dim]Ss[/dim] [dim]pid=95054 pgid=95054[/dim]
```

Exact PID and PGID reported, matching what was started.

### 4.3 systemd adapter — PASS (real unit)

Created a minimal user unit on `u24-307`, started it, then observed it:

```console
$ caasi target runtime u24-307 --runtime systemd --unit caasi-e3-test.service
  ● systemd (systemctl)
      caasi-e3-test.service [dim]active[/dim]
```

`--json` detail confirms the values are systemd's own:

```json
{"id": "caasi-e3-test.service", "activestate": "active",
 "substate": "running", "mainpid": "95238",
 "unitfilestate": "disabled", "loadstate": "loaded"}
```

**journalctl delegation** returned real journal lines from the unit:

```text
Oct 05 18:50:39 u24-307 systemd[13425]: Started caasi-e3-test.service - caasi E3 adapter validation ...
```

### 4.4 Container adapter — PASS (real container, local)

`u24-307` has no container runtime, so this was validated locally against real
Docker with a live container:

```console
$ caasi target runtime local --runtime container
  ● container (/usr/bin/docker)
      e3-adapter-test [dim]running[/dim] [dim]alpine (Up 2 seconds)[/dim]
      ros1-ref [dim]exited[/dim] [dim]osrf/ros:noetic-desktop-full[/dim]
      …
```

A running container and exited ones are reported with their real states. Podman
fallback is covered by test (`test_container_adapter_uses_podman_when_docker_is_absent`).

### 4.5 Failure cases — PASS

| Case | Result |
| :--- | :--- |
| Unknown target | rc 1, `No target matching '…' (configured: u24-307, local)` — **no silent local fallback** |
| Unknown runtime name | rc 1, `Unknown runtime 'kubernetes' (expected process, systemd, container, ros2)` |
| Unreachable target | rc 1, bounded **20.16 s**, every runtime reporting the transport reason |
| Runtime absent on a real target | Reported unavailable with a reason, not an empty success |

### 4.6 A test fixture that lied

The container adapter test initially failed: my fixture's column order did not
match real `docker ps --format` output. Checking real output showed caasi's
format string was correct and the *fixture* was wrong. Fixed the fixture.

Recorded because it is the reason for validating against real tooling rather than
only mocked shapes — a fixture that disagrees with reality is worse than no test.

---

## 5. What E3 establishes

1. caasi can observe **processes, systemd units, containers and ROS 2** on a
   local or remote target through one consistent interface.
2. Every reported value comes from the runtime's own tooling; **caasi implements
   none of these runtimes**.
3. **Absence is explicit** — an unavailable runtime says so and why, including
   the subtle case of `systemctl` present without systemd running.
4. The adapters are **project-agnostic and runtime-agnostic**: validated entirely
   with trivial workloads, with no OpenMover involvement.

## 6. What remains untested (explicitly)

- **No lifecycle operations.** Start/stop/restart/enable/disable are deliberately
  absent. This stage observes only.
- **No container logs or inspect.** Only listing exists; `docker logs` /
  `docker inspect` pass-through is not implemented.
- **No multi-target/fleet aggregation.** One target at a time. Although
  `caasi target list --check` composes for reachability, no combined runtime view
  across targets exists.
- **No polling or history.** On-demand queries only; no sampling, no time series,
  no alerting.
- **Container adapter not validated remotely**, because no reachable target in
  this environment has a container runtime. It is validated locally against real
  Docker.
- **No non-systemd init** (OpenRC, s6, runit) — only systemd is adapted.
- **No `caasi monitor` integration.** The E2 observation notes that `monitor`
  remains local-only; that is unchanged and out of E3 scope.
- **Podman validated only by mocked test**, not against a real podman host.
- **No security posture tested** (e.g. polkit/sudo requirements for system-scope
  systemd, or docker socket permissions).

---

## 7. Tests

**21 new tests** in `tests/test_runtimes.py`, covering:

- availability detection, including absence-with-reason and unreachable-target
  handling for every runtime;
- the subtle case of `systemctl` present but systemd not running;
- delegation contracts for `ps`, `systemctl show`, `journalctl` and `docker ps`
  (asserting caasi shells out to the native CLI rather than reimplementing);
- `--user` scope propagation;
- podman fallback;
- kernel-thread filtering, and that `--match` still reaches them;
- transport: no ssh wrapper locally, one joined command remotely;
- budget scaling with target link latency;
- `query_all` returning a report for every runtime, available or not;
- unknown runtime rejection;
- CLI: unknown target without local fallback, unknown runtime, and JSON shape.

**Full suite: 999 passed, 1 failed.** The single failure
(`test_perception_cmd.py::test_perception_segment_dry_run_passes_extra_args`) is
**pre-existing and unrelated** — proven so in Stage D by stashing changes and
reproducing it on the unmodified commit; it concerns Isaac ROS perception
(untouched by E3) and its cause is terminal-width line wrapping.

---

## 8. Files changed

| File | Change |
| :--- | :--- |
| `src/caasi/core/runtimes.py` | **new** — adapter registry, transport, four adapters |
| `src/caasi/cli/target_cmd.py` | `caasi target runtime` command |
| `src/caasi/i18n/en.py` | 9 new user-facing strings |
| `tests/test_runtimes.py` | **new** — 21 tests |

No reference tree modified: `openmover_robot` `f17c242a…` and `openmover_ws`
`1e09f5de…` unchanged. Validation fixtures were removed from `u24-307` (unit
stopped and deleted, workload killed) and locally (container removed).

---

## 9. Environmental note

`u24-307` connectivity remained variable throughout this stage, consistent with
the relay variability already recorded in the E2 report: probe round-trips
ranged roughly 325 ms to 1.35 s, with several transient SSH drops requiring a
retry. This is **environmental**, not caused by E3 or by E1. One drop was
initially attributed to the relay and turned out to be a real gotcha worth
recording: **`pkill -f "sleep 900"` over SSH matches the SSH command line
containing that string**, so the command kills its own session. The workaround
was to match on exact process name and inspect `/proc/<pid>/cmdline`.

---

## 10. Next step

E3 is complete. **Do not auto-proceed.** The remaining agreed work is the
**persistent runtime lifecycle** (install/configure, enable, durability
verification, update/redeploy, rollback), which still requires real robot
evidence and was deliberately not started.

The documented E1 limitation (`required:` parses but is not enforced) remains
documented and was **not** expanded, per instruction — E3 did not demonstrate a
need for it.
