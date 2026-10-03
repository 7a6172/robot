# 01 — Research Program Overview

## Mission

Build and validate a **Neuro-Mathematical Transfer Engine (NMTE)**: a framework that lets robots
learn once in simulation and keep working when the world changes — new environments, degraded
dynamics, weaker compute, and eventually different robot bodies — without retraining from scratch.

The program is anchored at Southwest Jiaotong University, where railway engineering is a core
competence: **railway maintenance robotics is the long-term application direction** (trackside
inspection, depots, yards — later ballast and rough terrain with legged platforms).

## The core idea (agreed wording)

> **Learning transfers; hardware is just the interface.** The same learned knowledge can drive one
> robot or many — eventually robots of different kinds.

The engine's operating rule, in one sentence: **when the world changes, freeze the structure and
adapt only the interface.** The dynamics core and the policy stay frozen; only the encoder
(`g_θ`), disturbance estimates (DOB), and safety margins (CBF) adapt.

## Assets inventory

| Asset | What it is | Research role |
|---|---|---|
| **openmover robot** | Small differential-drive AMR ("vacuum-cleaner class"), two 2D LiDARs, weak onboard PC | First test article. Expresses the engine's *mechanism*. Flat-floor scenarios only (depots, yards, walkways) |
| **pioneer3dx (sim)** | Pioneer 3DX asset in Isaac Sim (`isaac/assets/pioneer3dx/`), different wheel geometry (0.32 m / 0.09 m), casters, own inertia | **Second simulated embodiment, delivered in deploy-time form**: every ROS 2 rung run drove this plant with the openmover-trained frozen policy over a plain `Twist` boundary (no extra training run). Evidence + mechanism table: Isaac ledger §10 (`docs/isaac/06_results.md`) |
| **Quadruped robot** | Available in lab, not yet used | Future platform for rough-terrain/railway-ballast transfer (draft Gap 2) and cross-embodiment (pillar B) |
| **Robot hand** | Available in lab, not yet used | Future platform for contact-rich manipulation transfer (draft Gap 1) |
| **Development PC** | i7-12700K (20 threads), 16 GB DDR5, RTX 3080 10 GB, Ubuntu 24.04 | Training host. RAM upgrade to 32 GB is the single biggest unlock for Isaac Sim |
| **Robot PC** | Weak, laptop-class | *Is itself the experiment* for the edge-compute claim (draft Gap 5): deployment target for distilled ONNX artifacts |
| **ROS 2 stack** | This workspace (`openmover_ws`), migrated from ROS 1 | Simulation + deployment pipeline; Isaac Sim requires ROS 2, so this robot was migrated first as the rehearsal |
| **Lab-wide ROS 1 setup** | The rest of the lab still runs ROS 1 | Context: migration happens robot-by-robot, starting with this one |

Important practical notes:
- The dev machine **hard-froze twice** under full-parallel builds / heavy simulation. All builds use
  `-j2`; RAM tier guidance lives in `docs/build.html` and `tools/setup.sh`.
- The robot PC's weakness is a **contribution, not a limitation** — framed as "what transfers to a
  low-cost robot with a laptop brain" (hard deployment constraint).

## The paper arc

| Stage | Paper | Content | Status |
|---|---|---|---|
| 1 | **Engine mechanism** (first conference paper) | Frozen artifacts transfer across unseen environments and degraded dynamics regimes on the openmover robot, sim-first. Railway yard as target domain. See `03_paper_one_scope.md` | Scoped |
| 2 | **Sim-to-real axis** | Same frozen artifacts onto the physical robot; and/or parent-supervised online adaptation loop | Future work |
| 3+ | **Cross-embodiment reach** | Quadruped (rough terrain/railway), robot hand (contact-rich); Gromov-Wasserstein latent alignment (pillar B) goes live here | Roadmap |
| ∥ | **Localization standalone** | Learned global relocalization (candidate-scoring hybrid with the toolbox's RRT sampling) — parallel standalone paper, deliberately *not* folded into the NMTE paper (it is a perception problem, not a dynamics/safety one) | Candidate |

## Why this robot, why now

- It is the only platform fully migrated to ROS 2 — the same stack Isaac Sim requires.
- Simplicity isolates the claim: a reviewer cannot blame complexity for results; the mechanism is
  visible. (The "fruit fly expresses genetics" argument.)
- Environments are **disposable and free**: everything is built in simulation; no physical test
  site is needed for paper 1.
- The whole pipeline built for paper 1 (sim data factory, train+distill, deployment nodes,
  evaluation harness) is the infrastructure the rest of the thesis runs on — paper 1 is rehearsal
  1 by design.

## What the current robot can and cannot express from the draft

| Draft pillar | On openmover? | How |
|---|---|---|
| A — Koopman dynamics | **Yes** | Diff-drive dynamics with friction/payload/battery disturbance; math identical, body simpler |
| B — GW cross-embodiment | **No** (deferred) | Needs a second embodiment; quadruped/hand later, or sim-only preview |
| C — DOB-CBF safety | **Yes** | Pedestrian/obstacle safety set; the classical envelope already exists as baseline |
| D — Edge compute | **Yes** | The weak robot PC is the proof of the claim |

## Key design principles (agreed in discussion)

1. **Narrow proof, broad framing** — prove one mechanism deeply; frame the rest as roadmap.
2. **Environments are disposable** — train on procedural randomization, evaluate on held-out
   unseen layouts; never claim what depends on a specific hand-built world.
3. **Simulation mirrors the physical robot** — sim parameters are *measured* from the real robot,
   never guessed (see `06_validation_plan.md`).
4. **Test where classical breaks** — degraded friction/latency regimes where Nav2-style stacks fail
   give the simple robot its teeth.
5. **Deliberate deviations documented** — every intentional change from ROS 1 original is recorded
   (see `docs/changelog.html` and knowledge base `08_migration_notes.md`).

## Open questions (carried forward)

- Real-world ground-truth pose for later real-robot evaluations: landmarks? hand-labeled checkpoints?
- Tethered experiments: WiFi or cable for the robot↔parent link?
- Target venue for paper 1 (mid-tier list in `03_paper_one_scope.md`).
- ~~Whether paper 1 includes the cheap second-simulated-embodiment generality run (recommended, optional).~~
  **Resolved (deploy-time form):** the second embodiment is the pioneer3dx — every ROS 2 rung run
  drove the pioneer3dx plant with the openmover-trained frozen policy over a plain `Twist` boundary,
  so the generality run needed no extra training. Evidence + components×embodiments mechanism table:
  Isaac ledger §10 (`docs/isaac/06_results.md`).
