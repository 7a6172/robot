# 03 — Paper One: Scope Document (THE KEY DOCUMENT)

**Working title direction:** *"A Neuro-Mathematical Transfer Engine for Cross-Environment
Deployment of Low-Cost LiDAR Robots: From Randomized Training Worlds to Railway Inspection
Scenarios"* (title to be finalized; keep embodiment transfer OUT of any title).

## The claim the paper proves (agreed sentence)

> When the world changes — new environment, degraded dynamics, weak onboard compute — a frozen
> transfer engine keeps working with near-zero retraining, while classical stacks need rebuilding
> and end-to-end learning needs retraining.

Proven **simulation-first**, on the one robot available: a small differential-drive,
2D-LiDAR-only, warehouse-class AMR ("vacuum-cleaner class"). Railway scenario = **yard/depot**
(flat floors, clutter, degraded friction patches) — explicitly NOT ballast/tracks, which belong to
the future quadruped work.

## Contributions (the standard three-bullet shape)

1. A transfer engine instantiated on a low-cost LiDAR-only AMR: the **freeze-structure /
   adapt-interface rule** over a Koopman dynamics core + distilled LiDAR-only policy + DOB-CBF
   safety layer.
2. **Cross-environment zero/few-shot transfer** into unseen, structurally different domains,
   including a railway-maintenance yard scenario, with a systematic decomposition of *what
   transfers and what must adapt*.
3. **Cross-dynamics-regime transfer** under friction/mass/latency shifts with
   bounded-disturbance-adaptive safety margins, plus deployment across compute placements
   (GPU parent ↔ laptop-class robot CPU).

## The learned artifacts (what actually transfers)

| Artifact | What it is | Transfer rule |
|---|---|---|
| Koopman lifting `g_θ` + operator `K` | Linear dynamics model learned in randomized sim | `K` frozen; `g_θ` gets the small few-shot adaptation |
| Distilled policy `π` | LiDAR-only driving policy (teacher-student) | Frozen |
| CBF safety constraint set | Pedestrian/obstacle safety envelope | Frozen; margins widen with DOB disturbance estimate |

## Experiment design

### Domains (factorized — this is what makes it a real experiment, not a demo)

| Domain | Geometry | Dynamics | Role |
|---|---|---|---|
| Source | Procedurally randomized rooms/corridors/clutter | Randomized friction, mass, latency | Everything is learned here (headless, GPU-parallel) |
| Target 1 | **Railway yard** (unseen geometry; tracks as obstacles, cable ducts, tool carts, maintenance vehicles) | Same as training nominal | Geometry-axis transfer |
| Target 2 | Source-like geometry class | **Degraded regime**: friction patches, latency, battery sag | Dynamics-axis transfer |
| Target 3 | Railway yard | Degraded regime | **Both axes at once** (where things break, and where the adaptation rule recovers them) |

Deliverable: the **decomposition table** — what transfers when only the world changes, only the
physics changes, and when both change.

### Baselines (the defense against reviewers)

1. **Rebuild**: classical stack (custom controller + stop envelope / Nav2-style) reconfigured for
   each target → shows sample-efficiency advantage of the engine.
2. **Retrain-from-scratch** on the target → shows the engine's adaptation budget advantage.
3. **Randomization-only**: end-to-end policy with domain randomization, no math core (no Koopman,
   no CBF) → shows the engine is *not* "just randomization."

### Ablations & analyses

- Remove each engine part (no Koopman / no CBF / no DOB) → per-component contribution.
- **Headline figure — the adaptation budget curve**: x = number of target-domain adaptation
  samples (0 = zero-shot), y = task success. Engine vs. all baselines. *This curve is the paper:*
  if the engine plateaus high near zero samples while baselines need thousands, the transfer
  engine is visible.
- Failure case shown honestly + recovery via the adaptation rule (credibility, not weakness).
- Compute-tier rows: model size (MB), inference latency on robot CPU vs. parent GPU, control rate.

### Optional cheap generality run (recommended)

Apply the same engine recipe to a **second simulated robot** (different wheelbase/mass diff-drive
or a 3-wheel omni base). One extra training run, no new code. Turns "doesn't rely on hardware" from
rhetoric into demonstrated (modest) fact and answers "is this just tuned for one robot?"

## Scope management: narrow proof, broad framing

**Proven in paper 1:** frozen-artifact transfer across environment + dynamics axes, safety layer,
compute-placement contrast, all simulation-first.

**Positioned as design intent / future work (phrased "designed to extend to", never "we can do"):**
- Parent-supervised online adaptation (parent learns on the robot's behalf, pushes artifact
  updates) — see `05_transfer_learning_notes.md`.
- Sim-to-real on the physical robot (the second transfer axis; becomes the revision upgrade).
- Cross-embodiment: quadruped (railway rough terrain), robot hand (contact-rich); pillar B (GW).
- Railway field deployment.

The draft's five-gap framework becomes the **roadmap figure** in the discussion section — it says
"this is step one of a larger program" without claiming step five is done.

## Venues & calibration (honest)

| Tier | Venues | Notes |
|---|---|---|
| First target (sim-only OK) | IEEE CASE, ROBIO, ICAR, IEEE SII | Simulation-only acceptable with systematic analysis |
| Fast milestone | IROS/ICRA **workshops** | If the full experiments slip; the minimum viable demo below ships here |
| Later (needs real robot) | IROS/ICRA main, RA-L | Real-robot section from paper 2 / revision |

## Safety net: the two-level structure

- **Minimum viable demo (workshop-sized, 4–6 pages):** Koopman lifting trained in randomized sim →
  frozen drop into the railway yard → one success-rate table + adaptation curve + one ablation.
  Shows "the idea is something" even if the full version slips.
- **Full conference paper:** everything in this document.

Same experiments, growing paper — publication risk removed.

## Language rules (agreed)

- "Demonstrates / provides evidence that" — never "proves / solves."
- "Forward invariance under bounded disturbance" — never "100% certifiable safety."
- Future tiers: "the architecture extends to…" — never "we can transfer to…".
- Every claim sentence in the conclusion must point at a specific table or figure.

## Related-work positioning (write carefully)

- **Domain randomization** literature: we use it as the training ingredient, but the contribution
  is the freeze/adapt rule + math core (baseline 3 exists precisely to make this distinction).
- **Koopman control**: applied to a cheap AMR's sim-to-real transfer, not to manipulation/legs —
  check crowding at submission time.
- **Cloud/split robotics**: adjacent to the parent/tethered tier; differentiate: we transfer
  *frozen artifacts across compute placements*, not offload generic inference.
- **CBF safety filters**: ours is disturbance-adaptive (DOB widens margins) and wraps a distilled
  student policy.

## What could kill the paper (risk register)

| Risk | Mitigation |
|---|---|
| "Why not just use Nav2?" | Degraded-dynamics targets where classical fails are mandatory in the design |
| "This is just domain randomization" | Baseline 3 (randomization-only, no math core) |
| Sim robot not believable | Measured parameters from the physical robot (`06_validation_plan.md`) |
| Overreach detected | Scope management + language rules above |
| Engine works everywhere (suspicious) | Include and analyze a failure case; show recovery |
| Isaac Sim setup friction | Method nodes are simulator-agnostic ROS 2; Gazebo is the early testbed (`04_isaac_sim_strategy.md`) |
