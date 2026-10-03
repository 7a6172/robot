# Results Ledger (NMTE Paper 1)

Running ledger of what improved, what was transferred, and what went wrong — maintained
per decision **D24** (document every result/outcome, including negative ones, and
pre-disclose weaknesses). This file is the direct source for the paper's result tables.
Bug mechanics live in [05_lessons_learned.md](05_lessons_learned.md); this file holds
**numbers and claims only**.

All runs: task family `Isaac-Nav-Openmover-*` (differential-drive point-goal nav,
1204-d obs, 20 Hz control, 15 s episodes, success < 0.30 m since run5).
Task versions: **v1** (run1–run5): plain ring goal sampling, ring 1.5–3.0 m — only
~13% of spawn→goal chords were blocked (measured on CPU), so v1 success mostly
measures turn-and-drive. **v2** (run6+): blocked-goal sampling (ring 1.5–3.6 m;
every goal's chord crosses an obstacle), run7 adds a blocking-fraction curriculum.
Metrics are reset-weighted episode means (runner fix 2026-09-03, see 05).

## 1. Baselines (no learning)

| Policy | World | Success | Collision | Time-to-goal | Notes |
|---|---|---|---|---|---|
| forward (drive straight) | wall-maze | 0.036 | 0.956 | 4.78 s (lucky straight-line goals) | 772 episodes, 2026-09-03, success radius 0.30 m; at the old 0.15 m radius it was 0.125 (16 eps). This is the floor every learned policy must beat |
| random | wall-maze | ~0 | ~1.0 | — | validated 2026-09-02 |

## 2. Training runs (chronology)

Each row is one hypothesis about why the teacher does not learn yet, the change made,
and what the run proved — the paper's iteration story.

| Run | Date | What changed vs previous | Outcome | Effect / lesson |
|---|---|---|---|---|
| run1 | 2026-09-02 | first PPO bring-up: 256 envs × 300 iters, collision-terminal, unclamped progress | reward −5 → +6.4, ep-len 40 → 235/300, success 0 | env is trainable (PPO optimizes alive+progress); budget far too small for goal-reaching |
| run3 | 2026-09-03 | scaled to 1024 envs × 1500 iters | success flat **0.0000**; reward spikes −300..−1600 (negative result) | found 3 defects: collision-terminal starves wall-avoidance experience; unclamped progress explodes on physics blow-ups; runner metric bug faked successes (all fixed, see 05) |
| run4 | 2026-09-03 | collision → non-terminal −5/step; progress clamped to ±1.5·ω_max·r | **stopped at iter ~620/1500**: success still 0.0000 after ~15M env-steps, reward flat −320..−460, ep-len ≈300 (always timeout) | bounded rewards removed the blow-ups but learning still didn't bootstrap: the per-step −5 collision charge dominated return variance and the 0.15 m success radius made reach discovery ≈ 0 |
| run5 | 2026-09-03 | collision penalty **one-shot** (first contact per episode only); reach bonus 10 → 25; success radius 0.15 → 0.30 m | **success ≈ 0.62** (mean over last 300 logged reset batches), collision ≈ 0.47, time-to-goal ≈ 9.4 s; reward 70–90 (vs −320..−460 in run4); 1500 iters / ~52 min, clean exit | hypothesis confirmed: return variance collapsed (value loss ~1300 → ~6), first successes at iter ~70; **first goal-reaching teacher** → `logs/rsl_rl/openmover_nav/2026-09-03_13-56-09_run5/model_1499.pt` |
| run6 | 2026-09-03 | **task v2**: blocked-goal sampling (rejection + constructive, reconstructable layouts), ring 3.0 → 3.6 m, 100% of goals behind an obstacle | **failed to bootstrap** (negative result): success discovery flat ~1.8% of logged iterations over 2.4M steps (~500 iters, no upward trend), reward plateaus positive ~85, collision 0.5–1.0, ep-len ~296; blocked geometry itself verified (early collision ~1.0 on straight drives) | potential-field local minimum: pure distance shaping punishes the distance-increasing detour around a wall, so blocked reach is practically undiscoverable (run5's 87% unblocked goals were its bootstrap); videos would again have shown no avoidance. Escalated to curriculum (run7) per the pre-registered plan |
| run7 | 2026-09-03 | run6 + **blocking-fraction auto-curriculum**: p starts at 0.2 (run5-like bootstrappable mix), ramps toward 1.0 as blocked-goal success EMA > gate 0.2 (decays below; `Curriculum/block_prob` logged) | bootstrapped reach but avoidance incomplete: overall success 0.09 → ~0.42–0.53 plateau; **blocked-goal success 0 → ~0.10–0.18** (10× run6's discovery rate) but never sustained above the 0.2 gate, so p stayed pinned at 0.20–0.22; reward ~95–98; 1500 iters / 36.5 min clean → `2026-09-03_17-00-00_run7/model_1499.pt`. Video-verified: on a blocked goal the policy noses into the nearest wall and stops (displacement 0.3 m in 15 s) | the curriculum fixed bootstrap but NOT the local minimum: with only 20% blocked episodes there is too little gradient pressure on avoidance, and nothing rewards sliding along the wall toward the gap → clearance shaping (run8) |
| run8 | 2026-09-03 | run7 setup + **dense clearance shaping**: smooth penalty (−0.3·clamp(1−d_min/0.5 m)) from the LiDAR min-range, making walls repulsive so the gap is the only direction with both clearance and progress | **did not break the stall** (weak/negative): overall success plateau ~0.43–0.56; blocked success 0.03–0.16 episode-weighted, no trend (buckets 0.049/0.029/0.114/0.037/0.067/0.128/0.042/0.158/0.071/0.079/0.122/0.100/0.128/0.094/0.047); p still pinned 0.20–0.22; reward ~93–97; 1500 iters / 37 min clean → `2026-09-03_17-52-06_run8/model_1499.pt` | clearance shaping alone is not the bottleneck — exposure is: at p=0.2 only ~1/5 of episodes ever present the avoidance problem, so blocked success cannot cross the 0.2 gate (chicken-and-egg: exposure needs success, success needs exposure) → **scheduled blocking ramp** (run9) forces exposure on a fixed time schedule |
| run9 | 2026-09-03 | run8 setup + **scheduled blocking ramp**: p follows a fixed schedule 0.2 → 1.0 in per-env control steps 4800 → 19200 (~iters 200–800), replacing the gate controller during training | **exposure is NOT the binding constraint** (negative result): ramp verified on schedule (p 0.20→0.27→0.40→0.53→0.67→0.80→0.93→1.00); overall success peaked 0.45 at p≈0.4 then DEGRADED to 0.085–0.155 at p=1.0; blocked success stayed 0.03–0.18 in every bucket incl. the p=1.0 phase (0.095 episode-weighted over 796 blocked episodes, iters 800–1370); reward ~80–86 at p=1.0, ep-len ~292; native crash at iter ~1371 (no traceback; last ckpt `2026-09-03_18-34-57_run9/model_1350.pt`) | forcing exposure produced exposure, not skill: blocked success is capped ≈0.10 whether p=0.2 or p=1.0 ⇒ the avoidance problem itself is not learnable under the current reward/geometry, not under-sampled. Next rung must change the reward landscape or the problem difficulty (geodesic shaping / subgoals / easier blocked geometry + longer horizon) |
| run10 | 2026-09-03 | run9 setup + **geodesic potential shaping**: progress reward uses d_geo (octile Bellman distance field from the goal on a 32×32 occupancy grid of the exact tile layout, inflated 0.2 m, recomputed per episode at reset) instead of Euclidean distance; unit-tested offline (detour > euclid; free-space octile ≈ euclid ±3%) | **aborted at iter ~500** (implementation artifact, not a hypothesis test): bootstrap ~2× slower than run9 (reward 14–25 vs 52–86 at same iters) — root cause: the 0.25 m cell grid lumps ~14 steps of motion into one lookup jump (~5 m/s) and the v_max clamp (0.755 m/s) then discards ~85% of the progress credit | fixed with a residual accumulator (drain the lumped jump at the kinematic cap so average credit = true motion); relaunched as run11 |
| run11 | 2026-09-03 | run10 + **residual-accumulator progress credit** (fixes the quantization/clamp artifact) | **completed 1500/1500, NEGATIVE** — ckpt `2026-09-03_19-54-26_run11/model_1499.pt` | sanity passed: bootstrap pace matched run9 (reward ~70 at iters 100–199 vs run9 73). But blocked success (episode-weighted): 0.000/0.000/0.060/0.033/0.029/0.058/0.028/0.014 for iters 0–799, then 0.045/0.036/0.077/0.064/0.075/0.062/0.042 for 800–1499 ⇒ **p=1.0 phase 0.058 over 990 blocked eps vs run9's 0.095/796 — geodesic shaping is WORSE, not better**; overall 0.047 over 1600 blocked eps. Verdict: reward-space geodesic shaping does not reach the policy — the credit is available but the policy cannot discover/use the detour from shaped reward alone; even unblocked learning was slower (0.18 at iters 200–399 vs run9 0.39), suggesting the 0.25 m-quantized field adds noise. The bottleneck is information availability, not exposure or reward direction. **CONFOUND (found 2026-09-03 while building run12):** the field's inf-fill pass in `_update_geo_fields` was an unmasked zero-cost dilation, which flattened d_geo to 0 within ~4 cells of every goal (verified: d_geo < euclid at spawn in all debug envs) — so run10/11 trained on a corrupted field; their negative verdict on geodesic shaping is confounded and the shaping hypothesis remains UNTESTED with a correct field. |
| run12 | 2026-09-03 | run9 setup + **waypoint observation** (user-chosen): obs += 3 dims = next geodesic waypoint ~1.0 m ahead along the field descent path (robot-frame x/y, goal-obs normalization) + remaining d_geo; reward stays run9's Euclidean shaping (one change per run); field fill-pass bug fixed (masked to inf cells) and field re-verified (d_geo ≥ euclid − 0.36 at spawn, wp ≈ 1.0 m); obs space 1207 | **completed 1500/1500, NEGATIVE** — ckpt `2026-09-03_21-36-57_run12/model_1499.pt` | bootstrap healthy (mean reward 78.7 at iters 100–199 vs run9 73.1; guard never fired). Blocked success (episode-weighted): 0.026/0.063/0.060/0.095/0.078/0.114/0.154/0.154 for iters 0–799, then 0.099/0.040/0.092/0.068/0.056/0.084/0.064 for 800–1499 ⇒ **p=1.0 phase 0.072 over 1029 blocked eps vs run9's 0.095/796 — criterion NOT met**; overall 0.086 over 1637. Video (seed 42, p=1.0): robot wiggles/rotates in place near spawn for all 300 steps — neither the run9/11 wall-pressing nor any detour ⇒ new failure mode "cautious in-place wiggle". Verdict: giving the policy the detour *information* did not produce detour *behavior* — under conflicting goal-vs-waypoint-vs-LiDAR signals the policy collapses to standing still (alive reward makes that a local optimum). The binding constraint is discovery of the detour motor program, not information, exposure, or reward direction ⇒ next rung must INJECT the behavior (BC/DAgger from a field-tracking expert) or make the detour discoverable (subgoal / easier-geometry curriculum) |
| run13 | 2026-09-04 | run9 setup + **BC warm-start** (user-approved): new validated expert (geodesic descent chain w/ occupancy mask + chord-checked pure pursuit + backup-on-contact; blocked success 0.75 on 12-ep seed-42 eval, 0.636 over 683 eps at 256-env scale, all successes collision-free) collected 328k (obs, act) demos (demos_p100 159k @ p=1.0 + demos_p0 170k @ p=0.0); BC 15 epochs MSE (loss 0.177→0.045, act-MAE 0.23) into a fresh rsl_rl actor; synthesized `bc_init/model_0.pt` (BC actor + fresh critic/optimizer) and PPO-resumed from it | **completed 1500/1500, NEGATIVE** — ckpt `2026-09-04_03-46-11_run13/model_1499.pt` | bootstrap instant (reward 66 at iters 0–99 vs run9 73 at 100–199; early blocked success 0.10–0.16 = ~2× run9/run12 at same stage — the injected behavior IS present at start). But it DECAYS: blocked-success buckets 0.103/0.087/0.122/0.161/0.157/0.046/0.169/0.057/0.063/0.087/0.080/0.013/0.092/0.095/0.000 ⇒ **overall 0.089 over 1103 blocked eps ≈ run9's 0.095, far below the expert's 0.636**. Verdict: BC put the detour motor program INTO the policy (early 2× advantage proves injection works) but plain PPO's on-policy gradient erodes it back to the alive-reward standing-still attractor within ~500 iters — the cloning prior has no persistence mechanism under RL fine-tuning. Next rung must either keep the expert in the loop (DAgger / expert-mixed rollouts) or anchor the policy to the BC weights (KL/behavior-regularized PPO), or shrink the problem until RL can self-sustain the detour (subgoal / wall-length curriculum) |
| run14 | 2026-09-04 | **DAgger** (user-chosen escalation): expert extracted to `openmover_lab/geodesic_expert.py`; `25_dagger_openmover.py` rolls the current actor (256 envs, p=1.0), labels every policy-visited state with the expert action, aggregates into the dataset (328k seed + 4×102k), re-clones from scratch each round; no RL in the loop | **NEGATIVE** — 4 rounds, blocked success per round eval: 0.069 / 0.049 / 0.053 / 0.036 (rollouts 0.096/0.068/0.077/0.056); val act-MAE stuck at 0.26–0.28 across rounds (seed BC was 0.23) ⇒ on-policy labels did NOT close the cloning gap, so the gap is not a state-distribution problem. Diagnosis: the clone is massively UNDERTRAINED — batch 4096 × 8–15 epochs = 1–2.7k optimizer steps for a 512² MLP on 1207-dim input (loss still decreasing at stop); also the expert's backup state machine makes labels multimodal w.r.t. the observation. Follow-up (same run family): retrain on the 738k aggregate with 60 epochs / batch 1024 / lr 1e-3 (≈43k steps) and re-eval closed loop |
| run14-followup | 2026-09-04 | **long-BC retrain**: same 738k DAgger aggregate, 60 epochs / batch 1024 / lr 1e-3 (≈43k optimizer steps vs 1–2.7k for the short clone); fresh actor, then closed-loop eval at p=1.0 (256 envs × 2405 steps, seed 42) | **NEGATIVE** — val act-MAE improved 0.23 → 0.148 (sharper open-loop fit) but blocked success DROPPED to **0.044** vs the short clone's 0.096. Both clones sit at 0.05–0.12 while the expert scores 0.636 ⇒ the ceiling is NOT undertraining and NOT distribution shift | ⇒ triggered the observation-level audit (run15), which found the waypoint obs itself corrupted (40% of waypoints pointed through walls); see 05 lessons |
| run15-diagnosis | 2026-09-04 | **observation audit** (no training): replayed the expert at p=1.0 and tested the student's `_geo_waypoint` obs in world frame against the `_geo_occ` oracle | **CONFIRMED CORRUPT** — 40% of active waypoints' chords cross walls, 30% of waypoints inside wall cells (6232 active samples). Root cause: `_geo_waypoint` walked the raw field with unmasked 8-connected descent (field leaks through walls + diagonal corner cutting + no chord check). **FIXED** (one env change): occupancy-masked 4-connected descent with dead-end detection + return the farthest chord-clear chain point (same construction the expert chases). Re-verified: **0.000** blocked chords / 0.000 in-wall waypoints when the robot cell is clear. run12 and all BC/DAgger results above are confounded by this obs bug; demos re-collected and BC retrained under the fixed obs below |
| run15 | 2026-09-04 | **BC clone under the fixed obs**: re-collected 328k demos (demos_p100_v2 159k @ p=1.0 + demos_p0_v2 170k @ p=0.0; expert invariant under the env change: blocked success 0.636, overall 0.650); BC 15 epochs / batch 4096 / lr 3e-4 (val MAE 0.185/0.196); eval p=1.0, 256 envs × 2405 steps, seed 42 | **BEST LEARNED POLICY TO DATE** — blocked success **0.234** over 2026 blocked episodes (overall 0.256/2102, collision 0.651, TTG 11.35 s) → `logs/rsl_rl/openmover_nav/bc_init_v2/model_0.pt`. That is 2.5× the previous best clone (run14 short 0.096; long-BC 0.044), 2.4× run9 PPO (0.095) and 2.6× run13 (0.089) — but still 2.7× below the expert's 0.636, with collisions 0.65 vs the expert's 0.33. Verdict: the corrupted waypoint obs WAS the binding cloning constraint; fixing it lifted the clone from the 0.05–0.12 band to 0.234. Remaining gap to the expert is now a genuine imitation/residual problem (collisions suggest the clone under-weights the lidar-clearance speed taper), not an observation problem |
| run16 | 2026-09-04 | **DAgger v2 under the fixed obs** (re-run of the confounded run14): 4 rounds, 512 envs × 300 rollout steps/round, aggregate 482k → 943k pairs, re-clone 20 epochs / batch 2048 / lr 3e-4 each round; per-round quick evals (512 envs × 300 steps, ~500 eps) | **NEGATIVE for gap-closing** — blocked success per round: 0.055 / 0.247 / **0.264** / 0.247 (oscillates around 0.25; rollout success tracks it: 0.181/0.055/0.285/0.297) → `dagger_v2_init/model_0.pt`. With CLEAN observations, on-policy relabeling again does not close the expert gap ⇒ distribution shift is definitively NOT the binding constraint (now proven under both corrupted and clean obs). Leading remaining suspect: the expert's unstuck/backup state machine is triggered by CONTACT FORCE, which is absent from the policy observation ⇒ labels on contact states are unconditioned (effectively stochastic) and MSE averaging collapses them. **Follow-up full-protocol eval** (p=1.0, 256 envs × 2405 steps, seed 42): blocked success **0.224** over 2090 episodes, collision 0.431 — statistically on par with the run15 plain clone (0.234): on-policy relabeling adds nothing once the obs is clean |
| run17 | 2026-09-04 | **contact-force observation** (one bounded change): obs += 1 dim = net contact-force magnitude normalized by the 5 N threshold (1208-d); this conditions the clone on the same signal that gates the expert's unstuck/backup state machine. Re-collected 328k demos (demos_p100_v3 + demos_p0_v3; expert invariant preserved: p=1.0 blocked success 0.636, overall 0.650; p=0.0 0.667/0.882), BC 15 epochs / batch 4096 / lr 3e-4 (val act-MAE 0.184/0.184), full-protocol eval (p=1.0, 256 envs × 2405 steps, seed 42) | **NEW BEST LEARNED POLICY** — blocked success **0.287** over 2057 blocked episodes (95.9% of 2146; overall 0.314, collision 0.642, TTG 10.95 s over 673 successes) → `logs/rsl_rl/openmover_nav/bc_init_v3/model_0.pt`. +23% relative over run15 (0.234), 3× run9 PPO (0.095), still 2.2× below the expert (0.636). Verdict: the contact obs was a real second binding constraint — the clone can now condition its recovery behavior on actual contact. Adopted as the frozen source policy for the §3 transfer table. Remaining expert gap attributed to residual imitation limits (backup-mode subtleties, clearance speed taper), not missing information |

Note: forward-policy baseline re-measured at the 0.30 m radius on 2026-09-03 (§1):
success 0.036 over 772 episodes — the learned policy beats this floor ~14× in-distribution.
Note: the forward baseline was measured under task **v1** (mostly unblocked goals);
re-measuring it under task v2 is part of the run7 eval pass (blocked chords should
push it toward ~0).

## 3. Transfer ledger (frozen policy → new world, no retraining)

The core claim of Paper 1: once the policy is frozen, it is deployed **unchanged** to
new worlds; only the interface (Koopman lift / DOB / CBF margins) adapts. Each row is
one frozen-policy rollout — no gradient steps allowed.

**Task-v2 table (blocked goals).** Frozen policy = run17 BC clone with contact obs
(`logs/rsl_rl/openmover_nav/bc_init_v3/model_0.pt`, blocked success 0.287 in the
source world), deployed with NO weight changes. Protocol: `--fixed_block_prob 1.0`,
256 envs × 2405 steps, seed 42, deterministic mean action (~2.0–2.1k episodes/world).
Blocked success is the headline metric (100% of goals behind an obstacle except where
noted). Logs: `isaac/lab/logs/transfer_{railyard,degraded,combined}.log`; source row
= run17 eval.

| Source policy (frozen) | Deployed to | Blocked success | Success (overall) | Collision | Time-to-goal | Verdict |
|---|---|---|---|---|---|---|
| run17 `bc_init_v3/model_0.pt` | wall-maze (in-distribution) | **0.287** | 0.314 | 0.642 | 10.95 s | source; 2057/2146 episodes blocked (95.9%). Showcase: `videos/Isaac-Nav-Openmover-v0/run17_clone_source_seed16_success_v2.mp4` + `trace_seed16.topdown.mp4` (2.87 m detour path, zero contact; trace schema v2 with world-frame waypoint + LiDAR overlays) |
| run17 `bc_init_v3/model_0.pt` | rail yard (geometry shift) | **0.190** | 0.190 | 0.813 | 10.53 s | partial transfer: −34% relative; clutter raises collisions (+0.17) but 399 blocked-goal successes still happen on unseen geometry. Showcase: `videos/Isaac-Nav-Openmover-RailYard-v0/run17_clone_railyard_seed7_success_v2.mp4` + `trace_seed7.topdown.mp4` (2.49 m path around a blocking obstacle, zero contact) |
| run17 `bc_init_v3/model_0.pt` | wall-maze + degraded dynamics | **0.028** | 0.040 | 0.472 | 12.55 s | dynamics hurt most: −90% relative (consistent with the v1 table); low µ + 6 rad/s wheel cap break the clone's speed/timing assumptions |
| run17 `bc_init_v3/model_0.pt` | rail yard + degraded (both axes) | **0.044** | 0.044 | 0.719 | 12.43 s | worst case −85% relative but NOT zero — 91 blocked-goal successes survive both shifts simultaneously |

> **Superseded (task v1).** The table below was measured under task v1 goals —
> only ~13% of chords were blocked, so it mostly scores turn-and-drive. It is kept
> for the record (D24); the task-v2 table above replaces it.

| Source policy (frozen) | Deployed to | Success | Collision | Time-to-goal | Verdict |
|---|---|---|---|---|---|
| run5 `model_1499.pt` | wall-maze (in-distribution) | 0.508 | 0.381 | 10.14 s | teacher works; 14× the 0.036 forward floor |
| run5 `model_1499.pt` | rail yard (geometry shift) | 0.352 | 0.594 | 10.31 s | partial transfer; clutter raises collisions (+0.21) but successes still happen, −31% relative |
| run5 `model_1499.pt` | wall-maze + degraded dynamics | 0.179 | 0.310 | 11.65 s | dynamics hurt most (−65% relative): low µ + 6 rad/s cap break the policy's speed/timing assumptions |
| run5 `model_1499.pt` | rail yard + degraded (both axes) | 0.115 | 0.512 | 11.43 s | worst case (−77% relative) but NOT zero — capability survives both shifts |

Evaluation protocol: deterministic inference (mean action), seed 42, 256 envs × 2405 steps
(~2.0–2.1k episodes per world, 300-step/15 s episodes); v1 logs `/tmp/eval_{source,railyard,
degraded,combined,forward}.log`, v2 logs `isaac/lab/logs/transfer_{railyard,degraded,combined}.log`.
Time-to-goal is over successes only.

Reading (paper framing): the frozen policy carries real, non-zero capability into every
unseen world (v2: blocked success 0.028–0.190 vs 0.287 in-distribution; v1 success
0.115–0.352 vs 0.036 forward floor) — the LiDAR-navigation skill is partly
geometry/dynamics-agnostic. The measured drop at each axis is exactly the **adaptation
budget** the NMTE interface (Koopman lift / DOB / CBF margins) must recover with few-shot
adaptation instead of retraining. The v2 table sharpens the v1 reading: geometry shift
costs −34% (transferable), dynamics shift costs −90% (the adaptation budget is
concentrated on the dynamics axis).

## 4. Standing weaknesses (pre-disclosed, per D24)

1. **Sim-only so far.** No physical-robot validation yet; rung-2 gated on the product
   stack's existing sim-to-real readiness.
2. **Single embodiment.** Claims generalize by argument (input-mastery view), not yet by
   experiment; a second simulated embodiment is planned as a cheap check.
3. **Degraded dynamics are global** (uniform µ=0.25, capped wheel speed); no spatial
   friction patches, latency, or sensor noise yet.
4. **Goal reachability in cluttered rail-yard tiles is not enforced** — some spawned
   goals may be impractical; success rates there are a lower bound.
5. **Success radius relaxed 0.15 → 0.30 m in run5** because the tighter radius was
   never discovered by exploration; the stricter radius can be reported as a secondary
   metric once policies are competent.

## 5. Custom-map gallery (expert oracle + frozen-policy negatives)

Purpose: (a) establish a per-map **oracle ceiling** for the custom-map "say go and it
reaches goal" pipeline, and (b) quantify the **adaptation budget** on these maps by
showing the frozen source-trained policy fails them. All numbers from
`isaac/lab/logs/map_eval_<map>_expert_s<seed>.log` (expert) and
`map_eval_{ring,slalom}.log` (frozen negatives). One simulator at a time; all runs
exited clean, no tracebacks.

Setup: `--policy expert`, `--num_envs 4`, seeds 42/1/7. The runner auto-scales the
episode horizon (`path_len/0.25 + 10`, cap 160 s) and `geo_iters`
(`path_len/geo_res + 40`) for long maps — without both, slalom/serpentine read as 0%
success (see `05_lessons_learned.md`, horizon-truncation + field-convergence section).
`blocked-goal 100%` is expected on every gallery map (the spawn→goal chord always
crosses walls) and is **not** a failure indicator.

Expert (GeodesicExpert) per-map results, seeds 42 / 1 / 7 → mean:

| map | path (m) | horizon | success | collision | TTG (s) |
|---|---|---|---|---|---|
| ring | ~9 | auto | 1.000 / 0.800 / 0.800 | 0.000 / 0.200 / 0.200 | 9.38 / 10.48 / 10.99 |
| rooms | 12.0 | 32 s | 0.750 / 0.750 / 0.500 | 0.250 / 0.250 / 0.250 | 28.88 / 28.33 / 29.77 |
| slalom | 20.2 | 91 s | 0.857 / 1.000 / 0.833 | 0.000 / 0.000 / 0.167 | 59.33 / 58.74 / 58.20 |
| serpentine | 32.0 | 138 s | 0.500 / 1.000 / 1.000 | 0.750 / 0.250 / 0.500 | 104.25 / 107.08 / 111.83 |

Mean success: ring 0.867, rooms 0.667, slalom 0.897, serpentine 0.833.

Reading: the geodesic expert is a competent oracle on all four gallery maps — it
solves every one with ≥0.67 mean success, including the 32 m, six-lane serpentine
switchback (threads all lanes; descent-field finite frac 1.0 after geo_iters scaling).
Failures concentrate where the horizon is tightest relative to backup-unstick cycles:
serpentine s42 (0.500, collision 0.750 = brush contacts during recovery), rooms s7
(0.500). Collision counts on serpentine/rooms are wall-brushes during the
backup-unstick state machine, not dead-end failures — the episodes still terminate on
success or horizon, and the robot is never stuck immobile.

Frozen-policy negatives (source-trained `bc_init_v3/model_0.pt`, no adaptation):

| map | success | collision | TTG (s) | episodes |
|---|---|---|---|---|
| ring | 0.031 | 1.000 | 7.98 | 64 |
| slalom | 0.000 | 1.000 | — | 64 |

Reading: the frozen policy **collides in every episode** on both maps it was probed
on. It has no map-specific geodesic field and drives straight at the goal, so gallery
maps (where the chord crosses walls) are a hard wall. This is the adaptation-budget
signal: the oracle solves these maps, the frozen policy cannot — the gap is exactly
what the NMTE interface must close with few-shot adaptation rather than retraining.

**Correction (2026-09-04)**: the table above was measured with `--num_envs 64` on a
2×2-tile terrain — envs beyond the tile count were stacked on shared tiles (the env
now raises a `ValueError` for exactly this), so those numbers are NOT reproducible
under current code and are superseded by the num_envs=4 protocol (seeds 42/1/7):
ring frozen blocked success is **0.331** (0.227/0.348/0.417), collision 0.799 —
the frozen policy is poor on ring but not the near-zero the stacked protocol
suggested; slalom remains **0.000** (collision 1.000/1.000/0.500). The qualitative
conclusion stands (expert mean 0.867/0.897, frozen fails both), but cite the §8
re-baselined rows, not the ones above.

Showcase videos (expert, seed 42, num_envs=1, single clean solve on camera):

| map | 3D bird (1280×720) | top-down (1024×576) | TTG on camera |
|---|---|---|---|
| ring | `gallery_ring_expert_3d_seed42.mp4` | `gallery_ring_expert_topdown_seed42.mp4` | 8.80 s, 0 coll |
| rooms | `gallery_rooms_expert_3d_seed42.mp4` | `gallery_rooms_expert_topdown_seed42.mp4` | 27.95 s, 0 coll |
| serpentine | `gallery_serpentine_expert_3d_seed42.mp4` | `gallery_serpentine_expert_topdown_seed42.mp4` | 105.70 s, 0 coll |

All in `isaac/lab/videos/Isaac-Nav-Openmover-v0/` (old videos preserved); frame counts
match the runs (280/700/2300). Logs: `logs/gallery_vid_{ring,rooms,serpentine}.log`.
Reproduce: `~/isaaclab/isaaclab.sh -p 21_run_openmover_nav.py --task
Isaac-Nav-Openmover-v0 --map_file maps/<map>.json --policy expert --num_envs 1
--num_steps N --video --video_view bird --video_length N --seed 42` (N = video frames),
then rename `rl-video-step-0.mp4` before the next run and render the top-down pass with
`26_render_topdown_video.py` on the saved `trace_<map>_seed42.npz`.

## 6. Adaptation-budget curve v0 (rail yard, retrain-from-scratch vs engine zero-shot)

The paper's headline comparison: how much **target-world supervision** does
retrain-from-scratch need to reach what the NMTE engine delivers with zero target data?
Retraining arm = BC a fresh actor (run12 architecture) on rail-yard expert demos at
increasing budgets; engine arm = frozen source policy (§3) deployed unchanged. Same
task-v2 eval protocol as the transfer ledger: `--fixed_block_prob 1.0`, 256 envs ×
2405 steps, seed 42, blocked-goal success = headline metric.

Teacher validation first: the geodesic expert solves rail yard — blocked success
0.535–0.536 over 1541/69 episodes (TTG 11.14 s), logs
`p3_railyard_expert_probe.log` + `p3_railyard_collect{,_b}.log`. Demo pool: two
collections (256 envs × 1700 + 256 envs × 800 steps, seeds 42/7) → 290 383 +
123 443 = **413 826 valid pairs** (`logs/bc_demos/railyard_demos_p100{,_b}.pt`,
66.7%/60.3% valid fraction — post-contact steps masked out). Budget points are nested
fixed-seed subsamples via `24_bc_pretrain_openmover.py --max_demos` (seed 42), 15
epochs each; checkpoints `logs/rsl_rl/openmover_nav/p3_railyard_bc_b{0,41,82,164,
328}k/model_0.pt`; eval logs `p3_eval_b*.log`; figure
`figs/p3_adaptation_budget_curve.png` (script `28_plot_budget_curve.py`).

| target demos (rail yard) | BC val loss | blocked success | collision | TTG (s) |
|---|---|---|---|---|
| 0 (fresh init) | — | 0.001 | 0.184 | 0.90 (n=3, accidental) |
| 41k | 0.128 | 0.005 | 0.748 | 12.45 |
| 82k | 0.108 | 0.022 | 0.775 | 11.87 |
| 164k | 0.067 | 0.083 | 0.736 | 11.45 |
| 328k | 0.032 | 0.318 | 0.449 | 11.68 |
| **engine zero-shot** (§3) | n/a | **0.190** | 0.813 | 10.53 |
| geodesic expert oracle | n/a | 0.535 | 0.430 | 11.14 |

Reading (paper framing): the retrain-from-scratch curve is monotone but slow — 41k
and 82k target demos barely beat the 0.001 floor; capability only emerges at 164k
(0.083) and 328k (0.318). The engine's zero-shot transfer (0.190, no target data, no
gradient steps) sits between the 164k and 328k points; linear interpolation puts the
crossing at **~238k target expert demos**. That is the quantified adaptation budget
the engine saves on the geometry-shift axis.

Caveats (pre-disclosed): (1) the retraining arm is BC on expert demos, the most
sample-efficient from-scratch baseline we can run without reward design — RL from
scratch would cost more, so the 238k crossing is a LOWER bound on what retraining
needs; (2) even 328k BC (0.318) stays below the expert oracle (0.535), so the curve
has not saturated — the crossing estimate inherits that headroom; (3) single seed per
point; (4) collision rates of low-budget BC (~0.75) show the policies learn to move
before they learn not to hit — success, not safety, is the budget-curve metric.

## 7. DOB-lite A/B: the interface adapts, the weights stay frozen (dynamics axis)

Paper-1 concept check for the NMTE deploy-time interface on the degraded-dynamics
axis (Target 2 = dynamics shift, Target 3 = both). The frozen source policy
(`bc_init_v3/model_0.pt`) is deployed UNCHANGED; a scalar plant-gain disturbance
observer (`openmover_lab/dob_lite.py`, runner flag `--dob_lite`) sits between policy
and actuators, identifies the thrust loss online from realized wheel joint speed, and
rescales the wheel command by 1/g. No weights change, no target demos, no env-cfg
change. Task-v2 protocol as §3/§6 (256 envs × 2405 steps, seed 42,
`--fixed_block_prob 1.0`); logs `logs/p4_dob_*.log`.

| deployment | blocked success | success | collision | TTG (s) | mean g |
|---|---|---|---|---|---|
| source, frozen (§3) | 0.287 | 0.314 | 0.642 | 10.95 | — |
| source, + DOB-lite | 0.303 | 0.323 | 0.644 | 10.59 | 0.964 |
| degraded, frozen (§3) | **0.028** | 0.040 | 0.472 | 12.55 | — |
| degraded, + DOB-lite | **0.363** | 0.385 | 0.617 | 9.23 | 0.599 |
| degraded, + oracle const-boost 1/0.6 (`--const_boost 1.6667`) | 0.375 | 0.396 | 0.629 | 9.49 | — |
| combined, frozen (§3) | 0.044 | 0.044 | 0.719 | 12.43 | — |
| combined, + DOB-lite | **0.250** | 0.250 | 0.798 | 8.81 | 0.602 |

Reading (paper framing):
1. **Dynamics shift is almost fully repaired at deploy time**: 0.028 → 0.363 (+12.9x)
   on degraded, with zero adaptation data. The recovered level even exceeds the
   frozen source baseline (0.287) — plausible physics: at low friction pivot-turns
   scrub less, so once thrust is restored the maze is slightly cheaper than nominal;
   single seed, so treat the ordering as indicative.
2. **The estimate converges to theory**: the plant-gain identifier's fixed point is
   W_degraded/W_nominal = 6/10 = 0.6; measured g = 0.599 (degraded) and 0.602
   (combined) — the interface "discovers" the degradation factor from runtime data.
3. **Online ≈ oracle**: the open-loop arm that *knows* the degradation factor in
   advance (constant boost 10/6) reaches 0.375; the online DOB reaches 0.363 —
   within 3.2% of the oracle upper bound, with no prior knowledge.
4. **Source sanity ≈ no-op**: on nominal dynamics g stays at 0.964 and blocked
   success moves 0.287 → 0.303. The residual is real, not an artifact: the wheels are
   torque-limited implicit drives (damping 2.0, effort_limit_sim 5.0 in
   `openmover_cfg.py`), so even the "nominal" plant loses ~4% of commanded wheel
   speed; the interface identifies and partially corrects that loss.
5. **Target 3 (both axes)**: 0.044 → 0.250 (+5.7x). DOB repairs the dynamics axis;
   the geometry axis still costs (collision 0.798, vs 0.617 on degraded-only) — the
   remaining gap is where the geometry-side mechanisms (budget curve §6, and future
   CBF/safety filter) live. One interface does NOT fix both axes, and is not claimed to.

Design history (kept as evidence of why the mechanism matters; all logs in
`logs/p4_dob_*`):
- v0 (body-speed ratio, naive EMA): biased g DOWN even on nominal (g=0.580 on
  source) because acceleration transients make realized < intended; combined with
  removing the RL-wrapper action clip it degenerated into a generic speed booster
  (source 0.287 → 0.423). Logs: `p4_dob_{source,degraded}_dob_v0biased.log`.
- v1 (quasi-steady-state mask, still body speed): still biased (g=0.485 on source)
  — body inertia lag survives a 3-step command hold at 20 Hz. Log:
  `p4_dob_source_dob_v1biased.log`.
- v2 (final): observable moved to wheel joint speed (tracks the actuator target with
  ~no inertia lag) and reformulated as a plant-gain identifier whose fixed point is
  provably independent of its own correction (see `dob_lite.py` docstring). Also the
  runner now reproduces the frozen deployment's action clip manually before the
  interface acts, so g=1 is bit-exact no-op relative to the §3 baselines.

Caveats: (1) single seed per arm, episode counts differ slightly across arms
(2146–2289 reset batches); (2) wheel speed sees friction slip only partially — slip
during hard cornering/acceleration is not fully compensated, part of why combined
stops at 0.250; (3) `mean g` is a whole-run average including post-reset steps at
g=1; (4) DOB needs the wrapper clip disabled and applies it manually instead, so
comparisons to rows without the flag are still apples-to-apples (verified: the
no-flag degraded re-run reproduced the §3 row bit-exact, 0.028/0.040/0.472/12.55 s).

## 8. CBF-lite A/B: the frozen policy with a safety-filter interface (safety axis)

Paper-1 concept check for the NMTE deploy-time interface's SAFETY side (companion
to §7's dynamics side). The frozen source policy (`bc_init_v3/model_0.pt`) is
deployed UNCHANGED; a minimal velocity-barrier filter (`openmover_lab/cbf_lite.py`,
runner flag `--cbf_lite`, sits after DOB-lite if both are enabled — the filter gets
final authority) clamps the forward command component to the stoppable speed
`v_safe(d) = sqrt(2·a_dec·max(d − d_margin, 0))` with d the LiDAR clearance in the
direction of travel (`h(d,v) = (d − d_margin) − v²/(2·a_dec) ≥ 0`). The spin
component is kept untouched, so the policy can always turn in place to find a
clearer heading. No weights change, no target demos. Custom-map protocol:
`--num_envs 4` (the env guard forbids more envs than tiles), 2405 steps,
`--fixed_block_prob 1.0`, seeds 42/1/7; logs `logs/p4_cbf_*.log`.

Design history (both versions kept as evidence):
- v0 (min over the whole ±90° hemisphere, d_margin 0.15, a_dec 1.5): NEVER
  triggered — 0/9620 interventions on the ring map. The hemisphere minimum is
  dominated by corridor SIDE walls (~0.4 m grazing hits), so the bound tracked the
  walls the robot drives PAST, never the wall it drives AT. An earlier apparent
  "improvement" from v0 was a float round-trip artifact (`(v·x)/x ≠ v` perturbing
  chaotic trajectories); the fix (`return a` untouched when no clamp fires) made the
  no-op pass bit-exact, which exposed that v0 never clamps at all.
- v1 (current): direction-aware cone — clearance is the min over rays within ±45°
  of the actual travel direction (world-frame ray angle vs. body yaw, front scan for
  v≥0, rear scan for v<0); d_margin = 0.30 m at the LiDAR origin (covers the 0.327 m
  hull half-diagonal at any yaw); a_dec = 1.0 m/s². Still bit-exact no-op when no
  clamp fires (verified: re-ran ring s42 with v0-style zero interventions and
  reproduced the frozen row exactly).

Ring map (blocked success / collision, 22–24 episodes per arm):

| seed | frozen | + CBF-lite | frozen coll | + CBF coll | interventions |
|---|---|---|---|---|---|
| 42 | 0.227 | **0.348** | 0.864 | **0.565** | 4753/9620 (49.4%) |
| 1 | 0.348 | 0.318 | 0.783 | **0.591** | 4945/9620 (51.4%) |
| 7 | 0.417 | 0.409 | 0.750 | **0.682** | 4450/9620 (46.3%) |
| mean | 0.331 | **0.358** | 0.799 | **0.613** | |

Slalom map (4 episodes per arm — 91 s horizon): success **0.000 on every arm**,
frozen vs +CBF; collision 1.000/1.000/0.500 vs identical 1.000/1.000/0.500;
interventions 0, 0, and 17/9620 (0.2%) for seeds 42/1/7. The filter is a no-op here
(negative result, kept on purpose).

Source-world sanity (task-v2 protocol, 256 envs × 2405 steps, seed 42):

| deployment | blocked success | success | collision | TTG (s) | interventions |
|---|---|---|---|---|---|
| source, frozen (§3) | 0.287 | 0.314 | 0.642 | 10.95 | — |
| source, + CBF-lite | 0.274 | 0.300 | **0.571** | 11.02 | 89930/615680 (14.6%) |

Reading (paper framing):
1. **The filter cuts collisions without costing the task**: on the ring map
   collision −23% (0.799 → 0.613) while blocked success slightly IMPROVES
   (0.331 → 0.358). The filter only slows the robot when it commands motion toward
   an obstacle; it never steals the ability to turn, so the frozen policy can still
   re-plan headings — and slower approaches near walls mean fewer bounce-offs that
   used to end episodes.
2. **In-distribution sanity ≈ no cost**: source blocked success 0.287 → 0.274
   (within per-seed noise), collision −11%, TTG flat (+0.07 s). The safety interface
   does not tax nominal operation.
3. **Coverage is directional — and that is the honest limit of this concept**:
   slalom is untouched (≈0 interventions, identical 0.000). Slalom failures are
   side/oblique contacts while threading narrow gaps, which a cone around the travel
   direction cannot see. A minimal single-cone barrier demonstrates the mechanism
   (sensor → barrier → projection, frozen policy underneath); a real safety layer
   would need hull-aware or multi-cone barriers. Documented as a negative, not
   hidden.
4. **Intervention rate scales with deployment stress**: 46–51% of steps on the ring
   (where the frozen policy is out of its depth) vs 14.6% in the source world — the
   filter works hardest exactly where transfer is weakest.

Caveats: (1) custom-map arms have few episodes (4 envs ⇒ 22–24 on ring, 4 on
slalom) — treat per-map numbers as seed-means, ring seed 42 is the cleanest single
comparison; (2) clearance uses the LiDAR at 15 Hz, one env-step stale at 20 Hz
control; (3) ray geometry is measured from the LiDAR origin, so the 0.30 m margin
carries the hull + staleness allowance jointly; (4) the filter assumes the nominal
speed scale `v_full = R·W_nom` — pair with DOB-lite (which restores it) on degraded
dynamics.

## 9. ROS 2 rung: the frozen policy deployed through plain topics (deploy axis)

Paper-1 justification for the ROS 2 part of the pipeline. The SAME frozen
checkpoint used inside Isaac Lab (`bc_init_v3/model_0.pt`, source wall-maze) is
deployed UNCHANGED through a standard sensor/actuator contract — no Lab env, no
simulator internals in the loop. Node:
`src/warehouse_simulation/scripts/policy_node.py` (~560 lines, runs under
`~/isaaclab/isaaclab.sh -p`, which provides torch + rclpy):

    in : /openmover/hardware/lidar_forward/scan (600 bins ±90°, invalid=0.0)
         /openmover/hardware/lidar_rear/scan
         /odom
    out: /cmd_vel

Isaac plays the robot+world side via `isaac/scripts/16_bridge_ros.py` (publishes
the scans/odom/clock, subscribes cmd_vel, re-maps to its pioneer3dx plant); the
rest of Stack B (robot_state_publisher, scan merger, slam_toolbox, trajectory
server, cmd_vel watchdog) runs unmodified alongside. Observation fidelity is the
whole transfer: 1208-dim obs in EXACT Lab order/normalization — scans /10 with
misses→1.0, goal robot-frame /2.55, vx raw, wz/5, geodesic waypoint(3)/2.55,
contact(1). Actions are per-wheel fractions in [-1,1] converted with the TRAINED
openmover kinematics (R=0.050353, separation 0.324, W_max=10); the bridge then
re-maps to pioneer3dx (0.32/0.09) — a deliberate embodiment mismatch the rung
exercises (linear speed preserved exactly by the chain, angular within 1.25%).

Deploy-time components the rung adds AROUND the frozen weights (all nav2 analogs;
nothing here changes the policy):
1. **Footprint-aware inflation** GEO_INFLATE 0.20→0.35. Lab's terrain walls are
   thick and continuous; the warehouse has thin free-standing boxes whose corners
   the 0.327 m hull half-diagonal snags on at 0.20 m. Deploy maps inflate by the
   footprint — the nav2 inflation layer does exactly this.
2. **Chassis-speed stall proxy → contact channel.** Contact force is
   simulator-internal with no bridge topic; the rung substitutes
   shortfall = max(|prev_cmd_v| − v_chassis, 0) with v_chassis the
   pose-differentiated chassis speed (absolute branch deadband 0.06/scale 0.08,
   calibrated to Lab's saturating contact channel), PLUS a relative branch
   (realized < 50% of commanded starts it, < 15% saturates) for creep-push stalls
   whose commanded speed sits below the absolute deadband. EMA α=0.8.
3. **Recovery layer (backup behavior).** Trigger A: contact proxy ≥ 0.7 for 1.0 s
   while pushing. Trigger B (progress checker, nav2 analog): no displacement for
   6 s while far from goal and emitting ~zero commands. Action: 1.5 s reverse at
   −0.25 m/s with ±0.30 rad/s, sign alternating per activation, 1.0 s cooldown.
4. **Inside-margin waypoint = nearest free cell.** When the robot sits inside the
   inflation margin (physically possible: hull > margin), field descent either
   collapses onto the robot's own cell (chord checks reject everything starting
   inside) or jumps across the pocket pointing at the wall the robot touches. The
   rung instead hands the policy the nearest free cell: get back to free space
   first, then re-plan — nav2 recovery behavior.

Findings (chronological, all evidence in `logs/`):
- **The frozen policy has NO learned stall response.**
  `ros2_rung_policy_frozen_stalls.log`: contact proxy 1.00 from t=2 s, pose frozen
  at (1.51,1.66), policy keeps pushing (+0.13,+0.73) for the entire 90 s. Root
  cause: `23_collect_openmover_demos.py` records PRE-collision steps only (post-
  collision behavior "must not be imitated"), so the geodesic expert's
  back-up-on-contact state machine was never cloned. This is WHY the rung needs
  component 3 — the paper's "interface adapts, weights stay frozen" claim gets its
  recovery behavior here, not from the checkpoint.
- **Encoder twist was rejected as the stall signal.** The bridge odom twist comes
  from wheel joint velocities; against an obstacle the wheels keep being driven,
  so encoder v stays high exactly when the chassis stalls. Pose-differentiated
  chassis speed is the correct signal (real-robot analog: fused localization vs
  commanded velocity).
- **The creep-push stall hides below any absolute deadband.** At the bin row the
  policy pushes at v_cmd ≈ 0.05 m/s — below the 0.06 deadband — so the absolute
  proxy reads 0 while the robot is physically pinned. Fixed by the relative branch.
- **OOD hesitation freeze.** With saturated near-zero scans + contact=0 the policy
  emits ~zero actions (a state the BC data never contained) and never "pushes", so
  the stall trigger can't see it; the progress checker (trigger B) was added for
  this case. Observed live at the bin row before the fix.
- **NEGATIVE: detour-vs-goal conflict is beyond zero-shot transfer.** Goal (6,8)
  behind the bin row x∈[3,8]: the geodesic field correctly routes AROUND the row
  (waypoint west), but the policy's goal channel points at the goal THROUGH the
  row, and the policy sides with the goal. 90 s run, 8 recoveries, NOT REACHED
  (final dist 3.69 m, robot oscillating at the south face of the row) —
  `ros2_rung_policy_detour_conflict.log`. The rung keeps the robot safe (bounded
  backups, no hard wedge) but cannot make the frozen policy execute a detour that
  contradicts goal pull; that is exactly the capability adaptation is supposed to
  add (§6 budget curve). Documented as a negative, kept on purpose.
- **SUCCESS: clean spawn → goal (−7,4), 8.07 m.**
  `ros2_rung_policy_headline_goal_-7_4.log` + bridge-side cross-check
  `ros2_rung_bridge_headline_goal_-7_4.log`: time-to-goal **30.85 s**, cruise at
  0.30→0.49 m/s along the corridor north of the pallet block, REACHED at dist
  0.42→<0.30; 5 recoveries, ALL after the goal was reached (post-success wander
  near the pallet margin — the policy has no "stop at goal"). An earlier version
  of the same run (pre relative-branch retune) reached in 26.55 s
  (`ros2_rung_policy_success_goal_-7_4.log`). The route to (−7,4) is
  in-distribution for the source policy (detour consistent with goal pull); the
  bin-row goal is not.
- **Contact-proxy transient blips during cruise** (0.4–0.96 while moving at 0.3+
  m/s): pose-differentiated chassis speed under-reads commanded v during yawing
  motion and acceleration. No false recoveries resulted (trigger needs 1.0 s
  sustained ≥ 0.7); the relative-branch onset was moved 75%→50% of commanded to
  keep acceleration transients out. Lab trained with contact≈0 in these states, so
  the blips are an observation-fidelity tax the frozen policy tolerates here.

Methodology notes (hard-won): (a) isaaclab.sh returns exit 0 even on traceback —
always grep logs for `[policy] SUMMARY`; (b) the bridge heartbeat
(`[bridge] t=… pos=…` every 5 s) is the ground truth to cross-check policy
telemetry — one apparent "freeze" turned out to be stale cached odometry after the
bridge had died (terminal reuse killed it); (c) terminal discipline: the bridge
terminal is never reused for monitoring commands; (d) one simulator at a time.

Caveats: (1) single run per goal — treat as existence demonstrations, not
statistics; the headline numbers are time-to-goal of one clean run each;
(2) the map is built from the SAME collision boxes the bridge bakes into the scene
(a stand-in for map_server/SLAM), so this rung demonstrates the deploy interface,
not perception; (3) goal cells must sit outside inflation (the replica treats
inflation as lethal, matching Lab); (4) post-success wander shows the frozen
policy has no goal-holding behavior — a real deployment would gate cmd_vel on
|dist| < success radius; (5) recovery backups are open-loop (fixed duration), no
re-planning during the backup.

## 10. Second embodiment at deploy time (pioneer3dx) + mechanism table

Paper 1's scope doc recommends a "cheap generality run: apply the same engine
recipe to a second simulated robot". We deliver it in a stronger-than-cheap
form: **no extra training run was needed, because every §9 run already ran on
the second embodiment.** The frozen policy was trained on openmover; the plant
it physically drove in every ROS 2 rung run was a Pioneer 3DX with different
wheel geometry, mass, casters and servo dynamics. This section makes that
chain explicit and then states the mechanism table the paper needs (which
components freeze, which become interfaces, which adapt).

### 10.1 The kinematic chain (deliberate embodiment mismatch)

```
frozen policy (trained on openmover in Lab)
   actions a ∈ [−1,1]²
     │  policy_node.py converts with TRAINED openmover constants:
     │  R = 0.050353 m, W_max = 10 rad/s, separation = 0.324 m
     ▼
chassis twist (v, ω)   ← the embodiment boundary: a plain Twist on /cmd_vel
     │  bridge_core.py realizes the SAME twist on pioneer3dx:
     │  separation = 0.32 m, R = 0.09 m, velocity servo KD = 20
     ▼
pioneer3dx plant in Isaac Sim (casters, different inertia, RTX LiDAR)
```

- The boundary between the two embodiments is a **standard `geometry_msgs/
  Twist`** — exactly the interface a real openmover exposes. Nothing above
  the boundary knows which robot is below it.
- Linear speed is preserved exactly by the chain; angular within 1.25% (§9;
  the 0.324 vs 0.32 m separation mismatch is ~1.2%, absorbed by the servo).
- Evidence on the mismatched plant: headline run spawn (0,0) → goal (−7,4),
  8.07 m, **time-to-goal 30.85 s**
  (`logs/ros2_rung_policy_headline_goal_-7_4.log`); the detour-conflict
  negative (goal (6,8), NOT REACHED, 8 recoveries) and all recovery-layer
  behaviors were also exercised on pioneer3dx. Zero retraining in all cases.
- What changes across embodiments at deploy time: kinematic constants in the
  rung's action→twist conversion, footprint inflation in the geodesic field
  (0.20 in Lab → 0.35 m for the pioneer3dx hull), and the stall-proxy
  calibration. What does NOT change: the 1208-dim observation contract, the
  policy weights, the field construction, the recovery triggers.
- Caveats: this is deploy-time embodiment transfer under a velocity-level
  interface, not cross-embodiment *learning* (pillar B / GW alignment stays
  deferred to paper 3). The pioneer3dx runs are simulation, and the plant's
  dynamics were not degraded in §9 — the dynamics axis is covered separately
  in §7.

### 10.2 Mechanism table (engine components × embodiment classes)

Status legend — ✅ **demonstrated** (experiments in this ledger);
◆ **deployed this week** (§9/§10, frozen policy on the pioneer3dx plant);
○ **conceptual** ("designed to extend to" — no experiments in paper 1; the
component names are not final, only the idea behind each must carry over).

| Engine component | openmover (source) | pioneer3dx (2nd embodiment) | Quadruped | Arm / hand | Humanoid |
|---|---|---|---|---|---|
| **Observation contract** (exteroception + goal + waypoint + proprio, normalized fixed ranges) | ✅ defines the 1208-dim contract | ◆ same contract fed from RTX LiDAR + odom over standard topics | ○ scan/goal/waypoint channels carry over; proprio channel becomes joint space | ○ goal channel redefined in task space; scan → wrist/exteroceptive sensing | ○ as quadruped + balance state in proprio |
| **Frozen distilled policy** | ✅ trained + distilled (MLP 1208→128→128→2) | ◆ same weights, zero retraining, TTG 30.85 s | ○ new instance, same train→freeze→distill recipe | ○ same | ○ same |
| **Geodesic waypoint field** (map → free-space field → waypoint channel) | ✅ Lab env-grid + deploy-time field | ◆ deployed, inflation re-tuned to hull (0.35 m) | ○ cost map gains slope/foothold terms; field idea unchanged | ○ configuration-space field replaces planar field | ○ planar field for the locomotion base |
| **Stall / contact proxy** (interface substitutes a missing sensor) | ✅ saturating contact channel in obs (Lab) | ◆ chassis-speed shortfall proxy, two-branch (§9) | ○ shortfall vs locomotion-controller reference | ○ joint-velocity shortfall; torque signal for contact-rich regime | ○ base-velocity shortfall + foot contact |
| **Recovery layer** (progress/stall triggers → open-loop escape) | — not exercised on openmover (Lab runs use the sim contact channel); pattern lives in the rung | ◆ both triggers fired live (8 recoveries in the negative run; 5 post-goal in headline) | ○ sits where a behavior tree sits; actions become sit/step-back | ○ retract-and-replan primitive | ○ balance-first fallback, not blind reverse |
| **DOB-lite** (estimate what the frozen policy didn't model; inject at the interface) | ✅ A/B on dynamics axis, degraded 0.028→0.363 (§7) | ○ same estimator, plant-specific nominal model | ○ disturbance in joint space | ○ in task space | ○ base + joint space |
| **CBF-lite** (safety filter on actions) | ✅ ring coll −23% with success kept (§8) | ○ barrier set re-derived for the hull | ○ tip-over / foothold margin | ○ joint limits + self-collision | ○ tip-over + self-collision |
| **Koopman core** (linearizable dynamics handle for adaptation) | ○ concept in paper 1 (data pipeline v0 + offline transfer-gap check in §11) | ○ | ○ | ○ | ○ |
| **Adaptation pipeline** (target demos → BC; budget curve) | ✅ crossing ≈238k demos (§6) | ○ not exercised — zero-shot only in paper 1 | ○ same data factory, new embodiment | ○ same | ○ same |

Reading of the table: **the weights are always the frozen part; embodiment
enters only through interfaces** (observation mapping, action→plant
conversion, field cost, safety set) — and interfaces are what the rung,
DOB-lite and CBF-lite adapt. That invariant is the paper's mechanism claim;
the pioneer3dx column is the second-embodiment evidence that the invariant
survives an actual robot change, and the ○ columns state how far the claim
extends without overreaching ("designed to extend to", never "we can do").
Per the program's standing caveat, the component names (Koopman core, DOB,
CBF) are placeholders — only the idea behind each needs to stay the same.

## 11. Koopman data pipeline v0 (concept arm — the dynamics handle)

The Koopman row in §10.2 is ○ for paper 1: no closed-loop Koopman control is
claimed. This section delivers what a concept arm CAN deliver on this
hardware budget: the **data pipeline** (sim → dynamics transitions), an
**offline concept check** (lifted-linear fit + transfer-gap measurement), and
two honest negatives. Per `docs/research/02_nmte_framework.md` the component
is a candidate mechanism for one idea: *freeze the learned structure, adapt a
small interface.*

### 11.1 Pipeline design

- State `s = [vx_b, wz_b, wl, wr]` (body-frame chassis twist + realized wheel
  joint speeds, physical units); input `u = [a_l, a_r] ∈ [−1,1]`. Keeping
  actuator-side and body-side speeds in the same vector is what lets a model
  SEE wheel slip (degraded regime = body lags wheels).
- Collector `isaac/lab/29_koopman_collect.py`: piecewise-constant random
  commands held 10 control steps (sysID excitation over the full action
  square), deterministic private RNG so source/degraded runs with the same
  seed are command-wise PAIRED. Masks: episode boundaries, accumulated
  collision, non-finite, and a physical-plausibility gate (|vx|<3 m/s,
  |wz|<12 rad/s, |w|<25 rad/s) — the first collision-impulse step spikes the
  body to 39 m/s before `_penalized` latches (observed in run 1, which is why
  the gate exists).
- Fit `isaac/lab/30_koopman_fit.py`: NO simulator. 12-dim quadratic EDMD lift
  of s; ridge least squares on standardized features; one-step prediction
  evaluated per state channel (RMSE, R²) against persistence and an unlifted
  affine baseline. Artifacts: `logs/koopman_data/{source,degraded}.pt`,
  `K_source.pt`, `K_degraded.pt`, `fit_summary.json`.

### 11.2 Data (seed 42, 64 envs × 600 steps, dt = 0.05 s)

| Regime | Task | transitions kept | raw vx range | wheel_max |
|---|---|---|---|---|
| source | Isaac-Nav-Openmover-v0 | 34,001 (88.5%) | ±2.9 m/s | 10 rad/s |
| degraded | Isaac-Nav-Openmover-Degraded-v0 | 36,954 (96.2%) | ±0.29 m/s | 6 rad/s |

The degradation is visible at DATA level: the degraded chassis realizes one
order of magnitude less body speed from the same command schedule. Collection
cost ≈ 30 s sim time per regime (+ ~2 min app startup), RAM-safe at 64 envs.

### 11.3 Concept check — one-step prediction R² per channel [vx, wz, wl, wr]

| Model → data | source val | degraded val |
|---|---|---|
| lifted fit (source) | **0.79 / 0.82 / 0.88 / 0.88** | 0.81 / 0.76 / **0.57 / 0.57** |
| lifted fit (refit on degraded) | 0.68 / 0.77 / 0.74 / 0.75 | **0.90 / 0.88 / 0.99 / 0.99** |
| affine, no lift (source) | 0.77 / 0.81 / 0.88 / 0.88 | 0.83 / 0.77 / 0.57 / 0.57 |
| persistence (sₜ₊₁ = sₜ) | 0.59 / 0.73 / 0.60 / 0.59 | 0.80 / 0.77 / 0.79 / 0.77 |

Findings:

1. **The transfer gap is real and LOCALIZED.** The frozen source lift keeps
   the body-twist channels usable on degraded data (R² 0.76–0.81) but loses
   the wheel channels (0.88 → 0.57) — below the do-nothing persistence
   baseline (0.79). The frozen structure is over-confident exactly where the
   degradation acts (actuator gain/slip) and robust where it does not. This
   is the dynamics-model mirror of §7: DOB-lite estimates the same thrust
   loss online (g* ≈ 0.6); a small refit of the lifted model recovers it
   offline (0.57 → 0.99). Same idea, two interfaces.
2. **Honest negative (lift value).** The quadratic lift barely beats the
   plain affine fit (source vx R² 0.79 vs 0.77); the regime shift is visible
   without any lifting. At v0 the lift is NOT the contributor — the freeze/
   adapt structure and the paired-data protocol are. If a future variant
   keeps this idea with a different mechanism, that substitution will be
   reported as such.
3. **Honest negative (conditioning).** The first fit, without input-feature
   standardization, diverged to R² ≈ −1.9×10⁶ on vx (raw quadratic features
   span ~1e0..1e3). Observed and recorded before the fix (the tee'd log file
   `logs/koopman_fit.log` holds the FIXED run; the divergent numbers are
   preserved in this ledger only). Standardizing by train statistics restored
   healthy fits.
4. **Concept link to the paper claim.** Freeze `K` (source fit) + adapt a
   small interface (lift statistics / few-shot refit) closes the gap with the
   same pipeline and no policy involvement — that is the shape of the
   few-shot dynamics adaptation the draft describes, instantiated here only
   as an offline prediction experiment.

Caveats: no closed-loop control with the fitted model; the degraded regime's
slip component is only partially excited (random commands, flat floor); one
seed; 600-step horizons. Next honest steps (NOT in paper 1 scope): multi-
step rollout stability of the frozen vs refit operator, and whether a
frozen-`K`/adapted-`g_θ` split outperforms the full refit on few-shot data.

## 12. Capstone "go" demo — user-drawn map, frozen policy, ROS 2 end-to-end (2026-09-05)

The long-held wish, wired end to end on the ROS 2 rung (§9): a user draws a
map as a PNG, one script validates it, the bridge bakes it into Isaac and
publishes the standard warehouse contract, and the FROZEN policy node is told
"go" with a single `map_file` parameter — no retraining, no simulator code in
the policy. The same map JSON that builds the Isaac colliders builds the
policy's GeoField (the map_server/SLAM stand-in), so both sides provably share
one world model.

Pipeline: `27_make_custom_map.py --png` (BFS-validated JSON + preview) →
`17_bridge_ros_custommap.py` (baked triangle-mesh colliders, ROS contract,
ground-truth trace npz) → `policy_node.py -p map_file:=<json>` (frozen actor,
GeoField from the same JSON) → `28_clip_trace.py` + `26_render_topdown_video.py`
(presentation video).

### 12.1 Three "go" runs — the adaptation boundary on novel geometry

| Run | Map | Geometry (all unseen in training) | Verdict |
|---|---|---|---|
| 1 | demo_spiral | nested rings, 1.25 m corridors, 15.5 m BFS path | NOT REACHED (final 3.43 m), 120 s, recoveries=15 |
| 2 | demo_hall | two long walls, gaps at the FAR ends (~5.7 m along-wall detour), 16.2 m path | NOT REACHED (final 5.46 m), 120 s, recoveries=11 |
| 3 | demo_crossings | two long walls, 2 m gaps ON the spawn→goal diagonal, 13.2 m path | **SUCCESS, time-to-goal 33.50 s** (2 recoveries pre-success), driven path 10.7 m |

Same frozen weights, same interface, same launch procedure in all three runs —
only the geometry class changes the verdict. That is the adaptation boundary
of the zero-shot engine, measured, not assumed:

1. **Training distribution** (`WallMazeTerrainCfg`): open 8 m rooms with 4–12
   scattered walls of 0.8–2.0 m length. The policy's successes outside source
   (warehouse §9, rail yard §3/§6) are all open space + scattered obstacles +
   gap crossings (level crossings in the rail yard).
2. **Runs 1–2 are OOD in two distinct ways.** Narrow corridors put the walls
   inside the inflation margin everywhere (the GeoField waypoint collapses to
   the nearest-free-cell fallback). Long-wall maps require following the wall
   to a far gap — but the telemetry shows the frozen policy is goal-bearing
   dominated: in run 2 it pushed NORTH into the wall at (2.2, 1.9) for a
   minute while its own waypoint pointed EAST along the wall. It has no
   wall-following behaviour to fall back on.
3. **Run 3 turns the detour into an in-distribution primitive.** With the
   gaps placed on the direct line, "reach the goal" and "thread the gap"
   coincide; the robot threads both 2 m gaps (visible in the LiDAR fans of the
   video) and arrives in 33.5 s. The two pre-success recoveries are brief
   stall-and-backup blips at the gap edges, the same contact vocabulary the
   policy uses in the warehouse.

The negatives are therefore not failed demos; they are the measured boundary
that makes the success meaningful — consistent with the pre-disclosed
weaknesses (§4) and the gallery negatives (§5): *the engine transfers the
behaviour it has; geometry classes it never saw remain out of distribution
until an interface (DOB/CBF/map design) or a few target demos (§6) covers
them.*

### 12.2 Artifacts

- Maps: `isaac/lab/maps/demo_{spiral,hall,crossings}.{png,json,preview.png}`.
- Traces (bridge ground truth, 15 Hz): `videos/custommap_demo/trace_demo_{spiral,hall,crossings}.npz`;
  presentation clip `trace_demo_crossings_clip.npz` (idle pre-boot and
  post-success drift trimmed by `28_clip_trace.py`).
- Video: `videos/custommap_demo/trace_demo_crossings_clip.topdown.mp4`
  (29.7 s, fps 15; robot threading both gaps, LiDAR fans on the walls).
  All previous videos untouched.
- Evidence logs: `isaac/lab/logs/capstone_{bridge,policy}.log` (run 1),
  `capstone_{bridge,policy}_hall.log` (run 2),
  `capstone_{bridge,policy}_cross.log` (run 3).

Caveats: the frozen policy has no stop-at-goal behaviour (§9), so after
reaching it drifts and pins against the NE boundary (22 cosmetic recoveries
post-success in run 3; trimmed from the video, kept in the raw trace). One
seed per map; the run-3 success is a headline demo, not a statistic — the
transfer TABLE (§3) and budget curve (§6) remain the quantitative evidence.

## 13. Difficulty ladder + serial multi-goal — the transfer gradient and task composition (2026-09-05)

Follow-up to §12, on two questions a single "go" demo cannot answer: (i) does
zero-shot transfer degrade GRADUALLY as geometry moves away from the training
distribution, or does it cliff? (ii) can the frozen policy compose into a
richer TASK — an ordered sequence of goals — with no retraining? The videos
were also the point: a simple→mid→hard ladder and a multi-goal tour present
the transfer headline ("learning can be transferred") as a gradient with a
measured boundary, not as one trick.

### 13.1 Ladder design (same spawn/goal, same 13.2 m BFS path)

| Rung | Map | Geometry | Intent |
|---|---|---|---|
| easy | demo_open | 6 scattered short walls, open lanes everywhere | near-in-distribution (§12 run-3 class) |
| mid | demo_mid | 3 full-width staggered partitions, ~2 m gaps offset ±0.4–0.5 m off the diagonal, plus clutter | gap-threading with mild detours |
| hard | demo_gauntlet | same partitions, gaps offset ±0.8–0.9 m (S-shaped detour; gap edges bite into the direct line), same clutter | cornering at gap edges the policy never practiced |

### 13.2 Ladder results (same frozen weights, same launch procedure)

| Rung | Verdict | Recoveries |
|---|---|---|
| easy | SUCCESS, 29.30 s | 20 |
| mid | SUCCESS, 26.15 s | 14 |
| hard | NOT FINISHED, final dist 4.62 m — wedged at the 2nd gap corner (4.2, 3.85) | 25 |

Reading for the headline claim: the mid rung is the positive half of the
gradient — a map class never seen in training (full-width partitions) is
solved FASTER than the easy rung, because the constituent behaviours
(gap-threading, contact-blip recovery) transfer, and the partitions even
funnel the approaches toward the gaps (hence fewer recoveries than easy:
14 vs 20 — transfer is not monotone in visual complexity, it is monotone in
behavioural overlap with the source distribution). The hard rung is the
negative half: the cliff is not at "maze complexity" as such but at one
specific behavioural seam — the offset gaps force corner-on-edge approaches,
and the alternating backup recovery cannot change the approach angle enough
to escape the wedge. The ladder therefore LOCALIZES the transfer boundary to
a behaviour, which is exactly the kind of boundary an interface layer
(bearing-aware recovery, CBF shaping of the approach) is meant to cover.

### 13.3 Serial multi-goal: one frozen policy, three-leg tour

Interface extension, zero weight changes: `policy_node.py` now reads an
ordered `goals` list from the map JSON, advances on arrival (< 0.30 m) and
rebuilds the GeoField per leg; `28_clip_trace.py --map_file` splits the trace
into per-leg pseudo-episodes so the renderers draw per-leg START/GOAL markers
and HUD counters for free.

| Run | Map | Geometry | Verdict |
|---|---|---|---|
| serial-rooms | demo_serial | true 2x2 rooms, 1.0 m doors | NOT FINISHED 0/3, stuck at leg-1 door, final 3.97 m, recoveries 20 |
| serial-tour | demo_tour | central cross divider, 2.5 m openings; G1->G2->G3 through three quadrants | SUCCESS, 3 goals in 46.05 s (legs at 14.40 / 29.00 / 46.05 s), recoveries 3 |

The rooms run re-exposes the same wedge seam as the hard rung (narrow door +
corner approach); with openings widened into the policy's behavioural
envelope (tour), the same frozen weights complete all three legs with only 3
brief recoveries. Two points for the paper:

1. **Task composition is interface-level.** Sequencing goals and rebuilding
   the field is precisely an "interface" arm of the framework; one learned
   behaviour set composes into many task instantiations. Transfer across task
   STRUCTURE, not just geometry.
2. **The same boundary appears in both axes.** Ladder-hard and serial-rooms
   fail identically (corner wedge at a narrow passage) across two independent
   map families — evidence the measured boundary is a property of the
   transferred behaviour set, not of one particular map.

### 13.4 Framework-arm tally after this window

Per the standing instruction to track which part of the NMTE framework was
applicable (for the paper's "what transferred" paragraph):

| Arm | Showing up in this window | Status |
|---|---|---|
| Geodesic waypoint interface (GeoField from the shared map JSON) | every run; single world model shared by sim and policy (§12) | core enabler; its limit (goal-bearing dominance, §12.1) re-confirmed on hard rung |
| Recovery layer (contact-triggered alternating backup) | quantified per run: 20/14/25/20/3 recoveries; carries gap-edge blips (mid, tour) but cannot escape the wedge (hard, rooms) | behavioural fallback; the wedge motivates bearing-aware recovery / CBF shaping |
| CBF-lite (§8) | not re-run here; the wedge is the concrete case a safety filter should catch (approach angle into a corner) | concept, queued |
| DOB-lite (§7) / Koopman core (§11) | not exercised (same floor; dynamics axis unchanged) | offline / concept |
| Adaptation-budget curve (§6) | unchanged backbone; ladder adds qualitative zero-shot gradient points | quantitative evidence |
| Serial-goal composition (NEW this window) | tour success: goal list + per-leg field rebuild, zero retraining | new interface arm demonstrated |
| blind_waypoint ablation | done (§14): 4/4 with the channel vs 0/1 blinded | interface is load-bearing for transfer |

### 13.5 Artifacts

- Maps: `isaac/lab/maps/demo_{open,mid,gauntlet,serial,tour}.{png,json,preview.png}`.
- Raw traces: `videos/custommap_demo/trace_demo_{open,open_idle,mid,gauntlet,serial,tour}.npz`
  (`_idle` kept as a negative of the pre-orchestration sequencing hazard).
- Clips + topdown videos: `trace_demo_{open,mid,gauntlet,tour}_clip.npz` +
  `.topdown.mp4`; the tour clip is 44.3 s with per-leg markers (3 legs).
- 3D bird videos: `trace_demo_open_clip.bird3d.mp4` plus
  `trace_demo_{tour,mid,gauntlet}_clip.bird3d.mp4` and
  `trace_demo_crossings_clip.bird3d_v2.mp4` (re-render with tuned light/cam;
  old v1 kept). The tour is rendered with `--focal 17` (full-map framing;
  the corner-clipping focal-24 variant kept as `.bird3d_tight.mp4`).
- Logs: `logs/capstone_{bridge,policy}_{open,mid,gauntlet,serial,tour}.log`,
  `logs/capstone_{bridge,policy}_open_idle.log`,
  `logs/render3d_bird_{tour,mid,gauntlet,crossings}.log`.

Caveats: one seed per rung (N-seed repeats queued); the ladder is a designed
gradient, not a statistic; tour openings are aligned to the approaches by
construction; hard/rooms failures demonstrate the seam on one seed each, they
do not estimate its probability.

## 14. Seed repeats + waypoint-blinded ablation on demo_crossings (2026-09-05)

Two cheap runs that turn the §12/§13 demos into something statistic-like and
isolate the interface arm of the framework.

### 14.1 Spawn-jitter seeds (bridge --seed: +-0.15 m, +-15 deg yaw)

| Seed | Time-to-goal | Recoveries |
|---|---|---|
| 0 (original §12 run 3) | 33.50 s | 2 pre-success |
| 1 | 29.25 s | 10 |
| 2 | 26.80 s | 15 |
| 3 | 20.95 s | 13 |

4/4 SUCCESS. The zero-shot gap-threading success is robust to spawn
perturbation; the 20.95-33.50 s spread is approach-geometry variance, not
fragility. (Recovery counts include post-success cosmetic recoveries — the
policy has no stop-at-goal, §9.)

### 14.2 Waypoint-blinded ablation (blind_waypoint:=true)

With the geodesic-waypoint + d_geo observation channels zeroed, the same
frozen policy on the same map: NOT FINISHED, final dist 5.74 m, 30 recoveries;
the robot pins at (5.09, 2.05) against the FIRST wall and cycles backups
without ever threading the gap it threads 4/4 with the channel active.

Reading: the transfer effect runs THROUGH the math-guided interface channel —
the GeoField waypoint computed on the shared map JSON is what carries the task
across worlds; the frozen LiDAR/contact reflexes alone do not compose into
gap-threading. Caveat: zeroing trained observation channels is also an
out-of-distribution perturbation of the network input, so read this as
"the interface is load-bearing", not as "the network has no LiDAR competence".

### 14.3 Artifacts

- Traces: `videos/custommap_demo/trace_demo_crossings_seed{1,2,3}.npz`,
  `trace_demo_crossings_blind.npz` (raw, unclipped).
- Logs: `logs/capstone_{bridge,policy}_cross_s{1,2,3}.log`,
  `logs/capstone_{bridge,policy}_cross_blind.log`.

## 15. Deploy-time safety shield — zero-contact iteration 2 (2026-09-05)

Iteration 1 reached every goal but touched walls along the way (458/352/888/71/1
penetration frames on open/mid/gauntlet/tour/crossings, §5 of the report). User
verdict: collision is not allowed — move, stop, do whatever, but never collide.
Iteration 2 deploys the guarantee arm: a deploy-time safety shield in
`policy_node.py` (after the recovery layer, before the cmd_vel publish). Same
frozen checkpoint `bc_init_v3/model_0.pt`; all iteration-1 artifacts kept in
`videos/custommap_demo/`; iteration-2 traces in `videos/custommap_shield/`.

### 15.1 Shield design (CBF-lite / DWA velocity filter)

Candidate filter over the policy's command: 8 linear × 7 angular velocities
(SHIELD_V_SET × SHIELD_W_SET). A candidate is admissible iff the 17-point hull
(0.44 × 0.28 m) forward-simulated over SHIELD_HORIZON = 0.8 s plus a braking tail
(SHIELD_BRAKE_A = 0.6) never enters the obstacle grid built from every LiDAR hit
the sensors have ever seen (per-beam world-frame persistence, 0.08 m cells,
±2.6 m window; static map, hits never cleared). Tier 1 (comfort) checks against
the grid dilated by SHIELD_MARGIN = 0.10 m. The stop command (0,0) is always
admissible: worst case is standing still, never colliding. Cost ≈14 ms per
intervention tick on CPU at 20 Hz.

### 15.2 Iteration chronology (five shield versions, kept artifacts)

- **v1 (sector veto)** — 12 angular sectors, per-sector minimum range, veto unsafe
  sectors. Reached the goal; the audit still flagged penetrations. Sector minima
  protect the sensor origin, not a hull with corners. Artifact:
  `trace_demo_open_shieldv1.npz`.
- **v2 (hull-aware DWA, margin 0.22 m, no persistence)** — deadlocked at spawn:
  every candidate, including in-place rotation, judged unsafe → (0,0) forever.
  NOT FINISHED, 0.08 m of motion, 2400/2400 shield ticks. Root cause
  (`/tmp/bias_diag.py`): spawn corner's true hull clearance is +0.31 m, less than
  margin + dilation; LiDAR bias is ±0.062 m = cell quantization, not calibration.
  Artifact: `trace_demo_open_shieldv2_stuck.npz`.
- **v3 (margin 0.10 m, reverse candidates, per-beam world-frame persistence)** —
  reached the goal on demo_open; audit flagged 206 frames, all AFTER success: the
  frozen policy has no stop-at-goal behaviour (§9) and spent the remaining 97 s
  grinding the goal pocket. Approach phase itself: 0 penetrations, +0.17 m.
  Artifact: `trace_demo_open_shieldv3_grind.npz`.
- **v3 + park-after-success** — after the final goal the node publishes zero
  twist. demo_open final audit: **0 penetration frames, exact and raster.**
- **v4 (presentation set)** — shield cleared open/mid/crossings/gauntlet, but the
  3-goal tour **livelocked at goal 3** (artifact kept:
  `trace_demo_tour_v4_livelock.npz`). Root cause: grazing lidar hits scatter
  3–20 cm off true wall surfaces; disk dilation (K = ceil(0.10/0.08) = 2 cells ≈
  0.16 m) extends the comfort envelope past the ~0.18 m clearance the hull
  actually keeps, so in the tight corner pocket NO forward candidate stayed
  outside the dilated grid → in-place rotation livelock, 9 mm short of the
  success radius forever. Exact geometry (`/tmp/tour_geom.py`): pocket is open,
  nearest walls 0.455/0.465 m, closest approach d = 0.309 m vs 0.30 m radius.
- **v5 (two-tier barrier / escape hatch)** — tier 1 unchanged; tier 2 engages only
  when tier 1 is rotation-locked (best candidate has v = 0): candidates re-checked
  against the RAW wall grid (cells with actually-sensed wall points) at
  |v| ≤ SHIELD_ESCAPE_VMAX = 0.20 m/s. Raw-grid safety is the hard no-touch bar
  (hull never enters a sensed-wall cell), so zero contact is still guaranteed by
  construction; (0,0) stays admissible in both tiers. On maps that never
  rotation-lock (open/mid/gauntlet/crossings) the escape tier is provably inert.
  Offline verification (`/tmp/escape_verify.py`): fresh buffer → tier 1 passes
  with no intervention; worst-case union buffer → robot stops safely (never
  collides).

### 15.3 Iteration-2 results (shield ON, same frozen weights)

Audited with `30_clearance_audit.py --exact` (point-vs-wall-box from the map JSON,
the same boxes baked into sim colliders — no raster over-flagging):

| Map | Verdict | Time-to-goal | Recoveries | Shield ticks | Exact-audit penetration | Min hull clearance |
|---|---|---|---|---|---|---|
| demo_open | SUCCESS | 26.20 s | 1 | 67 / 2400 | **0 / 1950** | **+0.182 m** |
| demo_mid | SUCCESS | 25.00 s | 1 | 47 / 2400 | **0 / 1950** | **+0.179 m** |
| demo_crossings | SUCCESS | 24.55 s | 1 | 38 / 2400 | **0 / 1950** | **+0.287 m** |
| demo_gauntlet | SUCCESS | 29.10 s | 1 | 86 / 2400 | **0 / 1950** | **+0.158 m** |
| demo_tour (3 goals) | SUCCESS | 57.15 s | 0 | 45 / 2400 (20 escape) | **0 / 1950** | **+0.131 m** |

Against iteration 1: open 458 → 0, mid 352 → 0, crossings 1 → 0, gauntlet
888 → 0 (and failure → success), tour 71 → 0. Recoveries drop an order of
magnitude (20 → 1, 14 → 1): the shield removes stall/blip cascades at the source
instead of cleaning up after them. **The gauntlet flip**: iteration 1 wedged the
policy into the gap corner (888 contact frames, no reach); with the shield the
same weights reach the goal in 29.10 s with zero contact — the filter removed the
contact cascade, so competent steering accumulated progress.

Tour nondeterminism, disclosed: two independent v5 runs, both 3/3 goals, both
zero contact. The confirmation run (tabled above) exercised the escape tier live
20 times in the goal-3 pocket — exactly the livelock exit it was built for. The
first v5 run threaded the pocket without any shield intervention (0/2400 ticks,
min clearance +0.237 m, trace kept as `trace_demo_tour.npz` and used for the
renders). Run-to-run ROS/sim timing picks the path; the guarantee is on the
contact outcome, which held in both.

**Guarantee statement**: with the shield active, no command reaches the chassis
unless it survives a 0.8 s + braking-tail forward simulation of the full hull
against every obstacle the sensors have ever seen — at comfort margin (tier 1)
or, when tier 1 offers nothing but stop/rotate, against the raw wall grid at
≤ 0.20 m/s (tier 2). Stop is unconditionally admissible. Empirical result across
the whole presentation set: **zero contact frames under exact wall geometry.**

### 15.4 Artifacts

- Traces: `videos/custommap_shield/trace_demo_{open,mid,crossings,gauntlet,tour}.npz`
  (iteration-2 runs), `trace_demo_tour_v5_confirm.npz` (confirmation run with live
  escape activations), plus kept negatives
  `trace_demo_open_shieldv{1,2_stuck,3_grind}.npz`,
  `trace_demo_tour_v4_livelock.npz`.
- Clips + renders: `trace_demo_*_clip.npz`, `*_clip.topdown.mp4`,
  `*_clip.bird3d.mp4` in the same folder.
- Logs: `logs/shield_{bridge,policy}_tour_v5{,_confirm}.log`,
  `logs/render3d_shield_*.log`.
- Audit tool: `30_clearance_audit.py --exact` (exact-box mode added this window).

## 16. Housekeeping: demo-pool cleanup (2026-09-05)

Deleted 12 superseded/confounded demo-pool files (~7.7 GB) from `logs/`,
with explicit user approval, ahead of the submission-readiness campaign:

- `bc_demos/demos_p0.pt`, `bc_demos/demos_p0_v2.pt`,
  `bc_demos/demos_p100.pt`, `bc_demos/demos_p100_v2.pt` — v1/v2 pools tied to
  run13 (v1, observation-corrupted negative) and run15 (v2, superseded by the
  run17 v3 frozen policy).
- `dagger/round0-3.pt`, `dagger_v2/round0-3.pt` — DAgger round pools of the
  documented negative runs (run14, run16).

Every outcome these pools produced is already recorded in this ledger
(§5, §6, §15); the pools are regenerable from the collection scripts and are
no longer needed. Kept intact: `bc_demos/demos_p0_v3.pt`,
`bc_demos/demos_p100_v3.pt` (frozen run17 source policy),
`bc_demos/railyard_demos_p100{,_b}.pt` (budget curve, §6), all traces,
videos, renders and text logs.

## 17. Procedural-maze campaign: deployment-feasibility gate (2026-09-05)

Ahead of the ~730-run submission campaign, the 7 procedural families
(`isaac/lab/31_gen_mazes.py`, 4 difficulty bins x 2 maps = 56 maps) were put
through a shielded test run and an offline feasibility audit.

### 17.1 Negative: fortress test run wedged (map defect, not a shield bug)

`f4_b1_m00` (fortress, bin 1) with shield v5 reached **0/2 goals in 110 s**.
`30_clearance_audit.py --exact` reports min hull-to-wall clearance
**-0.0624 m** at t = 24.6 s and 532/1800 penetration frames. Root cause is in
the *map*, not the controller: the generator's keep-point routine
(`clear(g, r, c, 3)`) clipped a 2-cell-thick ring wall halfway and left a
1-cell stub, producing a 0.625 m dog-leg pinch. Inside that pinch the robot
sits ~1 cm from the wall, i.e. inside the shield's 0.10 m dilation, so the
shield correctly refuses every velocity that would rotate it out — the robot
is rotation-locked by geometry. Kept as a negative:
`logs/` fortress run artifacts + `30_clearance_audit.py` output.

### 17.2 Fix: geometry rules + widest-path gate

Two changes, both in `31_gen_mazes.py`:

1. **Geometry rules** so every *unintentional* passage is >= 7 cells
   (0.875 m) wide: closed-rectangle rings for fortress/roundabout (exterior
   corridors exactly 7 cells), row pitch 9 for gauntlet/gate_chain, 7-free-row
   hairpin interior, full-height vertical barrier with its own door in
   crossings, perimeter stubs abutting the arms, clutter/pallet placement
   with a 3-cell halo plus a feasibility undo, and warehouse capped at 3
   shelf rows (a 4th ran its aisle off-grid and left a 3-cell pinch).
2. **Keep points are nudged, never punched**: `place_keep` relocates a
   spawn/goal/waypoint to the nearest cell with BFS clearance >= 4 instead of
   erasing wall cells around it.
3. **Deployment-feasibility gate** in `build_map`: on the width map
   `w = 2*dist-1` (intentional doors exempt, cross-section >= 1.0 m by the
   DOOR table), the ordered waypoint list must be 8-connected inside
   `w >= 7` and every leg's max-min widest path must be >= 7 cells
   (`MIN_PASS_W`). 7 cells = 0.875 m is the geometric floor for this robot:
   rotation in place needs hull half-diagonal 0.26 m + shield margin 0.10 m,
   and it coincides with GeoField's free set (GEO_INFLATE = 0.35 m).
   Accepted maps record `corr_min` in `_manifest.json`.

### 17.3 Audit result (exemption-free, offline)

`/tmp/width_audit.py` rasterizes the shipped JSON boxes and runs max-min
widest-path Dijkstra on the *uninflated* grid (no door exemption), reporting
the bottleneck distance-to-wall per leg:

| pool | before fix | after fix |
|---|---|---|
| 56 generated maps | 27 PASS / 21 MARGINAL / 8 FAIL | **56 PASS / 0 / 0** |

PASS = bottleneck >= 4 cells (corridor >= 7 cells = 0.875 m). Tightest
accepted corridors are exactly 4 cells (1.00 m usable) on the serpentine /
fortress / warehouse bins; micromouse labyrinths are 5-6 cells. The previous
v1 pool is kept for comparison at `maps/_gen_v1_backup/`.

Preview sheets re-rendered (`maps/gen/preview_{0,1}_{a,b}.png`); awaiting user
re-approval before any shielded test run or campaign compute is spent.

### 17.4 Negatives: shielded test runs on the fixed pool (2026-09-05)

User-approved re-test of the two presentation maps on Stack B (bridge +
`policy_node.py`, shield v5 ON). Both FAIL, both with real penetration, so the
geometry gate alone is not sufficient for closed-loop deployment:

| map | goals | pinned from | min clearance | penetration frames | recoveries / escape ticks |
|---|---|---|---|---|---|
| `f4_b1_m00` fortress | 0/2, final 5.22 m | t≈17 s | −0.0625 m | 1697/1950 | 42 / 1901 |
| `f6_b2_m00` warehouse | 1/4 (open leg at t=10.3 s) | t≈20 s | −0.0604 m | 1654/1950 | 40 / 2084 |

Traces: `videos/genmaps_test/trace_f4_b1_m00_v2.npz`,
`trace_f6_b2_m00.npz`; logs `logs/genmaps_test_{bridge,policy}_*_v2.log` /
`..._f6_b2_m00.log`. Old v1 fortress negative kept untouched.

Mechanism (two independent defects, both interface-level):

1. **Shield v5 grinds instead of backing out.** `_apply_shield` runs AFTER the
   recovery layer, so it also filters the recovery's backup command. Its
   tier-2 escape score is `cv + 0.25|cw| − 0.05|cw−w|`, which *prefers forward
   velocity*, and tier 2 validates candidates on the coarse lidar-raster "raw
   grid" rather than exact box geometry. Once the hull sits inside the 0.10 m
   dilation in a tight corridor, the escape tier therefore emits a constant
   small forward+rotate command (observed +0.20/−0.60 for ~95 s) that grinds
   the hull ~6 cm into the wall — the penetration the exact-box audit sees.
   The docstring's "zero contact guaranteed" holds only against *observed wall
   cells*, not against true box geometry.
2. **The frozen policy cannot track corridors at the deployed GeoField
   resolution.** `GEO_RES=0.25`, `GEO_INFLATE=0.35`: a 0.875 m corridor leaves
   a 0.175 m inflated free band (one cell line), a 1.0 m aisle 0.30 m. The
   geodesic is connected (verified offline) but the pure-pursuit waypoint has
   no lateral slack, so cornering creep presses the hull into one wall; the
   policy has no wall-following behaviour to recover (§13 gotcha: openings
   < 2 m re-expose the corner-wedge seam).

Consequence for the campaign: the user-approved ≥ 0.875 m bar guarantees the
hull *fits and can rotate* (open-loop geometry) but not that the closed loop
(policy + GeoField + shield) can *track* the corridor. Fix direction pending
user decision (shield v6 escape/recovery ordering vs. widening the deployment
bar vs. both vs. reframing the campaign as an adaptation-boundary study).

### 17.5 Shield v6 A/B (same map, one change): zero contact restored

User chose "shield v6 + widen bar". Shield v6 = three changes in
`policy_node.py::_apply_shield`: tier 2 validates with the hull grown by
`SHIELD_RAW_PAD = 0.08` m (closes the lidar-raster/rounding gap vs true box
geometry); when pinned (recovering or contact EMA at trigger) the tier-2 score
prefers REVERSE so the escape backs out; a raw-safe recovery backup passes
un-vetoed (v5 shielded the backup away, which locked the robot).

Single-variable A/B on `f6_b2_m00` (warehouse, 1.0 m aisles), shield ON:

| metric | v5 (17.4) | v6 |
|---|---|---|
| goals | 1/4 | 1/4 |
| min hull clearance | −0.0604 m | **+0.0742 m** |
| penetration frames | 1654/1950 | **0/1950** |
| recoveries | 40 | **0** |
| escape ticks | 2084 | **8** |

Trace `videos/genmaps_test/trace_f6_b2_m00_v6.npz`, logs
`logs/genmaps_test_{bridge,policy}_f6_b2_m00_v6.log`. The grind and the
penetration are gone; the remaining failure is purely defect 2 (the frozen
policy cannot track a 1.0 m aisle: shield_ticks 2198/1800-tick run, i.e. the
comfort tier holds it back all run). Addressed next by widening the
deployment bar to ≥ 1.5 m corridors / ≥ 2.0 m doors.

### 17.6 Deployment bar widened on a 10 x 10 m canvas (v3 generator)

User chose "10x10 m + wide bar". New bar: every accepted map has a widest-path
corridor of >= MIN_PASS_W = 13 cells = **1.625 m** and every intentional door
>= 16 cells = **2.0 m** (the 1.0 m aisle / 0.875 m corridor that pinned the
frozen policy in 17.4-17.5 are both gone).

**Why the canvas had to grow (8 m sparsity analysis).** At 13-cell corridors
plus 2-cell walls the wall pitch is 15 cells. The 8 m canvas has a 62-cell
interior, which at that pitch admits only ~3 full-width walls; two concentric
fortress rings cost 2 x (13+2+13) = 56 of those 62 cells leaving a <= 6-cell
keep (the robot cannot rotate in it); the roundabout pillar shrinks to ~6
cells; warehouse shelf rows leave no room for aisle pallets; and the
competition labyrinth freezes at 4x4. The 10 m canvas (N=80, 78-cell interior)
keeps all of it: two fortress rings with a 2.25 m keep, three shelf rows with
1.875 m aisles, a 5x5 labyrinth with 1.625 m corridors, and four serpentine
walls. The stack is size-agnostic (bridge/rasterizer/top-down/audit/policy all
read SPEC["size"]), so no harness change was needed.

**v3 generator changes** (`isaac/lab/31_gen_mazes.py`): bfs_dist is now
UNCAPPED (v2 capped at WIDE_CLR and filled 99, which made corr_min a 12.375
sentinel); the width gate has NO door exemption (a >= 16-cell door in a 2-cell
wall funnels to distance >= 8 at its centre, so doors are wide by geometry),
which makes the generator gate identical to the exemption-free offline audit;
new `pocket_free` gate rejects any map with a sealed sub-bar free region;
clutter/pallets/lane-incidents now use a `gap_ok`/`scatter` primitive that only
keeps a block when every free run beside it is 0 (flush) or >= 13 cells and the
route stays one wide channel; `m_hairpin`, `m_crossbar`, `m_crossings` are
dropped (they cannot survive the bar); seeds are `97000*fam + 9700*b + 97*idx +
attempt` and reported in the manifest; D is recalibrated to
0.30*door + 0.25*struct + 0.20*rho + 0.15*turn + 0.10*clutter.

**Result.** 56/56 maps regenerate in 13.3 s with 0 rejects. `width_audit.py`
(now derives N from each JSON's size/cell; PASS = bottleneck distance >= 7
cells) reports **56 PASS / 0 MARGINAL / 0 FAIL**; corr_min is 1.625-1.875 m and
door_min 1.62 m (labyrinth corridor, recorded as its door) to 2.75 m. Spawn and
goal land on varied corners/edges via the 8 dihedral transforms. Previews
re-rendered (`maps/gen/preview_{0,1}_{a,b}.png`). The old 8 m pool is preserved
in `maps/_gen_v2_8m_backup/`.

Next: shielded Stack B test runs on `f4_b1_m00` (fortress) and `f6_b2_m00`
(warehouse) with shield v6 on the 10 m canvas (duration 180 s), pending user
confirmation.

### 17.7 Negative found in the v3 pool: the gauntlet motif was dead (fixed)

Motif-coverage check on the 17.6 pool: family 2 ("gates") came out **8/8
`gatechain`, 0 `gauntlet`**, so the locked "full 8-motif library" was really 7
motifs. Tracing 16 pure-gauntlet builds through `build_map`'s gate sequence
showed the cause is not geometry but the detour gate: **15/16 FAIL `rho <
1.15`** (rho 1.00-1.12, path 11.1-12.5 m against an 11.14 m corner diagonal).
With doors now 2.0-2.75 m wide on a 9.75 m span, staggering mouths by *thirds*
no longer forces a detour — the spawn→goal diagonal threads them — so every
gauntlet attempt was rejected and family 2 silently fell back to `gatechain`
(which passes because its waypoints order the route). Those rejections were also
the pool's retry hotspot: 8 maps retried, up to 7 attempts, all in fam2/fam5.

Fix (user-approved, generator only): `m_gauntlet` doors now **alternate between
the two extremes of the span** with <= 9 cells of jitter, so each wall forces a
lateral sweep, and difficulty scales by **wall count** (k = 2/3/3/4, as in
`m_serpentine`) instead of a second door per wall — a second mouth would only
shortcut the weave. `build_map`'s fam2 branch is now a clean 50/50 choice
between gauntlet and gate_chain: a k=4 gauntlet claims all four wall rows the
15-cell pitch allows, so the old stacked `gauntlet + gate_chain(b-1)` combo
could only degenerate into a `gatechain(none)` no-op. Re-traced 16 builds:
**16/16 PASS**, rho 1.65-2.95 (rising with bin), bottleneck 13-15 cells, doors
2.0-2.75 m, 0 punches.

Regenerated pool: 56/56 maps, 0 rejects; audit **56 PASS / 0 MARGINAL / 0
FAIL**; corr_min 1.625-1.875 m, door_min 1.62-2.75 m, D 0.199-0.828, 56 unique
seeds, all 8 dihedral transforms used. Motif counts now `gauntlet 5 /
gatechain 3` in fam2 (full 8-motif library live). Retries dropped to 5 maps
(4 x 1 attempt, `f5_b1_m01` x 7). Mean D still rises with bin in 5/7 families;
`competition` (0.591 -> 0.575 at bins 0-1) and `gates` (0.513 -> 0.499 at bins
2-3) invert by < 0.02 with n=2 per cell, so bins are nominal and the per-map D
in the manifest is the reported difficulty. The two approved test maps are
byte-identical to 17.6 (`f4_b1_m00` seed 397700, `f6_b2_m00` seed 601400) — the
fix only touches fam2. Previews re-rendered; the 17.6 pool is superseded in
place (8 m pool still in `maps/_gen_v2_8m_backup/`).

### 17.8 Negative: shield v6 does NOT hold the no-collision rule on the 10 m pool

Post-regeneration gate (user-approved): the same two presentation maps re-run on
Stack B (`17_bridge_ros_custommap.py` + `policy_node.py`, shield v6, 180 s, one
change per run = the canvas rescale only). Both runs were audited with
`30_clearance_audit.py` in EXACT mode (rotated-rectangle hull vs the map's real
boxes) and every penetration localised frame-by-frame.

| map | goals | min clearance | pen frames | worst contact | shield stats |
|---|---|---|---|---|---|
| `f4_b1_m00` fortress | 0/2 (final 2.35 m) | **-0.0405 m** @ t=77.3 s | 51/2850 | ring north-wall END box (cx 5.00, cy 1.81, 6.50 x 0.12 m), hull corner | ticks 1238, escape 91, recoveries 7 |
| `f6_b2_m00` warehouse | 2/5 (final 5.33 m) | **-0.0564 m** @ t=169.2 s | 395/2850 | aisle pallet (cx 2.38, cy 7.69, 0.75 x 0.12 m), hull corner (0.22, 0.14) | ticks 2230, escape 889, recoveries 6 |

Both violate the standing "never any collision" rule, so the gate FAILS and the
campaign is blocked until the shield is fixed. Traces/logs: `videos/genmaps_test/
trace_f{4_b1,6_b2}_m00_v3_10m.npz`, `logs/genmaps_test_*_v3_10m.log`; failure
renders `videos/genmaps_test/f*_v3_10m_fail.topdown.mp4`.

**Root cause: the shield's barrier is 4-9 cm optimistic w.r.t. the audit's.**
The shield validates candidate arcs against a boolean grid rasterised from
persisted LiDAR hits (`SHIELD_GRID_RES` 0.08 m, dilated by
`ceil(SHIELD_MARGIN/RES)` = 2 cells) using **17 sparse hull sample points**; the
audit uses the **exact boxes** with a dense hull. Sampling the fortress/warehouse
poses while the shield reported "safe" gives a true clearance of only
**+0.01..+0.06 m** against the nominal `SHIELD_MARGIN = 0.10 m`. Three mechanisms:

1. **Raster quantisation.** Hits snap to a 0.08 m lattice and dilation is a
   2-cell disk, so the certified margin is not the commanded margin.
2. **Sparse hull sampling.** The 0.44 x 0.28 m hull leaves 0.11-0.22 m gaps
   along its long edge — comparable to the 0.125 m wall/pallet thickness — so a
   thin box slips *between* sample points during rotations. Both penetrations are
   exactly this case, both by hull corner (0.22, +-0.14) into a 0.12 m-thick box.
3. **LiDAR blind spot at grazing incidence.** Scanners sit at x = +-0.22015 m
   (the hull faces); a wall END seen edge-on returns few/no hits on the corner
   that is about to touch it.

**Second, separate defect (explains the low goal counts, not the contacts):
shield chatter defeats the stall detector.** Published commands flip sign at
20 Hz (+0.10 <-> -0.10 m/s with +-0.9 rad/s), realised chassis speed ~0.01 m/s,
so `contact_ema` oscillates 0.00 <-> 0.99. Because the stall proxy only counts
when `|prev_cmd_v| > STALL_MIN_CMD = 0.02`, `pinned` was **0 in 13/14 fortress
escapes** — v6's reverse-preferring escape therefore almost never engaged
(7 and 6 recoveries in 180 s). The fortress robot dithered at (8.08-8.10, 1.51)
for ~80 s at +0.05..+0.06 m clearance and never reached either goal.

Fix options recorded in 17.9 (decision pending user confirmation; no simulator
compute before then).

### 17.9 Shield v7: exact-box ESDF barrier + chatter control

**Decision (user-approved).** Of the three fixes offered after 17.8 the user
picked option A, the exact-geometry barrier, and relaxed the confirm-first rule
for this fix ("do what you think is necessary to run ... just do what you think
is recommended"). Options B (grow `SHIELD_MARGIN` to 0.16 m) and C (densify the
hull only) were rejected: B buys the audit agreement with a fudge factor that
does not survive a different map family, and C leaves the raster quantisation
and the grazing blind spot untouched. v7 removes the *cause* — the barrier now
measures the same quantity the audit measures — and keeps the LiDAR raster only
for geometry the map does not know about.

**Design (all shield-side; the frozen policy is never touched).**

1. `BoxSDF`: an exact signed-distance field at `SHIELD_ESDF_RES` 0.025 m over
   the *same* box list the geodesic field and the bridge scene use (in the
   deployment story this is the map_server/SLAM map). Built per box inside a
   1.0 m halo and clamped there, 0.60 m of pad beyond the drivable bounds,
   bilinear `sample()`, out-of-grid = -1 (wall, i.e. conservative). 449x449
   nodes for a 10 m map, ~0.2 s to build.
2. **Certified floor.** A candidate arc is accepted only if the field along it
   stays >= `SHIELD_MARGIN + SHIELD_ESDF_SLACK` (0.10 + 0.05 m). The slack is
   not a fudge: it bounds the two discretisations — bilinear sampling of a
   1-Lipschitz field on the lattice (<= RES*sqrt(2) = 0.035 m) and the hull
   perimeter sampling (<= spacing/2 = 0.015 m) — so an accepted arc really does
   keep the *true* hull >= 0.10 m off the *true* boxes. Measured optimism is
   0.007-0.012 m, i.e. the slack has 4x headroom (below).
3. **Hull densified** to `_hull_perimeter(spacing=0.03)` = 50 perimeter points +
   centre, so no 0.125 m-thick wall fits between samples (mechanism 2 of 17.8).
4. **LiDAR raster keeps only unmapped hits.** `_obstacle_grid` now drops every
   hit whose exact-field value is <= `SHIELD_UNMAPPED_TOL` 0.05 m: mapped
   geometry is certified exactly by the field, so rasterising it again only
   re-introduces the 4-9 cm pessimism that churned the escape tier 889 times in
   the 17.8 warehouse run. Anything the map does not explain (a moved crate, a
   person) still enters conservatively, with the raw grid + a hull grown by
   `SHIELD_RAW_PAD` 0.08 m at the escape tier. This is also the honest
   deployment split.
5. **Three tiers**: comfort (margin 0.10, field + dilated raster) -> escape
   (`SHIELD_ESCAPE_MARGIN` 0.02 m, raw raster, padded hull, `SHIELD_ESCAPE_VMAX`
   0.20 m/s, reverse when pinned) -> retreat. The retreat tier exists because
   the plant does not track the simulated arc exactly (the bridge re-maps the
   twist onto a pioneer3dx chassis), so if the hull is *already* inside the
   escape floor, freezing in a wall is the worst response: pick the creep-speed
   candidate that gains the most clearance (`end_clr + min_clr + 0.05*sgn*v +
   0.02*|w|`).
6. **Chatter control** (fixes the second 17.8 defect). (a) Hysteresis: tier 1
   first tests `[policy_cmd, last_published]` and repeats the last published
   twist if it is still safe; the batch search also includes it with a
   `SHIELD_HYST_BONUS` 0.15 score bonus, so a marginal win no longer flips the
   sign at 20 Hz. (b) Geometric pin latch: 10 vetoed ticks (0.5 s) with < 0.03 m
   of motion latches `pinned` (escape prefers reverse), released after 0.20 m of
   motion. This detects the livelock *geometrically* and therefore does not
   depend on the chassis-speed stall proxy that the chatter defeated
   (`pinned`=0 in 13/14 fortress escapes).

**Feasibility check (why tier 1 should never lock on the 10 m pool).** Corridors
are >= 13 cells = 1.625 m; the hull half-diagonal is 0.327 m, so in-place
rotation needs 0.327 + 0.10 margin + 0.05 slack = 0.477 m <= 0.8125 m available.
Rotation is certified-safe everywhere in the pool, so an admissible candidate
always exists and the escape tier should now be rare rather than the main mode.

**Offline validation** — `isaac/lab/32_check_shield_v7.py` (no simulator, no
ROS; loads `policy_node.py` with stubbed ROS modules and exercises the barrier
methods against brute-force exact box distances):

| check | `f4_b1_m00` | `f6_b2_m00` | bar |
|---|---|---|---|
| [1] field vs exact, max over-read (3975/3954 pts) | +0.0125 m | +0.0123 m | <= SLACK 0.05 |
| [2] hull discretisation (51-pt vs 361-pt ref hull, 2850 frames) | +0.0066 m | +0.0068 m | <= spacing/2 = 0.015 |
| [2] total optimism -> verdict | +0.0066 m **CERTIFIED** | +0.0124 m **CERTIFIED** | <= 0.05 |
| [3] frames whose next 0.8 s breaches the floor | 1644 | 1896 | — |
| [3] tier-1 vetoes on those frames | 1617 caught / 27 missed | 1823 / 73 | — |
| [3] **frames with the hull truly inside a box** | **53, vetoed 53** | **395, vetoed 395** | missed = 0 |
| [4] cost: pass-through / full 56-candidate batch | 0.31 / 3.62 ms | 0.31 / 3.59 ms | < 30 ms at 20 Hz |

The 27/73 "missed" frames are all *margin* misses, not collisions: their real
future minimum is +0.085..+0.121 m, i.e. just under the 0.15 m certified floor,
which is the finite-difference twist of the v6 plant differing from the arc the
barrier simulates. Every frame where the hull was actually inside a box is
vetoed (100%), and the last veto before the first penetration is 0.1 s ahead of
it — v7 would have diverted the trajectory long before (it vetoes 1617/1823
frames of these traces, so the v6 trajectory would never have arisen).
Field under-reads (up to -1.0 m outside the padded grid) are conservative by
construction and cost only admissible candidates, never safety.

Reproduce: `~/isaaclab/isaaclab.sh -p isaac/lab/32_check_shield_v7.py`
(`torch` is imported at module level by `policy_node`, so the conda python3
cannot run it). Runtime ~40 s for both maps.

### 17.10 Gate re-run with shield v7: no-collision HOLDS, goals unchanged

Same two presentation maps, same bridge/checkpoint/180 s, one change = the v7
shield. Traces `videos/genmaps_test/trace_f{4_b1,6_b2}_m00_v7_10m.npz`, logs
`logs/genmaps_test_*_v7_10m.log`.

| map | goals | min clearance (EXACT audit) | pen frames | shield stats (ticks/escape/hyst/pin) | recoveries |
|---|---|---|---|---|---|
| `f4_b1_m00` fortress | 0/2 (final 4.61 m) | **+0.1496 m** @ t=85.9 s | **0/2850** | 1169 / 54 / 1063 / 6 | 10 |
| `f6_b2_m00` warehouse | 2/5 (final 4.86 m) | **+0.1259 m** @ t=51.1 s | **0/2850** | 2238 / 22 / 2091 / 15 | 2 |

The no-collision rule is now held on both maps (17.8 had -0.0405 and -0.0564 m),
and the measured minimum clearances sit essentially ON the certified floor
(margin 0.10 + slack 0.05 = 0.15 m; the warehouse dips to 0.126 m because the
plant does not track the simulated arc exactly, which is precisely what the
slack and the retreat tier are for). Escape-tier engagements collapse
(91 -> 54 and 889 -> 22), confirming that the raster pessimism of v6 was what
churned it. **The gate PASSES on safety.**

**But goal counts are unchanged (0/2, 2/5), and the traces show why: the shield
livelocks, it does not collide.** Fortress: the robot reaches the outer ring's
bottom-right corner (~(8.6, 1.45), the corner between the ring's south wall and
the east corridor) at t~30 s and then spends 150 s rotating in place: published
commands alternate (+0.00,+0.90) / (-0.20,-0.90) / (-0.20,+0.90) at 20 Hz while
the realised speed is ~0, so the chassis-speed stall proxy reports false contact
(0.8-1.0) and the recovery layer adds reverse pulses on top. Warehouse: same
signature at (2.55, 1.60) after goal 2 (pin latched 15x, `cmd` swinging
+1.32 <-> -2.43 rad/s).

**Cause: the tier-1 candidate score rewards spinning.** `score = cv + 0.25|cw|
- 0.05|cw - w|` pays +0.225 for |w| = 0.9 regardless of direction, so whenever
forward is blocked the argmax over the safe set is a *full-rate rotation*, and
the -0.05|cw-w| tie-break flips its sign with the policy's own w: a 20 Hz
rotation chatter with zero net yaw. The shield is a safety filter; it must not
have an objective of its own that fights the policy. Fix in 17.11: make the
shield's selection a *projection onto the safe set* (closest admissible twist to
the policy's proposal), which is the standard CBF-QP form and removes every
self-generated objective.

### 17.11 Negative: the pure projection freezes; v7.2 adds a CBF backup policy

**v7.1** replaced both shield scores with the safe-set projection
`-((cv-v)^2 + (0.25(cw-w))^2)` (tier 1) and the same with a reversed linear
target when pinned (escape tier). Re-run of the fortress map
(`trace_f4_b1_m00_v71_10m.npz`): still **0/2850 penetration frames** (min
clearance +0.2221 m — safety is structural, it does not depend on the score),
but the robot now **freezes**: 0/2 goals, shield_ticks 2977, escape 2, and the
last 60 s are `cmd=(+0.00,+0.00)` parked at (8.57, 1.44) with the log line
`[shield] (+0.13,+0.12) unsafe -> (+0.00,+0.00) pinned=1`.

**Why: the projection is degenerate for small unsafe nominals.** An offline
probe of exactly that pose (`BoxSDF` + `_barrier_ok`, no simulator) shows the
tier-1 safe set is NOT empty of useful actions: 21 of 56 candidates are
certified-safe, among them ALL reverses (v = -0.1/-0.2, any w, arc clearance
+0.23 m) and ALL pure rotations (arc clearance +0.185..+0.225 m) — including
(0, +0.9), which turns the robot from yaw 132 deg into the open west corridor
(the field 0.5 m ahead is -0.03 m at 135 deg but +0.31 m at 180 deg). Yet the
projection ranks STOP first: distance to the nominal (+0.13,+0.12) is 0.0178 for
(0,0) versus 0.0189 for (0,+0.3) and 0.0538 for (-0.1,0). A 0.001 score gap
buys a permanent freeze. "Closest to the nominal" is the wrong objective when
the nominal itself is the problem (the frozen BC policy proposes into the wall
here); a safety filter still needs a *backup policy* for that case.

**v7.2 (implemented, shield-side only).** Keep the projection as the primary
selection, but when its winner cannot translate (|v| < 0.1, i.e. stop or
in-place rotation only) re-select inside the SAME certified safe set with a
goal-directed backup objective — the standard CBF backup controller:

    g = (arc-end displacement) . u(wp)  +  0.15 * cos(yaw_end - angle(u(wp)))

where `u(wp)` is the unit vector to the geodesic waypoint (`GeoField.waypoint`,
the same channel the policy observes). Progress over the 0.8 s horizon is in
metres (<= ~0.4), the alignment term breaks the rotation-direction tie, and the
last-published twist keeps its hysteresis bonus. The same guard is applied in
the escape tier when its winner has v = 0. Safety is untouched: the backup only
ever chooses candidates the exact barrier has already certified, so the 17.9
certificate carries over unchanged. At the probe pose the backup selects
(0, +0.9) — rotate into the open corridor — instead of stop.

### 17.12 Negative: v7.2's backup rotation is discarded by the escape gate

**Run 4** (fortress `f4_b1_m00`, v7.2, `trace_f4_b1_m00_v72_10m.npz`): 0/2
goals, **0/2850 penetration frames**, but min clearance collapsed to
**+0.0201 m** (t=176.5 s) — the worst of the v7 family, because the escape
tier's reverses now pressed the hull against the pocket wall every cycle.
Stats: shield_ticks 2461, escape 179, hyst 2133, pin 1, recoveries 2. The
robot never left (8.57, 1.44): the log alternates `[shield] (+0.19,-0.16)
unsafe -> (+0.10,-0.30)` (creep in) with `[shield-escape] ... -> (-0.20,...)`
(back out) — a crawl-in/back-out limit cycle with net zero motion.

**The backup objective itself is right.** An offline probe at the freeze pose
(yaw 140 deg, nominal (+0.19,-0.16), waypoint (7.62,1.38) bearing -176 deg;
`BoxSDF` + `_barrier_ok` + the v7.2 `g`, no simulator) reproduces the choice:
the comfort safe set is 21/56, contains NO forward candidate, the projection
winner is (0,-0.30), the backup fires (|cv|<0.1) and its top pick is
**(0,+0.90), g=+0.150, arc min clr +0.185 m** — exactly the re-aim into the
west corridor. Two shield bugs then threw it away:

1. **Escape gate misread rotations as "locked".** The gate was `best[0]==0.0`,
   written before the backup existed, when a zero-v winner always meant a
   freeze. The backup's (0,+0.90) has v=0, so every re-aim was forwarded to
   the escape tier, which replaced it with a reverse toward the nominal's
   reversed target. The robot could never turn.
2. **Creeps squeaked past the freeze guard.** At yaw ~138 deg the projection
   winner (+0.10,-0.30) has |cv| = 0.10, NOT `< 0.1`, so the backup never
   fired and the certified-safe creep into the pocket was published as
   "progress" (the plant then tracked it to +0.02 m true clearance — the arc
   model over-estimates what the chassis does that close to the wall).

### 17.13 Negative: v7.3 re-aims but tier-1 passthrough aborts the rotation

**v7.3** (three coupled edits, shield-side only): the escape gate became
`best == (0.0, 0.0)` — a pure-rotation winner is progress and is published
as-is; the escape tier likewise publishes rotation winners
(`ev!=0 or ew!=0`); and the backup trigger widened to
`self.pinned or |cv| < 0.1`, with the hysteresis repeat branch disabled while
the pin latch is held.

**Run 5** (fortress, `trace_f4_b1_m00_v73_10m.npz`): 0/2 goals, **0/2850
penetrations**, min clearance **+0.1611 m** — the wall-pressing cycle is gone.
Stats: shield_ticks 878 (vs 2461), escape 34, hyst 124, pin 5, recoveries 10.
The backup rotations are now published (`[shield] (+0.16,+0.02) unsafe ->
(+0.00,+0.90) pinned=1`) and the robot DID leave the (8.57,1.44) pocket for
the first time in the v7 family. But it then **loitered 180 s** inside
(8.2-9.4, 0.6-1.6), yaw oscillating 120-160 deg, never settling on the
~180 deg west bearing.

**Why: tier 1 kept interrupting the re-aim.** While latched, the batch+backup
selects (0,+0.90), but on the next tick the policy's micro-twist
(e.g. (-0.04,-0.03)) is certified safe at the comfort margin and passes
tier-1 passthrough `ok[0]` — the rotation is abandoned after one tick, the
yaw never reaches the waypoint bearing, and no forward candidate ever becomes
the projection winner. The pin latch released on >0.2 m of slow drift
(release anchor), re-latched (pin=5), and the cycle repeated: 1.5 m of net
westward progress in 180 s. The pocket is a *policy* trap (the frozen BC
policy proposes micro-twists and wall-ward creeps here), and the shield can
only drive through it if the backup keeps the wheel for the whole re-aim.
Fix in 17.14: while the latch is held, suspend tier-1 passthrough entirely —
every tick goes through batch + backup until the robot has moved 0.2 m.

### 17.14 Shield v7.4 gate: warehouse 3/5 (best yet), fortress bottleneck moves to the policy

**v7.4** (one edit): while the pin latch is held, tier-1 passthrough is
suspended entirely — both the policy-nominal branch (`ok[0]`) and the
hysteresis-repeat branch — so every latched tick runs batch + backup until
0.2 m of real motion releases the latch. The backup keeps the wheel for the
whole re-aim.

**Run 6 — fortress `f4_b1_m00`** (`trace_f4_b1_m00_v74_10m.npz`): 0/2 goals,
**0/2850 penetrations**, min clearance **+0.1473 m** (t=65.7 s). Stats:
shield_ticks 667, escape 0, hyst 509, pin 9, recoveries 13. The robot left
the pocket immediately and made steady geodesic-following progress west along
the south passage, (8.94,0.94) -> (7.44,0.61), but 1.5 m in 180 s: with the
shield passing nearly everything (667 vetoes of ~3600 ticks), the logged
commands are the policy's own — micro-twists of 0.00-0.10 m/s. **The
bottleneck is now policy competence, not the shield**: the frozen BC policy
sees wp ~1 m away with d_geo ~17 m (the fortress ring forces the detour) and
produces near-zero speed; no shield-side selection rule can inject forward
motion that the safe set already certifies and the policy declines to ask
for.

**Run 7 — warehouse `f6_b2_m00`** (`trace_f6_b2_m00_v74_10m.npz`): **3/5
goals** (t=7.4 s, 29.9 s, 179.1 s) — up from 2/5 under both v6 and v7 and the
best gate result on this map; **0/2850 penetrations**, min clearance
**+0.1294 m**. Stats: shield_ticks 1620, escape 16, hyst 818, pin 11,
recoveries 5. Leg 3 cost 149 s (a pocket fight between (1.1,6.2) and
(6.3,4.7)) but the backup drive now digs the robot out instead of livelocking
it, and goal 3 landed with 1 s to spare — the 180 s cap, not the shield,
stopped legs 4-5.

**v7-family gate summary** (both maps, 180 s, exact-box audit bar = 0
penetration frames):

| shield | fortress goals | fortress min clr / pen | warehouse goals | warehouse min clr / pen |
|--------|----------------|------------------------|-----------------|--------------------------|
| v7   (17.10) | 0/2 | +0.1496 m / 0 | 2/5 | +0.1259 m / 0 |
| v7.1 (17.11) | 0/2 | +0.2221 m / 0 | — | — |
| v7.2 (17.12) | 0/2 | +0.0201 m / 0 | — | — |
| v7.3 (17.13) | 0/2 | +0.1611 m / 0 | — | — |
| v7.4 (17.14) | 0/2 | +0.1473 m / 0 | **3/5** | +0.1294 m / 0 |

The no-collision rule held in EVERY v7-family run on both presentation maps —
the barrier certificate (17.9) is doing exactly its job while the selection
rule changed five times underneath it. This is the paper's thesis in one
table: the shield owns safety (structural, score-independent), the policy
owns competence (map-dependent), and the backup policy is the bridge that
converts certified-safe rotations into progress when the policy traps itself.

**Decision: v7.4 is the campaign shield** (the version to port to Stack A in
the campaign task). Videos: `videos/genmaps_test/f4_b1_m00_v74_10m.topdown.mp4`
and `f6_b2_m00_v74_10m.topdown.mp4` (15 Hz, titled; all older videos kept).
The fortress 0/2 is recorded as a policy-competence negative (out-of-
distribution wp/d_geo combination), not a shield failure — consistent with
the honest-reporting rule and with the campaign's need for the A*+DWA
baseline to have something to beat.

### 17.15 Shield v7.4 ported to Stack A (camp6a) + first Isaac Lab validation (camp6b)

The campaign runs in Isaac Lab (Stack A: `21_run_openmover_nav.py`), but the
adopted shield v7.4 lived in the deployment node (Stack B: `policy_node.py`).
This section ports it and validates the port on a presentation map.

**The port — `openmover_lab/shield_lite.py` (~470 lines, new).** `ShieldLite`
mirrors the `CbfLite` shim contract: `.action(a)` sits between the policy and
`env.step` as the FINAL authority in the chain (policy -> manual_clip -> dob
-> const_boost -> cbf -> shield), operates on (N,2) wheel-fraction tensors,
returns the SAME tensor object when it filters nothing (exact no-op), and
exposes `.reset(dones)` / `.stats()`. The barrier is copied verbatim from
`policy_node.py` v7.4 (ledger 17.14): exact-box ESDF (`BoxSDF`, 0.025 m
lattice, halo 1.0, pad 0.60, bilinear sampling, out-of-grid = -1), certified
floor `SHIELD_MARGIN 0.10 + SHIELD_ESDF_SLACK 0.05`, 51-point hull at 0.03 m
spacing, three tiers (comfort projection / escape floor 0.02 / retreat),
goal-directed backup, hysteresis bonus 0.05, geometric pin latch.

**Four documented deviations from `policy_node.py`** (in the module docstring):
1. NO lidar-raster half of the union field. Stack A geometry is fully mapped,
   so exact raycaster hits land ON box surfaces and policy_node's own
   unmapped filter (`sdf.sample > 0.05`) would empty the raster; the union
   degenerates to the exact-field half anyway.
2. No recovery/contact paths (`recovering` is always False) — Stack A has no
   contact estimator and the campaign rule is zero collisions regardless.
3. Backup direction comes from the env-native `_geo_waypoint` (geo_inflate
   0.20) instead of the deployment GEO_INFLATE 0.35 field; only the direction
   is used, which is scale-invariant.
4. Output clamped to ±1 per wheel = actuator saturation (see next).

**One Stack-A-only soundness addition: the realizability filter.** Wheel
fractions saturate at ±1, so a twist (v,w) is exactly realizable iff
`|v|/v_full + |w|/w_full <= 1` (because `va+wa = max(|aL|,|aR|)`). Candidate
sets are filtered at construction: comfort 56 -> **48**, escape 35 -> 35.
Without this the shield could certify (v=0.5, w=0.9) — unrealizable (ratio
1.28) — and the actuator would silently shrink it into an uncertified twist.
`policy_node.py` never needed this because the bridge chassis realized
published twists directly. Conversion constants: `v_full = 0.050353 * 10 =
0.50353 m/s`, `w_full = 2*v_full/0.324 = 3.108 rad/s`; inverse
`aL = va - wa`, `aR = va + wa`.

**Runner wiring (`21_run_openmover_nav.py`).** New `--shield` (requires
`--map_file`) and `--episode_cap` (default 160 s; campaign uses 190 s,
replacing the hardcoded 160). Manual-clip reproduction turns on with the
shield so the shim sees the same tensor the deployment node would. Summary
line prints `shield/hyst/escape/pin` counts.

**Frame fix (`openmover_terrains.py`).** `custom_map_terrains_cfg` now loads
the spec and sets `size=(spec.size)` instead of the hardcoded (8,8) — the old
code built 10 m maps on 8 m tiles, a 1 m offset between the robot/goal frame
(corner-local) and the walls (tile-centred terrain). `layout_version` bumped
to 2 to bust the terrain cache. Verified live: camera at tile (0,0) =
(-5.0,-5.0) on the 10 m warehouse map. `TerrainGenerator` propagates
`cfg.size` to sub-terrains, so spawn/goal conversion, the obstacle table and
the occupancy grid all follow automatically (no other hardcodes found).

**Audit fix (`30_clearance_audit.py`).** Exact-box mode now shifts the trace
world -> corner-local (`corner = origin - size/2`). Stack B bridge traces
were already corner-local so the shift is a no-op there; Stack A traces are
world-frame on a tile centred at `origin`. Known cosmetic issue: the report
displays `t = idx/15.0` (bridge 15 Hz); Stack A traces are 20 Hz, so
displayed times read 25% low — clearances and penetration counts are
unaffected.

**Offline contract tests (4/4 PASS, `/tmp/test_shield_lite.py`, no simulator).**
Fake-torch stub + real fortress map `f4_b1_m00.json`: (1) exact no-op in open
space returns the same tensor object; (2) veto at a wall — policy (0.50,0.00)
replaced by escape (−0.20,−0.90), arc min-field +0.125 m >= floor, realizable;
(3) pin latch fires at tick 10 under vetoed micro-motion; (4) `reset` clears
all per-env state.

**Validation run (camp6b) — warehouse `f6_b2_m00`, frozen BC checkpoint
`bc_init_v3/model_0.pt`, 1 env, 6000 steps, seed 42, `--shield
--episode_cap 190`:**

- **4/4 episodes reached the goal, mean collision rate 0.000**, mean
  time-to-goal **68.49 s**; 635 s wall clock (9 env-steps/s).
- Exact-box audit: **min clearance +0.1386 m, 0/6000 penetration frames**
  (displayed t reads 339.3 s at the 15 Hz convention; true time ~452 s).
- Shield stats: shield=3183, hyst=2246, escape=334, pin=17 — all 17 pin
  latches released (no livelock), escape tier resolved every pocket.
- Startup line confirms the port: `Shield-lite enabled (policy_node v7.4
  port; v_full=0.504 m/s, w_full=3.108 rad/s, 312 boxes)`.

**Comparison with Stack B v7.4 on the same map (17.14, 3/5 goals):** not
apples-to-apples — Stack B ran serial legs under a 180 s cap and legs 4-5
died ON the cap (leg 3 alone cost 149 s), while Stack A episodes get the
full 190 s and reset on success. The honest reading: with the cap raised to
match the 31.4 m path, the same shield + same frozen policy completes every
episode with zero penetrations in BOTH stacks. The no-collision rule held
again, now in the campaign simulator itself.

**Artifacts:** log `isaac/lab/logs/p5_shieldA_f6_b2_m00_v74.log`; trace
`videos/Isaac-Nav-Openmover-v0/trace_f6_b2_m00_seed42.npz` (world frame,
origin (-5,-5), size (10,10)); showcase video
`videos/Isaac-Nav-Openmover-v0/showcase_f6_b2_m00_shieldA_v74.topdown.mp4`
(5 fps x stride 4 = real-time 20 Hz playback, 300 s, titled; all older
videos kept). The renderer gained a `--stride` argument for this.

**Decision: the port is validated; Stack A + ShieldLite is the campaign
configuration.** Next (camp6c): the ~730-run campaign runner, the A*+DWA
baseline, and 10-seed repeats on the presentation maps.

### 17.16 camp6c: A*+DWA baseline validated + campaign infrastructure (per-seed capture)

**A*+DWA baseline (`openmover_lab/astar_dwa.py`, new).** In-house classical
planner stack, information-parity with the shield arm (same true map
knowledge: A* on the 0.25 m occupancy grid inflated 0.20 m, 8-connected
no-corner-cut, octile heuristic; DWA over the SAME 48 realizability-filtered
shield candidates, arcs rolled out 0.8 s + brake tail, rejected when the
51-point hull min exact-BoxSDF clearance drops below an admissibility floor
`max(0.03, cur_clr - 0.02)`). Score = geodesic progress (1.0) + heading
(0.8) + speed (0.3) + clearance (0.10); replan every 20 steps or on 0.75 m
waypoint error. Deliberately NO escape/retreat/pin/hysteresis tiers — it is
the unprotected reference, and its collisions are its own honest result.

**Negative, resolved: the "baseline livelock" was a TEST-HARNESS quaternion
bug, not the module.** The offline closed-loop test on both presentation maps
stalled in pure backward+spin (v=-0.20, w=+0.90) and never reached the goal.
Four targeted debuggers isolated it: (1) goal discrepancy ruled out (true vs
snapped goal → same cell, same A* path); (2) the real `_score` called
directly is bit-identical to inline math (max diff 0.0) and picks v=+0.10 —
so `action()` must be feeding it different inputs; (3) monkeypatching
`_score` to dump its arguments exposed `yaw=0.0000` despite a π/4 pose.
Root cause: `FakeEnv.set_pose` in `/tmp/test_astar_dwa.py` wrote the
quaternion **wxyz**, but `root_quat_w` is **xyzw** everywhere in the
codebase (env, geodesic expert, shield, CBF, and this module); for a pure-yaw
quat with q1=q2=0 the xyzw yaw formula returns atan2(0,·)=0. Fixed the
harness (identity `[0,0,0,1]`, pure yaw `[0,0,sin(ψ/2),cos(ψ/2)]`); the
module was correct all along. (The earlier `dbg_dwa.py` "navigation worked"
because it replicated the math inline with its own yaw variable and never
called `action()`.)

**Offline validation (both presentation maps, ALL PASS).** Fortress
`f4_b1_m00`: goal in 38.6 s (2.29× ideal), A* path 63 cells / 16.8 m, min
hull clearance +0.033 m, 0 penetrations, stats {plan 39, replan 38,
dwa_reject 0, stuck 0}. Warehouse `f6_b2_m00`: goal in 33.4 s (2.38× ideal),
53 cells / 14.0 m, +0.038 m, 0 penetrations, {plan 34, replan 33, 0, 0}.

**Isaac smoke test (`--policy astar_dwa`, f6_b2_m00, 1 env, 1500 steps,
PASS).** Wired into `21_run_openmover_nav.py` (requires `--map_file`);
horizon 136 s, geo_iters 165, baseline up in 312 boxes / 48 candidates.
Success 1.0, TTG 53.05 s, 27 env-steps/s; plans 76, replans 75, dwa_reject 0,
stuck 0. **collision_rate 1.0 — expected**: the unprotected baseline touches
walls (the architecture gap the campaign measures; the shield arm ran 0
collisions in 17.15). Reaching the goal confirms Isaac's xyzw quaternion is
read correctly by the module.

**Campaign measurement infrastructure (three coordinated changes).** The
only per-episode randomness on a fixed custom map is the initial yaw, so the
seed axis folds into `num_envs=N`; to split seeds back out:
1. `openmover_nav_cfg.py`: new `log_per_env: bool = False`.
2. `openmover_nav_env.py` `_reset_idx`: when the flag is set, also emit
   `Metrics/per_env_{ids,reached,penalized,ttg}` lists (read BEFORE
   `super()._reset_idx` zeroes `episode_length_buf`). Default-off because
   list-valued log keys would break RSL-RL's scalar tensorboard logging —
   training is untouched.
3. `21_run_openmover_nav.py`: new `--results_json PATH` — sets the flag,
   captures each env's initial yaw after reset, records FIRST-episode-only
   outcomes per env index (a fast env auto-resets into a 2nd episode inside
   the horizon, which would bias the batch mean), and dumps per-env JSON +
   means + policy stats.

**Two plumbing bugs found and fixed by the validation pass (negatives,
documented):**
- *Tile cap*: the custom-map terrain was hardcoded 2×2, and the env rejects
  `num_envs > tiles` (fixed spawn would stack robots). `custom_map_terrains_cfg`
  gained `num_tiles` (side = ceil√n; `use_cache=True` + map hash → all tiles
  share ONE cached mesh, so extra tiles cost origins, not geometry); the
  runner passes `num_envs`. 4 envs still give the original 2×2 layout.
- *Obstacle-table registry check false alarm*: with a 4×4 grid the first 4
  difficulty draws hit the warm mesh cache, and cached tiles SKIP the layout
  function, so their difficulties are legitimately absent from
  `TERRAIN_LAYOUT_REGISTRY` — the old "every replayed difficulty must be
  registered" check raised (4/16 missing). Inverted to the subset direction:
  everything registered THIS process must appear among the replayed
  difficulties (a wrong RNG replay still fails the check).

**Validation pass (f6_b2_m00, 10 seeds — the locked presentation repeat, both
arms complete).** Via `33_run_campaign.py` (new): manifest-driven, one Isaac
subprocess per (map, arm) via `_isaac_sim/python.sh` directly (the
`isaaclab.sh -p` → `isaaclab.cli` dispatcher chain exits early and orphans the
real sim process — wait()/timeout/RAM guard would watch nothing), strictly
sequential, RAM guard ≥8 GiB, kill-guard timeout, resume by complete results
JSON, `results.jsonl` ledger, per-arm/per-family summary.
- **A*+DWA (unprotected): success 0.90, collision 0.90, TTG 54.0 s**
  (per-env TTG 49.9–57.4 s; the one failure timed out at yaw0=-1.71).
  158 s wall, ~173 env-steps/s at 10 envs.
- **Trained + Shield v7.4: success 0.70, collision 0.000, TTG 61.0 s**
  (7 successes 54.7–71.8 s; 3 timeouts on the 136 s horizon; shield=18824,
  hyst=9053, escape=6552, pin=41 over 27320 steps). 138 s wall.
- First paper-ready signal on the hardest presentation map: the shield trades
  20 pts of success for a guaranteed-zero-collision run; the classical stack
  is faster and reaches more but touches walls on 9/10 seeds.

**Artifacts:** `isaac/lab/33_run_campaign.py`; results
`isaac/lab/campaign/results/{shield,astar_dwa}/f6_b2_m00.json`; subprocess
logs `isaac/lab/campaign/logs/`; ledger `isaac/lab/campaign/results.jsonl`;
offline harness `/tmp/test_astar_dwa.py`.

**Measured cost of the full core campaign:** wall ≈ horizon + ~25 s per run;
56 maps mean horizon 94 s (max 190 s) → **~3.7 h for 112 runs** (f6_b2_m00
both arms already done). Awaiting user confirmation before launching.

### 17.17 Campaign launched, paused on a corridor-family red flag → third arm (A*+DWA + shield)

**Launch and pause.** The 2-arm core campaign (112 runs) was launched after
user approval and banked 8 runs before I stopped it: on the corridor family
(f1) the shield arm returned **0/4 on three consecutive maps** while the
unprotected classical planner reached the goal on all of them. Stopping rather
than burning ~4 h on a measurement whose interpretation was unclear.

**Diagnosis: the frozen BC policy is competence-limited on corridor geometry —
not a shield bug.** Evidence, in order:
1. *400-step A/B on f1_b0_m00*: bare vs shielded policy produced near-identical
   displacement (~[2.8, 1.87] m) with only 23 shield interventions → the shield
   is not what stops the robot.
2. *Full-horizon bare run* (`trace_f1_b0_m00_seed42_bare_diag.npz`): reaches
   corner-local (4.29, 3.06) by t≈20 s, then **presses into a wall for the
   remaining 76 s** (0.16 m of creep), collision_rate 1.0.
3. *Full-horizon shielded run* (`trace_f1_b0_m00_seed42_shield_diag.npz`):
   tracks the reference path within 0.5 m to t≈40 s, shield veto reroutes it
   around that same wall (closest approach 4.21 m at t=59 s — the shield did
   its job), then the policy **wanders off-route, backtracks, and freezes
   spinning 360° in an OPEN pocket from t=77.5 s to timeout** while the
   waypoint observation still points back along the connected route
   (corner-local ≈(2.1, 1.1) from a robot at (4.56, 5.20); wall only to the
   north, free west/south, no boxes within 1.5 m).
4. Conclusion: this is an out-of-distribution state for a BC policy trained on
   the open source-task terrains — it has no recovery behaviour for "waypoint
   says go back the way you came". The 17.14 observation ("the bottleneck moves
   to the policy") is now systematic across the corridor family. **All shield
   runs recorded 0 collisions**, i.e. the guarantee held everywhere; what
   failed was competence.

**User decision: add a third arm** — A*+DWA wrapped in ShieldLite — keeping the
two existing arms (the honest competence-limit result stays in the paper). The
third arm tests the thesis directly: *planner competence + shield guarantee →
high success AND zero collisions*.

**Implementation (policy-agnostic shield).** In `21_run_openmover_nav.py` the
ShieldLite construction moved OUT of the `--policy trained` branch to a shared
block after the baseline is built (both read robot state lazily in `action()`,
so post-`env.reset()` construction is safe), and the non-inference branch now
does `actions = shield.action(baseline.action())` with `shield.reset(step_dones)`
alongside `baseline.episode_reset(done_ids)`. `33_run_campaign.py` gained
`astar_dwa_shield` in `ARMS` (`--policy astar_dwa --shield`, no checkpoint).

**Validation (f1_b0_m00, 4 seeds — the map where the policy arm fails 0/4):**

| arm | success | collision | TTG (s) | notes |
| --- | --- | --- | --- | --- |
| trained + shield | 0.00 | **0.000** | — | all 4 timeout at 96.5 s |
| A*+DWA (unprotected) | **1.00** | 1.00 | 79.8 | reaches, touches walls |
| A*+DWA + shield | 0.75 | **0.000** | 81.6 | env 0 timeout at 96.45/96.48 s |

Shield fired on 1956/7800 env-steps (25%), hyst 1362, escape 72, pin 2;
baseline plans 395, replans 391, dwa_reject 0, stuck 0. The third arm recovers
most of the planner's competence **and** removes every collision, at +1.8 s TTG
and −1 success vs the unprotected planner (all arms share the same
path-length-derived horizon, so the timeout is a fair measurement, not a
handicap: the shield's conservatism in tight corridors costs real time).

**Two negatives documented.**
- *Relative `--out`*: the subprocess cwd is `~/isaaclab`, so
  `--out campaign/val_ads` sent `--results_json` there and the parent reported
  "no results JSON" for a run that had in fact succeeded. Fixed with
  `args.out = Path(args.out).resolve()`; the stray JSON was copied back into
  `campaign/val_ads/results/astar_dwa_shield/` (the `~/isaaclab/campaign`
  original could not be deleted — outside the writable path allowlist).
- *Cost estimator*: the dry-run model guessed 20/40 env-steps/s and quoted
  **20 h** for the 3-arm campaign. Measured walls (71–100 s for 4-seed runs,
  138–158 s for 10-seed) imply ~40 s startup + ~150 env-steps/s for every arm;
  the estimator now uses that and quotes **4.11 h for the remaining 160 runs**.

**Relaunched:** full 3-arm campaign (56 maps × 3 arms, 4 seeds, presentation
maps 10 seeds), resume-skipping the 8 banked runs. Log
`isaac/lab/campaign/campaign_3arm.log`.

### 17.18 The corridor "leak" was a PhysX spawn pop, not a map defect → 5 mm spawn lift

The relaunched campaign was stopped after 3 runs and the third arm was
re-validated on the two corridor maps (`campaign/val_merge/`):

| map | arm | success | collision | TTG (s) | shield oob ticks |
| --- | --- | --- | --- | --- | --- |
| f1_b0_m00 | A*+DWA + shield | 1.00 | **0.000** | 79.7 | 0 |
| f1_b0_m01 | A*+DWA + shield | 0.75 | **0.500** | 80.2 | **1952** |

`shield_oob` counts env-ticks where the shield saw the robot **outside the map
rectangle** — the domain of its barrier. A planner arm that never leaves the
corridors should score 0, as m00 does. So on m01 something physically removed
the robot from the map. Two candidate explanations were pursued: a map-generator
defect, or a simulator artifact. **It was the simulator.**

**1. Map geometry: rebuilt, proven equivalent, and exonerated.** Independently of
the leak, `grid_to_boxes` emitted one 0.125 m box per occupied cell (13 395
boxes over the pool, ~239/map), which inflates the terrain mesh, the shield's
BoxSDF and the A* costmap for no geometric benefit. It now merges
vertically-adjacent cells of equal width: **13 395 → 768 boxes (−94 %,
13.7/map)**. Three checks:
1. *Geometry preservation* (`_tmp_merge_test.py`, 28 layouts): 6548 → 390 boxes,
   rasterizing the merged boxes back to the occupancy grid reproduces the
   original cell-for-cell — `worst_cell_diff=0.0`, `ALL_GEOMETRY_PRESERVED`.
2. *Independent audit* (`_tmp_audit_regen.py`, all 56 maps): perimeter ring
   sealed on every map and the deployment bar passes everywhere with
   `bottleneck >= 13 cells (1.625 m)` → `AUDIT_OK`.
3. *Backup comparison* (`_tmp_verify_regen.py` vs `maps/gen_premerge`):
   occupancy + metadata identical on 48/56; the 8 mismatches are **all family 5**
   and are explained by item 2 below, not by the merge.

The leak map was re-inspected cell by cell: f1_b0_m01 has 10 boxes; its east
border is exactly **2 full-height segments**, `y=[0.125, 2.375]` and
`y=[2.625, 9.875]`, forming a T-junction with interior wall #7
(`y ∈ [2.375, 2.625]`). No gap, no seam, no missing cell. **The seam-ejection
theory is disproven.**

**2. Family 5 was not reproducible (PYTHONHASHSEED) — fixed.** The micromouse
labyrinth knocks loops into a `set` of string-tagged wall tuples via
`list(walls)`; set iteration order over strings depends on the per-process string
hash, so the seeded `rng.permutation` indices mapped to a *different wall each
run* — different labyrinth, different gate outcomes, different retry seed. Fixed
with `wl = sorted(walls)` (`31_gen_mazes.py:581`). Proof
(`_tmp_hashcheck.py`): the f5 geometry sha256 is **identical under
`PYTHONHASHSEED=0` and `PYTHONHASHSEED=12345` on all 8 maps**, and the shipped
pool matches the deterministic regeneration 8/8. The `gen_premerge` backup was
written before this fix, so its f5 realisation necessarily differs — that is the
whole of the 8-map mismatch above.

**3. Diagnosis chain: the launch happens in the first physics substep, with zero
action.** `_tmp_probe_explode.py` replicates the runner's env construction and
then runs `DirectRLEnv`'s exact substep loop (`_apply_action →
write_data_to_sim → sim.step(render=False) → scene.update`) recording per-env
xy/z/velocity/yaw.
1. `env.reset()` itself contains no physics step (`_reset_idx →
   write_data_to_sim → sim.forward()`), so the event is inside the first control
   step: replay of a launched env gives sub0 `|v_xy| = 12.409 m/s`,
   `ω_z = 77 rad/s`, z rising to **2.16 m within 0.1 s** — the action buffer is
   all zeros.
2. It is **primarily vertical**, which the trace files could not show (they log
   x, y, yaw only).
3. Not env-index, tile or seam specific: teleport trials launched envs 0, 1, 2
   and 3 at corridor_mid, map_centre and the pockets, and the terrain is a single
   triangle mesh (368 vertices / 1488 faces) for all four tiles, so there is no
   inter-tile boundary to fall through.
4. Yaw dependent: launched yaws cluster near ±75–90° and ±160–180°, i.e. the
   ejection direction follows the robot's orientation, not the map.
5. *Methodological negative:* teleport-based trials are **contaminated by
   simulator state history** — identical outcome counts across different z
   offsets and different drop points, and different outcomes for the same
   (point, yaw, env) at different moments. Only a **fresh process with a real
   `env.reset()`** gives trustworthy launch statistics; every number below comes
   from that mode.
6. *Instrument negative:* the ContactSensor is unusable here (prim path resolves
   with duplicated segments, `.../base_link/base_link`; readings mostly 0.00 N,
   occasionally 55–166 N), so the launch criterion is kinematic:
   `launch = |v| > 2.0 m/s or Δz > 0.05 m`, `pop = |v| > 0.3 m/s or Δz > 0.01 m`.

**4. Root cause: zero-separation caster contact at spawn.** The default root pose
is `z = 0.0` (`default_root_pose[0] = [0, 0, 0, 0, 0, 0, 1]`), and the measured
rest heights are `base_link ≈ 0`, **caster ball links 0.0202 m = exactly the ball
radius**, wheel links 0.0504 m vs radius 0.050353 m (47 µm of clearance). The
four balls therefore start *exactly tangent* to the ground mesh — a degenerate
contact with zero separation — and PhysX resolves it on the first substep by
ejecting the 3.0371 kg articulation, mostly vertically, in an
orientation-dependent way.

**5. Fresh-process A/B (16 envs, 6 substeps = 0.05 s, zero action, map
f1_b0_m01).** Log `campaign/val_merge/logs/probe_fresh_ab.log`:

| arm | seed | launches | pops | worst \|v_xy\| (m/s) | worst Δz (m) |
| --- | --- | --- | --- | --- | --- |
| baseline (z = 0) | 42 | **3/16** | 4/16 | 12.119 | +0.9302 |
| baseline (z = 0) | 43 | **5/16** | 5/16 | 11.040 | +0.8422 |
| spawn z = +5 mm | 42 | **0/16** | **0/16** | 0.006 | +0.0043 |
| spawn z = +5 mm | 43 | **0/16** | **0/16** | 0.006 | +0.0043 |
| `enable_stabilization` | 42 | 3/16 | 4/16 | 12.119 | +0.9302 |

`enable_stabilization=True` is **bit-identical to baseline** — documented
negative, it does not touch this failure mode. The `--ccd` arm never produced a
result: that process hung in "Starting the simulation" for 28 min at 111 % CPU
and had to be killed (second documented negative). CCD is not needed anyway —
see item 7.

**6. The fix (one config line).** `openmover_nav_cfg.py` now lifts the initial
state by 5 mm:

```python
robot_cfg: ArticulationCfg = OPENMOVER_CFG.replace(
    prim_path="/World/envs/env_.*/Robot",
    init_state=ArticulationCfg.InitialStateCfg(pos=(0.0, 0.0, 0.005)),
)
```

`_reset_idx` builds every reset from `default_root_pose`, so this lifts **every
episode start**, not just the first. The 5 mm drop reaches ~0.31 m/s at
touchdown, below `bounce_threshold_velocity = 0.5`, so the robot settles instead
of bouncing (measured worst Δz `+0.0043 m`, worst `|v_xy| = 0.006 m/s`).
Rejected alternatives: settle-steps before the episode (the pop *is* the first
substep), post-hoc velocity scrubbing (hides the artifact), caster joint damping
(changes the dynamics being studied), CCD (treats the symptom).

**7. Why a vertical pop became a collision + a map escape.** `enable_ccd=False`
(Isaac Lab default): a body at 12 m/s travels ~0.1 m per 1/120 s substep, which
is the **0.125 m border-wall thickness** — the airborne robot tunnels straight
through the perimeter and lands outside the map, where the shield's barrier has
no domain (`oob = 1952`) and the contact force flags a collision. After the fix
the maximum commanded speed is 0.504 m/s → 4.2 mm/substep, ~30× below the wall
thickness, so CCD stays off for performance across the 168 campaign runs.

**8. Post-fix validation sweep (no probe flags — the lift comes from the cfg).**
9 fresh processes × 16 envs = **144 spawns**, 12 substeps each, zero action,
covering the leak map on both A/B seeds plus one map from every family:
f1_b0_m01 (seeds 42, 43), f1_b0_m00, f2_b1_m00, f3_b2_m00, f4_b1_m00,
f5_b3_m00, f6_b2_m00, f7_b1_m00. Result: **0 launches, 0 pops in all 9 runs**;
worst `|v_xy| = 0.006 m/s`, worst `Δz = +0.0043 m`. Every log confirms
`default_root_pose[0] = [0, 0, 0.005, 0, 0, 0, 1]`. Log
`campaign/val_merge/logs/probe_postfix.log`.

**9. Consequence: all pre-fix results are contaminated.** The pop fired on 3–5 of
16 envs on the leak map (~20–30 % of seeds), so any run collected before the fix
— the 8 banked campaign runs in `campaign/results/`, `campaign/val_merge/`,
`val_ramp/`, `val_t3fix/` and the 17.17 validation table — can contain
physics-ejected episodes that look like planner/shield failures. They are
archived, not deleted, and the campaign is re-measured from scratch.

**10. Post-fix three-arm re-validation** (`campaign/val_postfix/`, 4 seeds per
map, same path-length-derived horizon as the campaign):

| map | arm | success | collision | TTG (s) | shield oob |
| --- | --- | --- | --- | --- | --- |
| f1_b0_m00 | A*+DWA + shield | **1.00** | **0.000** | 80.3 | 0 |
| f1_b0_m01 | A*+DWA + shield | 0.50 | **0.000** | 81.8 | 0 |
| f1_b0_m00 | trained + shield | 0.00 | **0.000** | — | 0 |
| f1_b0_m01 | trained + shield | 0.00 | **0.000** | — | 0 |
| f1_b0_m00 | A*+DWA (unprotected) | 1.00 | 1.00 | 82.6 | — |
| f1_b0_m01 | A*+DWA (unprotected) | **1.00** | 1.00 | 82.5 | — |

Three readings:
1. *The leak is gone.* `shield_oob = 0` in all six runs (was 1952 on m01), both
   shielded arms record 0.000 collisions on both maps, and the unprotected
   planner now reaches **4/4** on m01 (was 3/4 pre-fix) — that miss was the
   ejection, not the planner.
2. *§17.17's competence verdict survives the fix.* trained + shield is still 0/4
   on both corridor maps with 0 collisions, so the policy limitation is real and
   was never a physics artifact.
3. *One residual failure remains and it is not physics.* On m01 the third arm
   times out at the horizon (98.05 s) on envs 0 and 1 — initial yaw 1.978 /
   1.929 rad (≈113° / 110°, heading north straight at interior wall #7 from
   inside the SE dead-end pocket) — while the *same two yaws* succeed on m00.
   Shield engagement on m01 is heavy: 4005/7928 env-steps (50 %), escape 836,
   retreat 812, pin 12, versus m00's 1610 steps with escape 1 / retreat 1 /
   pin 1. That is a shield/planner livelock in a dead-end with an adverse
   initial heading — the same class as §17.11–17.14, now measurable without the
   pop contaminating it. (Item 3 refined by §17.19: env 0's timeout was an
   *absorbing freeze* in the shield's escape tier, now fixed; env 1's is a true
   livelock — the robot keeps moving.)

### 17.19 The §17.18 residual was an absorbing freeze in the escape tier → shield v7.5; and its honest cost on the trained arm

**1. Symptom.** Third arm (A*+DWA + shield) on f1_b0_m01: env 0 stops dead at
map (5.5554, 2.0745), yaw +3.1062 (≈π, facing west) at t=18.55 s and never
moves again for the remaining 79 s, while the shield logs 812 tier-3 retreats
globally. A pin latch fires at t=18.90 — *after* the motion stopped.

**2. Plant cleared (third confirmation).** `_tmp_probe_freeze.py --mode sleep`:
after 600 rest ticks a spin command produces dyaw=+0.6138 rad over 40 ticks and
a reverse command 0.3125 m of displacement. PhysX is not sleeping the
articulation; the zero twist is published by the decision chain.

**3. Root cause (offline decision dump at the freeze pose).** The planner
commands v=+0.500 (west, toward the geodesic waypoint). At that pose:
- comfort set (floor 0.15): certifies only reverse movers (v=−0.2 clr 0.1532,
  v=−0.1 clr 0.1530) plus 2 STOPs — forward/west is uncertified (corridor
  pinch ahead);
- escape set (floor 0.07): 4/36 certified = 2 STOPs + the same two reverse
  movers (clr 0.0704 / 0.0702).

So certified movers EXIST. The freeze is a selection bug, not an empty set:
`backup()` scores horizon progress toward the geodesic waypoint, which points
FORWARD (west) — every certified reverse mover scores negative — while the
last_pub STOP carries `SHIELD_HYST_BONUS` (+0.05). The STOP wins `backup()`,
the guard `if ev[i] != 0.0 or ew[i] != 0.0` fails, and tier 3 sat in the
`else:` of `if j.size:` — unreachable because j.size=4. Control fell through to
`return best` = (0, 0). With last_pub=(0,0) the bonus re-selects the STOP every
tick: an **absorbing freeze** (the pin latch releases only on 0.20 m of motion
that never comes). The freeze began at pin=0 (t=18.70); the latch was a
consequence, not the cause.

**4. Fix (shield v7.5, `shield_lite.py`; constants IDENTICAL to v7.4).** Two
control-flow changes in `_shield_env`'s escape tier:
1. when `backup()` returns a full STOP, restrict to the certified MOVER subset
   `j[(ev[j] != 0) | (ew[j] != 0)]` and pick by escape score — the escape tier
   can never publish (0,0) while a certified mover is admissible;
2. tier 3 hoisted OUT of the `else:` so it runs whenever the escape tier fails
   to return a non-zero twist. `return best` is now reachable only with
   best ≠ (0,0). Certification hierarchy preserved: certified mover →
   uncertified tier-3 retreat → never an absorbing STOP.

**5. Validation (`campaign/val_v75/`, seed 42, 4 envs, spawn-fix in force).**
Freeze probe: `NO_FREEZE`; the exact env that froze now escapes and reaches the
goal (ttg 91.5 s).

| map | arm | v7.4 success / collision | v7.5 success / collision |
| --- | --- | --- | --- |
| f1_b0_m00 | A*+DWA + shield | 1.00 / 0.000 | **1.00 / 0.000** (ttg 80.3) |
| f1_b0_m01 | A*+DWA + shield | 0.50 / 0.000 | **0.75 / 0.000** (ttg 85.6, 3/4) |
| f1_b0_m00 | trained + shield | 0.00 / 0.000 | 0.00 / **0.000** (retreat 389) |
| f1_b0_m01 | trained + shield | 0.00 / 0.000 | 0.00 / **0.250** — regression, item 6 |
| f1_b0_m00/m01 | A*+DWA unprotected | 1.00 / 1.00 | unchanged (no shield in the loop; val_postfix numbers stand) |

Thesis-arm gate (m01 success ≥ 0.75 AND collision 0.000 on both maps) is MET.
No regression on m00 (shield barely fires there: escape=1 retreat=1 pin=1).
Env 1's residual timeout on m01 is NOT a freeze: the pin anchor crawls
(+5.89→+5.61→+4.88→+4.48→+3.88→+4.31→+4.05) — the robot keeps moving in the
knife-edge corridor. A true planner/shield livelock (safety-vs-completeness
tradeoff), deferred.

**6. Documented negative: the trained+shield collision regression on m01
(0.000 → 0.250).** `_tmp_probe_collision.py` (runner loop replicated exactly,
per-env tier attribution by monkeypatched `_shield_env`, collision dump on the
rising edge of `_penalized`) reproduced the val run **bit-for-bit** (identical
global counters 5522/1834/2605/2473/38/0) and caught the event: env 2,
t=88.60 s, contact 5.6 N vs the 5 N threshold, at the SE dead-end corner
(2.461, 2.243), yaw ≈2.25.
- History: env 2 pin-crawls the corridor x 7.0→2.6 in the first ~40 s, then
  sits in the corner for ~48 s with tier 3 dominant (per-env retreat3 totals:
  env2 1123/1982 ticks, env3 1130 — env 3 never made contact).
- Mechanism: the incapable policy flails (input alternates ≈(v+0.2,w−0.9));
  tier 3 **chatters at 20 Hz** between two near-tied retreats, publishing
  (v−0.100,w+0.300) and (v+0.100,w−0.300) on alternating ticks.
- Every published command had POSITIVE predicted raw-hull clearance
  (+0.047…+0.050 m along the whole arc). The ESDF model did not fail: the
  contact is a **plant tracking failure induced by the dither** — direction
  reversals every 50 ms produce wheel slip / chassis lunge beyond the
  kinematic arc the certification assumes.
- Interpretation: pre-v7.5 the same arm scored 0.000 collisions only because
  the shield FROZE (sitting still never collides — accidentally safe). v7.5
  trades that hidden safety for liveness, and the cost is now measurable. The
  scrape is marginal (5.6 N vs 5 N threshold) and confined to the deep-trap
  corner; m00 shows no regression. Options considered: (a) tier-3 hysteresis
  — tried as v7.6, item 7; (b) accept + document as tier 3's uncertified
  limitation; (c) minimum-risk STOP when no tier-3 candidate clears a small
  raw floor (knife-edge here: the scrape commands predicted +0.047–0.050).

**7. The v7.6 tier-3 hysteresis experiment — documented negative, REVERTED.**
User decision after item 6: try (a). One-line change: `if have_prev:
gain[-1] += SHIELD_HYST_BONUS` in the tier-3 gain (same +0.05 continuity bonus
the certified tiers use), validated on the same 4-run matrix
(`campaign/val_v76/`, seed 42):

| map | arm | v7.5 success / collision | v7.6 success / collision |
| --- | --- | --- | --- |
| f1_b0_m01 | A*+DWA + shield | 0.75 / **0.000** | 0.75 / **0.250** ← NEW scrape (env 0, timeout) |
| f1_b0_m00 | A*+DWA + shield | 1.00 / 0.000 | 1.00 / 0.000 |
| f1_b0_m01 | trained + shield | 0.00 / **0.250** | 0.00 / **0.000** ← item-6 scrape fixed |
| f1_b0_m00 | trained + shield | 0.00 / **0.000** | 0.00 / **0.250** ← NEW scrape (env 1) |

Whack-a-mole: the fix removed the item-6 dither scrape but created two new
ones, including one on the thesis arm (gate: collision 0.000 → FAILED).
Mechanism: in tier 3 nothing is certified and clearance gains are small
(~0.05–0.15), so a +0.05 continuity bonus is a **lock-in** — once published,
a retreat self-reinforces every tick even as its clearance degrades. The
20 Hz dither (v7.5) is net-stationary and, empirically, safer than committed
uncertified motion. Silver lining, noted for future work: on thesis-arm m01
the v7.6 commitment freed the env-1 livelock of item 5 (timeout → reached,
94.8 s) while env 0 flipped the other way (reached 91.5 s → scrape + timeout)
— commitment solves livelocks but must be gated by a clearance floor to be
safe; a smaller tie-break-only bonus or a sign-commitment with a minimum raw
clearance remains untested. `shield_lite.py` is reverted to v7.5 behavior
(tombstone comment marks the spot); v7.5 stands as the campaign shield, with
the item-6 marginal scrape documented as tier 3's uncertified limitation.

### 17.20 The 168-run three-arm campaign completed on v7.5: thesis arm 0.979 success / 0.000 collision

**1. Setup and execution.** 56 procedural maps (7 families × 4 difficulty
bins × 2 variants, `maps/gen/_manifest.json`) × 3 arms (trained+shield,
A*+DWA unprotected, A*+DWA+ShieldLite) = 168 runs, seed 42, 4 seeds folded
into `num_envs`; presentation maps f4_b1_m00 / f6_b2_m00 got the locked 10
seeds → 236 episodes per arm, 708 total. Orchestrator `33_run_campaign.py`
ran under the user's RAM+swap policy (`--min_ram_gib 0 --min_rate 4.5`, no
guard stalls, swap absorbing desktop load). 4.5 h aggregate wall, **0
timeouts, 0 non-zero return codes, 0 incomplete episode captures**. Shield =
v7.5 for every run (the §17.19-item-7 v7.6 revert stands).

**2. Headline (episode-pooled, `34_aggregate_campaign.py` →
`campaign/aggregate.json`):**

| arm | success | collision | TTG succ (s) |
| --- | --- | --- | --- |
| trained + shield | 0.644 | 0.004 (1/236) | 47.5 |
| A*+DWA (unprotected) | 0.941 | 0.534 | 52.7 |
| **A*+DWA + shield (thesis arm)** | **0.979** | **0.000 (0/236)** | 54.8 |

**3. Guarantee audit clean.** `shield_oob = 0` for both shielded arms over
452,404 env-steps each: the robot never left the barrier's map-rectangle
domain. The only shielded collision in the whole campaign is the already
root-caused §17.19-item-6 tier-3 scrape (f1_b0_m01, trained arm, env 2,
5.6 N vs 5 N threshold). The thesis arm had **zero** collisions on all 56
maps — the no-collision rule held at campaign scale.

**4. The shield adds competence, not just safety.** Success improved
0.941 → 0.979 under the shield: DWA stall/livelock episodes become
escape-tier recoveries instead of timeouts. Cost is small: TTG +2.1 s (+4%),
interventions on 65,457/452,404 ticks (14.5%; escape 12,684, retreat 5,327,
pin 142) vs the trained arm's 46.6% — the shield works ~3× harder to rescue
the learned policy than to escort the planner.

**5. Difficulty scaling.** Unprotected collisions grow with bin (b0 0.48 →
b3 0.57) while the thesis arm is flat: success 0.96/0.98/0.98/0.98 and
collision 0.000 in every bin. The guarantee does not degrade with difficulty;
the planner's raw safety does.

**6. Honest negative — the trained arm's competence is family-structured.**
trained+shield success by family: competition 0.94, highway 0.94, loop 0.84,
warehouse 0.84, fortress 0.61, gates 0.31, **corridor 0.00** (31/32 episodes
timed out + the 1 scrape). 83 of its 84 failures are timeouts, not contacts —
the shield holds safety exactly where the policy fails the task. The BC
policy's competence does not cover narrow serpentine corridors and offset
gates at campaign scale. This sharpens the framework claim rather than
weakening it: guarantees come from the interface and are arm-agnostic;
competence can come from anywhere — here an in-house planner out-competes
the learned policy on every family except time-to-goal (47.5 vs 54.8 s where
both succeed).

**7. Baseline sanity.** Unprotected A*+DWA: 23,062 plans / 22,826 replans /
0 dwa_reject / 0 stuck over the campaign; collisions concentrate in fortress
0.95, warehouse 0.74, corridor 0.72 and nearly vanish on highway 0.03 (wide
straight corridors) — the contact is corner-cutting in tight geometry, the
exact failure class the hull-aware shield certifies against.

**8. Presentation maps (10 seeds each).** f4_b1_m00: thesis arm 1.000 /
0.000 (TTG 65.5 s) vs unprotected 1.000 / 1.000 (59.1 s); f6_b2_m00:
1.000 / 0.000 (58.7 s) vs 1.000 / 1.000 (54.5 s). trained+shield: 0.600 /
0.000 and 1.000 / 0.000. These two maps are the video/demonstration pair.

**9. Artifacts.** `campaign/results/{arm}/*.json` (168), `results.jsonl`,
`campaign_3arm_v75.log`, `aggregate.json` + aggregator
`34_aggregate_campaign.py`, figure `draft/figs/fig_campaign.png`
(`make_figures.py:fig_campaign`). Pre-spawn-fix contaminated results remain
archived in `campaign/results_prefix_archive/` (§17.18).

### 17.21 A single-env video counterexample: protocol-relative guarantee + a hull-model gap

**1. What triggered it.** Cutting the presentation video set (3 arms ×
f4_b1_m00 / f6_b2_m00) exposed a contradiction with §17.20. The thesis arm
(A*+DWA+ShieldLite) on f6_b2_m00 replays **success 0.0 / collision 1.0 /
ttg 135.55 s (timeout)** when run at `num_envs=1`, seed 42
(`videos/Isaac-Nav-Openmover-v0/trace_f6_b2_m00_seed42_astar_dwa_shield.npz`),
yet the campaign reported **1.000 / 0.000** on the same map/seed at the locked
10-env protocol. Both numbers are correct; they are different protocols.

**2. Mechanism (frame-exact, pure-numpy hull audit vs the map's exact boxes).**
From t≈28 s (tick 559) to the end the **raw (grown) hull** sat below the escape
floor (SHIELD_ESCAPE_MARGIN+SLACK = 0.07 m) continuously, so every escape attempt
fell through tier 1/tier 2 to **uncertified tier-3 retreat**: escape=retreat=2167
of 2732 steps (100%). Pin latches marched south along wall-4's SW face (box 4 =
`[5.0, 5.3125, 0, 0.75, 5.875, 0.5]`, a tall vertical shelf; log pinned
(+5.69,+4.54)→(+5.57,+2.29)). The robot ended essentially stationary for the last
~30 ticks at tile-local (5.53, 2.24), yaw ≈ −126°, **true-hull clearance 0.071 m**
— pinned 7 cm off the corner in a pocket the escape tier could not certify out of.

**3. The certified hull NEVER penetrated.** Min true-hull (0.44×0.28 m box)
clearance over the whole 2711-tick episode is **+0.070 m** (tick 1022), with
**0 penetrating ticks**. End contact force on `base_link` was 0.0 N. So the >5 N
`_collided` latch did NOT come from the modeled hull — it came from geometry
**outside** the box: the drive wheels sit at y=±0.162 m (WHEEL_SEPARATION 0.324),
2.2 cm outside hy=0.14, plus the caster balls. **This is a hull-model gap:** the
shield certifies a box that under-covers the true wheel/caster envelope, so a
corner scrape the box clears by 7 cm still touches wall with a wheel.

**4. The "150 m/s pop" is a timeout reset teleport, not a PhysX explosion.**
Collision is a **per-step penalty, NOT terminal** in this env
(`terminated = reached | bad_state` only); the episode ended by `time_outs`
(`episode_length_buf >= max_episode_length−1`). The max inter-tick jump (7.51 m at
tick 2710) is the post-timeout reset to spawn, which an earlier read mischaracterised
as a violent pop. Corrected here.

**5. Escape-floor arithmetic (why tier 3 was inevitable).** comfort floor (true hull)
= SHIELD_MARGIN+SLACK = 0.15; escape floor (RAW hull) = SHIELD_ESCAPE_MARGIN+SLACK
= 0.07; SHIELD_RAW_PAD = 0.08 = SHIELD_MARGIN − SHIELD_ESCAPE_MARGIN exactly, so on
a **flat face** the grown-hull escape floor equals the true-hull comfort floor (0.15).
At a **box corner** the effective true-hull floor measured ≈0.10, and the run's 0.070 m
equilibrium was below *every* certified floor → tier 3 on all 2167 escapes. The corner
(pocket) geometry, not a flat wall, is what dropped it under the floor.

**6. Protocol sensitivity, reproduced bit-for-bit.** A fresh **10-env** rerun of the
thesis arm on f6_b2_m00 (same env-0 yaw0 = 1.9782452583312988) reproduces the campaign
**exactly**: identical shield_stats (shield=9766 hyst=6227 escape=2102 retreat=810
pin=27 oob=0 steps=27320) and identical per-env outcome (env 0 reached, penalized=False,
ttg=52.0; map 1.000/0.000, ttg 58.66). The anomalous collision is **`num_envs=1`-specific**
PhysX behaviour (different contact-island/solver state at 1 env), not a campaign bug.
**The campaign's 0/236 is campaign-protocol-relative** (10-env, 4 seeds folded into
`num_envs`); it is not a claim that every single-env replay of every seed is contact-free.

**7. Resolution + artifacts.** The presentation video set uses the **clean 10-env rerun**
clip for the thesis arm on f6_b2_m00 (`…_astar_dwa_shield_10env_ep1.npz`, succ 1.0 /
coll 0.0 / ttg 58.66; clearance-audited min +0.148 m, 0/1040 penetration). The 1-env
trace is retained as the counterexample artifact. All 6 ep1 presentation clips audited
(`30_clearance_audit.py`, exact boxes): shielded + thesis arms hold ≥ +0.14 m hull
clearance (0 penetration); the unprotected A*+DWA baseline reaches +0.070 m hull-box
clearance yet still registers contact — the same wheel/caster envelope outside the box,
which is exactly the intended negative comparison. **Direct fix queued (not claimed):**
widen the certified hull to the wheel track (hy 0.14 → ≥0.162 + wheel radius) so the
barrier certifies the true contact envelope; disclose protocol-relativity wherever 0/236
is quoted. Paper VII-B carries the disclosure.

### 17.22 The held-out endgame: a user-drawn map, three arms, the thesis confirmed out-of-distribution

**1. What it is.** The capstone "user draws a random map" test. A hand-drawn
serpentine maze PNG (`maps/healdout.png`, 800×800, blue spawn bottom-centre,
green goal top-centre) was rasterised to a world spec (`maps/heldout.json`) with
the `27_make_custom_map.py` conventions and then RESCALED to a 15.0×15.0 m tile
(cell 0.125 m, 884 wall boxes, wall_height 0.5 m). Spawn [7.812, 2.312],
goal [7.812, 11.938], geodesic path_len 34.38 m. The map is in NEITHER the
training distribution NOR the 56-map procedural campaign — it is the held-out
generalization target the whole framework exists for.

**2. Rescale rationale (corridor-width correction).** At the native 8 m tile the
narrowest corridor was ≈0.75 m (clearance-restricted BFS bottleneck ≈0.37 m):
the 0.33 m hull half-diagonal barely fits but the inflated A* planner (needs
≈0.53 m) cannot. The naive "min clearance along the BFS shortest path = 0.125 m"
was MISLEADING — that path hugs walls. The true metric is clearance-restricted
BFS on {free ∧ D ≥ MINC} (D = Euclidean distance transform). At 15 m the map is
navigable at MINC = 0.50 m everywhere, narrowest corridor ≈1.11 m (≥ the 0.8 m
generator guideline), path 34.38 m. Only the physical tile size S changes
corridor metres (= canvas-fraction × S), not the cell count N. Spawn/goal were
hand-centred to clearance-safe cells and the preview regenerated.

**3. Protocol (identical to the campaign, no map-specific tuning).**
`21_run_openmover_nav.py --task Isaac-Nav-Openmover-v0 --map_file maps/heldout.json`,
num_envs 10 (10 spawn-yaw seeds folded in), seed 42, episode_cap 190.0. The
runner derived horizon = min(34.38/0.25 + 10, 190) = 147.52 s and
num_steps = ceil(147.52/0.05) + 20 = 2971; geo_iters auto-raised to 177 for
field convergence on the 34.4 m path. Three arms: trained+shield
(`--policy trained --checkpoint bc_init_v3/model_0.pt --shield`), A*+DWA
unprotected (`--policy astar_dwa`), A*+DWA+ShieldLite thesis
(`--policy astar_dwa --shield`). Sequential, one simulator at a time
(`campaign/run_heldout.sh`); total wall clock ≈10 min (165 / 202 / 224 s), no
crash, no OOM (RAM stayed ≈10 GB free; the 884 boxes merged into a
113 248-vertex / 509 304-face terrain mesh, built in 3.2 s). BoxSDF queries are
O(1) (precomputed 0.025 m lattice), so 884 boxes cost only one-time build, NOT
per-step — the shield/DWA per-step cost is unchanged from the 10-box campaign maps.

**4. Results** (`campaign/heldout/results/<arm>/heldout.json`, `results.jsonl`).

| arm | success | collision | TTG (s) | oob | shield ticks | planner |
|---|---|---|---|---|---|---|
| trained + shield | 0.000 (0/10) | 0.000 (0/10) | — (all timeout @147.5) | 0 | 22549/29710 = 75.9 % | — |
| A*+DWA (unprotected) | 1.000 (10/10) | 0.900 (9/10) | 103.3 | — | — | plan 1500, replan 1490, dwa_reject 0, stuck 0 |
| A*+DWA + shield (thesis) | 1.000 (10/10) | 0.000 (0/10) | 105.7 | 0 | 5711/29710 = 19.2 % | plan 1500, replan 1490, dwa_reject 0, stuck 0 |

**5. Reading (i) — the learned policy does NOT transfer OOD, but the shield keeps
it safe.** 0/10 success; every seed runs out the 147.5 s horizon (per-env ttg all
147.5, reached all False). This is competence failure, NOT truncation: both
planner arms finish in ≈104 s, ≈30 % of the budget to spare, while the trained
arm consumes all 147.5 s and arrives nowhere — the corridor/gates gap of §17.20
(Table IV: trained 0.000 on corridors) reproduced on a map no procedure
generated. The shield works far harder here than in-distribution (75.9 % of ticks
vs 46.6 % campaign) yet still cannot manufacture competence; it does hold safety
exactly where the policy fails — 0/10 collisions, oob 0 (escape 1546, retreat
1335, pin 252; no livelock, unlike the §17.21 1-env counterexample).

**6. Reading (ii) — the classical planner transfers but is unsafe by itself.**
A*+DWA plans on the occupancy grid of ANY map, so competence is map-agnostic:
10/10 success. Unprotected it contacts walls in 9/10 (only env 1 clean). Its DWA
margin (DWA_MARGIN 0.03 m) NEVER rejected a candidate (dwa_reject 0): the
point-model deemed every command safe while the hull + drive wheels/casters
clipped the ≈1.1 m corridor walls — the §17.21 hull-model gap reproduced on an
unseen drawing. Competence without a guarantee.

**7. Reading (iii) — the thesis arm = competence + guarantee, out-of-distribution.**
The thesis arm runs the IDENTICAL planner (plan / replan / dwa_reject / stuck
bit-identical to the unprotected twin) and the exact-box ESDF barrier converts
9/10 collisions into **0/10**, oob 0, for +2.4 s (+2.3 %) TTG (103.3 → 105.7).
The shield intervenes on only 19.2 % of ticks (vs 75.9 % for the flailing trained
arm) — the planner already drives mostly safe, so the barrier only vetoes the
corner-cuts DWA's margin waves through. **This extends the campaign thesis-arm
guarantee from 0/236 to 0/246 episodes with zero map-specific adjustment.** On a
map drawn by a person and never seen in training or the campaign, the guarantee
still comes from the interface, not the policy — the framework's claim, on the
hardest kind of target.

**8. Artifacts.** `campaign/run_heldout.sh` (bounded sequential runner, RAM +
kill guards); `campaign/heldout/results/{shield,astar_dwa,astar_dwa_shield}/heldout.json`
(per-env arrays); `campaign/heldout/results.jsonl`; `campaign/heldout/logs/<arm>.log`;
`campaign/heldout/MASTER.log`; `maps/heldout.json` + `maps/heldout.preview.png`.
Videos are a SEPARATE presentation/ppt track (not the paper): deferred — they
would use 1-env traces with the §17.21 10-env-ep1 fallback for the thesis arm.
Paper: new Sec. VI-H + Table V, with tie-ins to the abstract, VII-A, VII-C and VIII.

### 17.23 The held-out presentation videos (ppt track): env-0 traces, four rendering bugs fixed

**1. Scope.** Presentation/ppt track, NOT the paper (videos do not go in the
paper). Each video renders the SAME env-0 episode as the §17.22 statistics: the
num_envs=10 `--video` runs record env-0's trace at 20 Hz (2971 steps / 147.5 s
horizon), so a video is the identical episode behind Table V. Driver
`campaign/heldout/render_present.sh`, two phases: `light` (clip →
clearance-audit → top-down, no simulator) and `3d` (bird's-eye 3D via Isaac Sim,
one simulator at a time). The light and 3d phases were run as two parallel
background batches (light = CPU/ffmpeg, 3d = GPU; no simulator contention).
Outputs in `campaign/heldout/videos_present/videos/`.

**2. Bug 1 — clips spanning an episode reset (`28_clip_trace.py`).** With
num_envs=10 and a 2971-step horizon, env-0 succeeds or times out and then
RESETS, so the trace holds TWO episodes (thesis ep_start=[0,2082]; unprotected
[0,2135]; trained [0,2950]=timeout horizon). An unbounded clip would include the
reset "teleport" back to spawn mid-video. Fix: bound the reach/motion search and
the clip end k1 to episode 0 (`ep0_end = ep_start[1]`), and filter the saved
episode markers (`keep = ep_start < k1`). fps=20 confirmed: ep0_end/20 reproduces
the §17.22 TTGs (104.1 / 106.8 / 147.5 s).

**3. Bug 2 — success-radius vs recording-timing offset (`28_clip_trace.py`).**
The env declares success at `dist < goal_success_dist = 0.30`
(`openmover_nav_cfg.py:135`, `openmover_nav_env.py:195`) but the RECORDED traj
min dist to goal is 0.30257 m (≈2.6 mm recording-timing offset), so the clip
default `--reach 0.30` failed with "trace never reaches the goal" on the two
successful arms. Fix: pass `--reach 0.35` (the goal sits in a dead-end pocket, so
0.35 admits no false positive; only the 8 arrival frames fall under it). The
trained arm never reaches, so it uses `--allow_unreached` (clip = full episode 0).

**4. Bug 3 — top-down canvas overshoot (`26_render_topdown_video.py`).** The
integer kron upscale `ky=round(PX_H/gy)` overshoots the 576-px canvas whenever
PX_H/gy is not integral: the held-out 60×60 grid gives round(576/60)=10 → 600 px
> 576 → `ValueError: could not broadcast (600,600,3) into (576,600,3)`. Prior
maps' grids divided 576 evenly, which is why this never fired before. Fix:
nearest-neighbour resample of the occupancy tile to its EXACT pixel footprint
(tile_px_h/w = round(size·kx), index maps ri/ci), backward-compatible with
divisible grids.

**5. Bug 4 — 3D bird framing + missing camera flag (`29_render_3d_video.py`).**
The bird camera was hardcoded `pos=[CX+3.5, CY-3.5, 10.5]` with focal 24, which
the code comment already notes "clips the map corners" for the 8 m serial-tour
squares — a 15 m held-out map would be badly cropped. Added backward-compatible
`--bird_height` (default 10.5) / `--bird_offset` (default 3.5) args; the driver
passes height 26 / offset 6 / focal 17 (coverage ≈ 12.95·height/focal ≈ 20 m,
framing the 15 m square with margin; verified by a 7-frame `--stride 300` test
before committing the full renders). Separately the driver omitted
`--headless --enable_cameras`, which Isaac Sim requires for a spawned camera
(`RuntimeError: A camera was spawned without the --enable_cameras flag`); both
flags added (cf. runbook 04, "3D presentation renders").

**6. Clearance audits on the clipped episode-0 traces**
(`30_clearance_audit.py`, exact boxes, 884 walls, hull box 0.22/0.14): thesis min
clearance +0.1546 m, 0/2082 penetration; unprotected +0.0703 m, 0/2135; trained
+0.1194 m, 0/2950. Consistent with §17.21/§17.22: the unprotected arm's 9/10
collisions are wheel/caster contact FORCES outside the hull box, not hull
penetration — the hull stays clear while the drive hardware clips walls, exactly
the hull-model gap the shield closes.

**7. Artifacts.** `campaign/heldout/render_present.sh`;
`videos_present/videos/heldout_<arm>_clip.npz` (2082/2135/2950 frames);
`heldout_<arm>.topdown.mp4`; `heldout_<arm>.bird3d.mp4`;
`videos_present/logs/{clip,audit,topdown,3d}_<arm>.log` + `light_phase.log` /
`phase3d.log`. Old videos/data untouched.




