# Phase 7 Stage E4 Discovery: Persistent Runtime Lifecycle

**Status:** Discovery + Design (implementation follows)
**Date:** October 2026
**Parents:** [`stage-e-discovery.md`](stage-e-discovery.md) (the two-lifecycle analysis), [`stage-e3-report.md`](stage-e3-report.md) (adapter pattern)

---

## 1. The question

> If caasi deploys software to a long-lived target such as a robot, how does caasi
> install / configure / enable / verify / manage that deployment over time?

`deploy` and `build` already land software on a target (Stages B, C1). What is
missing is everything that makes the result *an operational installation*: the
target should bring the stack up itself, after logout and after reboot, without
the workstation.

---

## 2. What the reference actually does — measured, not assumed

The task warns against reproducing OpenMover's `.bashrc` setup as the caasi
architecture. Reading `openmover_robot/install.sh` confirms why it must not be
treated as a design:

**Observed fact.** The only *persistence* the reference establishes is shell
environment. Five appends, and nothing else:

```text
source /opt/ros/noetic/setup.bash                                              >> ~/.bashrc
source .../cartographer_ws/install_isolated/setup.bash --extend                >> ~/.bashrc
source .../openmover_ws/devel/setup.bash --extend                              >> ~/.bashrc
export PYTHONPATH=$PYTHONPATH:.../scripts/hal                                  >> ~/.bashrc
export DISABLE_ROS1_EOL_WARNINGS=1                                             >> ~/.bashrc
```

**Observed fact.** It never installs a service, never touches systemd, never
adds an autostart entry. Grepping the whole script for `systemd|rc.local|
autostart|cron` returns nothing.

So the reference establishes **environment persistence only**. Bringing the robot
up was a manual act (`roslaunch openmover bootloader.launch`), and the
`bootloader.launch` file is the *entrypoint description* — it names the nodes to
run, and it is the closest thing the reference has to a service definition.

**Consequence for the design.** There are two distinct persistent concerns, and
the reference only solved one:

| Concern | Reference | caasi |
| :--- | :--- | :--- |
| **Environment persistence** — a shell on the robot finds ROS and the project overlay | `~/.bashrc` appends | must be generalised, not copied |
| **Service persistence** — the stack starts itself and comes back after reboot | **not done** | must be added, via a native mechanism |

Copying `.bashrc` appends would be wrong for three reasons: it is shell-specific
(useless to a systemd unit or a container), it is not idempotent (re-running
duplicates lines forever), and it is not verifiable (nothing can ask "is the
robot's environment correct?").

---

## 3. What the target can actually do — measured

**Measured on `u24-307` (the real remote target):**

| Mechanism | Present |
| :--- | :--- |
| systemd (systemd running as PID 1) | **yes** |
| `systemctl` / `journalctl` | **yes** |
| `/proc` | yes |
| docker / podman | **no** |

**The critical constraint — measured:**

```console
$ loginctl show-user zar | grep -E '^(Linger|State)'
State=active
Linger=no
```

`Linger=no` means **user units do not survive logout or reboot** on this target.
That is a genuine, measured limitation and it bounds what this stage may claim:
caasi can install and enable a unit and record that enablement, but
**user-scope reboot durability cannot be demonstrated here**, and will not be
claimed. Full durability needs either lingering enabled or a system-scope unit,
both of which are target-provisioning decisions, not caasi features.

This is exactly the kind of boundary the stage must state rather than paper over.

---

## 4. Design

### 4.1 The boundary, restated for lifecycle

> **caasi owns identity, declaration, invocation, verification and provenance.
> The native mechanism owns running the thing.**

caasi writes a unit *template* the project supplies, installs it, enables it, and
then **asks systemd whether it is enabled and running**. caasi never becomes a
supervisor: it has no restart loop, no dependency graph, no process table of its
own.

### 4.2 Two declarations, not one

The two concerns from §2 become two separate declarations, because they are
genuinely different things and conflating them is what made the reference
unverifiable:

```yaml
# caasi.yaml — the project declares WHAT should run and HOW it is persisted
runtime:
  kind: systemd            # the native mechanism (systemd is the first backend)
  unit: openmover.service  # the unit name caasi installs and manages
  entrypoint: >
    ros2 launch openmover bootloader.launch.py
  environment:             # environment persistence, declared not appended
    - /opt/ros/jazzy/setup.bash
    - install/setup.bash
  working_dir: .           # relative to the deployment destination
  restart: on-failure
```

- `runtime` describes **service persistence**.
- `environment` describes **environment persistence** and is what replaces
  `.bashrc` appends — declaratively, idempotently, and verifiably.

The declaration is *data*; caasi renders it into whatever the backend needs.

### 4.3 Lifecycle model

```text
deploy → install → enable → start → operate → update → verify → rollback
```

| Operation | What caasi does | Who owns the semantics |
| :--- | :--- | :--- |
| **deploy** | materialize project (existing Stage B) | caasi |
| **install** | render the project's `runtime` declaration into a unit; write environment fragment; record revision | caasi |
| **enable** | `systemctl --user enable <unit>` | **systemd** |
| **start** | `systemctl --user start <unit>` | **systemd** |
| **operate** | the unit runs | **systemd** |
| **observe** | `systemctl show` / `is-enabled` / `is-active` (E3 adapter) | caasi asks, systemd answers |
| **update** | install revision B over A, restart, record the transition | caasi orchestrates, systemd runs |
| **verify** | confirm the *active revision* matches what is deployed | caasi |
| **rollback** | reinstall the previous revision and restart | caasi orchestrates |

### 4.4 Deployment revision identity

**Observed gap today.** `DeploymentRecord` has `git_revision` and
`deployment_id`, but there is no notion of "which revision is *active* on the
target right now", and no previous-revision retention — so rollback has nothing
to roll back to.

Proposed: each install writes a revision marker on the target containing the
deployment id, git revision and installed timestamp, and keeps the previous
marker as `previous`. Then:

- **verify** compares the target's active marker with what the workstation
  believes is deployed → detects drift.
- **rollback** reinstalls from the previous marker.

### 4.5 The destructive-cleanup hazard

The user explicitly raised this: artifact collection (E1) must not be able to
destroy a persistent deployment. Two guards:

1. `releasable` is only ever set for `lifecycle: ephemeral` — already
   implemented in E1.5, and a persistent deployment is never marked.
2. Nothing in E4 deletes anything either. `rollback` **reinstalls**; it does not
   remove the newer revision.

### 4.6 Scope

**In scope:** systemd user-scope units; install/enable/start/verify/update/
rollback; revision identity and drift detection; environment declaration.

**Explicitly out of scope:** other supervisors (container restart policy, OpenRC,
s6) — the backend interface is left open but only systemd is implemented, per
"start with the smallest real mechanism that proves the model"; fleet
scheduling; reboot *testing*.

---

## 5. What cannot be claimed

Stated before implementation so the report cannot drift:

- **No physical reboot recovery.** `Linger=no` on the measured target means user
  units do not survive reboot there. Enablement can be *recorded and verified*;
  actual reboot survival is **untested and will not be claimed**.
- **No physical robot bringup persistence.** Hardware bringup on the real robot is
  not tested — no robot hardware is involved in this stage.
- **No claim that the OpenMover stack itself runs persistently.** This stage
  proves the *lifecycle mechanism*; running the actual navigation stack as a
  managed service on hardware is a later, hardware-dependent validation.

---

## 6. Evidence summary

| Claim | Class | How established |
| :--- | :--- | :--- |
| Reference persistence is `.bashrc` env only | Observed fact | read `install.sh`; no systemd/autostart/cron anywhere |
| Reference never installs a service | Observed fact | grep for `systemd|rc.local|autostart|cron` → empty |
| `bootloader.launch` is the entrypoint description | Observed fact | read the launch file |
| Target has systemd + systemctl + journalctl, no container runtime | Measured | probed `u24-307` |
| **User units do not survive reboot on the target** | Measured | `loginctl show-user` → `Linger=no` |
| No active-revision concept exists today | Observed gap | `DeploymentRecord` inspected; no marker, no previous revision |
| `releasable` already cannot be set for persistent deployments | Existing capability | E1.5 `is_releasable` guard |
