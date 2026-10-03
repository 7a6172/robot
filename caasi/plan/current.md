# Current Project Status

## Repository Baseline
- **Root Repository Location**: `/home/zar/Documents/phd/robot/`
- **Baseline Commit**: `79dc52f80f156b36c1383a5cb19315dc87eb858e`
- **Latest Checkpoint**: `e4f8c6b` (Phase 1 completion)
- **Branch**: `master`
- **Scope Tracked**:
  - `caasi/`: Caasi package, CLI tools, documentation, tests, and persistent `/plan`
  - `openmover_robot/`: Legacy ROS 1 OpenMover source reference (**STRICT READ-ONLY**)
  - `openmover_ws/`: ROS 2 + Isaac Sim/Lab reference source & assets (**STRICT READ-ONLY**)
  - `caasi-workspace/`: Primary writable Caasi working environment (`caasi-workspace/openmover_ws/`)
  - `draft/`: Research papers, presentation, and figures

## Safety Boundaries Enforced
- `/openmover_robot` and `/openmover_ws` are strictly read-only and preserved untouched on disk.
- Over 5 GB of runtime logs, build/install outputs, and Isaac Lab RL video/checkpoints remain intact on disk and are excluded from Git object tracking via root `.gitignore`.

## Current State & Next Steps
- **Completed**:
  - Baseline Git Checkpoint established (`79dc52f80f156b36c1383a5cb19315dc87eb858e`).
  - **Phase 1: Discovery & Inventory completed**:
    - [caasi v0.3.0 Capability Audit](file:///home/zar/Documents/phd/robot/caasi/plan/audits/caasi_v0.3.0_audit.md)
    - [OpenMover Inventory](file:///home/zar/Documents/phd/robot/caasi/plan/audits/openmover_inventory.md)
    - [OpenMover Architecture Reference](file:///home/zar/Documents/phd/robot/caasi/plan/reference/openmover_architecture.md)
    - [Capability Mapping & Gaps](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-01/mapping_and_gaps.md)
    - [Phase 1 Summary Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-01/phase-01-report.md)
    - [Packaging & Testing Audit](file:///home/zar/Documents/phd/robot/caasi/plan/audits/packaging_and_testing_audit.md)
    - [Testing Strategy & Proposals](file:///home/zar/Documents/phd/robot/caasi/plan/audits/testing_strategy_and_proposals.md)
  - **caasi Testing Infrastructure Baseline**:
    - **T1**: Sourced ROS 2 pytest plugin conflict resolved in `pyproject.toml`.
    - **T4**: Added `pytest-cov>=5.0` to optional dev dependencies; verified opt-in.
    - **T3**: Implemented un-mocked real-subprocess smoke tests in `caasi/tests/test_real_subprocess.py` (5 tests passing in 0.84s).
    - **T2**: Implemented `caasi test` command with default full suite, tiers (`full`, `unit`, `smoke`), deterministic checkout binding, opt-in coverage, filtering (`-k`), verbose mode, machine-readable `--json`, and dedicated CLI tests in `tests/test_test_cmd.py` (12 tests passing in 0.42s).
    - Verified full test suite executed via native `caasi test`: **55 test modules, 859 passing tests** in 183.32s.
  - **Phase 2: caasi-Managed OpenMover Workspace completed**:
    - [Phase 2 Summary Report](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-02/phase-02-report.md)
    - [Phase 2 Case Study Evidence](file:///home/zar/Documents/phd/robot/caasi/plan/phases/phase-02/case_studies.md)
    - Fully represented OpenMover in `/home/zar/Documents/phd/robot/caasi-workspace/openmover_ws/` (`caasi.yaml`, `caasi.lock`, `robots/`, `scenes/`, `tasks/`, `ros/`, `nav/`, `experiments/`).
    - Preflight checks verified: `caasi check project` (READY), `caasi sim check` (READY), `caasi audit` (PASSED).
    - Executed live headless Isaac Sim run via `caasi sim run` (Run ID: `20261003-154048-isaac-sim-smoke`, PID 110981, 60 physics frames stepped at 2432 steps/s, exit code 0, 11 provenance artifacts captured).
    - Re-evaluated Phase 1 candidate gaps (none are blockers; existing tools and patterns handle all requirements).
    - Identified two minor friction points (`cwd` relative resolution and Isaac Lab launcher override flag).
- **Current State**: Phase 2 workspace initialized, fully verified, and live simulation run completed with zero modifications to `caasi` core and zero modifications to read-only trees (`openmover_robot`, `openmover_ws`).
- **Next Concrete Step**: Review Phase 2 report with user and decide on next integration milestone (Phase 3: Live ROS 2 + Isaac Sim + Nav2 integration).