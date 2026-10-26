# Changelog

## [Unreleased]

## [0.4.0]

Milestone: **target and control-plane capabilities**. Version 0.3.x described an
environment-oriented tool; 0.4.0 makes targets — remote machines and robots — a handled
concept end to end. Everything below is implemented and validated, and the release is
defined by that set rather than by a date.

### Fixed — a run is only "stopped" when nothing it started is still running

The wrapper exits as soon as the program it launches returns or detaches, so a pid-only
check answered the wrong question. Two consequences, both seen on a real robot, where a
node survived `run stop` and kept holding its UDP port:

* `caasi run status` reported `succeeded` for a run whose child was still running
* `caasi run stop` returned early for any terminal status without looking for survivors

Both now ask about the process *group*. Status reports **`stale`** — a new state, distinct
from `stopped` and `lost` — when the wrapper is finished but the group is still alive, and
`stop` only returns once survivors have actually been signalled, killing the group when
needed. A process that detaches into its own session escapes group-based tracking; that
remains a documented limitation rather than something reported as clean.

The remote manifest update also expanded no `~` (a literal tilde inside the `python -c`
string is not a home directory), so it silently did nothing.

### Fixed — target paths: a leading `~` is expanded on the target, everywhere

One mistake — quoting a path containing `~` as a whole — appeared at four call sites and
failed differently at each. Found while driving a real robot, not in tests:

* deployment materialisation created a literal `~/caasi/...` tree on the target
* `caasi build` could not find a deployment that `caasi deploy` had just reported VERIFIED
* a managed run started correctly but `caasi run status` reported `lost`
* `caasi exec --overlay '~/...'` could not source a perfectly valid overlay

All sites now go through the single `targets.remote_path_expr` helper, so the write path,
the read path and every probe agree on what the path means.

### Fixed — managed runs recorded no exit status when setup failed

The wrapper wrote `exit_code` after `"$@"`, so any early failure (a setup script that could
not be sourced, an unset working directory) exited before the write. Such runs left no
status and were reported `lost` rather than `failed`, hiding the real cause. The wrapper now
records its status through an `EXIT` trap, which fires on every exit path.

An explicit stop still wins over that recorded status: `caasi run stop` on a run whose
wrapper then reports an exit code is reported `stopped`, not `succeeded`.

### Added — `caasi target deps`: operation-aware dependency inspection

* **`caasi target deps <target> [--for build|bringup|sim|project] [--json]`** reports whether a
  target can perform an operation, and what exactly is missing. Read-only by construction.
* Scopes are caasi's real operations, not an invented taxonomy: `project` (exactly what the
  manifest declares), `build` (adds the build toolchain), `bringup` (the robot stack),
  `sim` (the simulation stack).
* **Operation-specific requirements.** Simulation-only dependencies (`isaac_sim`,
  `isaac_lab`, `ros_gz_*`) are *optional* for `bringup` and only required for `sim`, so a
  hardware bringup does not fail because the simulator is absent.
* States are distinguished: `installed`, `missing`, `incompatible`, `optional-absent`,
  `unknown`. A target asking for `jazzy` that reports `humble` is `incompatible` — a named
  distribution is an identity, not a version range. Version *ranges* keep the shared
  ladder's §57 caution and are reported as `unknown` rather than asserted broken.
* **Reuse, not a new framework.** Requirements come from the manifest's `requires:` (the
  authoritative declaration); the verdict ladder is `check.evaluate_requirement`; remote
  facts come from `execution.run_on_target` in a single round-trip. No second SSH path.
* Remediation is derived only when it can be: a ROS package resolves to
  `sudo apt install -y ros-<distro>-<pkg>` and is marked **verified** only when the distro
  and a Debian-family OS are known; otherwise it is explicitly marked *review required*.
  Nothing is ever installed.
* **Fails honestly.** An unreachable target or a failed inspection reports every dependency
  as `unknown` and exits non-zero — never as "all installed".

Two false negatives found on the real robot and fixed:
  * ROS packages were looked up in `dpkg` by their ROS name, but the Debian package is
    `ros-jazzy-<name>`, so installed packages were reported missing. The probe now checks
    the installed share tree (authoritative) with a dpkg version fallback.
  * Metapackages were reported missing when only their components were installed — `nav2`
    is not installed itself while `nav2_costmap_2d` and friends are. A family match is now
    accepted and named in the report.

### Added — ad-hoc managed processes on a target

* **`caasi exec --detach --name <n> -- CMD ...`** starts an arbitrary command as a tracked,
  detached run on a target, reusing the existing run lifecycle: one wrapper format, one
  launch shape (`nohup setsid`), the same PID/PGID recording, and the same
  `caasi run status|logs|stop`. There is no second supervisor.
* Bounded and managed modes share target resolution, ROS environment setup, argument
  handling and error reporting; they differ only in whether caasi waits. The bounded
  outcome vocabulary (`ok`/`nonzero`/`timeout`/`transport`/`setup`/`no_ros2`) is
  unchanged, and managed runs use the run lifecycle's own states rather than forcing
  asynchronous process states into the bounded model.
* Unlike an experiment run, an ad-hoc command needs **no project, deployment or build
  preconditions** — diagnostics often have to run before anything is deployed, and
  refusing them would push the user back to raw SSH.
* Sourcing failures in the managed wrapper are fatal (exit 126), so a process cannot run
  silently without the environment it was told to use.

Two defects found by using it, both fixed:
  * **Status reported `lost` for every ad-hoc run.** `remote_effective_status` required a
    deployment `destination`, which an ad-hoc command does not have; the check now
    requires only the run directory.
  * **Run directories were placed under `cache/`**, which is documented as safe to clear,
    while logs and exit codes must survive. Managed runs now live under
    `~/caasi/data/runs/<run_id>`.

### Added — generic command execution on a target

* **`caasi exec --target <t> [--ros] [--overlay <setup.bash>] [--cwd DIR] [-e K=V] [--timeout S] -- CMD ...`**
  runs any command on a target through one path. `caasi ros` remains the ROS-specific
  delegate and now *shares* this implementation instead of keeping a second snippet
  builder, so argument handling, environment setup and outcome classification are
  identical everywhere.
* Outcomes are stated, not inferred: `ok`, `nonzero`, `timeout`, `transport`,
  `setup`, `no_ros2`. Callers branch on the outcome, because "ssh returned 0" does not
  mean the remote command succeeded. Exit statuses are mapped honestly — a transport
  failure keeps ssh's 255, setup failures use 126, a missing `ros2` 127, a timeout 124,
  and a remote non-zero is preserved unchanged.
* **Setup failures are no longer silent.** The previous snippet used `test -f X && . X`,
  which skipped a missing setup script and then reported whatever the command did, so a
  broken overlay looked like a working environment. A missing or failing setup script now
  aborts with a marker and a distinct exit code.
* **The ROS CLI is only required when ROS is explicitly requested.** Sourcing a workspace
  overlay alone does not imply `ros2` must exist; requiring it there made an ordinary
  command fail with a ROS error (caught by the suite running without ROS on PATH).
* The ROS distribution is **discovered from the target**, never assumed: an unknown distro
  is reported instead of guessing `/opt/ros/jazzy`.
* Arguments are passed as structured argv through `bash -c ... -- "$@"`, so spaces,
  quotes, Unicode and shell metacharacters survive without becoming a second command.

### Added — one directory layout per target

* caasi now owns where material lives on a machine it manages, so a new target needs no
  convention debate and every command looks in the same place:

  ```
  ~/caasi/
  ├── robots/{robot}/              physical robots and their deployed environments
  ├── projects/{project}/          robotics projects, regardless of where they run
  ├── fleet/                       shared robot inventory, profiles and configuration
  ├── workspaces/{workspace}/      source checkouts and development workspaces
  ├── data/
  │   ├── datasets/{dataset}/
  │   ├── recordings/{recording}/
  │   └── results/{result}-{date}/
  ├── artifacts/{artifact}/        reusable build outputs and packaged releases
  └── cache/{entry}/               re-creatable temporary data, safe to clear

  Each root holds one directory per named entity, and small helpers (`robot_root`,
  `project_root`, `dataset`, `recording`, `result`, `artifact`, `cache_entry`) build the
  leaf paths so callers never join the strings by hand.
  ```

  The tree lives in `caasi.core.layout`; further roots (simulations, maps) can be added
  there without touching callers. The default deployment destination is now
  `~/caasi/robots/<robot>` for a target tagged `robot` -- a robot owns one directory, and
  the project name is deliberately not appended, because the robot is the unit of
  identity (`~/caasi/robots/swjtumover05` and `~/caasi/robots/openmover` are two robots).
  A non-robot compute target keeps `~/caasi/workspaces/<target>/<project>`, since one
  machine may host several unrelated projects. The distinction comes from the target's
  own tags, so any robot name works and nothing is hardcoded to one machine. An explicit
  `deployment_root` still overrides the default, so existing deployments are unaffected.

### Fixed — remote deployment reliability

* **Fresh-robot deployment works.** Three defects made the first deploy to a new target
  fail, and together they explain the "missing files" verification error:
  * A `~` in `deployment_root` was quoted, so the remote shell never expanded it and
    `mkdir -p '~/x'` created a *literal* `~` directory. The real destination never
    existed. Remote paths are now expanded on the target via `$HOME`, through one shared
    helper (`targets.remote_path_expr`) used by deploy and build.
  * The destination is resolved to an **absolute path by the target itself** in the same
    round-trip that creates it. `rsync` does not expand `$HOME` in a `host:path`
    argument — it prefixes the remote home to anything not already absolute — so the
    resolved path is what rsync, the metadata write and verification all use.
  * The changed-file list only matched `>f` itemize lines, but a **push** itemizes as
    `<f.st......`. Every real file change was therefore omitted from the deployment
    record while created directories were still listed. Both directions are now
    reported, along with creations and deletions.

### Added — remote targets

* **Targets** are declared in configuration and addressed by name, with per-target
  `transport`, `host`, `port`, `user`, `deployment_root` and `ssh_timeout`.
* `caasi target list|check|info|add|remove` plus `caasi target runtime` for observing what
  a target is running.
* A **per-target SSH timeout** now drives both `ConnectTimeout` and the reachability probe.
  Previously a hard-coded 3 s probe made a relayed target look unreachable; the error now
  names the setting to raise.

### Added — remote deployment and execution

* `caasi deploy <target>` materializes a project on a target with provenance recording and
  post-deploy verification, distinguishing `verified` from `verification_failed`.
* Target-native builds and remote execution, so a run happens where the software lives.
* Deployment records carry a **`lifecycle`** (`persistent` by default) separate from
  `status`: `status` describes the deployment act, `lifecycle` describes intended
  longevity. An undeclared project is never treated as disposable.

### Added — observability

* `caasi ros … --target <target>` queries a remote ROS 2 graph. `--domain` is required for
  remote queries so an empty graph cannot be mistaken for a valid observation.
* `caasi target runtime` generalizes observation beyond ROS 2 to **process**, **systemd**
  and **container** runtimes, each delegating to its own native interface (`ps`,
  `systemctl`/`journalctl`, `docker`/`podman`) and reporting absence with a reason rather
  than as an empty success.

### Added — result collection

* Outputs are **declared** in `caasi.yaml`; a declaration acts as a filter, while an
  undeclared project inventories every non-bookkeeping file.
* `caasi collect` inventories, routes and collects results with provenance, hashing small
  files by default (8 MiB) and large ones only with `--verify`.
* Collected results are recorded for succeeded, failed **and** stopped runs — a stopped run
  is never silently discarded.
* Artifact collection never deletes a persistent deployment; `releasable` can only be set
  for an `ephemeral` lifecycle, and it is a recording, not a deletion.

### Added — persistent runtime lifecycle

* A project may declare a `runtime:` block (unit, entrypoint, environment, restart policy).
  caasi renders it into a systemd unit and writes an environment fragment.
* `caasi runtime install|enable|start|status|verify|update|rollback`.
* **caasi owns identity, declaration, invocation, verification and provenance; systemd owns
  running the service.** caasi writes the unit and asks systemd for state — it has no
  restart loop and no process table of its own, and is not a supervisor.
* The declared `environment` replaces the ROS 1 reference's `~/.bashrc` appends with
  something idempotent and verifiable. Assignments are normalized to the `KEY=VALUE` form
  systemd accepts, and `source` lines are applied by the login shell that runs the
  entrypoint, because `EnvironmentFile` cannot express them.
* **Revision identity**: each install records the deployment, git revision and timestamp on
  the target, retaining the previous revision so rollback has a real target.
* **Rollback redeploys the previous revision from the workstation** and refuses when it
  cannot honestly restore that content, rather than rewriting a marker to claim a rollback
  that did not occur.

### Added — workload model and selection

* **Workloads** (`caasi workload list|inspect|run`) declare the work a project wants done
  as data: what it needs (`requires:`) and the steps that carry it out.
* **A closed step vocabulary** — `deploy`, `build`, `run`, `collect`. An unknown step is
  rejected when the workload is parsed rather than silently skipped, and there are no
  conditionals, loops or retries: a workload needing control flow is a program.
* **`caasi target select`** — requirement-driven, per-target verdicts **with reasons**,
  read-only and advisory. Three states are kept distinct: satisfied, asked-and-absent, and
  **unmeasured** (which is not evidence of absence).
* **`caasi target occupancy`** — read-only, showing what is running where and distinguishing
  `occupied`, `idle` and **`unknown`** (a run whose state could not be determined).
* **`--where any|idle|prefer:<tag>`** — an explicit, explained choice among currently
  suitable targets. Mutually exclusive with `--target`, and one is required. Ordering is
  deterministic (policy key, then target name) — no scoring, ranking or load balancing.
  When nothing fits it **fails with the reasons** rather than queueing or waiting.
* **`caasi rviz2|rqt|rosbag --target <t>`** — target-aware invocation of existing tools
  (R2). Caasi resolves the target's ROS 2 context and then executes the **real** tool; the
  domain is resolved explicitly (explicit option > target-reported > **refuse**), never
  silently defaulted. `caasi tools list|run` exposes the same mechanism.

### Changed — local target semantics

* **`local` is now a deployed target like any other.** Previously `build` recorded in the
  project root while `run` looked at the deployment destination, so `caasi build --target
  local` followed by `caasi run --target local` failed. The discriminator is now whether a
  deployment exists, not whether the target is named `local`; the standalone workspace
  build is preserved.

### Documentation

* A **runnable example catalog** (`examples/`): seven coherent projects plus a cookbook
  covering the whole basic CLI, with `examples/README.md` as the command index and
  `examples/COVERAGE.md` as an auditable command → example matrix checked by the test
  suite. Where a canonical ecosystem example exists (ROS 2 `demo_nodes_py` and `turtlesim`,
  Isaac Lab `cartpole`, Docker) it is **referenced, not duplicated**.
* Documentation for the control plane: targets and selection, workloads and execution,
  deploy and runtime lifecycle, the examples catalog, and a page on limitations and
  deliberately deferred capabilities.

### Fixed

* **Workload identity is recorded in run provenance.** A composed run previously recorded
  the experiment name but not *which workload* produced it, so two workloads sharing an
  experiment were indistinguishable. Runs now record `workload`, `selected_by` and
  `selection_reason`.
* **Refusal exit codes.** `output.fail()` raises its own exit, so a `raise` written after it
  was unreachable and several refusals exited `1` instead of the intended `3`. A CLI-wide
  test now guards against the class.
* `caasi deploy` used `rsync --delete`, which removed caasi's own runtime state
  (`.caasi-runtime.json`, `.caasi-env.sh`) from the destination and silently destroyed the
  rollback point of a persistent installation. Both are now excluded.
* `update` on a reinstall no longer overwrites the rollback point with the revision being
  installed, which previously left the marker pointing at itself.
* `verify` treats a `-dirty` suffix as the same content identity (it describes the
  workstation tree, not the deployed revision) and reports a changed deployment id as
  evidence rather than as drift, since a rollback legitimately produces a new one.

## [0.3.0]

### Changed — information architecture

The command surface is reorganized around the invariant *"a command may have many entry
points, but one underlying semantic operation"* — each root node owns a concept and never
wraps an upstream product.

* `robot`, `scene` and `task` move **under `project`** (`caasi project robot create …`).
  The root nodes are removed; the same functions are now reachable one level down.
* `sim status|stop|pause|resume|logs` move into the generic run controls
  (`caasi run --backend sim`). `sim` keeps `run|headless|check|extensions`.
* `run list|status|stop|pause|resume` gain a `--backend B` flag: `list` filters, while
  action verbs guard against operating on a run from a different backend.
* `lab train` moves to the root `train` launcher; `lab` keeps `status|run|play|evaluate`.
* `synth` moves to `dataset generate`; the standalone `synth` node is removed.
* `project init` is now **canonical**; root `caasi init` remains as a thin alias.
* Root `caasi logs` remains as a thin alias of `run logs`.
* The previously planned root `status` node is dropped.

### Added — Layer 1: project core

`caasi project` becomes the project namespace on top of a component-driven tree.

* **Flat manifest** (`caasi.yaml`) keyed by an integer `schema` marker, replacing the
  overloaded `version: 1`. Legacy `{kind, name, version: 1}` files are bridged on read
  (`schema=1`, `version="0.0.0"`); reads never rewrite the file.
* **Components** define capability subtrees for `isaac.sim`, `isaac.lab`, `ros2`, `nav2`,
  `moveit`, `robot`, `navigation`, and `manipulation`. `project init` creates only the
  base directories; `project add` materializes a component's directories and requirements.
* New commands: `project add <component>`, `project remove <component> [--purge]`,
  `project list`, `project inspect`, `project add-file <domain> <kind> <FILE>`, and
  `project config show|get|set`.
* `project validate` is now **component-aware**, checking the schema, name, base directories,
  and registered component directories.
* New `doctor project` diagnostics validate the manifest, schema, name, and registered
  component directories; the check is skipped outside a project.
* The singular `robot/` component subtree (asset descriptions) coexists with the base
  `robots/` definitions directory.

### Added — Layer 2: environment fingerprint

A new root group, `caasi env`, provides a "CPU-Z for the robotics environment". It delegates
to existing detectors and lightweight version probes without importing the heavy robotics
stack.

* Environment fingerprints cover system, hardware, GPU, drivers, compilers, Python, ROS,
  Isaac, Docker, and Git.
* Fingerprints have a stable SHA-256 identity that excludes volatile fields such as
  timestamps, PIDs, load average, and free memory.
* Fingerprints can be stored per project under `.caasi/environment/` or globally under
  `~/.caasi/environment/`.
* `env inspect` shows the live environment.
* `env fingerprint [--save]` collects the environment and prints its stable hash, optionally
  saving it.
* `env compare [A] [B]` compares stored fingerprints, or a stored fingerprint with the
  current environment.
* `env show` displays a stored fingerprint without re-collecting the environment.
* `env lock` records the resolved environment baseline and project requirements in
  `caasi.lock`.

### Added — Layer 3: requirements + check contract

A single compatibility model now backs root `caasi check`, `sim check`, `container check`,
and `control check`.

* Version requirements support common PEP 440 operators, comma-separated constraints,
  `1.2.x`/`1.2.*` wildcards, and string equality for non-numeric versions.
* Checks distinguish **verified**, **compatible**, **untested**, **missing**, and
  **incompatible** evidence without inventing a verdict when something cannot be verified.
* A detected version outside a required range is reported as **untested** with an
  explanatory warning; `incompatible` is reserved for failed functional probes or
  missing required components.
* `caasi check [project]` preflights a project using its environment and requirements.
  `caasi check run <id>` checks a stored run's command, working directory, and experiment
  configuration.
* Incompatible checks exit with **3**; warnings do not fail a build.
* `caasi.lock` records resolved versions and required dependencies as a reproduction
  baseline, not as a package or environment freeze.
* `check.strict` is an opt-in mode that escalates untested results to incompatible in
  the root orchestrator.

### Changed — check exit codes

`sim check`, `container check`, and `control check` now use the common check contract,
including the same result ladder, JSON structure, and exit policy.

* Incompatible results now exit **3** instead of 1.
* `--json` emits the common `CheckReport` format instead of the previous doctor envelope.

### Added — Layer 4: diagnostics that explain themselves

A failing check now explains what is wrong, why it matters, what proves it, its impact,
and what to do next.

* `caasi doctor --details <section>` renders a **Problem → Cause → Evidence → Impact →
  Suggested action** explanation for each `fail` or `warn`.
* `--details` runs only the selected section, like `--component`.
* Existing doctor output, JSON behavior, and exit codes remain unchanged except that
  `--json --details` adds an `explanations` array.
* Sections with nothing to explain explicitly say so.

### Added — Layers 5–6: canonical run launcher + provenance

Starting a tracked run is now a single operation shared by all supported launch paths.

* **`run start CONFIG`** is the canonical launcher, with `--backend`, `--name`,
  `--dry-run`, and pass-through script arguments.
* Root **`caasi start`** remains a thin alias.
* `sim run`, `sim headless`, `train`, `lab run/play/evaluate`, and `dataset generate`
  now use the same tracked-run and provenance path.
* **`run restart QUERY`** stops the source run when necessary and launches a new run from
  its recorded command, working directory, backend, and kind, preserving the relationship
  through `restarted_from`.
* Every started run receives a provenance bundle containing its manifest, environment,
  hardware, dependencies, configuration, Git state, and process information.
* Secrets in recorded configuration are redacted.
* Provenance collection degrades without blocking a run when information such as Git,
  project context, or individual files is unavailable.
* **Log aggregation** adds `--component`, `--errors`, `--since`, and `--json` to
  `run logs` and `caasi logs`, with the same filters available while following logs.

### Added — Layer 7: monitoring

A new monitoring operation samples resources exposed by the machine and tracked run
without importing the monitored robotics stack.

* `caasi monitor [<run>] [--interval N] [--once]` monitors run status, CPU, RAM, GPU,
  VRAM, throughput, runtime, and top processes.
* `--once` and `--json` provide a single machine-readable snapshot.
* Monitoring stops following a run once it leaves its active states.
* With no recorded runs, monitoring falls back to machine resources.
* `gpu monitor` remains GPU-only, while `system status|memory|processes` remain
  machine-only.

### Added — Layer 8: audit

The new `audit` command answers whether a project can be accounted for and reproduced,
distinct from `doctor` (machine diagnostics), `check` (compatibility), and `validate`
(structure).

* **`caasi audit [scope] [--fix]`** audits `project`, `dependencies`, `environment`,
  `files`, `runs`, and `reproducibility`, or all scopes by default.
* Reports use ✓/⚠/✗ groups and return an overall warning/error result.
* Warnings do not fail an audit; errors exit with **1**.
* `--json` provides structured audit results.
* `--fix` performs only CAASI-owned safe fixes. It currently creates missing CAASI
  directories and does not rewrite manifests, delete records, kill processes, or modify
  user source, packages, drivers, ROS, or Isaac installations.
* `audit.fix` can enable the fix behavior by default; it is disabled by default.

### Changed — documentation & version

The static documentation site and README are updated for the v0.3.0 command surface.
Page badges and footers now read `v0.3.0`, and the package version is bumped from `0.2.0`
to `0.3.0`.

* Added `docs/observability.html` covering monitoring, aggregated logs, audit, and
  provenance.
* Updated the documentation command map and project, environment, run, and README pages
  for the reorganized command surface and check contract.

### Fixed

* Two runs started within the same second no longer collide: run IDs now gain a `-2`,
  `-3`, … suffix when the directory already exists. This fixes fast `run restart` failures
  caused by `FileExistsError`.

## [0.2.0]

### Added

* GPU-accelerated robotics groups: `isaac-ros`, `perception`, `slam`, `mapping`, `motion`,
  `nitros`, `pipeline inspect` — discover Isaac ROS / NITROS / nvblox / cuMotion stacks,
  launch them as tracked runs, verify graphs with `slam test` and per-group doctors.
* Synthetic data & teleop: `synth` (Replicator SDG generate/preview/validate) and
  `teleop` (keyboard/joystick drive, rosbag2 record/replay).
* Physics & foundation models: `physics` (run/benchmark experiments on PhysX, Newton,
  Warp, MuJoCo or Gazebo), `warp` (kernel test/benchmark), `groot` (GR00T setup, run,
  train, evaluate via the repo's own interpreter), `cosmos` (Cosmos/NuRec delegation).
* Capability catalog: upstream probes are data and fully overridable through
  `caasi config catalog [domain]` and `caasi config set catalog.<domain>.<capability>.<field>`.
* Subcommands: `sim headless|logs|extensions`, `lab run|train|play|evaluate`,
  `ros service`, `nav|moveit|control|gpu|system|container doctor`, `gpu monitor`,
  `run attach`, `container status`, `view run`, `dataset list|download`,
  `robot import|validate`, `scene import|validate|capture|reconstruct`, `config catalog`.
* USD tool delegation (`usdcat`, `usdchecker`, `usdconvert`, `usdview`) and URDF/MJCF
  import behind `robot|scene import|validate`.
* Doctor: five new sections (accelerated, physics, assets, data, platform; 18 total) and
  a ROS-environment-sourced check.
* `caasi help [command …]` — help for the root or any command path (`caasi help gpu
  status`), resolved like `git help`.
* Global `--color auto|always|never`, honoring `NO_COLOR`.
* Documentation pages for GPU-accelerated robotics, synthetic data/teleop, physics &
  foundation models, and capability-catalog configuration.
* `--layout rich|plain` — bordered tables or space-aligned columns, also settable via
  `CAASI_LAYOUT` or `layout:` in `config.yaml`.
* `CAASI_HELP_ORDER` / `help_order:` in `config.yaml` — `grouped` (default), `core`
  (entry points first, then a–z), or `alpha` (flat a–z) ordering for the root command
  listing.
* Root help lists commands in titled groups, alphabetical within each group; subcommand
  listings keep their existing order.

### Fixed

* `run_ros2` sources the distro `setup.bash` when the shell has not, allowing ROS groups
  to work in unsourced environments.
* `sim run` accepts a local `--json` flag like its sibling commands.

## [0.1.0]

### Added

* Initial release: CLI-first orchestration layer for NVIDIA Isaac Sim, Isaac Lab and the
  robotics ecosystem — discovers and delegates to installed tools without importing the
  heavy stack (Typer, Rich, PyYAML only).
* `doctor`: 13-section environment diagnostics covering hardware, NVIDIA driver/CUDA,
  graphics, Python, Isaac, ROS 2, Nav2/MoveIt/ros2_control, ML, vision, simulators,
  containers, and storage, with `--component`, `--json`, and scriptable `--quiet` exit codes.
* `sim`, `lab`: launch/monitor Isaac Sim and Isaac Lab through a multi-version tool
  registry, headless-first.
* Runs engine: detached tracked processes under `~/.caasi/runs` — `run
  list|status|logs|stop|pause|resume|delete|inspect`, with `logs --follow`; jobs survive
  the terminal.
* ROS 2 delegation: `ros`, `nav` (Nav2), `moveit`, `control` (ros2_control) —
  status/launch/inspect/test on top of the `ros2` CLI.
* `train`, `benchmark start|report`: Isaac Lab workflows driven by a shared YAML experiment
  config.
* Data & review: `dataset generate|inspect|convert|validate`, `sensor`, `vision`, `replay`,
  `view rviz|foxglove|open3d|attach`.
* Projects: `init`, `setup`, `project`, `robot list|inspect|info|create`, `scene`, `task`.
* `remote` (SSH) and `container` (Docker/Podman, NVIDIA runtime); `native`/`shell` escape
  hatches.
* Configuration: `~/.config/caasi/config.yaml` merged with project `./caasi.yaml`,
  multi-version tool registry, environment overrides, `config show|get|set|path|tools`.
* Global `--verbose/--quiet/--json/--config/--lang` flags, shell completion, i18n-ready
  message layer, static documentation site; MIT.

[unreleased]: https://github.com/7a6172/caasi/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/7a6172/caasi/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/7a6172/caasi/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/7a6172/caasi/releases/tag/v0.1.0