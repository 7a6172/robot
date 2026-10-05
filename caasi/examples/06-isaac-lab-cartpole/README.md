# 06 — Isaac / Isaac Lab (opt-in: GPU + Isaac Sim)

**Prerequisites:** NVIDIA GPU with CUDA · Isaac Sim · Isaac Lab.
**This example is opt-in and is skipped automatically when those are absent.**

> ⚠️ **Not validated without a GPU and Isaac Sim.** The commands below are the
> documented workflow; they are not run in environments lacking the prerequisite.

**Isaac Lab provides the task and the training; caasi provides the project, the
requirements, the target choice and the run tracking around it.**

We use **`cartpole`** — Isaac Lab's canonical minimal task. It is small, fast and
well known, which makes it the right thing to demonstrate *caasi* around: there is
nothing interesting about the task itself here, and that is the point.

---

## The commands this example teaches

`caasi train` · `caasi lab` · `caasi benchmark` · `caasi sim` · `caasi view` ·
`caasi check` · `caasi target select --where prefer:gpu` · `caasi gpu` ·
`caasi physics`

---

## The caasi project

`caasi.yaml` declares what the work needs — and because requirements are checked
against **measured** target facts, this is what makes `--where prefer:gpu` mean
something:

```yaml
requires:
  isaac_lab:
    version: ">=2.0"
  gpu:
    count: 1
    memory_gb: 8
```

Check where it can run **before** starting anything:

```bash
caasi target select
```

A CPU-only target is eliminated with the measured reason (*"target reports no
GPUs"*), not silently.

## Running the canonical task

The experiment config names Isaac Lab's own training entry point as its `script`.
**caasi does not hardcode that path** — `caasi train` delegates to whatever script
the experiment declares, so the training entry point stays Isaac Lab's:

```bash
caasi train experiments/cartpole.yaml --target local
caasi logs <run-id> -f              # follow it
caasi run status <run-id>
caasi run list
```

And the rest of the ecosystem surface, through caasi:

```bash
caasi sim status                    # Isaac Sim
caasi lab list                      # Isaac Lab tasks
caasi benchmark start experiments/cartpole.yaml
caasi view <run-id>                 # if a display is available
```

### GPU and physics inspection

```bash
caasi gpu                           # nvidia-smi, through caasi
caasi physics                       # which physics engines are available
caasi check                         # is this project runnable here?
```

---

## Not demonstrated here

- **`nav`, `moveit`, `motion execute`** — these drive **physical motion**. Only
  their read-only siblings (`nav status`, `moveit plan`, `motion plan`) are shown.
  Nothing in this example moves hardware.
- **`teleop start` / `teleop record`** — likewise; see the cookbook.

---

## What caasi provides vs what Isaac Lab provides

| Isaac / Isaac Lab provides | caasi provides |
| :--- | :--- |
| The simulator, the tasks, and the training entry point | Project structure and declared requirements |
| `cartpole` and every other canonical task | Target selection against measured GPU/software facts |
| Physics and the learning stack | Run tracking, logs, provenance, and observation |

**caasi implements none of the simulation or learning stack.** It configures,
launches, tracks and observes it.
