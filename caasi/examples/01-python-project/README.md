# 01 — Your first project

**Prerequisites:** Python 3.10+ · no GPU, no ROS 2, no second machine.

The backbone example. One small project demonstrates the command families a new
user meets first — because they are all facets of *one* real workflow, not
separate features.

**Your script, not ours.** `scripts/analyse.py` is deliberately trivial (read a
CSV, write a mean). caasi does not care what your code does; what this example
teaches is the caasi workflow *around* it.

---

## The commands this example teaches

| Command | What it shows |
| :--- | :--- |
| `caasi project validate` | the project layout is complete |
| `caasi project info` / `inspect` | what caasi understands about the project |
| `caasi project list` | declared components |
| `caasi config show` / `path` | effective configuration and where it lives |
| `caasi env fingerprint` / `env inspect` | this machine's environment, recorded |
| `caasi check` | can this project work here? |
| `caasi workload list` / `inspect` | the declared work |
| `caasi workload run analyse --target local` | the composed chain |
| `caasi run list` / `status` / `logs` | the run model |
| `caasi run artifacts` | what the run produced |
| `caasi audit` | provenance across the chain |

---

## Walk through it

```bash
cd examples/01-python-project
caasi project validate                 # the layout is complete
caasi workload list                    # what work is declared here
caasi workload run analyse --target local
```

Then look at what that produced:

```bash
caasi run list                         # the run, and its state
caasi run logs <run-id>                # what it printed
caasi run artifacts <run-id>           # what it produced, and where each file went
caasi audit                            # the provenance chain
```

### Doing the steps by hand

The composed command is a convenience, not a requirement. The same sequence
individually, which is what you would use when debugging:

```bash
caasi deploy local
caasi run start experiments/analyse.yaml --target local
caasi run artifacts <run-id> --collect
```

### A lesson the tool will teach you

If you skip `deploy` and run the workload with only `run`, caasi **refuses**:

```
✖ run — No active deployment found on target 'local' at
  '~/.caasi/deployments/local/python-demo'. Run 'caasi deploy local' first.
```

That is deliberate: a run executes a **deployed copy**, so a run needs a deployment
even when the target is this machine. The failure is informative on purpose.

---

## The two declaration files

**`workloads/analyse.yaml`** — *what work is, and the steps that carry it out.*
`steps` names operations caasi already has (`deploy`, `build`, `run`, `collect`).
It is not a scripting language: there are no conditionals, loops or retries. If a
workload needs real control flow, that belongs in your program.

**`experiments/analyse.yaml`** — *how to run one script as a tracked run*, and
which of its files are **outputs**. `outputs:` declares what matters; caasi routes
each declared file by its `kind` and records where it went.

---

## What caasi provides vs what you provide

| You provide | caasi provides |
| :--- | :--- |
| The script and what it computes | Project structure, validation and inspection |
| The workload declaration (what it needs, the steps) | Requirement checking against a target |
| The experiment declaration (script, args, outputs) | Detached execution, run tracking, logs |
| | Artifact routing, collection and provenance |

---

## Nothing here is destructive

No command in this example deletes anything. `caasi run delete` and
`caasi project remove` are **never** run here — they remove data and have no
`--dry-run` guard, so this example documents them rather than demonstrating them.
