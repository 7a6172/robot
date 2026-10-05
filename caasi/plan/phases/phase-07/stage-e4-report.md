# Phase 7 Stage E4 Report: Persistent Runtime Lifecycle

**Status:** Completed & Empirically Verified (with explicitly untested parts)
**Date:** October 2026
**Parents:** [`stage-e4-discovery.md`](stage-e4-discovery.md) (the evidence and design this implements), [`stage-e3-report.md`](stage-e3-report.md) (the adapter pattern it builds on)

---

## 1. The question

> If caasi deploys software to a long-lived target such as a robot, how does caasi
> install / configure / enable / verify / manage that deployment over time?

Lifecycle: `deploy → install → enable → start → operate → update → verify → rollback`

---

## 2. The boundary, held

> **caasi owns identity, declaration, invocation, verification and provenance.
> The native mechanism owns running the service.**

caasi renders a unit from the project's declaration, invokes `systemctl`, and then
**asks systemd** what the state is. It has no restart loop, no dependency graph,
and no process table of its own. It is not a supervisor, and E3's read-only
observability adapters are unchanged.

---

## 3. What was implemented

### 3.1 Two declarations, because they are two problems

The reference (`openmover_robot/install.sh`) solved only **environment**
persistence, via five `~/.bashrc` appends; it never installed a service, and
grepping it for `systemd|rc.local|autostart|cron` returns nothing. Copying that
approach would be wrong: it is shell-specific, not idempotent, and not verifiable.

So the two concerns are separated and both declared:

```yaml
lifecycle: persistent
runtime:
  kind: systemd
  unit: openmover.service
  entrypoint: ros2 launch openmover bootloader.launch.py system_mode:=1
  working_dir: .
  environment:
    - source /opt/ros/jazzy/setup.bash
    - source install/setup.bash
    - export RCUTILS_LOGGING_BUFFERED_STREAM=1
  restart: on-failure
```

| Concern | Reference | caasi |
| :--- | :--- | :--- |
| Environment persistence | `~/.bashrc` appends | declared, rendered to a systemd `EnvironmentFile` + login shell |
| Service persistence | **not done** | declared entrypoint, unit rendered, enablement delegated to systemd |

### 3.2 `caasi.core.lifecycle` (new module)

`parse_runtime` / `render_env_fragment` / `render_systemd_unit` /
`plan_install` (pure) / `install_runtime` / `enable_runtime` / `start_runtime` /
`runtime_status` / `verify_runtime` / `update_runtime` / `rollback_runtime` /
`check_rollback_feasibility`, plus `RuntimeState` (deployment id, git revision,
installed time, previous revision).

### 3.3 `caasi runtime` (new command group)

```bash
caasi runtime install  <target> [--dry-run] [--json]
caasi runtime enable   <target> [--disable]
caasi runtime start    <target> [--stop]
caasi runtime status   <target> [--json]
caasi runtime verify   <target> [--json]
caasi runtime update   <target> [--json]
caasi runtime rollback <target> [--json]
```

`install` writes three things and nothing else: an environment fragment, the
unit, and the revision marker. It deliberately does **not** enable or start, so a
partial failure is visible rather than half-applied invisibly.

---

## 4. Design decisions

1. **Environment and service persistence are separate declarations.** Conflating
   them is what made the reference unverifiable.
2. **`EnvironmentFile` syntax is not shell syntax.** Measured: systemd logged
   *"Ignoring invalid environment assignment 'export A=1'"* and dropped it,
   leaving the service running with the variable missing. Assignments are now
   normalised to `KEY=VALUE`; `source` lines cannot be expressed there at all and
   are applied by the login shell that runs the entrypoint.
3. **A unit is a rendering of a declaration.** caasi supplies structure (workdir,
   env wiring, restart policy); the project supplies the entrypoint. Everything
   describing what the robot does comes from the project.
4. **A revision marker records what is active**, retaining the previous revision,
   because rollback needs something real to return to.
5. **Rollback restores content; it does not relabel.** See §5.2.
6. **Nothing is deleted.** Rollback reinstalls; no lifecycle operation removes a
   revision or a deployment.

---

## 5. Defects found by validating against a real target

Recorded because they are the substance of the stage.

### 5.1 `deploy` destroyed caasi's own runtime state

`caasi deploy` uses `rsync -a --delete`. Because `.caasi-runtime.json` and
`.caasi-env.sh` are written by `caasi runtime install` and are not shipped by the
project, `--delete` removed them on the next deploy — **silently destroying the
rollback point**.

Found by tracing: `runtime update` reported `read previous=None` even though the
marker existed, because the preceding deploy had deleted it. Both filenames are
now in `DEFAULT_EXCLUDE_PATTERNS`. Verified: the marker now survives a deploy and
the chain is intact (`active=…122049`, `previous=…121803`).

### 5.2 Rollback as a marker rewrite was a lie

The first implementation of `rollback` rewrote the marker to the previous
revision and restarted — but left the newer **files** in place, since it never
deleted anything. Measured result on `u24-307`:

```text
marker says r5   |   files on disk are r6   |   process runs r6
```

The marker misrepresented reality. **This was put to the user as a design fork
rather than patched silently**, and the decision was: *rollback = redeploy the
previous revision from the workstation*. Rollback now re-materializes content
through the ordinary deploy path, and `verify` compares the **revision**
(treating a `-dirty` suffix as the same content identity) while reporting a
changed deployment id as evidence, not drift.

### 5.3 Rollback could not be honest, so it refuses

If the workstation is not at the recorded revision, or has uncommitted changes,
rollback **refuses and changes nothing**:

```console
$ caasi runtime rollback u24-307
✖ rollback on u24-307: workstation is at 5acfa0d… but the rollback target is
  3f06b5a…; rollback redeploys the previous revision from the workstation,
  so check out 3f06b5a… first
```

A subtlety: `git status` counts caasi's own `.caasi/` bookkeeping as dirt, which
produced a message telling the operator to check out the revision they were
already on. caasi's bookkeeping is now excluded from that judgement, since caasi
writes it and never deploys it.

### 5.4 `update` overwrote the rollback point on a reinstall

Re-installing the revision already active set `previous` to that same revision,
making the marker self-referential and losing the original rollback point. Found
by a unit test; `update` now distinguishes a genuine update (record the active
revision) from a reinstall (preserve the existing chain).

---

## 6. Validation on the real target

Fixture: a trivial long-running Python service that prints its revision and a
marker variable. Deliberately minimal — this stage proves the *lifecycle
mechanism*, not the robot stack. Target: **`u24-307`** (real systemd, no container
runtime).

| Step | Result |
| :--- | :--- |
| `install --dry-run` | Plan printed, nothing written |
| `install` | Env fragment + unit + marker written; verified by reading them back on the target |
| `enable` | `systemd` created `default.target.wants/…` symlink |
| `start` | `active (running)`, MainPID reported |
| env reaches the process | `CAASI_E4_MARKER=hello-from-env` present in `/proc/<pid>/environ`, **0** "Ignoring invalid" warnings |
| `status` | `enabled` + `active (running)` + MainPID, from systemd's own properties |
| `verify` | Passes; reports the active revision |
| `update` A→B | New PID, app reports `revision=rB`, marker chain records previous=A |
| `rollback` (not restorable) | **Refused** with the checkout instruction; target untouched |
| `rollback` (restorable) | Redeployed revision A; disk, process and marker **consistent** |
| `verify` after rollback | Passes on revision; deployment-id change reported as evidence |
| Drift: service stopped | `verify` **failed** (`not active (state=inactive)`), exit code **1** |
| Failed update | Bad entrypoint → `state=failed`, exit 127, `verify` failed, exit code 1, message named the retained previous revision and the recovery command |
| Recovery from failed update | `rollback` restored the good revision; `verify` passed; env still applied |

The environment-precedence check (`/proc/<pid>/environ`) is what caught the
`EnvironmentFile` syntax bug — the service *ran* and looked healthy while the
variable was silently absent. Running the service was not sufficient evidence.

---

## 7. Version

Phase 7 is scoped as the upcoming **caasi 0.4.0** milestone: *target and
control-plane capabilities*. `pyproject.toml` and `__version__` are set to
`0.4.0`, and `CHANGELOG.md` records remote targets, deployment/execution,
observability (ROS 2 + non-ROS adapters), result collection and the runtime
lifecycle under that version, with the two deploy/rollback defects above recorded
as fixes. No other version-related behavior was changed.

---

## 8. What is NOT claimed

Stated before implementation and still true after it, so claims cannot drift:

- **No physical reboot recovery.** `Linger=no` on the measured target meant user
  units did not survive logout or reboot there. All *preconditions* were then
  established and observed — `Linger=yes` set successfully, the `default.target.wants`
  symlink created, `UnitFileState=enabled` — **but the machine was never rebooted**,
  so reboot survival is **untested and not claimed**. The lingering probe was
  reverted afterwards to leave the target as it was found.
- **No physical robot bringup persistence.** No robot hardware was involved.
- **No claim that the OpenMover stack itself runs persistently.** The rendering
  was exercised with the real project's entrypoint and environment (§3.1), but the
  stack was not running as a managed service on hardware.
- **System scope untested.** Only user-scope units were used; system-scope would
  need privileges this stage did not have and did not seek.
- **No container/systemd-unit backend other than systemd.** The registry shape is
  left open, but only systemd is implemented.

---

## 9. Tests

**55 new tests** in `tests/test_lifecycle.py`: declaration parsing and rejection;
environment splitting, `export` normalisation, `source` exclusion, and
`{{dest}}`/relative resolution (including a regression for the double-prefixing
bug); unit rendering (login shell, `exec`, working directory, restart policy);
state round-trip and forward compatibility; revision comparison with `-dirty`;
the rollback refusal rules including the `.caasi/`-is-not-dirt case; install
success, per-file failure reporting, dry-run writing nothing, and previous-revision
recording; enable/start/status delegation to the exact `systemctl` verbs; verify
against revision drift, a stopped service, a disabled unit and a never-installed
runtime; the deployment-id-is-not-drift distinction; rollback refusal paths,
that a failed redeploy does not touch the target, and that a successful rollback
is itself reversible; update chain-awareness, verification failure, and that a
failed install is not followed by a restart.

**Full suite: 1054 passed, 1 failed.** The failure
(`test_perception_cmd.py::test_perception_segment_dry_run_passes_extra_args`) is
the pre-existing terminal-width artifact, unrelated to this stage. One real
regression *was* introduced and fixed: `runtime` had to be added to
`HELP_PANELS`, caught by `test_help_panels_cover_every_root_command`.

---

## 10. Files changed

| File | Change |
| :--- | :--- |
| `src/caasi/core/lifecycle.py` | **new** — declaration, rendering, install, enable, start, status, verify, update, rollback |
| `src/caasi/cli/runtime_cmd.py` | **new** — the `caasi runtime` command group |
| `src/caasi/core/manifest.py` | read/serialize `runtime:` and `lifecycle:` |
| `src/caasi/core/deploy.py` | exclude caasi's runtime state from `rsync --delete` |
| `src/caasi/cli/main.py` | register the group; add it to the platform help panel |
| `src/caasi/i18n/en.py` | 29 new strings |
| `src/caasi/__init__.py`, `pyproject.toml` | 0.4.0 |
| `CHANGELOG.md` | 0.4.0 milestone entry |
| `tests/test_lifecycle.py` | **new** — 55 tests |

Reference trees unchanged: `openmover_robot` `f17c242a…`, `openmover_ws`
`1e09f5de…`. All fixtures removed from `u24-307` (unit stopped, disabled and
deleted; deployment root removed; lingering reverted) and locally.

---

## 11. Next step

Stage E4 is complete. **Do not auto-proceed.** Fleet scheduling and other
control-plane features were explicitly out of scope for this bounded stage.

The natural next validations, each needing something this environment does not
have, are: **actual reboot survival** (needs a target that may be rebooted),
**system-scope units** (needs privileges), and **running the real robot stack as
a managed service** (needs robot hardware). The documented E1 `required:`
limitation remains documented and was not expanded.
