# Phase 8 — M1: Actuation Permission Gate + Fail-Closed Configuration

**Status:** Implemented and workstation-verified, then **read-only reviewed** (see §11).
**No physical hardware contacted, nothing deployed, no package installed, no system configuration
changed.**
**Date:** 2026-10-26
**Scope:** M1 only. M2 and later not started. Watchdog deliberately not implemented.

---

## 1. What was built

| # | Requirement | Implementation |
|---|---|---|
| 1 | `actuation_enabled` defaults false; never granted by hardware selection or YAML | **Two independent factors required** (§12): the parameter (read from the override map, no default) **and** environment variable `CAASI_MOTOR_ACTUATION` exactly `"1"`. A params file cannot set an environment variable, so the params-file bypass found in review is **closed** (`actuation_permitted()`, `:157`). |
| 2 | Verify *every* nonzero path | Call-graph audit (§3, re-verified in §11.1): 5 `sendto()` sites, all in `main()`; 1 runtime, 4 shutdown-flush |
| 3 | Suppress at the final boundary | Guard applied **after** packet composition, immediately before the runtime `sendto()` (`:619`) |
| 4 | No stale release after enabling | `fresh_command_after_enable` latch, re-armed on every disabled→enabled edge; command buffer zeroed on that edge; permission is a **startup decision**, so no runtime transition exists (§5) |
| 5 | Preserve shutdown zero-flush | The 4 flush `sendto()` calls are **deliberately not gated**; covered by a dedicated test |
| 6 | Missing/invalid required params fail closed; report clearly | Presence from the override map; typed reads; distinct FATAL messages for *missing* vs *invalid type*; additionally range-validates geometry/limits |
| 7 | Preserve telemetry while disabled | The gate touches only the two speed bytes; publishers untouched. Verified by test |

---

## 2. Files changed

| File | Change |
|---|---|
| `caasi-workspace/openmover/src/openmover/src/driver/motor_handler.cpp` | Permission flag, fail-closed param loading, range validation, boundary guard, fresh-command latch, **plus the M1 hardening second factor** (env gate, `actuation_permitted()`, denial-reason logging) |
| `caasi-workspace/openmover/src/openmover/config_defaults/hardwares.yaml` | Comment only — **explicitly does not define `actuation_enabled`** |
| `caasi-workspace/openmover/src/openmover/config_defaults/hardware/swjtumover.yaml` | **New.** Robot motion parameters (verified values). Deliberately contains **no** actuation key |
| `caasi-workspace/openmover/src/openmover/launch/hardwares/bringup.launch.py` | Declares `motor_actuation_enabled` (default `'false'`), **validates the raw spelling** (only `true`/`false`), passes it to `motor_handler`, and supplies `CAASI_MOTOR_ACTUATION` via `additional_env` (`'1'` only when the argument is exactly `true`) |
| `caasi/tests/test_motor_actuation_gate.py` | **New.** 9 workstation tests against a UDP sink |

**Deviation, disclosed:** the launch-file edit is arguably M2 territory. It is the *minimum* needed
to satisfy requirement 1 (no YAML grant) while keeping requirement 7 (telemetry alive): without an
explicit supplier the node fails closed and produces no telemetry. No hardware-selection argument
was added — `hardware::`, `lidar_driver::`, `io_driver::` remain untouched for M2.

---

## 3. Call-graph audit (requirement 2 — not assumed)

```
$ grep -nE "\bsend\b|sendmsg|sendto|write\(|MSG_" motor_handler.cpp
619:  sendto(...)   <- the ONLY runtime command transmission   <-- GATE HERE
795:  sendto(...)   \
798:  sendto(...)    |  shutdown zero-flush: speed bytes are
804:  sendto(...)    |  written 0x00 unconditionally, so these
807:  sendto(...)   /   are already safe and are NOT gated
```

No other file in the package emits motor frames (`grep -rl "MOTOR_CMD_BUFFER_SIZE|0x64"` →
`motor_handler.cpp` and `crc8_maxim.cpp` only). `io_board_handler` shares the CRC helper but its
frame has no wheel-RPM field (§11.1). The data path is the single mutable field
`motor_speed_cmd_data.speed_rpm_{left,right}`, written only inside the two `cmd_vel` callbacks.

---

## 4. Configuration separation (requirement 1) — bypass closed (§12)

Verified after the change:

```
lab YAML motor keys:  ['chassis_radius','control_freq','ip_address','odom_compensation_ratio',
                       'port','wheel_acc','wheel_max_speed_rpm','wheel_radius']
lab grants actuation: False
robot YAML:           has actuation key: False
launch default:       motor_actuation_enabled default_value='false'
```

Neither repo YAML declares the key, **and the bypass identified in review is now closed by a
second factor** (§12). A supplied params file that declares `actuation_enabled: true` still sets the
parameter — the override map cannot distinguish it from a `-p` argument — but actuation stays denied
unless the process environment also carries `CAASI_MOTOR_ACTUATION=1`, which **no params file can
set**. Executed proof: params-file `true` with no environment factor transmits only zero speeds
(`test_h4_params_file_alone_cannot_grant`).

Permission therefore travels through an explicit launch argument plus the launch-supplied
environment variable, both visible in provenance. Direct CLI use
(`-p motor.actuation_enabled:=true`) additionally requires the operator to export the environment
variable — a deliberate two-step, documented in §12.6.

**Behaviour change, intended:** the lab bringup now defaults to **deny**. Driving the lab robot
requires passing `motor_actuation_enabled:=true`. This is the deliberate consequence of
requirement 1 and is the D3 decision now needing sign-off.

---

## 5. Stale-command handling (requirement 4)

Two independent mechanisms:

1. **Structural.** Permission is read once at startup and never re-read, so there is no runtime
   disabled→enabled transition to leak through. A `ros2 param set` cannot grant movement
   (verified by `test_runtime_enable_attempt_does_not_actuate`).
2. **Defensive latch.** `fresh_command_after_enable` is set only when a `cmd_vel` arrives *while
   permission is already granted*; on any disabled→enabled edge it is re-armed to false and the
   command buffer is zeroed. If permission is ever made dynamic, a pre-enable command still cannot
   be released.

---

## 6. Test commands and results

```bash
cd caasi-workspace/openmover && source /opt/ros/jazzy/setup.bash \
  && colcon build --packages-select openmover --cmake-args -DCMAKE_BUILD_TYPE=Release
# Result: success, no warnings from motor_handler.cpp

cd caasi && source /opt/ros/jazzy/setup.bash \
  && source ../caasi-workspace/openmover/install/setup.bash \
  && export PYTHONPATH="${PYTHONPATH}:/home/zar/Documents/robot/caasi/src"
.venv/bin/python -m pytest tests/test_motor_actuation_gate.py -v
# Result (pre-hardening): 9 passed
# Result (post-hardening, 16 tests): 16 passed in 224 s
```

| Test | Requirement | Result |
|---|---|---|
| `test_v1_no_nonzero_frame_while_disabled` | 3 | **PASS** — 400+ frames captured, all speed 0, after real nonzero `cmd_vel` |
| `test_v1b_telemetry_still_publishes_while_disabled` | 7 | **PASS** — `odom`, `twist`, `motor_state/{left,right}` all present |
| `test_v2_enabled_actuation_actually_drives` | control | **PASS** — 94 RPM ≈ 0.5 m/s ÷ r 0.05035 (94.8 expected) |
| `test_v3_missing_actuation_param_fails_closed` | 6 | **PASS** — exit 1, names the key |
| `test_v3b_missing_geometry_param_fails_closed` | 6 | **PASS** |
| `test_v4_invalid_actuation_type_fails_closed` | 6 | **PASS** — non-bool refused, not coerced (quoted string; see §11.2 for launch coercion) |
| `test_v6_robot_parameters_are_the_ones_used` | 6 | **PASS** — 92–96 RPM discriminates r=0.05035 from the old default 0.0535 (~89) |
| `test_shutdown_flush_still_emits_zero` | 5 | **PASS** — no nonzero frame at/after shutdown |
| `test_runtime_enable_attempt_does_not_actuate` | 4 | **PASS** — `ros2 param set` cannot escalate |

`test_v2` matters as much as `test_v1`: without it, `test_v1` would pass even if actuation were
broken outright. The pair proves the gate **gates** rather than blanket-blocks.

### 6.1 Regression suite

```bash
.venv/bin/python -m pytest tests/ -q
# 1249 passed, 2 failed, 9 skipped  (239 s)
```

| Failure | Verdict |
|---|---|
| `test_dataset_cmd.py::test_dataset_generate_dry_run` | **PRE-EXISTING** — reproduced against a pristine `git archive HEAD` export (§11.7) |
| `test_perception_cmd.py::test_perception_segment_dry_run_passes_extra_args` | **PRE-EXISTING** — same artifact; already recorded in Phase 7 as a terminal-width wrap |

Both are text-wrapping artifacts in dry-run output (`<dir>` / `model:=unet` wrapped to the next
line); neither touches the motor path. **Zero new failures introduced.**

---

## 7. Findings recorded, not fixed

### 7.1 `motor_handler` exits with SIGSEGV (-11) after the shutdown flush — PRE-EXISTING

Observed while testing requirement 5. Verified pre-existing by stashing all M1 changes, rebuilding
the unmodified source, and reproducing `exit rc: -11` exactly. The flush frames *do* arrive (delta
4, all zero) before the crash. Out of M1 scope; see §11.5 for the full impact assessment.

### 7.2 A ground-truth correction during implementation

Three earlier approaches to parameter presence were **wrong** and were discarded after measurement,
not by preference:

1. `has_parameter()` + `declare_parameter(PARAMETER_NOT_SET)` → `declare_parameter` throws; the
   sentinel type is illegal.
2. `get_parameter_or()` → reports "not set" for an override that has not been declared, so every
   key looked absent.
3. `declare_parameter(name, sentinel)` → declaring consumes the override, and a supplied value
   equal to the sentinel is indistinguishable from absence.

The working mechanism, established by instrumenting the built node
(`get_parameter_overrides()` = 1 entry, `get_parameter_or` = 0), is the **override map**. This is
why `NodeOptions.arguments(argv+1, argc)` is now required — without it the override map is empty.

### 7.3 Harness bugs found in my own test code

- `PYTHONPATH` inherited into `ros2` CLI subprocesses broke their entry-point resolution
  (`importlib.metadata` `StopIteration`), so the publisher died and `cmd_vel` never arrived —
  making early "disabled" passes **vacuous**. Fixed by filtering the caasi path out of the
  subprocess environment (while keeping the ROS entries, which the CLI needs).
- Fresh ROS domains plus a stale daemon produced empty graph queries; tests now use per-test
  domains and `--no-daemon --spin-time 5`.
- The `cmd_vel_mode` service proved unreliable on a cold domain, so tests drive the **manual**
  channel, whose flag defaults to true. Both channels reach the same boundary, so what is proven
  is unchanged.

### 7.4 Environment limitation

`ros2 launch openmover bringup.launch.py --show-args` fails on this workstation because
`ros_gz_sim` is not installed. The launch edit was therefore verified **statically** (syntax +
argument default + parameter wiring) rather than by launch introspection, with the wiring
*mechanism* probed separately by execution (§11.4). Full project-launch validation remains an M2
concern.

---

## 8. Remaining risks

| Risk | Severity | Mitigation / status |
|---|---|---|
| Lab bringup now denies actuation until `motor_actuation_enabled:=true` is passed | **Medium (intended)** | Explicit, visible, documented; D3 decided (option a) |
| ~~A supplied params-file can grant actuation~~ | ~~High~~ | **CLOSED by the M1 hardening — §12** |
| Permission is startup-only, so it cannot be revoked at runtime | Medium | Fails safe (cannot escalate); runtime revoke is a future improvement |
| No `cmd_vel` timeout → last command persists | **High (pre-existing)** | Out of scope (D7); **blocks M7** |
| SIGSEGV on exit | Medium (pre-existing) | Recorded; §11.5 |
| Launch path unverifiable on this host (`ros_gz_sim` missing) | Medium | Mechanism verified separately; resolve in M2 |
| Range thresholds are judgement values | Low | Conservative and visible in the FATAL message |

---

## 9. What was NOT done (scope discipline)

No M2 hardware-selection argument · no Vanjee integration · no `screen_node` port ·
no `swjtumover_msgs` work · no watchdog · no deployment · no hardware driver run ·
no package installed · no system configuration changed.

---

## 10. Decision needed (D3)

**Decided: option (a)** — the lab bringup stays actuation-disabled by default, and
`motor_actuation_enabled:=true` is passed explicitly when intentionally operating the lab setup.
No automatic lab opt-in is to be introduced in M2 without separate approval.

---

## 11. Read-only M1 review (2026-10-26)

**Method:** read-only inspection plus executed probes against the built binary, a throwaway launch
file in `/tmp`, and a **pristine `git archive` export** of `HEAD`. No source, test, config,
dependency or system setting was modified. `/tmp` artefacts only.

### 11.1 Permission enforcement — PASS

| Check | Evidence |
|---|---|
| Socket-write sites | **5** `sendto()` in `motor_handler.cpp`: `:619` runtime; `:795/:798/:804/:807` shutdown flush |
| Speed-byte writes | only `:582-583` (gated) and `:785-786` (flush, zeros) |
| Command-state writes | `motor_speed_cmd_data.speed_rpm_*` written **only** in the two `cmd_vel` callbacks (`:211-270`) plus the enable-edge zero (`:564-565`) |
| Other motor-capable nodes | `io_board_handler` shares `crc8_maxim` but its frame (`ros_to_io_frame_t`) has **no wheel-RPM field** — only reported `vx`/`vyaw`. **Cannot command motor speed.** |
| Gate placement | after packet composition, immediately before `:619` |

**Verdict:** the single runtime transmission path is guarded, and the shutdown flush is correctly
excluded from the gate (it writes zeros unconditionally). Requirements 2 and 5 hold.

**Observation (low severity, not fixed).** The brake/release byte logic (`:596`, `:604`) reads the
**ungated** stored `motor_speed_cmd_data.speed_rpm_*`, not the gated `speed_rpm`. While disabled
with a nonzero command stored, byte[7] stays `0x00` instead of `0xff`. The transmitted **speed is
still 0**, so no motion is possible. ROS1 has byte-identical logic and no comment explaining
byte[7], so its meaning is undocumented in both trees; parity is preserved. Not a safety defect;
worth documenting.

### 11.2 Fail-closed configuration — PASS, with one uncovered granting path (§11.6)

| Case | Result |
|---|---|
| Missing required key | FATAL, exit 1, key named |
| Non-boolean permission (`garbage`, `1`) | FATAL "type invalid", exit 1 |
| Out-of-range `control_freq: 0.0` | FATAL "value invalid" |
| Out-of-range `wheel_acc: -5` | FATAL "value invalid" |
| Out-of-range `chassis_radius: 0.0` | FATAL "value invalid" |
| Integer literal for a double param (`chassis_radius: 0`) | FATAL "type invalid" (strict typing) |

**Strict-boolean caveat — launch-time coercion.** Via `ros2 launch`, YAML-standard truthy spellings
are accepted as enabled:

```
motor_actuation_enabled:=true    -> actuation_enabled=true
motor_actuation_enabled:=yes     -> actuation_enabled=true
motor_actuation_enabled:=1       -> FATAL type invalid
motor_actuation_enabled:=garbage -> FATAL type invalid
```

`yes` becoming **true** is standard YAML 1.1 parsing and is an *explicit* operator input, so it does
not enable actuation implicitly. It does mean "strict Boolean" is in practice "YAML boolean". A
literal-`true`-only rule would be a deliberate tightening to decide, not a defect to patch silently.

### 11.3 Stale commands / no runtime escalation — PASS

| Check | Evidence |
|---|---|
| Permission assignment sites | **exactly one** (`:458`, startup). No re-read anywhere |
| Runtime escalation | `ros2 param set ... actuation_enabled true` → node keeps running, no motion; covered by `test_runtime_enable_attempt_does_not_actuate` |
| Stale release | impossible by construction (no runtime transition) + defensive latch, re-armed and buffer zeroed on the enable edge (`:561-567`) |

**Observation (usability, fail-safe).** `ros2 param set` reports **"Set parameter successful"**
while having no effect, because permission is read once. An operator could believe actuation was
enabled when it was not. Fails safe, but the CLI message is misleading.

### 11.4 Launch wiring — PASS, now evidence-based rather than assumed

Previously **unverified by execution** (`ros_gz_sim` is absent, so the project's bringup cannot be
introspected here). The mechanism was therefore probed directly:

- `/tmp/m1_wiring_probe.launch.py` declared the argument and passed
  `{'motor.actuation_enabled': LaunchConfiguration(...)}` to the real `motor_handler`, mirroring
  `bringup.launch.py`.
- **Executed result:** `actuation_enabled=false` — the substitution arrives as a **bool**, not a
  string. Had it arrived as a string, the node would have refused to start with a type error.
- Declaration, default (`'false'`) and node wiring confirmed **statically** in
  `bringup.launch.py:102` (binding), `:183` (declare, default `'false'`), `:261` (parameter).

**Remaining gap:** the *project's* bringup as a whole is still only statically verified on this
host; full launch validation needs `ros_gz_sim` (M2 concern).

### 11.5 Shutdown SIGSEGV — separate pre-existing defect, no established safety impact

| Measurement | Result |
|---|---|
| Reproducibility | **3/3 runs**, `exit=-11` (SIGSEGV) |
| Flush before crash | **4 frames, all speed 0**, every run |
| ROS1 equivalent | same 4-send zero flush, then `return 0`; no rclcpp teardown |

**Assessment:** cleanup and shutdown *sequencing* are correct — the zero flush always completes
before the crash. Impact is **reliability/provenance, not safety**: a normally-exiting node reports
signal 11 (shell rc 139), so `caasi run` would record a successful run as failed.

**ROS1/ROS2 comparison**

| Component | ROS1 finding | ROS2 finding | Evidence | Recommended action |
|---|---|---|---|---|
| Shutdown | flush then `return 0`; no teardown | **SIGSEGV after flush**, 3/3 | measured; ROS1 not executable here | fix in a later milestone (likely teardown ordering) |
| `cmd_vel` timeout | **none** — last command persists | **none** — same | `grep` both trees | D7 blocker for M7; separate change |
| Param defaults | `param(name, default)` fail-open | *was* fail-open; **now fixed** | source both trees | ROS1 still fail-open (unchanged, read-only) |
| Actuation permission | **absent entirely** (0 matches) | present, default deny | source both trees | ROS2 improvement; ROS1 gap documented |

Not fixed within M1, per instruction. **No direct safety impact established.**

### 11.6 DEFECT FOUND — a YAML file CAN grant actuation (corrects §4)

**Confirmed by execution:**

```
$ motor_handler --ros-args --params-file /tmp/grant.yaml   # declares actuation_enabled: true
[INFO] actuation_enabled=true
```

Also enabled by `yes`, `on`, `TRUE`; rejected for `1`; denied for `false`.

**Why:** the implementation reads the merged parameter-override map, which merges `-p` arguments
**and** params-file values and exposes no origin. So "a YAML cannot grant" was an inference from
the absence of the key in this repo's YAMLs — not an enforced property. **That claim in the earlier
version of this report was wrong and is corrected in §4.**

**Impact:** the stated requirement ("must not be granted … by loading a YAML file") is **not met by
mechanism**. Practical risk today is low — no repo YAML contains the key, and granting requires
deliberately writing it — but the guarantee is policy, not enforcement.

**Recommended fix (needs approval; ~10 lines):** require a second, launch-only signal that a params
file cannot set — e.g. the node also requires environment variable `CAASI_MOTOR_ACTUATION=1`
(exact string match), with the launch file supplying it only when
`motor_actuation_enabled:=true`. Environment variables are not settable from ROS parameter files,
which restores the property mechanically. Alternatives (scanning params files at launch) are
bypassable via direct `ros2 run --params-file`.

### 11.7 Regression baseline — evidence preserved

Verified against a **pristine `git archive HEAD` export** (working tree untouched):

```
2 failed in 0.80s
FAILED tests/test_dataset_cmd.py::test_dataset_generate_dry_run
FAILED tests/test_perception_cmd.py::test_perception_segment_dry_run_passes_extra_args
```

Both are dry-run text-wrapping artifacts, unrelated to the motor path. **No test was altered.**

### 11.8 Unresolved risks

| Risk | Severity | Status |
|---|---|---|
| **Params file can grant actuation** (§11.6) | **High vs the stated requirement** | open — fix recommended, awaiting approval |
| No `cmd_vel` timeout | **High (pre-existing, both trees)** | D7; blocks M7 |
| Shutdown SIGSEGV (rc 139) | Medium (reliability) | separate defect, unfixed by design |
| `ros2 param set` reports success with no effect | Low (fail-safe, misleading) | document |
| `yes` accepted as true | Low (explicit input) | decide whether to tighten |
| Project bringup not launch-executed here (`ros_gz_sim`) | Medium | M2 |
| Integer literal rejected for double params | Low (strict, surprising) | document |

### 11.9 Recommendation

**The gate itself is sound and should be kept.** Permission enforcement, fail-closed loading,
stale-command handling, telemetry preservation and flush integrity all pass with executed evidence.

**But one explicit safety requirement was not met by mechanism** — a params file could still grant
actuation (§11.6). That gap was subsequently **fixed and verified in §12**: permission now requires
the parameter *and* `CAASI_MOTOR_ACTUATION=1`, so the params-file bypass is closed mechanically.
This recommendation is therefore superseded by §12.7.

---

## 12. M1 hardening — params-file bypass closed, strict Boolean (2026-10-26)

Authorized as a narrowly scoped follow-up to §11.6. No M2 work, no hardware, no deployment.

### 12.1 The fix

Permission now requires **two independent factors**, both read once at startup:

```cpp
inline bool actuation_permitted() { return actuation_enabled && actuation_env_ok; }
```

| Factor | Source | Default |
|---|---|---|
| `motor.actuation_enabled` | parameter override map | **absent ⇒ deny** |
| `CAASI_MOTOR_ACTUATION` | **process environment**, exact string `"1"` | **absent/any other ⇒ deny** |

A ROS 2 parameter *file* cannot set an environment variable, so the bypass is closed
**mechanically**, not by convention. The boundary guard now reads
`if (!actuation_permitted() || !fresh_command_after_enable) speed_rpm = 0;`, and the
fresh-command latch is also gated on the full predicate.

**Denial reason is logged without logging sensitive data** (the variable is a permission flag,
not a secret; only satisfied/not-satisfied is reported):

```
物理驱动禁用（缺少: 环境变量 CAASI_MOTOR_ACTUATION）
物理驱动禁用（缺少: 参数 motor.actuation_enabled）
物理驱动禁用（缺少: 参数与环境变量）
物理驱动已启用（参数=true 且 CAASI_MOTOR_ACTUATION=1）
```

### 12.2 Launch wiring (inspected, then executed)

`bringup.launch.py` now:
- validates the **raw** launch-argument string in an `OpaqueFunction` that runs before any node,
  rejecting anything other than exactly `true`/`false`;
- maps the argument to the environment with a `PythonExpression`
  (`'1' if arg == 'true' else '0'`) and passes it on the motor node only, via
  `additional_env={'CAASI_MOTOR_ACTUATION': ...}`.

**Executed** against a mirror launch file (the project bringup still cannot run here — `ros_gz_sim`
absent), so this is not inference:

| Launch argument | Outcome |
|---|---|
| `false` (default) | node runs, `物理驱动禁用` |
| `true` | node runs, `物理驱动已启用` (launch supplied the env factor) |
| `yes` / `on` / `TRUE` / `1` | **rejected before any node starts** (`must be exactly 'true' or 'false'`) |
| empty | rejected by `ros2 launch` itself (`malformed launch argument`) |

This is the earliest reliable boundary: ROS 2 parses argument values as YAML, so `yes` would
otherwise become boolean `true` *before* the node could see the spelling.

### 12.3 Executed permission matrix (direct node invocation)

| Parameter | `CAASI_MOTOR_ACTUATION` | Result |
|---|---|---|
| `true` | `1` | **enabled** |
| `true` | unset | denied |
| `true` | `0` / `true` / `yes` / `01` / `" 1"` / `""` / `TRUE` | denied |
| `false` | `1` | denied |
| from **params file** `true` | unset | **denied** ← the bypass, now closed |
| from params file `true` | `1` | enabled (both factors deliberately present) |

### 12.4 Test evidence

```
.venv/bin/python -m pytest tests/test_motor_actuation_gate.py -q
16 passed in 224.09s
```

New/updated coverage (`test_motor_actuation_gate.py`):

| Test | Proves |
|---|---|
| `test_h1_param_true_without_env_denies` | param alone is insufficient |
| `test_h2_param_true_with_wrong_env_values_denies` | 7 wrong values, incl. `""` and `" 1"`, all deny |
| `test_h3_param_false_with_env_one_denies` | env alone is insufficient |
| `test_h4_params_file_alone_cannot_grant` | **the review bypass** — params file `true` + no env ⇒ no motion |
| `test_h5_both_factors_permit_and_drive` | positive control: both factors ⇒ nonzero frames |
| `test_h6_invalid_param_types_fail_closed` | `"yes"`, `1`, `0.5`, `"on"` refused at startup |
| `test_h7_geometry_validation_intact` | existing range validation preserved |
| earlier V1/V1b/V2/V3/V3b/V4/V6 + flush + runtime-escalation | still green |

### 12.5 Regression

```
2 failed, 1249 passed, 16 skipped in 247.98s
```

**Identical failure set to the preserved baseline** (`test_dataset_cmd`,
`test_perception_cmd` — terminal-width wrap, reproduced against a pristine `git archive HEAD`).
The skipped count rose 9 → 16 because the hardware-gated tests were added. **No new failures, no
tests altered.**

### 12.6 Status of previously-open items

| Item | Status |
|---|---|
| Params-file can grant actuation (§11.6) | **CLOSED** — §12.1 |
| Ambiguous Boolean spellings (`yes`/`on`/`TRUE`) | **CLOSED at the launch boundary** — §12.2 |
| `ros2 param set` reports success with no effect | open (fail-safe, misleading) — document only |
| Brake byte `[7]` uses the ungated stored speed | open (no motion risk) — document only |
| Shutdown SIGSEGV (rc 139) | open, pre-existing, no established safety impact |
| No `cmd_vel` watchdog | open, pre-existing, **blocks M7** |
| Direct `-p motor.actuation_enabled:=yes` on the CLI | **residual**: bypasses launch validation; YAML-parsed to `true`, but the env factor is still required, so it cannot grant alone. Documented, not silently accepted. |

### 12.7 Recommendation (supersedes §11.9)

The two review conditions that blocked closure are now closed with executed evidence: the
params-file bypass (§12.1, `test_h4`) and ambiguous Boolean spellings at the launch boundary
(§12.2, executed matrix). Regression is unchanged from baseline.

**M1 can be closed**, with these carried forward as separate, non-blocking items: the shutdown
SIGSEGV (reliability only), the `ros2 param set` message (documentation), the brake-byte
observation (no motion risk), and the direct-CLI `-p ...:=yes` residual noted in §12.6.

**The `cmd_vel` watchdog remains a hard blocker for M7 (any physical movement test).** It is out of
M1 scope and still unfixed.

---

## 13. Batch D — command watchdog implemented (2026-10-26)

### 13.1 The defect

Both trees kept the last instructed speed forever. `speed_rpm_*` was written only inside
the `cmd_vel` callbacks, and the send loop transmitted the stored value every iteration
with no expiry, so a command source that stopped mid-command left the robot driving.
**Pre-existing in both ROS 1 and ROS 2** — not a parity defect, and not something to
preserve for the sake of matching.

### 13.2 The fix

| | |
|---|---|
| Parameter | `motor.cmd_vel_timeout`, seconds, **optional**, default `0.5` |
| Semantics | command older than the window is zeroed in the loop, before the boundary guard |
| Negative | treated as "disabled" (never "instant expiry") |
| `0` / `0.0` | expiry explicitly disabled |
| Separation | **independent of actuation permission** — permission asks *"may this process drive at all?"*, the watchdog asks *"should the last command still be in effect?"* |

Why defaulted rather than required: this parameter can only ever **reduce** motion, so a
default is safe — unlike the motion-determining set, which stays fail-closed.

### 13.3 Implementation note (a trap hit twice)

`get_parameter_or()` reports "not set" for an override that was never declared, so the
first implementation silently ignored every supplied value and always used the default
(measured: `0`, `0.0`, `2.0` all logged `0.50 s`). The value is now read from the
override map, accepting both integer and double spellings. Identical to the trap the
required parameters hit earlier — recorded so it is not repeated a third time.

### 13.4 Evidence (workstation, UDP sink)

```
nonzero frames while commanded : 87
nonzero frames >1s after stop  : 0        <- command expired
```

Tests added to `test_motor_actuation_gate.py` (now **19**):

| Test | Proves |
|---|---|
| `test_w1_command_expires_after_timeout` | expiry works, and is not vacuous (asserts frames were nonzero first) |
| `test_w2_watchdog_does_not_grant_permission` | expiry is not an authorisation path |
| `test_w3_timeout_zero_disables_expiry_by_explicit_choice` | opt-out is explicit and still requires both permission factors |

### 13.5 Status of the M7 blocker

The watchdog now exists and is tested, which **removes the specific defect that blocked
physical movement testing**. It does **not** by itself authorise movement: M7 still needs
explicit approval, a raised robot, and a supervised procedure. Also still open and
unrelated: the shutdown SIGSEGV (reliability only).
