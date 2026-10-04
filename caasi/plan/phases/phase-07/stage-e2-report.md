# Phase 7 Stage E2 Report: Remote ROS 2 Observability

**Status:** Completed & Empirically Verified
**Date:** October 2026
**Parents:** [`stage-e-discovery.md`](stage-e-discovery.md), [`stage-e-observability-addendum.md`](stage-e-observability-addendum.md)

---

## 1. Objective

Make caasi's existing ROS 2 query surface **target-aware**, so a workstation can
observe a ROS 2 runtime on a separate machine through caasi, using thin
delegation to the target's own `ros2` CLI.

Explicitly **not** in scope: reimplementing DDS, parsing ROS 2 internals,
building a metrics store, or a fleet supervisor.

---

## 2. What was implemented

### 2.1 Remote query primitives (`caasi.core.ros`)

Three new functions, following the module's existing thin-delegation discipline
("caasi never speaks rclpy"):

| Function | Purpose |
| :--- | :--- |
| `remote_ros2(target, args, ...)` | run `ros2 <args>` on a target over SSH |
| `remote_ros2_lines(target, args, ...)` | same, returning stdout lines |
| `remote_ros_environment(target)` | discover the target's ROS 2 environment in one round-trip |

The target-side snippet sources the ROS underlay, optionally the project overlay,
then delegates:

```bash
test -f "/opt/ros/<distro>/setup.bash" && . "/opt/ros/<distro>/setup.bash"
if ! command -v ros2 >/dev/null 2>&1; then echo "CAASI_NO_ROS2" >&2; exit 127; fi
exec ros2 "$@"
```

This mirrors what `rosenv.wrap()` already does locally, so a remote answer means
the same thing as a local one. **No ROS 2 semantics are reimplemented.**

### 2.2 `--target` on the existing query surface

Added to the commands that answer "what is the runtime doing right now":

```text
caasi ros status     --target <t>
caasi ros list       <kind> --target <t>
caasi ros graph      --target <t>
caasi ros node       <name> --target <t>
caasi ros topic      <name> --target <t>
caasi ros service list|info --target <t>
caasi ros doctor     --target <t>
```

`caasi ros launch` and `caasi ros topic --echo` were deliberately **excluded**:
they start long-lived processes, which is the *execution* lifecycle, not
observability. Remote `--echo` reports that explicitly and points at
`caasi run start --target`.

### 2.3 `--domain` (ROS_DOMAIN_ID)

Added because a runtime may legitimately live on a non-default domain, in which
case querying the default returns an **empty graph rather than an error** —
silently misleading. `--domain` selects the domain on both local and remote
paths.

### 2.4 `caasi target state` — deliberately NOT implemented

The addendum raised this as optional ("implement it only if it is the smallest
clean abstraction"). It was **not** implemented, because every input it would
aggregate already exists as a composable command:

| Aggregation input | Existing command |
| :--- | :--- |
| reachability | `caasi target check <t>` |
| fleet reachability | `caasi target list --check` |
| active deployment | `caasi deploy <t> --status` |
| last build | build record via `caasi build --target` |
| running runs | `caasi run list --target <t>` |

Adding a wrapper would duplicate existing commands without adding capability,
so it was left out. This is recorded as a decision, not an omission.

---

## 3. Validation environment

Per the instruction to use the **smallest workload that provides valid
evidence**, E2 was validated with standard ROS 2 demo nodes, **not OpenMover**.

| | Workstation | Target |
| :--- | :--- | :--- |
| Host | `u24-z690p` | **`u24-307`** |
| Transport | — | SSH over Tailscale (relay) |
| ROS | Jazzy | Jazzy |

**Demo runtime on `u24-307`** (scripts committed under `e2-demo-runtime/`):

```text
demo_nodes_cpp talker              -> /chatter publisher
demo_nodes_cpp listener            -> /chatter subscriber
demo_nodes_cpp add_two_ints_server -> /add_two_ints service
ROS_DOMAIN_ID=42
```

Three nodes, one topic, one service — enough to exercise node/topic/service/
graph/info queries without OpenMover's complexity.

---

## 4. Evidence

### 4.1 Remote observation of a live runtime — PASS

```console
$ caasi ros status --target u24-307
ROS 2 (u24-307)
  Distro     jazzy
  Binary     /opt/ros/jazzy/bin/ros2

$ caasi ros list nodes --target u24-307 --domain 42
ROS 2 nodes
  /add_two_ints_server
  /listener
  /talker

$ caasi ros list topics --target u24-307 --domain 42
ROS 2 topics
  /chatter
  /parameter_events
  /rosout

$ caasi ros graph --target u24-307 --domain 42
ROS 2 Graph (u24-307)
  Nodes (3)
    /add_two_ints_server  /listener  /talker
  Topics (3)
    /chatter  /parameter_events  /rosout

$ caasi ros node /talker --target u24-307 --domain 42
/talker
  Publishers:
    /chatter: std_msgs/msg/String
  Subscribers:
    /parameter_events: rcl_interfaces/msg/ParameterEvent

$ caasi ros topic /chatter --target u24-307 --domain 42
Type: std_msgs/msg/String
Publisher count: 1
Subscription count: 1

$ caasi ros service list --target u24-307 --domain 42
  /add_two_ints
  /add_two_ints_server/describe_parameters
  ...

$ caasi ros doctor --target u24-307
All 3 checks passed
```

Node, topic, service, graph and doctor queries all return the target's real
state.

### 4.2 The decisive cross-check — it is genuinely remote

The same domain (42) and the same command, differing only in `--target`:

```text
workstation local (ros2 directly)      -> (nothing)
caasi ros list nodes --domain 42       -> No nodes found.
caasi ros list nodes --target u24-307 --domain 42
                                       -> /add_two_ints_server /listener /talker
```

The demo runtime exists **only** on `u24-307`, so caasi is observing a remote
ROS 2 runtime, not echoing local state.

### 4.3 Validation matrix

| Case | Result |
| :--- | :--- |
| Caasi's local ROS 2 needed to observe the remote runtime | **No** — the workstation's own ROS returned nothing on domain 42 |
| Reachable target, ROS 2 running | **PASS** (above) |
| Reachable target, ROS 2 unavailable | **PASS** — rc 127 + `CAASI_NO_ROS2` marker; CLI reports "has no ros2 CLI available" |
| Unreachable target | **PASS** — rc 1, `Target 'offline-e2' is unreachable: … Connection timed out`, bounded (~22 s = SSH ConnectTimeout) |
| Remote query failure (no such node) | **PASS** — rc 1, `'/no_such_node' was not found on target 'u24-307' (ROS 2 ran and returned no match)` |
| Unknown target name | **PASS** — rc 1, no silent fallback to local (asserted by test) |
| Fresh invocation after reconnect | **PASS** — every caasi call is a fresh process; verified additionally from a fully-unsourced shell (`env -u ROS_DISTRO -u AMENT_PREFIX_PATH …`) |
| Local commands unchanged when `--target` omitted | **PASS** — `status`, `list`, `graph`, `doctor` all behave as before |
| Non-default domain handled | **PASS** — `--domain` reaches the target's invocation (asserted by test and observed live) |

### 4.4 Observation: relay latency is variable

Repeated `caasi target list --check` while writing this report showed probe times
climbing **6.0 s → 8.4 s → 10.0 s → 7.5 s** against the configured 20 s budget,
and one run in the same period transiently reported `UNREACHABLE` before
returning `online` on retry. Recorded as an environmental observation: the
Tailscale relay path is variable, and the G1 budget (Stage D) has less headroom
than it appears on a good sample. Not a defect in E2.

---

## 5. Error-reporting design

Remote failures are classified so an operator is told the right thing:

| Condition | Reported as |
| :--- | :--- |
| SSH transport failed (rc -1 / 255, or connect error with no output) | `Target '<t>' is unreachable: <detail>` |
| Target has no ros2 (rc 127 / marker) | `Target '<t>' has no ros2 CLI available.` |
| ros2 ran, object absent | `'<name>' was not found on target '<t>' (ROS 2 ran and returned no match).` |
| Other ros2 non-zero | `ROS 2 query failed on target '<t>' (<subject>).` |

Distinguishing "unreachable" from "no ROS 2" from "not found" matters: they have
different remedies, and the earlier single message sent an operator chasing the
wrong cause. All failure paths exit **1**.

---

## 6. Tests

8 new tests in `tests/test_ros_cmd.py` (16 → 24 in that file), SSH mocked so no
network is required; the behaviour under test is caasi's own:

| Test | Asserts |
| :--- | :--- |
| `test_remote_query_builds_sourced_ssh_invocation` | ssh transport + underlay sourced + `exec ros2` delegation |
| `test_remote_query_reports_missing_ros2_as_127` | 127 + marker propagation |
| `test_remote_query_passes_domain_id` | `ROS_DOMAIN_ID` reaches the target invocation |
| `test_remote_query_unreachable_is_negative_returncode` | transport failure → rc -1 |
| `test_cli_unknown_target_fails_without_querying_local` | no silent local fallback |
| `test_cli_local_path_unchanged_without_target` | local behaviour preserved |
| `test_remote_status_json_includes_target` | remote results are labelled with their target |
| `test_remote_status_unreachable_reports_error` | unreachable exits 1 with a clear message |

**Full suite: 936 passed, 1 failed.** The single failure
(`test_perception_cmd.py::test_perception_segment_dry_run_passes_extra_args`) is
**pre-existing and unrelated**: it was proven so in Stage D by stashing the
changes and reproducing it on the unmodified commit, it concerns Isaac ROS
perception (untouched by E2), and its cause is terminal-width line wrapping.

---

## 7. What E2 establishes

1. A workstation can observe a **remote** ROS 2 runtime through caasi —
   nodes, topics, services, graph, node/topic detail, doctor — for a **separate
   physical machine**.
2. The implementation is **thin delegation**: the target's own `ros2` produces
   every answer; caasi contributes only transport, environment sourcing and
   presentation.
3. Local behaviour is **unchanged** when `--target` is omitted.
4. Failures are **classified and bounded**, not hanging or misleading.
5. The method is **project-agnostic**: validated entirely with standard ROS 2
   demo nodes, and applicable to any ROS 2 project.

## 8. What remains untested (stated explicitly)

- **Non-ROS runtimes.** The adapter registry described in the addendum
  (containers, systemd, plain processes) is **not implemented**; only the ROS 2
  path was built. `caasi monitor` remains local-only.
- **Multi-target / fleet views.** A single remote target was observed. Although
  `caasi target list --check` and `run list --target` compose for a fleet view,
  no multi-target aggregation was exercised, and no shared abstraction exists
  yet.
- **Continuous polling.** All queries are on-demand. No sampling loop, no
  time-series, no alerting — deliberately, per the addendum's "query-on-demand
  first".
- **Non-SSH transports.** Only SSH was exercised.
- **`--domain` semantics across a real DDS network.** Domain isolation was
  observed locally↔remotely, but no multi-host DDS discovery across a domain was
  tested.
- **OpenMover integration.** Not used for E2 (by instruction). Using OpenMover as
  an additional integration validation is a natural follow-up but is **not**
  required to prove this capability, and was not done here.
- **Secure/authenticated ROS 2.** No SROS 2 / DDS security tested.

---

## 9. Files changed

| File | Change |
| :--- | :--- |
| `src/caasi/core/ros.py` | `remote_ros2`, `remote_ros2_lines`, `remote_ros_environment`; `--domain` support |
| `src/caasi/cli/ros_cmd.py` | `--target` / `--domain` on query commands; failure classification |
| `src/caasi/i18n/en.py` | 5 new user-facing strings |
| `tests/test_ros_cmd.py` | 8 new tests |
| `plan/phases/phase-07/e2-demo-runtime/` | `start_demo.sh`, `stop_demo.sh` (reproducible demo runtime) |

No reference tree modified. `openmover_robot` and `openmover_ws` unchanged.

---

## 10. Next step

E2 is complete. **Do not auto-proceed.** Per the agreed staging, the remaining
work is:

- **E1 — result/output collection** (declaration, inventory, routing,
  provenance). Already designed; completes the compute path.
- **Later — persistent runtime** (install/configure, enable, durability, update,
  rollback), still requiring real robot evidence.
- **Later — non-ROS adapters** (container, systemd, bare process) behind the same
  capability-keyed registry.

Recommended next: **E1**, which remains the highest-value bounded step and was
the original Stage E proposal.
