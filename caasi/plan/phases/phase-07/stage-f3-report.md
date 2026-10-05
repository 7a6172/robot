# Phase 7 Stage F3 Report: Target-Aware Tool Invocation

**Status:** Completed & Empirically Verified — with one **honest environmental limitation**
**Date:** October 2026
**Requirement:** **R2** — target-aware existing tools (no gap: a new capability)
**Design:** [`stage-f3-design.md`](stage-f3-design.md)
**Traceability:** [`traceability.md`](traceability.md)

---

## 1. The principle, and what was built

> **caasi supplies context, then gets out of the way.**

Implemented as **one generic mechanism**, not a set of tool integrations:

```bash
caasi rviz2 --target <t>  [--domain N] [--dry-run] [--exec] [--json] [tool args…]
caasi rosbag --target <t> record /scan /tf
caasi tools list
caasi tools run <tool> --target <t> …
```

`caasi.core.toolctx` resolves target context and builds the environment;
`caasi.cli.tools_cmd` exposes it. **No part of rviz2, rqt or rosbag is
implemented**, and no part of DDS is either.

### 1.1 A tool is data, not code

```yaml
tools:
  rviz2:
    invoke: rviz2
    environment:
      - RCUTILS_COLORIZED_OUTPUT=1
```

Verified: a **new tool was added purely in configuration** during validation and
became immediately invocable (`exitprobe`, `ros2-nodelist`) with **no code change**.
That is the genericity claim tested rather than asserted.

---

## 2. Validation

### 2.1 Successful cases

| Case | Result |
| :--- | :--- |
| `local` context resolution | `ROS_DISTRO=jazzy`; refused on an unresolved domain; proceeded with `--domain 0` |
| `u24-307` context resolution | `ROS_DISTRO=jazzy` **from the target's own probe**; refused on an unresolved domain |
| Explicit `--domain 0` | honoured, echoed back as `domain 0 from --domain` |
| Argument pass-through | `rosbag --target local --domain 0 record --unknown-flag -x /scan /tf` → `ros2 bag record --unknown-flag -x /scan /tf` |
| Config-extended registry | new tools invocable with no code change |
| Declarative per-tool env | `RCUTILS_COLORIZED_OUTPUT=1` applied from config |
| Ordinary local invocation | a non-ROS tool ran with **no environment overrides** and arguments intact |

### 2.2 Refusal cases — first-class evidence

| Case | Result |
| :--- | :--- |
| **Domain unresolved** | **refused (exit 3)**, *"…does not set ROS_DOMAIN_ID, so the domain it runs on is unknown; pass --domain explicitly rather than assuming the default (an assumed domain can silently show an empty ROS graph)"* |
| Unreachable target | refused (exit 3) with the transport reason (`Connection timed out`) |
| Target with no ROS 2 | refused: *"has no ROS 2 installation detectable, so 'rviz2' has nothing to attach to"* |
| Unknown tool | refused, listing the available tools |
| Missing local binary | would refuse naming the binary (the tool runs locally) |
| Tool exits non-zero | **the tool's own code propagated unmodified** (verified: `7` → `7`) |

**The domain refusal is the important one.** It is the empty-graph guard: caasi
refuses rather than letting a tool attach to an assumed domain and appear to work.

### 2.3 Target facts are never substituted with local facts

Verified directly: `rmw=None` on both targets (no back-fill), and a target asked
which sets no domain reports `UNSET` — a **measured absence** — which is kept
distinct from `None` (never asked). The environment omits `RMW_IMPLEMENTATION`
rather than inheriting the workstation's, because doing so would silently change
the target's DDS behaviour.

---

## 3. The remote GUI / discovery question — the honest result

The design predicted this might not work and required it to be **measured, not
assumed**. It was measured.

**Method.** A real ROS 2 node (a `talker`, no hardware, no motion) was started on
`u24-307` on domain 42, and a local node on the workstation on the same domain.

| Observation | Result |
| :--- | :--- |
| Node visible **on the target** | `ros2 node list` → `/f3_probe_talker` ✅ |
| Node visible **locally** (workstation, domain 42) | `/f3_local_talker` ✅ — **local discovery works** |
| `u24-307`'s node visible **from the workstation** | ✗ **not discovered** |
| caasi's resolved context for `u24-307` | **correct** — `ROS_DISTRO=jazzy`, `ROS_DOMAIN_ID=42` echoed from caasi's own resolution |

**Conclusion: caasi's context is correct; DDS discovery does not traverse this
network.** The failure is isolated to the cross-machine path — local discovery
demonstrably works on the same domain with the same mechanism.

**Verified it is not a mismatch caasi could resolve within scope:**

- `RMW_IMPLEMENTATION` is **unset on both sides** (so the defaults match);
- `ROS_LOCALHOST_ONLY` is unset on both;
- both machines have routable interfaces;
- the two machines are on **different LANs** — the target's `192.168.31.34` is
  **100% packet loss** from the workstation, and they are reachable only via
  Tailscale (`100.111.167.124/32`, ~440 ms RTT).

So the cause is that **DDS multicast discovery does not traverse the Tailscale
link**, and the two hosts share no L2 segment. That is a **network topology fact**.

**Per the agreed boundary this is NOT worked around.** caasi does not implement
DDS discovery, multicast relays or tunnels, and this result is **not** claimed as
working. It would be equally wrong to report "RViz opened" as success: the window
would show an empty graph, which is exactly the failure mode the domain guard
exists to prevent.

---

## 4. What is NOT implemented (scope held)

No automatic target selection, forwarding, queues or scheduling; no multi-target
orchestration; no new ROS/DDS functionality; no RViz replacement, rqt subsystem or
any tool reimplementation; no remote GUI management or display forwarding; no web
UI; **no daemonisation** of the launched tool (`--exec` hands over entirely);
**G4 not started**.

---

## 5. The F1 consolidation item

**Not fixed, and not encountered as a blocker.** F3 does not evaluate project
requirements, so the duplicated ladder and the `check.strict` divergence are
untouched. Still recorded open: `selection.py` calls `summarize(..., strict=False)`
unconditionally, so under `check.strict: true` `caasi check` reports `incompatible`
(exit 3) where `target select` reports a `warning` (exit 0).

---

## 6. Defects found

**One, in F3's own code, found during validation:**

`output.fail()` **raises its own `Exit(1)`**, so a `raise typer.Exit(3)` placed
after it was unreachable and every refusal exited **1** instead of 3. Caught by
checking the exit code rather than trusting the printed message — the printed
reason was already correct, so only measuring the code revealed it. Fixed by
passing `exit_code=3` into `fail()`.

**No defects found in the pre-existing code.**

Also recorded, because it recurred: on the target, `pgrep -f talker` matched **the
`ssh` command line containing the word "talker"**, reporting phantom processes
after the real one was killed. The same self-match trap was documented in E3;
cleanup was confirmed by inspecting `/proc/<pid>/cmdline` instead.

---

## 7. Tests

**35 new tests** in `tests/test_toolctx.py`: the registry being generic and
config-extensible (including that the older `tools:` version shape is **not**
mistaken for an invocable tool); environment construction (target distro used,
RMW only when reported, domain only when known, declarative substitution, unknown
substitution empty rather than invented); the domain hazard (explicit wins,
target-reported used, **unset refused**, unknown refused, never defaulted to 0);
planning refusals (unreachable, no ROS, unresolved domain, missing RMW reported not
defaulted, a non-ROS tool not gated on a domain); command construction and
pass-through; execution (exit code propagated, environment applied, missing binary);
and context probing (reachability vs ROS availability distinguished, unset domain
recorded as measured rather than unknown).

**Full suite: 1175 passed, 1 failed** — the failure is the pre-existing
`test_perception_cmd.py` terminal-width artifact.

---

## 8. Files changed

| File | Change |
| :--- | :--- |
| `src/caasi/core/toolctx.py` | **new** — context probe, domain resolution, registry, environment, invocation |
| `src/caasi/cli/tools_cmd.py` | **new** — `caasi tools list|run` and the direct `caasi rviz2/…` surface |
| `src/caasi/cli/main.py` | register the group, the direct tools and the help panel |
| `src/caasi/i18n/en.py` | 16 new strings |
| `tests/test_toolctx.py` | **new** — 35 tests |

Reference trees unchanged: `openmover_robot` `f17c242a…`, `openmover_ws`
`1e09f5de…`, `caasi-workspace/openmover` 0 dirty. The temporary probe targets and
tool entries were removed from the configuration, which is byte-identical to its
original state; the probe ROS 2 node was stopped and its directory removed on
`u24-307`; local probe processes and files were removed.

---

## 9. Next step

**Stopping for F3 review.** Not started: **G4** cleanup, the F1 consolidation item,
and any scheduling/control-plane work.

**Carried forward, none blocking:**

- the **DDS-over-Tailscale limitation** above — an environmental fact, recorded not
  worked around;
- the **F1 consolidation item** (duplicated ladder, `check.strict` divergence);
- the **local build/run destination mismatch** from F2;
- **G4** `remotes:` retirement.
