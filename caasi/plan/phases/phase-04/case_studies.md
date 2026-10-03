# Phase 4 Case Study Evidence: Empirical Evaluation of Campaign Execution, Result Inspection, and Recovery

**Date**: 2026-10-03  
**Status**: Completed  
**Context**: Evaluation and case-study evidence supporting technical reports and academic papers on caasi  
**Target Workspace**: `/home/zar/Documents/phd/robot/caasi-workspace/openmover_ws/`  
**Git Checkpoint**: `91415c1`

---

## 1. Overview and Methodology

This document preserves empirical, real-world evidence gathered during Phase 4 of the OpenMover dogfooding project. In Phase 4, we evaluated `caasi`'s ability to manage meaningful, multi-arm simulation campaigns, preserve provenance across long-running runs, recover deterministically from process interruptions, and inspect/aggregate evaluation results.

### Evaluation Criteria
Every case study is structured around seven explicit questions:
1. **Actual Situation**: What was the concrete codebase, asset layout, or operational setup before the intervention? (Distinguishing observed project reality from general technical background).
2. **Action Taken with caasi**: What exact commands, configuration files, and workflows were executed?
3. **What caasi Actually Provided**: What did `caasi` discover, validate, manage, execute, or capture? (Strictly distinguishing `caasi`'s management role from existing domain software implementations).
4. **Empirical Evidence**: What concrete artifacts, metrics, exit codes, PIDs, and files directly prove what occurred?
5. **Directly Supported Benefit**: What practical advantage is strictly supported by the observed evidence?
6. **Unmeasured Counterfactuals & Hypotheses**: What reasonable alternatives or advantages remain unmeasured, hypothetical, or dependent on future multi-system experiments?
7. **Observed Friction & Limitations**: What honest limitations, path resolution bugs, or manual workarounds were encountered?

---

## Case Study 1: First-Class Campaign Management and Complete Provenance Preservation

### 1. Actual Situation
- **Observed Setup**: OpenMover includes an evaluation pipeline (`33_run_campaign.py`) that schedules sequential Isaac Sim runs across procedural mazes, testing multiple navigation policy arms (`astar_dwa`, `astar_dwa_shield`, `shield`).
- **General Background**: Running multi-hour or multi-day evaluation campaigns directly from an interactive shell risks job loss from terminal closure, mixes simulator logs across runs, and leaves no standardized record of git revision, system configuration, or launch parameters.

### 2. Action Taken with caasi
We formulated a bounded campaign manifest ([`experiments/isaac_lab_bounded_campaign.yaml`](file:///home/zar/Documents/phd/robot/caasi-workspace/openmover_ws/experiments/isaac_lab_bounded_campaign.yaml)) targeting map `f5_b0_m00` across two algorithmic arms with two seeds, and launched it as a detached background run:
```bash
caasi run start experiments/isaac_lab_bounded_campaign.yaml
caasi run status 20261003-190446-isaac-lab-campaign-bounded
caasi run inspect 20261003-190446-isaac-lab-campaign-bounded
```

### 3. What caasi Actually Provided
`caasi` managed the campaign execution entirely out-of-band:
- Registered Run ID `20261003-190446-isaac-lab-campaign-bounded` (`backend: python`, PID 263110).
- Isolated stdout and stderr into dedicated log files.
- Maintained process lifecycle tracking from `running` to `succeeded` with exit code 0.
- Generated an immutable Layer 6 provenance bundle recording git commit (`91415c1`), hardware specs (16 cores, 62.4 GiB RAM), python dependencies, and exact CLI invocation.
- *Boundary Note*: `caasi` did not implement the campaign logic or simulator stepping; it managed and captured the execution of OpenMover's existing Python campaign scheduler.

### 4. Empirical Evidence
- **Run Records**: `manifest.yaml` recorded `created: '2026-10-03T19:04:46+08:00'`, PID 263110, exit code 0.
- **Subprocess Execution**:
  - Arm 1 (`astar_dwa`): 762 steps completed in 28.86 s (53 env-steps/s; wall 34 s). Result written to `results/astar_dwa/f5_b0_m00.json`.
  - Arm 2 (`astar_dwa_shield`): 762 steps completed in 29.48 s (52 env-steps/s; wall 34 s). Result written to `results/astar_dwa_shield/f5_b0_m00.json`.
- **Telemetry**: Hardware snapshot recorded 8.5% system RAM usage during Isaac Sim child execution.

### 5. Directly Supported Benefit
Allows robotics researchers to launch long-running simulation campaigns in the background with immediate detached status monitoring and permanent, immutable provenance bundles linking results to exact software revisions.

### 6. Unmeasured Counterfactuals & Hypotheses
- It remains unmeasured whether provenance bundles prevent reproducibility failures across different operating system distributions or distant GPU hardware generations.
- It is hypothesized, but unmeasured, that automated provenance significantly accelerates debugging during collaborative multi-researcher campaigns.

### 7. Observed Friction & Limitations
- Initial campaign launch failed with exit code 2 because the script path was specified as `../isaac/lab/33_run_campaign.py` instead of `../isaac/lab/tasks/33_run_campaign.py` following workspace restructuring. `caasi run logs` immediately surfaced the error, allowing prompt correction.

---

## Case Study 2: Process Group Termination and Resumption Lineage

### 1. Actual Situation
- **Observed Setup**: Campaign runs execute nested subprocesses (the Python campaign scheduler launches Isaac Sim Kit child processes via `python.sh`).
- **General Background**: Terminating a long-running campaign via `kill` or Ctrl+C often kills the top-level parent script while leaving child simulator processes running in the background, consuming GPU memory and locking Isaac Sim IPC resources. Furthermore, resuming after interruption typically requires manual tracking of completed tasks.

### 2. Action Taken with caasi
We launched a multi-map campaign ([`experiments/isaac_lab_multi_map_campaign.yaml`](file:///home/zar/Documents/phd/robot/caasi-workspace/openmover_ws/experiments/isaac_lab_multi_map_campaign.yaml)) across two maps. After Map 1 completed and Map 2 was actively stepping in Isaac Sim, we explicitly stopped the run using `caasi run stop`:
```bash
caasi run stop 20261003-190631-isaac-lab-campaign-interrupted
caasi run restart 20261003-190631-isaac-lab-campaign-interrupted
```

### 3. What caasi Actually Provided
- **Process Group Cleanup**: `caasi` issued `SIGTERM` to the process group (`os.killpg`), successfully terminating both the Python campaign scheduler and the active Kit simulator process.
- **State Capture**: Updated run manifest to `stopped: true` and recorded status as `stopped`.
- **Restart Lineage**: On `caasi run restart`, launched a new run (`20261003-190733-isaac-lab-campaign-interrupted`) that explicitly linked back to its predecessor via `restarted_from: 20261003-190631-isaac-lab-campaign-interrupted` in `manifest.yaml`.
- *Boundary Note*: Domain resume logic (skipping completed `f5_b0_m00.json`) was executed by OpenMover's campaign runner; `caasi` provided the reliable process teardown, relaunch mechanism, and lineage record.

### 4. Empirical Evidence
- **Process Verification**: `ps aux | grep kit` immediately after `caasi run stop` showed zero active Kit or simulator processes.
- **Result Preservation**: Partial result `results/astar_dwa/f5_b0_m00.json` (615 B) was preserved intact on disk.
- **Skip Behavior**: Log of restarted run confirmed Map 1 was skipped:
  ```text
  [camp] plan: 1 runs (2 maps x arms ['astar_dwa'])
  [camp]   astar_dwa        f5_b0_m01 seeds=2 horizon=37s steps=762 est~0.8 min
  ```
- **Final Completion**: Map 2 ran to completion in 34 s. Status transitioned to `succeeded` with exit code 0. Both `f5_b0_m00.json` and `f5_b0_m01.json` were complete and present.

### 5. Directly Supported Benefit
Guarantees clean process teardown without orphaned simulator processes consuming GPU resources, while maintaining an explicit, auditable chain of custody across restarted and resumed experiment runs.

### 6. Unmeasured Counterfactuals & Hypotheses
- We have not measured whether `SIGTERM` process group termination remains 100% effective when simulator worker processes are distributed across multi-node compute clusters.

### 7. Observed Friction & Limitations
- `caasi run restart` re-executes the exact command recorded in the original run's manifest. If an interrupted run failed due to a bug in script arguments, the user must update the experiment config and start a new run rather than restarting the failed record.

---

## Case Study 3: Result Inspection and Domain Metric Aggregation

### 1. Actual Situation
- **Observed Setup**: Campaign results are written as individual JSON files per `(map, arm)` pair under `results/<arm>/<map>.json`. OpenMover provides an aggregation script (`34_aggregate_campaign.py`) that calculates episode-pooled success, collision rates, time-to-goal, and shield intervention statistics.
- **General Background**: Experiment managers often attempt to ingest all numerical metrics into a generic database. For specialized robotics evaluations (e.g. episodic collision metrics, shield hysteresis ticks, navigation time-to-goal), rigid metric schemas often fail to capture domain-specific phenomena.

### 2. Action Taken with caasi
We inspected run metadata and artifacts using `caasi run inspect`, and executed OpenMover's native aggregation script against the campaign outputs:
```bash
caasi run inspect 20261003-190446-isaac-lab-campaign-bounded
python3 34_aggregate_campaign.py --campaign_dir campaign_bounded
```

### 3. What caasi Actually Provided
- **Run Artifact Overview**: `caasi run inspect` provided structured verification of run directory artifacts (manifest, environment, hardware, logs, exit code) and run status.
- **Domain Delegation**: Domain aggregation script generated comprehensive cross-arm comparisons without requiring custom plugin development in `caasi`.
- *Boundary Note*: Domain metric pooling was performed entirely by `34_aggregate_campaign.py`; `caasi` validated file existence, run health, and artifact integrity.

### 4. Empirical Evidence
- **Generated Aggregate**: `campaign_bounded/aggregate.json` successfully produced with episode-pooled metrics for both arms:
  ```text
  | arm            | maps | episodes | success | collision | TTG succ (s) |
  | A*+DWA         | 1    | 2        | 1.000   | 0.000     | 27.6         |
  | A*+DWA+shield  | 1    | 2        | 1.000   | 0.000     | 27.9         |
  ```
- **Shield Safety Verification**: Shield statistics correctly aggregated: 81 shield ticks, 74 hysteresis ticks, 0 out-of-bounds violations across 1,524 environment steps.

### 5. Directly Supported Benefit
Preserves complete domain freedom for metric formulation and tabular reporting while providing standardized CLI inspection for run health and artifact inventory.

### 6. Unmeasured Counterfactuals & Hypotheses
- It remains unmeasured whether domain scripts vs unified database storage scales better when querying millions of episodes across multi-year research projects.

### 7. Observed Friction & Limitations
- `34_aggregate_campaign.py` initially assumed `LAB` was `Path(__file__).resolve().parent`, which failed when the script was placed inside `tasks/`. Updating `LAB = TASKS_DIR.parent` resolved the path resolution cleanly.
