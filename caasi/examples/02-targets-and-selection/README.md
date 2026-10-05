# 02 — Targets and selection

**Prerequisites:** none beyond example 01. **Works with only the built-in `local`
target** — a second machine makes it richer, but is not required.

Teaches the part of caasi that answers *"where should this run?"* — and, just as
importantly, *"why not there?"*

---

## The commands this example teaches

| Command | What it shows |
| :--- | :--- |
| `caasi target list` | what targets are configured |
| `caasi target inspect <t>` | discovered hardware, OS and ecosystem facts |
| `caasi target check <t>` | is it reachable, and does it match what was declared |
| `caasi target select` | **the whole point**: per-target verdicts **with reasons** |
| `caasi target occupancy` | what is running where — read-only |
| `caasi target runtime` | what runtimes the target exposes (process/systemd/container/ROS 2) |
| `caasi workload run <w> --where any\|idle\|prefer:<tag>` | choosing among suitable targets |

---

## Walk through it

```bash
caasi target list
caasi target inspect local
caasi target occupancy                 # read-only: what is running where
```

Now ask *where this project could run* — caasi evaluates every configured target
against the project's declared requirements:

```bash
caasi target select
```

You get a verdict **per target**, each with the measured fact behind it. Three
outcomes are possible and they are deliberately distinct:

| Verdict | Meaning |
| :--- | :--- |
| `compatible` | the requirement is satisfied by a discovered fact |
| `incompatible` / `missing` | the target was asked, and does not have it |
| `untested` | **the fact could not be measured** — which is *not* evidence of absence |

That last row is the most important idea in caasi: an unmeasured fact is reported
as unmeasured, never silently treated as a satisfied or a failed requirement.

### Choosing, rather than typing a name

`--target` names a target explicitly. `--where` asks caasi to choose among the
targets that **currently** satisfy the workload — and always explains the choice:

```bash
caasi workload run analyse --where any          # any suitable target
caasi workload run analyse --where idle         # prefer one with no live runs
caasi workload run analyse --where prefer:gpu   # prefer a tag, if one is carried
```

`--target` and `--where` are **mutually exclusive**, and one is required.

### If nothing fits

caasi **fails immediately**, naming why each target was eliminated. It does not
queue, wait, retry, or silently pick something else — choosing *whether to wait* is
a scheduling decision, and this example demonstrates selection only.

---

## What a tag is

Tags are labels you put on a target in your configuration (`~/.config/caasi/config.yaml`):

```yaml
targets:
  my-robot:
    transport: ssh
    host: 192.0.2.10
    user: someone
    tags: [robot, cpu-only, ros2]
```

`--where prefer:cpu-only` then prefers targets carrying that tag among the ones
that already satisfy the workload. **A tag cannot rescue an unsuitable target** —
requirements are checked first, always.

---

## A limitation, stated plainly

Occupancy is an **observation, not a reservation**. Two commands started at the
same moment can both see a target as idle and both select it. That is intentional:
reserving a target would require the scheduling machinery caasi deliberately does
not have. `caasi target occupancy` tells you what is running; it does not hold
anything for you.

An occupancy state of **unknown** means a run's state could not be determined. It is
counted as neither busy nor free, and reported as such rather than guessed.

---

## What caasi provides vs what the ecosystem provides

| Ecosystem provides | caasi provides |
| :--- | :--- |
| The machine, its hardware, and its OS | Live discovery of what each target actually has |
| SSH and the remote shell | Reachability checks, capability comparison, and per-target verdicts |
| The ROS 2 / systemd / container runtimes | Observing them through their own native interfaces |

caasi does not invent hardware facts. It **asks** the machine and reports what it
was told — including, plainly, when it could not get an answer.
