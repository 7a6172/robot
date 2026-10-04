# Stage D Gap: remote run control uses timeouts that are too small for slow targets

**Status:** Identified during Phase 7 Stage D (real remote target validation)
**Severity:** Remote `run stop` / status / logs fail or mis-report on targets with
non-trivial SSH latency
**Scope:** `caasi.core.runs` remote paths
**Related:** `stage-d-gap-ssh-timeout.md` (same root cause, discovery path)

---

## 1. What Stage D exposed

With a genuinely remote target (`u24-307`, ~5–6 s SSH round-trip via a Tailscale
relay), stopping a live remote run failed:

```console
$ caasi run stop 20261004-182424-target-smoke-stop
TimeoutExpired: Command '['ssh', ..., 'kill -TERM -78467 2>/dev/null || kill -TERM 78467 ...']'
timed out after 5.0 seconds

$ caasi run status 20261004-182424-target-smoke-stop
  Status           lost
```

## 2. What actually happened

The kill **succeeded**. Verified directly on the target immediately afterwards:

```text
  are the tested PIDs still alive?
    gone:  78467
    gone:  78488
    gone:  78493
  any process in PGID 78467?
    (none)
```

So the process tree was terminated correctly, but caasi's own SSH round-trips
each need ~5–6 s while the code budgets **5.0 s per call**. Every step of
`remote_stop_run` (check-alive, SIGTERM, poll, SIGKILL, manifest update) can
individually exceed its budget, so:

- the operation raises `TimeoutExpired`, and
- the run is then reported as **`lost`** rather than **`stopped`** — a
  *mis-report*, not merely a slow path.

A stale `lost` status is actively harmful: an operator reading it cannot tell
whether the workload was actually terminated, which is precisely the question
`stop` exists to answer.

## 3. Root cause in the code

`caasi/core/runs.py` hardcodes **12** subprocess timeouts across the remote
paths:

| Line(s) | Operation | Budget |
| :--- | :--- | :--- |
| 218 | `remote_effective_status` (check-alive probe) | 5.0 s |
| 477 | `remote_stop_run` check-alive | 5.0 s |
| 486 | `remote_stop_run` SIGTERM | 5.0 s |
| 496 | `remote_stop_run` poll loop | 5.0 s |
| 506 | `remote_stop_run` SIGKILL | 5.0 s |
| 512 | `remote_stop_run` final check | 5.0 s |
| 524 | `remote_stop_run` manifest update | 5.0 s |
| 671 | `read_run_log` (`tail` over SSH) | 10.0 s |
| 707 | `inspect_run_files` (`find`/`stat` over SSH) | 10.0 s |
| 875, 893, 970 | launch wrapper upload / launch / provenance | 10.0 s |

None of these is derived from the target. They assume a container or LAN peer
where an SSH round-trip is milliseconds — the exact assumption Stage A and C2
were validated under (`127.0.0.1` containers). Stage D is the first stage to use
a separate machine over a WAN-like path, and it breaks the assumption.

## 4. Why this is a genuine general gap

- Real robotics targets are commonly reached over WiFi, VPN or relayed
  Tailscale links. On such links *every* control-channel round-trip costs
  seconds, so a fixed 5 s budget makes `stop`, `status`, `logs` and `inspect`
  unreliable-to-unusable.
- The failure is **silent in the dangerous direction**: the workload does get
  killed, but caasi reports `lost`, which reads as "state unknown". That is
  worse than an outright error because it can prompt an operator to re-issue
  destructive operations, or to conclude a robot was stopped when it was not
  (or vice versa).
- It is the same class of defect as G1 (fixed budgets that ignore target
  latency), so it should be fixed consistently rather than patched per call.

## 5. Smallest general solution proposed

Reuse the per-target `ssh_timeout` introduced for G1, and derive the run-control
budgets from it. No new concept, no new abstraction:

1. **Scale SSH round-trip budgets from the target**, e.g.
   `per_call = max(5.0, target.ssh_timeout)`, applied to the check-alive,
   SIGTERM, SIGKILL, poll, log-tail and file-inventory calls. A target that does
   not set `ssh_timeout` keeps today's behaviour exactly (default 3.0 ⇒ 5.0 s
   floor unchanged).

2. **Make `stop` distinguish "kill sent" from "state confirmed".** The signal
   delivery and the status confirmation are different facts. If the kill call
   succeeds but a follow-up probe times out, the run status must not be recorded
   as `lost`; it should surface as "stop issued, confirmation unverified" so the
   operator knows the workload was signalled and can re-check, instead of
   reading a false `lost`.

3. **Do not swallow `TimeoutExpired` into a terminal status** in
   `remote_effective_status`: a probe that could not complete is a *transport*
   result, not evidence that the process died.

**Deliberately out of scope:** retries, connection multiplexing/`ControlMaster`,
adaptive back-off, and any scheduling/fleet concern. Those are separate
capabilities and must not be pulled in by this fix.

## 6. Decision

Implement (1) and (2) as the smallest general fix, with tests, then re-run the
Stage D stop step on `u24-307` to confirm `stop` reports `stopped` and the
tested tree is gone. Record the evidence in the Stage D report.
