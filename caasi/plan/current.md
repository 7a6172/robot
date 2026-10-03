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
    - Verified full test suite: **54 test modules, 847 passing tests** in ~184s.
- **Current State**: T1, T3, T4 implemented and fully verified; T2 design refined with meaningful default suite, deterministic checkout binding, and no premature `project` subcommand. Paused awaiting user review.
- **Next Concrete Step**: User review of T2 proposal and authorization to proceed to Phase 2.