# Stage D Gap: SSH probe/connect timeout is not configurable

**Status:** Identified during Phase 7 Stage D (real remote target validation)
**Severity:** Blocks real remote targets with non-trivial network latency
**Scope:** `caasi.core.targets`, `caasi.core.deploy`, `caasi.core.build`, `caasi.core.runs`

---

## 1. What Stage D exposed

Stage D validates the target lifecycle against a **real second machine**
(`u24-307`) reached over Tailscale/SSH, rather than a local container.

The very first command failed:

```console
$ caasi target check u24-307
Error: Target 'u24-307' discovery error: Remote probe timed out after 3.0s
```

## 2. Measured cause

The failure is **latency**, not reachability or authentication.

| Layer | Measured | caasi budget | Verdict |
| :--- | :--- | :--- | :--- |
| TCP preflight to `:22` | **~350 ms** | `min(timeout, 2.0)` = 2.0 s | passes comfortably |
| SSH connect + probe round-trip | **~5–6 s** | **3.0 s** (hardcoded) | **fails** |

Three consecutive SSH invocations cost 5.03 s, 6.12 s and 4.83 s. The target is
reached via a Tailscale **relay** (`relay "hkg"`), so the SSH handshake carries a
multi-second round-trip that a local container or LAN target never shows.

## 3. Root cause in the code

Two hardcoded, non-overridable values:

```python
# caasi/core/targets.py — the SSH transport prefix
def target_ssh_prefix(target: Target) -> list[str]:
    args = ["ssh", "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=3",      # <-- hardcoded 3 s
            "-o", "StrictHostKeyChecking=accept-new"]
```

```python
# caasi/core/targets.py — the discovery probe
def discover_target(target, config=None, timeout: float = 3.0):   # <-- default 3 s
```

and four call sites that either pass `3.0` explicitly or rely on the default:

| Call site | Timeout used |
| :--- | :--- |
| `caasi/cli/target_cmd.py` (×4) | default `3.0` |
| `caasi/core/deploy.py:163` | explicit `timeout=3.0` |
| `caasi/core/build.py:428` | default `3.0` |
| `caasi/core/runs.py:761` | default `3.0` |

`Target` has no field to express a per-target or per-environment latency budget.

## 4. Why this is a genuine general gap, not a local hack

- The Stage A/C2 reports validated targets that were **local containers** on
  `127.0.0.1`, where a 3 s budget was generous. Stage D is the first stage to use
  a genuinely separate machine over a WAN-like path, and it exposes the
  assumption.
- Real robotics deployments routinely reach targets over WiFi, VPN, cellular or
  relayed Tailscale paths where SSH setup is seconds, not milliseconds. A fixed
  3 s budget makes such targets permanently unreachable to caasi.
- The failure mode is also **misleading**: it reports "timed out after 3.0s"
  (an error status) rather than "too slow for the configured budget", and the
  same 3 s truncates every later operation (deploy preflight, build, run
  preflight), so the target is unusable end-to-end, not just for `check`.

## 5. Smallest general solution proposed

Add an **optional per-target timeout** with a conservative default, and thread it
through the existing call sites. No new abstraction, no new subsystem:

1. `Target` gains one optional field:

   ```python
   ssh_timeout: float = 3.0     # seconds; per-target override
   ```

   Parsed from the `targets:` section of `caasi.yaml` / global config, exactly
   like the existing `identity` / `port` fields.

2. `target_ssh_prefix(target)` uses `target.ssh_timeout` for `ConnectTimeout`
   instead of the literal `3`.

3. `discover_target(...)` uses `target.ssh_timeout` when the caller does not pass
   an explicit timeout, so all four existing call sites inherit the configured
   value without signature churn.

4. The error message distinguishes *unreachable* from *too slow*, so the operator
   is told to raise `ssh_timeout` rather than chase a phantom connectivity fault.

**Why this is minimal and general.** It is one optional config field plus one
parameter substitution. It is project-agnostic (any slow target benefits), it
preserves current behaviour exactly for targets that do not set the field
(default stays 3.0), and it requires no change to the deployment, build or run
architectures established in Stages A–C2.

**Explicitly out of scope:** retry logic, connection multiplexing/`ControlMaster`,
adaptive timeouts, or any fleet/scheduling concern. Those are separate
capabilities and must not be introduced by this fix.

## 6. Decision

Implemented as the smallest general fix above, with tests, before continuing the
Stage D lifecycle validation. Recorded here first so the change is traceable to
observed evidence rather than to convenience.
