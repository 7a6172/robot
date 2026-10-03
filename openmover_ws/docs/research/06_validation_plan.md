# 06 — Validation Plan: What Must Be Verified Before Any Learning

Everything downstream rests on one foundation: **the simulation must be a faithful twin of the
physical robot.** If the sim robot behaves differently from the real one on a clean floor, no claim
about degraded conditions is worth anything — reviewers ask this first. Verification order below;
do not skip ahead.

## Step 1 — Characterize the physical robot (the most important step, and cheap)

Physical measurements:
- [ ] Wheel radius, wheel separation (track width)
- [ ] Total mass (and CoG approximation)
- [ ] LiDAR mounting positions/orientations relative to the base frame
- [ ] Caster geometry (the two caster wheels) if it affects turning friction

Behavioral tests (teleop or scripted `cmd_vel` replay, log `/odom`):
- [ ] Straight lines: commanded distance vs. actual (odometry drift, wheel slip)
- [ ] In-place turns: commanded angle vs. actual
- [ ] **Motor dead zone**: minimum `cmd_vel` magnitude that produces motion (must be modeled in sim)
- [ ] Max reliable acceleration before wheel slip
- [ ] Stop behavior: coast distance after zero command

Output: a one-page parameter sheet — the single source of truth for every sim model.

## Step 2 — Build the sim robot from measured numbers

- URDF (`pioneer3dx.urdf.xacro`) parameters updated to measured values → exported to USD for Isaac.
- Friction coefficients, mass, inertia, motor/acceleration limits from the parameter sheet.
- 2D LiDAR sensor model matched to the real LiDAR (range, FOV, resolution, rate, noise).
- Rule: **simulation mirrors the physical robot that exists** — if hardware ever changes
  (e.g., bigger tires on a future variant), the sim model changes with it, and the engine's
  `g_θ` adaptation absorbs the residual. (Wheel change = dynamics-regime change = more engine
  evidence, not a problem.)

## Step 3 — Baseline fidelity check

Run the same drive script (a square and a figure-8) in sim and on the real robot; compare
trajectories. Acceptance: trajectories match on clean floor within a small tolerance
(defined when we have data). If they don't match, fix the twin before anything else.

## Step 4 — Characterize degraded-condition surfaces

Real-world degraded regimes do NOT require railway tracks. Different floor materials are the
degraded dynamics regime for a vacuum-class robot:
- [ ] Smooth tile (baseline) / carpet / plastic sheet / taped zone — simple push-tests give
  friction (μ) estimates to mirror in sim.
These become both the sim's friction-patch parameters and the later real-robot upgrade path.

## Step 5 — Only then: environments and learning

Source domains + railway yard in Isaac Sim; engine training per `03_paper_one_scope.md`;
early development of the simulator-agnostic ROS 2 method nodes against the running Gazebo stack.

## Railway yard scene specification (Target 1/3)

Flat-floor railway *maintenance yard/depot*, not ballast:
- Tracks rendered as floor-level obstacles or fenced-off zones
- Cable ducts, maintenance equipment, tool carts, parked service vehicles as clutter
- Degraded friction patches (oil/dust/rubber-mat equivalents) for the dynamics axis
- Corridors between equipment rows (a long trackside corridor can be added later as a bonus
  stress test — perceptually degenerate for 2D LiDAR, harder and more impressive)

Ballast, sleepers, and rough terrain are explicitly **out of scope for this robot** — that is
quadruped territory (draft Gap 2, paper 3+).

## Metrics (define once, use everywhere)

- Task success rate, collision rate (target: 0 under CBF by construction)
- Minimum clearance to pedestrians/obstacles
- Time-to-goal, path efficiency
- QP solve time / model size / inference latency (compute-tier rows)
- **Adaptation budget**: samples of target-domain experience vs. performance (the headline curve)
- Degradation under shift: train-nominal → test-shifted, with vs. without the engine

## Open items for later real-robot work

- Ground-truth pose in the real world: fixed landmarks? hand-labeled checkpoints? (decide when
  paper 2 starts)
- Tethered link: WiFi or cable (measure latency/jitter either way; the CBF absorbs it)
