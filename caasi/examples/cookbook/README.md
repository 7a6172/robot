# Cookbook — read-only commands

Commands that **inspect** rather than change anything, and therefore need no project
and no example of their own. Run them anywhere.

These are the commands you reach for when something is unclear: *what is this
machine? what can it do? what is configured?*

---

## Identity

```bash
caasi version          # the CLI version
caasi info             # CLI, configuration and detected ecosystem versions
caasi help             # command help
caasi help <command>   # help for one command
caasi test             # caasi's own self-test
```

## This machine

```bash
caasi system           # OS, CPU, RAM, processes
caasi gpu              # NVIDIA GPUs via nvidia-smi (delegated, never reimplemented)
caasi sensor           # sensors and sensor SDKs
caasi vision           # OpenCV, Open3D and friends
caasi physics          # available physics engines: PhysX, Newton, Warp, MuJoCo, Gazebo
caasi native           # escape hatch to the native Isaac/ROS tooling
caasi shell            # a shell inside the Isaac/ROS environment
```

Each of these **asks the ecosystem** — `nvidia-smi`, the OS, the installed SDKs —
and reports what it finds. caasi does not implement drivers, sensor stacks or
physics engines.

## Configuration

```bash
caasi config show            # effective configuration
caasi config path            # where the config file is
caasi config get <key>       # one value
caasi config catalog         # what can be configured
caasi config tools           # the tool registry
```

`caasi config set` **writes** configuration, so it is demonstrated in
[example 01](../01-python-project/README.md) where a scratch project makes that
safe, rather than here.

---

## Commands deliberately NOT demonstrated

Honesty matters more than completeness. These are **not** run by any example, and
this page says so rather than faking a safe path:

| Command | Why not |
| :--- | :--- |
| `caasi run delete` | **Destructive**, and it has **no `--dry-run`**. It removes a run's data. |
| `caasi project remove` (and `--purge`) | **Destructive**, no `--dry-run`. It removes declared component directories. |
| `caasi setup` | **Modifies your environment** (installs/detects components). Not something a read-only example should trigger. |
| `caasi teleop start` / `teleop record` | **Physical robot motion.** An example must never move hardware. |
| `caasi nav launch`, `moveit launch`, `motion execute` | **Physical motion and hardware bringup.** Only read-only siblings (`status`, `plan`, `inspect`, `doctor`) are shown. |
| `caasi run attach` | Needs an interactive terminal; it cannot be scripted meaningfully. |

**No example invents a `--dry-run` flag or any other safety mechanism that the CLI
does not actually provide.** Where a command is unsafe to run, the honest answer is
to document it and not run it.

---

## What caasi provides vs what the ecosystem provides

| Ecosystem provides | caasi provides |
| :--- | :--- |
| `nvidia-smi`, the OS, the installed SDKs and physics engines | A single, consistent place to ask about them |
| The tool registry and configuration files | Resolution and inspection of the effective configuration |
| Sensor, vision and physics stacks | Reporting what is present, and **what could not be determined** |

Every command on this page **asks the ecosystem** and reports the answer. caasi
implements no driver, no sensor stack, no physics engine and no configuration
format of its own beyond its own config file.
