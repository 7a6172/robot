# 05 — Transfer Learning & Sim-to-Real Notes

Background knowledge gathered during discussion: what transfers, what doesn't, and the
parent/tethered deployment architecture that grew out of it.

## What transfers easily, and what doesn't

| Task class | Transfer difficulty | Notes |
|---|---|---|
| **Geometric 2D-LiDAR navigation** (our case) | **Low — transfers well** | Physics is simple, sensor is geometric, domain gap is mostly layout |
| Camera-based perception | High | Needs heavy domain randomization or real2sim calibration |
| Contact-rich manipulation (arms) | High | The draft's Gap 1; needs dynamics adaptation (Koopman) + calibration |
| Rough-terrain locomotion (legs) | High | The draft's Gap 2; quadruped future work |

Practitioner evidence (from community experience):
- **Real2sim calibration** (measuring real sensor/system parameters and mirroring them in sim)
  cuts sim-to-real error by roughly 30–50% for contact-heavy tasks. Our version of this rule:
  *the sim robot is built from measured parameters of the physical robot* (`06_validation_plan.md`).
- **Synthetic → real fine-tuning** on the order of 50–100 real samples recovers most of the gap
  for many tasks — the few-shot adaptation budget curve in paper 1 tests exactly this shape.
- Large foundation models (GR00T, Cosmos, etc.) target humanoid/arm video-to-action pipelines —
  **not applicable** to a differential-drive LiDAR robot; ignored for this program.
- Example external workflow studied for reference: SO-101 arm — RL in Isaac Lab → distilled policy
  → real arm. Structurally identical to our train-on-PC / deploy-on-robot plan.

## Core techniques in play

- **Domain randomization**: procedural layouts + randomized dynamics (friction, mass, latency) at
  training time. Ingredient, not contribution — the engine's freeze/adapt rule is the contribution,
  and baseline 3 of the paper exists to prove the distinction.
- **Teacher-student distillation**: teacher trains with privileged ground truth (pedestrian states,
  exact pose) in GPU-parallel worlds; student sees only LiDAR + odometry + goal. LiDAR-only
  observation → headless training, no rendering → the 10 GB GPU can run many parallel environments.
- **Dynamics learning (Koopman)**: see `02_nmte_framework.md`, pillar A.
- **Safety envelope wrapping**: learned policy inside a classical/CBF-verifiable envelope. The robot
  already has a classical envelope (footprint collision check, perception-based pedestrian stop,
  `cmd_vel` watchdog, e-stop) — the paper's baseline and the CBF's comparison target.

## The hard deployment constraint (framed as contribution)

The robot PC cannot run anything heavy → every deployed artifact must be a small ONNX-class model.
Framed right — *"what transfers to a low-cost robot with a laptop brain"* — this is draft Gap 5 and
a contribution, not a weakness. Every results table gets both rows: full-size model (parent) and
distilled artifact (onboard).

## The parent/tethered architecture (idea from discussion — KEEP)

**Core insight:** the transfer engine does not have to live on the robot. A powerful parent PC
running Isaac Sim and the engine can supervise a "dumb" robot that just does what it's told.
The engine's artifacts are **compute-agnostic** — the same frozen artifacts run at three placements:

| Tier | Where inference lives | What the robot runs |
|---|---|---|
| **Onboard edge** | Small ONNX on robot CPU | Everything (thin and slow-brained) |
| **Tethered parent** | Full engine on the parent PC, over network (DDS/WiFi or cable) | Thin client: stream sensors, execute `cmd_vel`, keep local safety reflexes |
| **Parent-supervised (future)** | Parent *learns on the robot's behalf* | Thin client; parent re-identifies dynamics from streamed data, re-tunes `g_θ`, pushes artifact updates back |

Why this is paper-relevant:
- It turns Gap 5 into a **compute-placement axis**: transfer across placements of the same artifacts,
  with measured latency/safety trade-offs per tier.
- **The safety filter makes tethering certifiably tolerable**: network latency/jitter is a bounded
  disturbance → DOB estimates it, CBF margins widen accordingly.
- The existing `cmd_vel` watchdog doubles as the deadman when the link drops.
- It foreshadows the fleet future: one parent supervising many dumb robots (vacuum-class AMR now;
  quadruped and hand later).
- Related-work positioning: adjacent to cloud/split robotics — differentiate: we transfer *frozen
  artifacts across placements*, not offload generic inference.

**Scope decision:** paper 1 keeps onboard + tethered contrast; **parent-supervised online
adaptation is future work** (paper 2 material) — keeps paper 1 simple per agreement.

## Two deployment rows in every results table

| | Tethered | Onboard |
|---|---|---|
| Model | Full size, parent GPU | Distilled ONNX, robot CPU |
| Latency | + network hop (measured, CBF-absorbed) | Local |
| Failure mode | Link drop → watchdog stop | Compute ceiling |

If tethered wins and onboard is *within X%*, that is a strong practical finding ("the transfer
engine makes the cheap robot nearly as good as the tethered one"). If onboard loses badly, the
engine is motivated even more. Either outcome publishes.

## Environments are disposable (agreed principle)

The current warehouse world is only for system validation. Research environments are built fresh:
procedural randomization at training time; held-out unseen layouts (including the railway yard) at
evaluation time. "Generalizes to unseen environments" is a much stronger claim than "works where we
trained."
