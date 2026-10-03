# 08 — Decisions Log

Every decision made during the research discussions, with rationale. Agents: treat decided items
as settled unless explicitly reopened; treat open questions as genuinely open.
(All decisions: August 2026 discussion rounds.)

## Decided

| # | Decision | Rationale |
|---|---|---|
| D1 | The whole point of the ROS 2 migration is Isaac Sim readiness; this robot is the first test article | Isaac Sim requires ROS 2; the lab migrates robot-by-robot |
| D2 | First output = one conference paper demonstrating the **transfer engine mechanism**, simulation-first; real robot later | Prove the idea cheaply; everything built is reusable for the thesis |
| D3 | The core claim wording: **"Learning transfers; hardware is just the interface"** | Agreed one-sentence thesis of the engine |
| D4 | Railway scenario for paper 1 = **yard/depot/walkway (flat floors)**; ballast & tracks are OUT (quadruped territory, paper 3+) | The vacuum-class robot physically cannot do ballast; SWJTU railway context preserved honestly |
| D5 | **No new hardware for paper 1** (no bigger-tired robot build) | Fewer variables, faster to paper; sim mirrors existing robot; wheel changes later are themselves engine evidence |
| D6 | Experiment geometry: 1 randomized source + **factorized targets** (geometry-only / dynamics-only / both) | Decomposition table = understanding, not luck |
| D7 | Baselines: rebuild-classical, retrain-from-scratch, randomization-only-no-math-core | Defends against "just use Nav2" / "just domain randomization" attacks |
| D8 | Headline figure = **adaptation-budget curve** (performance vs. target-domain samples) | Makes the transfer engine visible in one plot |
| D9 | Simulation-only results acceptable for paper 1; target venues mid-tier (CASE, ROBIO, ICAR, SII) + IROS/ICRA workshops as fast milestone; IROS/ICRA main needs real robot later | Honest calibration of sim-only acceptance |
| D10 | **Parent/tethered architecture adopted**: same frozen artifacts across compute placements (onboard / tethered / parent-supervised) | Compute-agnostic artifacts; the weak robot PC becomes an axis, not a limit; CBF absorbs link latency |
| D11 | **Parent-supervised online adaptation is FUTURE WORK (paper 2)**, not paper 1 | Keep paper 1 simple per agreement |
| D12 | Scope management = **narrow proof, broad framing**; five-gap roadmap figure in discussion; language rules ("demonstrates", "designed to extend to") | Avoid overclaim while not seeming small |
| D13 | Learned relocalization (candidate-scoring hybrid) = **parallel standalone paper**, not inside the NMTE paper | It's a perception problem, not dynamics/safety |
| D14 | Social navigation RL folds into the engine flagship experiment (student policy) rather than a separate thread | One experiment, multiple pillars |
| D15 | Quadruped + robot hand (available in lab) deferred to paper 3+ / cross-embodiment work | Don't start complex embodiments before knowing Isaac Sim |
| D16 | Verification order: **characterize robot → build measured twin → fidelity check → surface characterization → learning** | Sim claims rest on twin honesty |
| D17 | Method nodes are **simulator-agnostic ROS 2** (`/scan` in, `/cmd_vel` out); Gazebo is the early testbed while Isaac matures | Paper never blocks on Isaac setup |
| D18 | Environments are disposable: procedural training randomization + held-out unseen evaluation layouts; Gazebo warehouse = system-validation only | Stronger generalization claim |
| D19 | Research docs live in `docs/research/`, **Markdown only** (agents + humans; HTML docs stay for stable project docs) | Single source of truth, low maintenance |
| D20 | Engine operating rule: **freeze the structure, adapt the interface** (K & π frozen; g_θ, DOB, CBF margins adapt) | The intellectual content that separates engine from plain randomization |
| D21 | **Publication ladder** (2026-09-03): rung 1 = sim-first mechanism paper (mid-tier per D9); rung 2 = sim-to-real on the physical robot (revision / paper 2 — product stack gates already passed); rung 3 = cross-embodiment (quadruped/humanoid) + railway field deployment | De-risks "sim-only, simple robot" without overclaiming; every rung is publishable; simple platform is a methodological feature (isolates the transfer signal) |
| D22 | **Evidence philosophy** (2026-09-03): show even small advantages now, extend in later iterations; pre-disclose every known weakness in the paper itself (risk register → limitations section) so reviewers see awareness instead of discovering flaws | User directive; honest small claim > inflated big claim (language rules of 03) |
| D23 | **Vision / north star** (2026-09-03): if the system knows how to use its available inputs (LiDAR, camera, …), embodiment details (2 wheels vs 10, 1 kg vs 10 kg) should not matter — adapt to a new robot/world **without learning from zero**, filling the sim-to-real ("reality") gap. Paper 1 = first controlled demonstration of the mechanism on the available robot; cross-embodiment generality is the later rungs (D15, D21) | Aligns the program with the original NMTE motivation; keeps paper 1 scope honest |
| D24 | **All results/outcomes documented** in `docs/isaac/` (01 tables, 05 lessons, 04 runbooks) as they land — including negative results (run3 success 0.0 is documented, not hidden) | Reproducibility + the paper's decomposition table needs the full evidence trail |

## Open questions

| # | Question | Context |
|---|---|---|
| Q1 | Final target venue for paper 1 | Mid-tier list in D9; pick when experiments are near |
| Q2 | Include the cheap second-simulated-embodiment generality run in paper 1? | Recommended (one extra training run), optional |
| Q3 | Bonus long-corridor stress test in the yard scenario? | Nice-to-have; corridor is perceptually degenerate for 2D LiDAR |
| Q4 | Real-world ground-truth pose method (landmarks vs. hand-labeled checkpoints) | Needed for paper 2 / real-robot section |
| Q5 | Tethered link: WiFi vs. cable | Measure latency/jitter either way |
| Q6 | RAM upgrade to 32 GB on the dev PC | Single biggest Isaac Sim unlock; machine froze twice at 16 GB |
| Q7 | Exact tolerance for the sim-vs-real fidelity check (Step 3 of `06_validation_plan.md`) | Define once first data exists |

## Explicitly rejected / parked

- Game-style brake-then-reverse teleop semantics (implemented: repeat-while-held instead — see
  changelog).
- Claiming cross-embodiment results in paper 1 titles/abstract.
- Borrowing the ">500 Hz" control-loop figure for this robot.
- Building a bigger-tired robot before paper 1 is written.
- Isaac ROS GPU perception (tier E) before the training pipeline exists.
