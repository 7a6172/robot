# 04 — Containers, and target runtimes

**Prerequisites:** Docker or Podman on this machine. No GPU, no ROS 2.

**Docker provides the container; caasi observes it and reports where it lives.**
There is no caasi container runtime and no caasi image format — caasi asks the
container CLI, and reports absence *with a reason* when there is none.

---

## The commands this example teaches

| Command | What it shows |
| :--- | :--- |
| `caasi container list` | containers, via the container CLI |
| `caasi container status` | the same, for one container |
| `caasi container check` / `doctor` | whether the container stack is usable here |
| `caasi container run` | running a container as a tracked run |
| `caasi target runtime` | that `container` is one of four runtimes caasi can observe |

---

## Walk through it

Start a real container — an entirely upstream image, chosen because it is tiny:

```bash
docker run -d --name caasi-demo alpine sleep 600
```

Now observe it through caasi:

```bash
caasi container list
caasi container status caasi-demo
caasi target runtime local          # notice: 'container' is one of the runtimes
```

Clean up when you are done:

```bash
docker rm -f caasi-demo
```

### What the four runtimes are

`caasi target runtime` reports what a target exposes, through each runtime's **own
native interface**:

| Runtime | caasi asks |
| :--- | :--- |
| `process` | `ps`, falling back to `/proc` |
| `systemd` | `systemctl`, `journalctl` |
| `container` | `docker`, or `podman` |
| `ros2` | the `ros2` CLI |

### When a runtime is absent, caasi says why

On a machine with no container runtime you get an honest answer rather than an
empty list:

```
○ container - no docker or podman on PATH
```

**Absence is reported with its reason**, never as a silently empty success — you
should never have to infer "there is nothing here" from "I got no rows back".

The same applies to `systemctl` being present without systemd running (common
inside containers): caasi reports the runtime as unavailable and says why, rather
than claiming it works.

---

## What caasi provides vs what Docker provides

| Docker / Podman provides | caasi provides |
| :--- | :--- |
| The runtime, images and container lifecycle | Observation through the container CLI |
| Container state and metadata | The same reporting shape as processes, systemd and ROS 2 |
| | An explicit reason when no container runtime exists |

**caasi reads; it does not manage containers.** It implements no container runtime,
and adding one would breach the boundary that keeps caasi thin.
