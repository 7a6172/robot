# 02 — The NMTE Framework (as specified in the draft)

Source material: `/home/zar/Documents/phd/robot/draft/draft.pdf` (paper skeleton) and
`/home/zar/Documents/phd/robot/draft/presentation.pdf` (June 2026 progress-report deck).
Status: **framework specified on paper; zero implementation, zero experiments.**

## The five gaps (draft's motivation)

| # | Gap | Source domain in draft |
|---|---|---|
| 1 | Zero-shot sim-to-real transfer for high-precision, contact-rich manipulation | Robotic arms, warehouse bin picking |
| 2 | Dynamic task-invariant feature extraction for locomotion on degraded terrain | Quadruped railway inspection on ballast |
| 3 | Parameter-efficient cross-embodiment representation learning | Arm → quadruped skill transfer |
| 4 | Certifiable safety guarantees during continuous sim-to-real adaptation | All platforms |
| 5 | Energy-aware, compute-constrained transfer learning on edge devices | Weak robot PCs |

## The four pillars (draft sections III-A … III-D)

### A — Koopman operator theory (Gaps 1 & 2)
Learn a lifting `g_θ(x)` that maps nonlinear robot dynamics into a linear Koopman space with
operator `K`; policies/MPC act in the lifted linear space. **Transfer rule:** when the world
changes, freeze `K` and fine-tune only the lifting encoder `g_θ` — the linear structure generalizes;
only the observation mapping is embodiment/world-specific. Absorbs friction, contact, and
disturbance variation without policy retraining.

### B — Gromov-Wasserstein optimal transport (Gap 3)
Cross-embodiment latent alignment: find a bijection `Γ: X → Y` between latent skill primitives of
two morphologically different robots by aligning relational structure (distance geometry) rather
than pointwise features. Enables zero-shot skill mapping across embodiments.
**Status: needs a second embodiment — deferred to paper 3+.**

### C — DOB-CBF safety filter (Gap 4)
A disturbance observer (DOB) estimates unmodeled disturbances (friction, latency, model mismatch);
a Control Barrier Function + QP safety filter projects the learned policy's action onto the safe
set, widening CBF margins with the disturbance estimate. Guarantees forward invariance of the safe
set **under the bounded-disturbance assumption** — the paper must say exactly that, never "100%
certifiable safety" (see `07_draft_review.md`).

### D — Edge execution (Gap 5)
Heavy training offline in simulation; deployment = linear-algebra inference + a small QP. Artifacts
ship as small ONNX-class models that run on laptop-class robot CPUs. Claim to calibrate: the QP
solves in µs at whatever rate the control loop needs — do **not** borrow the draft's ">500 Hz"
figure, which comes from a hydraulic-quadruped citation while our loop runs ~20 Hz.

## The freeze/adapt rule (the engine's actual intellectual content)

> **When the world changes, freeze the structure, adapt the interface.**
> `K` frozen · policy `π` frozen · adapt: encoder `g_θ` (small), DOB estimates, CBF margins.

This rule is what separates "a transfer engine" from "we did domain randomization."

## Roadmap phases (draft)

| Phase | Content | Mapping to our plan |
|---|---|---|
| A | Koopman dynamics modeling | Paper 1 core (diff-drive version) |
| B | GW latent alignment | Paper 3+ (quadruped/hand) |
| C | Safety certification (DOB-CBF) | Paper 1 safety layer |
| D | Edge-compute hardware validation | Paper 1 compute-tier rows; robot PC as proof |

## Where the framework stands

- Math architecture: specified (draft).
- Implementation: none.
- Validation platform: half-built — ROS 2 robot stack done (this workspace), Isaac Sim not started.
- The first paper's job: make the engine's mechanism visible on the simplest available platform,
  simulation-first. See `03_paper_one_scope.md`.

## Methods are candidates, not commitments (agreed 2026-09-04)

The draft's Koopman core, DOB, and CBF filter are **ideas we currently think can work**, not the
final word. What must survive is the *idea behind them*: **freeze the structure, adapt the
interface**, with few-shot recovery instead of retraining. If another mechanism demonstrates the
same idea better on our platform (e.g., a simpler few-shot dynamics adapter recovers the dynamics
drop more reliably than a Koopman lift), we use that and report the substitution honestly. The
experiments are an exploration of what works for the idea; nothing in this file is final.
