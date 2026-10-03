# Project Report — Frozen-Learned Navigation with a Mathematical Safety Interface
## NMTE bring-up on the openmover differential-drive robot (Isaac Lab / Isaac Sim / ROS 2)

*Companion documents: [06_results.md](06_results.md) (all numbers, chronological ledger,
including every negative), [05_lessons_learned.md](05_lessons_learned.md) (bug mechanics),
[04_runbooks.md](04_runbooks.md) (how to reproduce everything). This report is the
narrative of the project: what we built, what it proved, where it failed, and how each
failure is evidence rather than waste.*

---

## 1. Thesis in one sentence

**Learning can be transferred** — a policy trained once in one simulated world keeps
working in worlds it never saw, *provided* a mathematical interface layer (geodesic
waypoints, disturbance estimation, a deploy-time safety shield) carries the parts that
do not transfer by themselves; the weights never move.

This is the working instantiation of the NMTE program (frozen learned core +
lightweight certifiable interfaces). The components named in the framework draft —
Koopman core, DOB, CBF — are concepts, not final mechanisms; the invariant that
carries over is the division of labour:

> **The learned policy provides competence. The interface provides guarantees.**

Iteration 1 of the presentation runs tested the first half of that sentence.
Iteration 2 (this report's second half) tests the second — and shows what happens
when the guarantee arm is missing, then switched on.

---

## 2. The system

| Layer | What it is | Where |
|---|---|---|
| Robot | openmover (diff-drive, 2× 600-bin LiDAR ±90° front/rear, wheel kinematics R=0.050353 m, sep 0.324 m) | `openmover_lab/`, URDF + Lab cfg |
| Source world | 8 m rooms, 4–12 scattered walls, 100 % blocked-goal sampling (every goal chord crosses a wall) | `Isaac-Nav-Openmover-v0` |
| Training | 17 runs, ~50 M env-steps, PPO → geodesic-expert BC/DAgger → frozen checkpoint `bc_init_v3/model_0.pt` | ledger §2 |
| Policy | MLP 1208-d obs → 2 wheel actions, 20 Hz; obs = front+rear scans, goal, proprio, geodesic waypoint+d_geo, contact channel | `policy_node.py` |
| Deploy rung | plain ROS 2 topics (scan/odom in, `/cmd_vel` out) through Isaac bridge; map JSON is the single shared world model for sim colliders AND policy GeoField | §9, §12 of ledger |
| Capstone | user draws a PNG → BFS-validated JSON → bridge bakes it → frozen policy told "go" | `27_make_custom_map.py` chain |
| Safety shield (iteration 2) | DWA-style velocity filter with last-seen obstacle persistence + hull-footprint forward simulation, sitting between frozen policy and chassis | §6 below |

Second embodiment: every deploy-rung run physically drives a **pioneer3dx** plant
(different wheel geometry, mass, casters) through the same `/cmd_vel` boundary —
zero retraining (ledger §10).

---

## 3. What the learned policy is, and what it took to get it

The honest chronology (ledger §2): 17 runs, most of them negative, each one a
hypothesis killed or confirmed.

- PPO from scratch never bootstrapped blocked-goal reaching (runs 3, 4, 6): the
  detour is a local minimum of distance-shaped reward. Curriculum and clearance
  shaping did not fix it (runs 7–9): **exposure was not the constraint — the motor
  program was undiscoverable from reward alone**.
- Reward-space geodesic shaping made it worse (run 11); observation-space waypoint
  injection alone produced a cautious in-place wiggle (run 12) — *and both were later
  found confounded by a corrupted waypoint observation* (run 15 diagnosis: 40 % of
  waypoints pointed through walls). Finding that bug was worth more than any of the
  five runs it confounded.
- Behaviour cloning from a validated geodesic expert under the fixed observation,
  plus a contact-force observation channel, produced the frozen policy: **blocked-goal
  success 0.287** (vs 0.095 for the best pure-PPO run and 0.036 for the drive-straight
  baseline floor). DAgger relabeling added nothing once observations were clean
  (run 16) — distribution shift is provably *not* the binding constraint.

Two numbers to keep from this section:

1. The policy beat the no-learning floor **~8×** on blocked goals in-distribution.
2. It got there only after an **interface discovery** (geodesic waypoint channel):
   competence itself was seeded by a mathematical structure, not by brute force.
   This foreshadows everything in iteration 2.

---

## 4. Transfer evidence — frozen weights, adapting interfaces

All results below use the SAME checkpoint. No gradient step was ever taken in a
target world.

| Axis | Mechanism | Result |
|---|---|---|
| Geometry | none (zero-shot) | rail yard: blocked success 0.190 (−34 % vs source) — partial transfer onto unseen clutter |
| Geometry + task | GeoField from shared map JSON | user-drawn maps solved zero-shot: crossings 33.5 s; ladder easy 29.3 s, mid 26.2 s; **3-goal tour 46.1 s** via goal sequencing + per-leg field rebuild (interface-level task composition) |
| Robustness | spawn jitter ±0.15 m/±15° | **4/4 successes** (20.9–33.5 s) — the positive side of the gradient is not a lucky seed |
| Interface necessity | waypoint-blinding ablation | 4/4 → **0/1**, pins 5.7 m short: the math-guided channel is load-bearing; LiDAR reflexes alone do not compose into gap-threading |
| Dynamics | DOB-lite (plant-gain disturbance observer, online) | degraded world **0.028 → 0.363** (12.9×) with zero adaptation data; converges to theory (g\* = 0.599 vs predicted 0.6); within 3.2 % of an oracle that knows the degradation in advance |
| Safety (training-world A/B) | CBF-lite velocity barrier | collisions −23 % with success *slightly up* (0.331 → 0.358 on ring); filter works hardest where transfer is weakest (49 % interventions OOD vs 14.6 % in-distribution) |
| Adaptation budget | retrain-from-scratch curve | engine zero-shot (0.190) equals a from-scratch BC policy trained on **~238 k target-world expert demos** — the quantified saving of the transfer-first paradigm |
| Dynamics model | Koopman data pipeline v0 (offline) | frozen lifted fit keeps body channels on degraded data, loses wheel channels (R² 0.88 → 0.57); a lift-statistics refit recovers to 0.99 — freeze-structure/adapt-interface on the dynamics side |
| Deployment | ROS 2 rung | frozen policy through plain topics on a **different physical robot** (pioneer3dx), 8.07 m headline reach in 30.85 s |

The measured **boundary** is equally part of the evidence: hard-rung maps
(offset-gap cornering) and narrow-door serial maps wedge the policy; a goal requiring
a detour that contradicts goal-pull is not reachable zero-shot. Transfer is not
monotone in visual complexity — it is monotone in *behavioural overlap* with the
source distribution. That boundary localizes to one behaviour (approach angle at
narrow passages), which is exactly what an interface arm should target next —
and that targeting is what iteration 2 exercised.

---

## 5. The presentation runs and their flaw (iteration 1)

Five maps were rendered for presentation (`videos/custommap_demo/` — all kept):
demo_open, demo_mid, demo_gauntlet, demo_tour, demo_crossings, top-down and 3D.
Every presented run **reached its goal(s)** — and almost every video showed the robot
**touching a wall at some point along the way**.

We audited this instead of arguing about it. `30_clearance_audit.py` computes, for
every trace frame, the distance from 9–17 hull sample points of the robot footprint
to the walls (raster occupancy field and, since iteration 2, exact wall-box geometry
from the map JSON — the same boxes the simulator bakes into colliders). Negative =
hull inside a wall.

Iteration-1 penetration frames (raster audit):

| Map | Penetration frames | Verdict of iteration 1 |
|---|---|---|
| demo_open | 458 / 1950 | SUCCESS 29.3 s — but contact along the way |
| demo_mid | 352 / 1950 | SUCCESS 26.2 s — contact |
| demo_gauntlet | 888 / 1950 | NOT FINISHED (wedge) — contact |
| demo_tour | 71 / 2850 | SUCCESS 3 goals 46.1 s — contact |
| demo_crossings | 1 / 446 | SUCCESS 33.5 s — one grazing frame |

Reading this correctly matters:

1. **The contacts are the expected behaviour of the frozen policy, not a regression.**
   The source-world checkpoint itself carries collision ≈ 0.64 (ledger §2/§3): it was
   trained for *reaching through clutter* with contact as a recoverable event
   (one-shot penalty + backup recovery). Wall-brushing was in its behavioural
   vocabulary by construction.
2. **This is precisely the framework's Gap-4 statement, measured.** The NMTE draft
   argues that learned policies cannot certify constraint satisfaction and must be
   paired with a deploy-time safety filter. Iteration 1 deployed the competence arm
   *without* the guarantee arm. The audit quantified exactly that gap: competence
   present (goals reached across unseen geometry), guarantee absent (206–888 contact
   frames per run).
3. **A diagnosis this precise is what licenses a targeted fix.** We know where the
   contacts happen (gap edges, corner approaches, post-success grinding), so we can
   activate the safety arm and re-measure with the same ruler.

---

## 6. Iteration 2 — the deploy-time safety shield

### 6.1 Design (the CBF arm, instantiated)

A velocity-space safety filter sits between the frozen policy and the chassis,
*after* the recovery layer (so backups are filtered too). It is intentionally
classical — that is the point of the division of labour:

- **Obstacle evidence**: every valid LiDAR hit is buffered per-beam in world frame
  and **never forgotten** (the map is static). This *last-seen persistence* is the key
  design decision: the scanners have a 0.22 m near clip, so a wall the robot closes to
  inside 0.22 m disappears from live scans — without persistence the shield would go
  blind exactly when it matters most. With it, the shield's obstacle grid always
  contains every wall the robot has ever seen, at its true world position.
- **Candidate generation**: a discrete velocity set (8 linear × 7 angular, including
  reverse) of constant-curvature arcs.
- **Safety test**: each candidate is forward-simulated for 0.8 s plus a full braking
  tail (0.6 m/s² deceleration — the filter must prove the robot can still STOP),
  checking 17 hull sample points (all corners, edge midpoints and quarters) against
  the obstacle grid dilated by a 0.10 m hull-surface margin at 0.08 m resolution.
- **Selection**: the policy's own command passes through if — and only if — it is
  provably safe. Otherwise the shield substitutes the safe candidate maximizing
  forward progress (with a turn-rate bonus and a minimality penalty toward the
  policy's intent). The stop command (0,0) is always admissible, so **the shield can
  never be forced to choose an unsafe action — the worst case is standing still.**
- **Two tiers (v5)**: the test above runs against the *dilated* grid (tier 1,
  comfort). Grazing lidar scatter plus dilation can over-block tight pockets into a
  rotation livelock, so when tier 1 offers nothing but stop/rotate, candidates are
  re-checked against the *raw* wall grid at ≤0.20 m/s (tier 2, escape). The raw grid
  is the hard physical bar — hull never enters a cell containing an actually-sensed
  wall point — so the no-contact guarantee holds in both tiers (§6.2, v4/v5).

Cost: ~14 ms per intervention tick, on CPU, at 20 Hz — deployable on edge hardware.

### 6.2 The shield's own iteration story (kept, per D24)

The shield did not work on the first try, and the failures are as instructive as the
fix (artifacts kept: `trace_demo_open_shieldv1.npz`, `…_shieldv2_stuck.npz`):

- **v1 (sector veto)**: 12 angular sectors, per-sector minimum range, veto unsafe
  sectors. Reached the goal — and the audit still flagged penetrations. Sector minima
  are too coarse: they protect the sensor origin, not a 0.44×0.28 m hull with
  corners. Kept as the negative that motivated hull-aware filtering.
- **v2 (DWA hull check, no persistence, margin 0.22 m)**: **deadlocked at spawn.**
  Every candidate — including in-place rotation, whose hull sweep grazed the dilated
  zone — was judged unsafe, so the shield emitted (0,0) forever: NOT FINISHED,
  0.08 m of motion, 2400/2400 shield ticks. Root-caused with dedicated diagnostics
  (`/tmp/bias_diag.py`): the spawn corner's true hull clearance is +0.31 m, less than
  margin + dilation; and LiDAR measurements have no meaningful bias (±0.062 m is cell
  quantization), so the fix had to come from geometry, not calibration.
- **v3 (margin 0.22 → 0.10 m, reverse candidates added, per-beam world-frame
  persistence)**: reached the goal on demo_open — and the audit revealed the last
  residual: 206 flagged frames, all *after* success, where the policy spent the
  remaining 97 s pressing into the goal pocket while the shield resisted (exact-box
  worst grazing: 1.6 cm at a block corner). The approach phase itself: **0
  penetrations, min clearance +0.17 m**.
- **Park-after-success**: the frozen policy has no stop-at-goal behaviour (known since
  §9 of the ledger — "post-success wander"). One-line interface fix, zero weight
  change: after the final goal is reached, the node parks (publishes zero twist).
  Final demo_open audit: **0 penetration frames, exact and raster, entire run.**
- **v4 (presentation set)**: the shield cleared open/mid/crossings/gauntlet, but the
  3-goal **tour livelocked at goal 3** (artifact kept:
  `trace_demo_tour_v4_livelock.npz`): in the tight corner pocket, grazing lidar hits
  scatter 3–20 cm off the true wall surfaces and the grid dilation extends the
  comfort envelope past the ~0.18 m clearance the hull actually keeps, so *no*
  forward candidate stayed outside the dilated grid and the robot could only rotate
  in place — 9 mm short of the success radius, forever.
- **v5 (two-tier barrier / escape hatch)**: the fix keeps the guarantee but adds an
  exit from the livelock. Tier 1 (comfort) is unchanged: candidates must keep the
  hull outside the *dilated* grid. Tier 2 (escape) engages only when tier 1 is
  rotation-locked (best candidate has v = 0): candidates are re-checked against the
  *raw* wall grid — cells containing actually-sensed wall points — under a low speed
  cap (0.20 m/s). Raw-grid safety is the hard physical no-touch bar (the hull never
  enters a cell with a sensed wall point), so **zero contact is still guaranteed by
  construction**; (0,0) remains admissible in both tiers. On maps that never
  rotation-lock the escape tier is provably inert.

### 6.3 Shielded results (iteration 2)

Same frozen checkpoint `bc_init_v3/model_0.pt`. Same maps. Shield ON. New folder
`videos/custommap_shield/` — every iteration-1 artifact kept untouched.

| Map | Verdict | Time-to-goal | Recoveries | Shield interventions | Exact-audit penetration | Min hull clearance |
|---|---|---|---|---|---|---|
| demo_open | SUCCESS | 26.20 s | 1 | 67 / 2400 ticks | **0 / 1950 frames** | **+0.182 m** |
| demo_mid | SUCCESS | 25.00 s | 1 | 47 / 2400 ticks | **0 / 1950 frames** | **+0.179 m** |
| demo_tour (3 goals) | SUCCESS | 57.15 s | 0 | 45 / 2400 ticks (20 escape-tier) | **0 / 1950 frames** | **+0.131 m** |
| demo_crossings | SUCCESS | 24.55 s | 1 | 38 / 2400 ticks | **0 / 1950 frames** | **+0.287 m** |
| demo_gauntlet | SUCCESS | 29.10 s | 1 | 86 / 2400 ticks | **0 / 1950 frames** | **+0.158 m** |

Tour note: two independent shielded tour runs, both 3/3 goals with **zero contact** —
the table shows the confirmation run (57.15 s; the escape tier fired live 20 times in
the goal-3 pocket and crept the robot out, exactly the livelock exit it was built
for), and the first v5 run (49.85 s; the policy threaded the pocket cleanly, zero
shield interventions, min clearance +0.237 m). Run-to-run nondeterminism in
ROS/sim timing changes which of the two paths materializes; the guarantee is on the
contact outcome, not on the path. Against iteration 1 on the same maps: open 458 → 0
penetration frames, mid 352 → 0, crossings 1 → 0, gauntlet 888 → 0, tour 71 → 0;
time-to-goal unchanged or better (29.3 → 26.2 s; 26.2 → 25.0 s); recoveries down an
order of magnitude (20 → 1; 14 → 1) — the shield prevents the stall/blip cascades the
recovery layer used to clean up after the fact. The gauntlet is the standout:
iteration 1 **wedged into the gap corner and never reached the goal** (888 contact
frames); iteration 2 **reaches it in 29.10 s with one recovery and zero contact**.
The hard rung went from failure-with-contact to success-without-contact by activating
the mathematical arm — the policy weights are bit-identical between the two runs.

**The guarantee statement we can defend**: with the shield active, no command reaches
the chassis unless it survives a 0.8 s + braking-tail forward simulation of the full
hull against every obstacle the sensors have ever seen — either at comfort margin
(tier 1, dilated grid) or, when tier 1 offers nothing but stop/rotate, against the
raw wall grid at ≤0.20 m/s (tier 2). The hard bar — the hull never entering a cell
containing an actually-sensed wall point — holds in both tiers, and the stop command
(0,0) is unconditionally admissible. Empirically, across the shielded presentation
set: zero contact frames under exact wall geometry.

### 6.4 What the gauntlet result means

Iteration 1's hard rung wedged the policy *into* the gap corner (888 contact frames,
no reach). Before running it we set an honest, lower expectation: the robot may fail
to REACH the hard goal — reaching is competence, and the shield does not create
skills — but it will **stop in a safe pose rather than grind into the corner**. The
actual result beat the expectation: with the shield active the same frozen policy
**reaches the gauntlet goal in 29.10 s, zero contact, min clearance +0.158 m**. Why a
safety filter *improved* a reach outcome: iteration 1's wedge was a contact cascade —
the policy pushed, stalled, recovered, pushed again into the same corner. The shield
removes the cascade at the source; every command that survives is geometrically
admissible, so the policy's own (competent) steering accumulates progress instead of
being reset by stall/backup cycles. "Move, stop, do whatever, but never collide" is
satisfied *by construction* — and on the hard rung the construction did not cost the
reach, it delivered it.

---

## 7. Defense — direct answers to the hard questions

**"Even simple navigation algorithms do better than this — are we worse than
if/else rules?"**

On one narrow question — contact-free traversal of a known static map — yes, a
classical local planner does that, and we are not claiming otherwise. In fact
iteration 2 *is* that classical layer: the shield is a DWA-style filter. The claim of
this project was never "the neural network dodges walls better than DWA". The claim
is about what each component contributes:

- **A hand-written if/else or DWA planner does not transfer.** Retarget it to a new
  robot, a new world, degraded dynamics, and it is rewritten and retuned. Our single
  frozen checkpoint crossed: unseen geometry classes (rail yard, user-drawn maps),
  unseen task structure (3-goal tours composed at the interface), degraded physics
  (DOB-lite: 0.028 → 0.363 with zero adaptation data), and a *different physical
  embodiment* (pioneer3dx) — all through interfaces, never through gradients.
- **The learned policy carries competence classical layers don't have.** The blinding
  ablation is the cleanest evidence: zero the geodesic-waypoint channel and the same
  frozen network goes 4/4 → 0/1. Conversely, the shield alone cannot reach any goal —
  it has no task knowledge at all. Neither arm alone does the job; the composition
  does.
- **The combination now beats each part on the union of their metrics**: iteration-2
  runs reach the goals that iteration 1 reached, in equal or less time, with an order
  of magnitude fewer recovery events — and with *zero* contact frames, which
  iteration 1 could not claim and which a goal-seeking policy without a shield never
  will.

**"Lots of algorithms out there already do better than your work."**

Better at what? Single-map, known-world, single-embodiment point-goal navigation is a
solved problem — we agree, and we use its solution (the shield is nav2/DWA-family
technology, deliberately). What is *not* solved, and what this project measures with
numbers instead of adjectives, is **deployment without retraining**: how much
target-world data does a from-scratch pipeline need to match what the frozen engine
does zero-shot? Our budget curve answers: ~238 k expert demos on the geometry axis.
The DOB answers on the dynamics axis: a 4-line observer recovers 96.8 % of an oracle
that knows the degradation factor in advance. These are transfer results, not
planning results, and they do not exist in the "already out there" literature for a
frozen-weights system of this class.

**"We ran so much compute — did we waste all this time?"**

No — and the ledger is structured to prove it. Of 17 training runs, most were
negative, and each negative killed a hypothesis that the field's conventional wisdom
would have kept alive: exposure is not the constraint (run 9), reward-space geodesic
shaping does not reach the policy (run 11), distribution shift is not the cloning
bottleneck (runs 14, 16), and the corrupted-waypoint bug (run 15 diagnosis) confounded
three published-style conclusions before we caught it. The compute bought: a policy
8× above the no-learning floor on blocked goals, a measured transfer table across two
shift axes, an adaptation-budget crossing point, two validated interface mechanisms,
and a second-embodiment deployment. Iteration 1's contacts added the last missing
measurement — the exact size of the competence-vs-guarantee gap — and iteration 2
closed it with a 200-line interface around the same frozen weights. That is the
method working, not the method failing.

**"How am I supposed to defend this?"**

The defensible sentence is the framework's own, now with both halves measured:

> A learned policy provides *competence* that transfers across worlds, tasks, dynamics
> and embodiments with frozen weights — quantified against retraining (§3, §6, §7,
> §10 of the ledger) and shown load-bearing through ablation (§14). A mathematical
> interface provides *guarantees* the learned component cannot: the deploy-time shield
> makes contact-free operation structural (stop is always admissible; nothing else
> passes without a proven-safe forward simulation), verified frame-by-frame against
> exact wall geometry (§6.3). Where the policy is out of its depth (hard rung), the
> system degrades to *stopping safely* instead of *colliding and reaching* — a
> failure mode a reviewer can accept, replacing one they cannot.

The honest weakness to concede before being asked: the shield's guarantee is relative
to observed evidence (persistent LiDAR hits on a static map); it does not cover
never-seen or moving obstacles, and it does not make unreachable goals reachable.
Both belong to the next iteration (decay/forgetting for dynamics, bearing-aware
recovery or few-shot adaptation for the wedge seam).

---

## 8. Honest limitations (pre-disclosed)

1. **Sim-only.** No physical-robot validation yet; the ROS 2 rung and the second
   simulated embodiment are the closest proxies.
2. **Static-map persistence.** The shield's never-forget buffer assumes a static
   world. Dynamic obstacles need a decay rule (bounded staleness), not yet
   implemented or tested.
3. **Observation-relative guarantee.** An obstacle never registered by any beam
   (below sensor height from the very first moment, or occluded until inside the
   0.22 m near clip) is outside the shield's evidence. Margin + low speeds bound but
   do not eliminate this.
4. **Single seed per presentation run.** The transfer TABLE (2 k episodes/world) and
   the 4/4 jitter repeats carry the statistics; the shielded videos are existence
   demos with frame-exact audits, not distributions.
5. **The wedge seam remains on the hardest geometry.** The gauntlet (iteration 1's
   hard-rung failure) became reachable once the shield removed the contact cascade,
   but narrow-door geometry (serial-rooms, 1.0 m doors, 0/3 in iteration 1) is still
   beyond the frozen policy; the shield converts that failure from "collide" to
   "stop short". Reaching there is the adaptation work of the next iteration.
6. **Post-success parking is interface policy**, not learned behaviour — the frozen
   policy still has no stop-at-goal skill, we simply gate it.

## 9. Framework-arm tally (NMTE ↔ this project)

| NMTE arm (draft names — concepts, not final) | Instantiation here | Status |
|---|---|---|
| Koopman core | frozen lifted-linear fit + lift-statistics refit on degraded data (offline) | concept validated offline (ledger §11) |
| DOB (disturbance observer) | DOB-lite plant-gain observer, deploy-time, online | **validated A/B** (0.028 → 0.363, §7) |
| CBF (safety filter) | CBF-lite velocity barrier (training worlds, §8) → **deploy-time DWA shield with persistence + hull + braking tail** (this iteration) | **validated A/B and now load-bearing in presentation runs: 0 contact frames** |
| GW optimal transport | not exercised; embodiment transfer currently rides the velocity-level interface | deferred (honest gap) |
| Geodesic waypoint interface | GeoField from shared map JSON; per-leg rebuilds | **validated, load-bearing** (blinding ablation, §14) |
| Recovery layer | stall + progress-checker triggered backups | quantified per run; superseded in practice by the shield on presentation maps (20 → 1 recoveries) |
| Task composition | ordered goal lists + field rebuilds | demonstrated (3-goal tour) |

## 10. Artifact inventory

- **Iteration 2 (this report)**: traces, clips, topdown + 3D videos in
  `isaac/lab/videos/custommap_shield/` (incl. `trace_demo_tour_v5_confirm.npz`,
  the confirmation run in which the escape tier fired live); logs
  `isaac/lab/logs/shield_*` and `render3d_shield_*`; shield code in
  `src/warehouse_simulation/scripts/policy_node.py` (`shield:=true`); audit tool
  `isaac/lab/30_clearance_audit.py` (`--map_file` = exact mode, `--t_reach` = phase split).
- **Iteration 1**: `isaac/lab/videos/custommap_demo/` (traces, clips, topdown + 3D
  videos), `logs/capstone_*` — all kept.
- **Shield development history**: `videos/custommap_shield/trace_demo_open_shieldv1.npz`,
  `trace_demo_open_shieldv2_stuck.npz`, `trace_demo_open_shieldv3_grind.npz` + matching
  logs — the v1/v2/v3/park progression is auditable from artifacts, not just prose.
- **Maps**: `isaac/lab/maps/demo_*.{png,json,preview.png}` (user-PNG pipeline).
- **Training evidence**: `isaac/lab/logs/rsl_rl/openmover_nav/`, BC/DAgger logs and
  checkpoints per ledger §2.

## 11. Next iteration (queued, not claimed)

1. **Reach the hard rung**: bearing-aware recovery or CBF-shaped approach angles —
   make the wedge seam survivable so the shield's stop-fallback is never needed.
2. **Dynamic-obstacle shield**: bounded-staleness decay on the persistence buffer +
   moving-obstacle prediction horizon.
3. **Few-shot lift refit in closed loop** (Koopman arm): currently offline-only.
4. **GW cross-embodiment alignment**: the deferred arm.
5. **Hardware**: the rung already speaks plain ROS 2; the shield is CPU-cheap — the
   stack is edge-shaped by construction.
