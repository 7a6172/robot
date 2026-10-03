# Phase 4 Report: Campaign Execution, Result Inspection, Comparison, and Recovery

**Date**: 2026-10-03  
**Status**: Completed  
**Repository Baseline**: `91415c1`  
**Target Workspace**: `/home/zar/Documents/phd/robot/caasi-workspace/openmover_ws/`  
**Read-Only Trees Preserved**: `/openmover_robot` and `/openmover_ws` (100% untouched)

---

## 1. Executive Summary

Phase 4 addressed the central operational question:
> *After successfully managing an integrated robotics workflow, what happens when we use caasi for a meaningful experiment campaign and need to preserve, inspect, compare, and recover its results?*

Following the validation-first dogfooding methodology, we evaluated `caasi`'s interaction with OpenMover's existing multi-arm procedural campaign evaluation suite (`33_run_campaign.py` and `34_aggregate_campaign.py`). Rather than building a parallel campaign engine or embedding domain metrics inside `caasi`, we investigated whether `caasi`'s existing run management, provenance bundling, process control, and log isolation effectively manage real campaign workloads, recover from interruptions, and preserve reproducible artifacts.

### Key Outcomes
- **Bounded Real-World Campaign Executed**: Managed a multi-arm evaluation campaign (`astar_dwa` baseline vs `astar_dwa_shield` safety filter) across procedural maze environments on CUDA:0 as a first-class tracked `caasi` experiment (`backend: python`).
- **Complete Run Lifecycle & Provenance Preservation**: `caasi` tracked the end-to-end campaign lifecycle (`running` $\longrightarrow$ `succeeded`), isolating stdout/stderr logs and generating immutable provenance bundles (`manifest.yaml`, `environment.yaml`, `hardware.yaml`, `dependencies.yaml`, `configuration.yaml`, `git.json`, `processes.json`).
- **Clean Interruption & Deterministic Resumption**: Tested campaign interruption via `caasi run stop <ID>` mid-run. `caasi` terminated the entire process group (including child Kit simulator processes) cleanly without orphaned GPU workers, recorded status as `stopped`, and preserved partial results. Upon `caasi run restart <ID>`, the domain campaign runner skipped completed runs and resumed from remaining tasks, successfully completing the campaign pass (`status: succeeded`).
- **Domain vs Management Decoupling Validated**: Verified that metric pooling (episode-level statistics across difficulty bins and map families) is cleanly handled by domain tooling (`34_aggregate_campaign.py`), while `caasi` manages process lifecycle, provenance, and run history. No changes to `caasi` core were required.

---

## 2. Workflows & Empirical Results

### Workflow 1: Bounded Multi-Arm Campaign Execution
- **Manifest**: [`experiments/isaac_lab_bounded_campaign.yaml`](file:///home/zar/Documents/phd/robot/caasi-workspace/openmover_ws/experiments/isaac_lab_bounded_campaign.yaml)
- **Command**: `caasi run start experiments/isaac_lab_bounded_campaign.yaml`
- **Run ID**: `20261003-190446-isaac-lab-campaign-bounded` (PID 263110)
- **Parameters**: Map `f5_b0_m00`, Arms `['astar_dwa', 'astar_dwa_shield']`, Seeds 2, Horizon 37s, Steps 762 per run.
- **Execution Observations**:
  - Arm 1 (`astar_dwa`): Completed 762 steps in 28.86 s (53 env-steps/s). Wall clock: 34 s. Mean success: 1.000, collision: 0.000, mean TTG: 27.58 s.
  - Arm 2 (`astar_dwa_shield`): Completed 762 steps in 29.48 s (52 env-steps/s). Wall clock: 34 s. Mean success: 1.000, collision: 0.000, mean TTG: 27.85 s. Shield ticks recorded: 81 (hysteresis: 74).
  - Status Lifecycle: `running` $\longrightarrow$ `succeeded` (exit code 0).
  - Provenance Captured: `manifest.yaml` (727 B), `hardware.yaml` (162 B), `dependencies.yaml` (563 B), `git.json` (134 B), `processes.json` (914 B).

### Workflow 2: Interrupted Campaign Recovery & Resumption
- **Manifest**: [`experiments/isaac_lab_multi_map_campaign.yaml`](file:///home/zar/Documents/phd/robot/caasi-workspace/openmover_ws/experiments/isaac_lab_multi_map_campaign.yaml)
- **Initial Run ID**: `20261003-190631-isaac-lab-campaign-interrupted` (PID 264516)
- **Intervention**:
  - Map 1 (`f5_b0_m00`) finished in 34 s (`results/astar_dwa/f5_b0_m00.json` written).
  - As Map 2 (`f5_b0_m01`) launched, issued `caasi run stop 20261003-190631-isaac-lab-campaign-interrupted`.
  - Result: `caasi` signaled the process group (`SIGTERM` $\longrightarrow$ verified dead within timeout). The child Isaac Sim/Kit process (PID 264871) was reaped immediately; `ps aux | grep kit` confirmed no orphaned simulator processes. Run status recorded as `stopped`.
- **Resumption**:
  - Issued `caasi run restart 20261003-190631-isaac-lab-campaign-interrupted`.
  - New Run ID: `20261003-190733-isaac-lab-campaign-interrupted` (PID 265486).
  - Provenance recorded lineage: `restarted_from: 20261003-190631-isaac-lab-campaign-interrupted` in `manifest.yaml`.
  - Domain skip verification: Campaign scheduler detected `f5_b0_m00.json` complete, skipped Map 1, planned only Map 2 (`f5_b0_m01`).
  - Completion: Map 2 ran to completion (success=1.000, ttg=25.08s). Status transitioned to `succeeded` with exit code 0. Both result JSON files (`f5_b0_m00.json`, `f5_b0_m01.json`) preserved.

### Workflow 3: Aggregation and Result Inspection
- **Script**: `34_aggregate_campaign.py`
- **Command**: `python3 34_aggregate_campaign.py --campaign_dir campaign_bounded`
- **Output Artifacts**:
  - `campaign_bounded/aggregate.json`: Machine-readable episode-pooled metrics across difficulty bins and families.
  - Formatted Markdown Tables: Pooled success rate, collision rate, TTG, and shield safety instrument statistics (shield ticks, hysteresis, escape actions).
- **Inspection Command**: `caasi run inspect <ID>`
  - Evaluated on completed, stopped, and restarted runs. Consistently displayed run metadata, status, directory location, and artifact sizes.

---

## 3. Friction Classification & Gap Analysis

Following the strict dogfooding classification rubric:

| Problem / Friction | Classification | Mechanism / Solution |
| :--- | :---: | :--- |
| **Simultaneous Process Lifecycle Management** | **A** (Already solved by existing caasi) | `caasi run start`, `status`, `logs`, `stop` reliably tracks detached long-running campaign processes. |
| **Run Lineage & Provenance Tracking** | **A** (Already solved by existing caasi) | `caasi run inspect` and manifest metadata capture launch command, git commit, dependencies, and `restarted_from` run lineage. |
| **Clean Process Teardown (No Orphaned Kit Processes)** | **A** (Already solved by existing caasi) | `caasi run stop` sends `SIGTERM` to the process group (`os.killpg`), terminating the campaign wrapper and any active simulator child processes. |
| **Algorithmic Evaluation Sweeping & Metric Aggregation** | **B** (Solved by domain tooling; caasi manages it) | `33_run_campaign.py` sweeps maps and algorithmic arms; `34_aggregate_campaign.py` pools episode statistics into `aggregate.json` and Markdown tables. `caasi` does not need to duplicate this. |
| **Resumption of Interrupted Campaigns** | **B** (Solved by domain tooling; caasi manages it) | Domain campaign script checks for existing `results/<arm>/<map>.json`. `caasi run restart` re-launches the campaign command, which automatically resumes from remaining work. |
| **Path Resolution in Relocated Scripts** | **C** (Workable via simple workflow) | Scripts referencing `Path(__file__).resolve().parent` needed adjustment when moved into `tasks/` subdirectory. Solved cleanly with workspace path anchor `TASKS_DIR.parent`. |
| **Cross-Run Metric Comparison CLI** | **C** (Workable via simple workflow) | `caasi run inspect` provides artifact file inspection but does not parse domain-specific metric payloads (`aggregate.json`). Domain scripts (`34_aggregate_campaign.py`) provide comprehensive comparative tables across arms and maps. |

**Genuine Caasi Gaps (Category D)**:
- **Zero Category D gaps identified**. Existing `caasi` capabilities (Layer 6 provenance, run process engine, restart lineage) paired with existing domain campaign tooling fully satisfy experimental campaign execution, recovery, and inspection without core architectural modifications.

---

## 4. Phase Status & Next Steps

Phase 4 is complete. All evaluation objectives have been met:
1. Meaningful campaign executed and managed under `caasi`.
2. Clean process teardown and interruption recovery verified.
3. Domain vs management separation strictly preserved.
4. Read-only trees preserved intact.
5. All observations empirically grounded in concrete artifacts.
