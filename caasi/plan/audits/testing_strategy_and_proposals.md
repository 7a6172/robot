# caasi Testing Strategy, Baseline, and Proposals

## 1. Local Development Invocation & Packaging Resolution

### 1.1 Root Cause of the Discrepancy
- The workstation has a global `caasi` binary managed by `pipx` (`/home/zar/.local/bin/caasi`).
- That global binary imports from an external repository: `/home/zar/Documents/caasi/src/caasi/`.
- Furthermore, the local virtual environment at `/home/zar/Documents/phd/robot/caasi/.venv` was originally cloned/copied from that external tree, and its `_editable_impl_caasi.pth` pointed to `/home/zar/Documents/caasi/src`.
- **Consequence**: Modifying code in `/home/zar/Documents/phd/robot/caasi/` would not be executed by either `caasi` or `.venv/bin/caasi` under the old configuration.

### 1.2 Resolution & Verification
- Ran `uv sync --extra dev` inside `/home/zar/Documents/phd/robot/caasi/`. This rebuilt the editable wheel link, repointing `.venv` directly to `/home/zar/Documents/phd/robot/caasi/src`.
- **Verification Proof**:
  - Injected temporary `__dev_marker__ = "verified_local_checkout_active"` into local `caasi/src/caasi/__init__.py`.
  - `.venv/bin/python` imported the marker from `/home/zar/Documents/phd/robot/caasi/src/caasi/__init__.py`.
  - Global `pipx` reported `NOT FOUND`.
  - Reverted the test marker.
- **Rule for Development**:
  Always use `/home/zar/Documents/phd/robot/caasi/.venv/bin/caasi` or activate the local virtual environment. Never execute bare `caasi` from PATH during development.

---

## 2. Test Baseline & Verified Status

### 2.1 Verified Test Suite Baseline
- `caasi` includes **54 test modules** in `tests/`, encompassing **847 individual unit, integration, and real-subprocess tests**.
- All 847 tests pass cleanly in ~184s without warnings or errors.

### 2.2 T1 Implementation: ROS 2 Pytest Plugin Conflict Resolution (Completed)
- **Problem**: When pytest ran in a shell where ROS 2 was sourced, ROS 2 entry points (`launch_testing`, `launch_ros`) registered incompatible hooks with pytest 9, crashing collection with `PluginValidationError`.
- **Implementation**:
  Updated [caasi/pyproject.toml](file:///home/zar/Documents/phd/robot/caasi/pyproject.toml):
  ```toml
  [tool.pytest.ini_options]
  testpaths = ["tests"]
  addopts = "-p no:launch_ros -p no:launch_testing"
  ```
- **Validation**:
  All tests run cleanly in any sourced environment without requiring manual CLI flags.

### 2.3 T4 Implementation: `pytest-cov` Optional Dependency (Completed)
- **Implementation**:
  Added `"pytest-cov>=5.0"` to `[project.optional-dependencies] dev` in [caasi/pyproject.toml](file:///home/zar/Documents/phd/robot/caasi/pyproject.toml) and synced via `uv sync --extra dev`.
- **Policy**:
  Coverage is strictly **opt-in** (not present in default `addopts`).
- **Validation**:
  Verified coverage on `caasi.core.runs`:
  ```bash
  .venv/bin/pytest tests/test_real_subprocess.py --cov=caasi.core.runs --cov-report=term-missing
  ```
  Reports statement coverage cleanly without impacting normal test speed.

### 2.4 T3 Implementation: Real Subprocess Smoke Tests (Completed)
- **Implementation**:
  Created [caasi/tests/test_real_subprocess.py](file:///home/zar/Documents/phd/robot/caasi/tests/test_real_subprocess.py) covering 5 un-mocked OS lifecycle mechanics:
  1. `test_real_subprocess_success_lifecycle`: Verified detached bash wrapper `run.sh` execution, generation of `manifest.yaml`, `stdout.log`, `stderr.log`, exit code recording `0`, state transition (`running` -> `succeeded`), PID tracking, and process reaping.
  2. `test_real_subprocess_failure_lifecycle`: Verified runtime failure exit code capture (`42`), stderr log writing, state transition (`running` -> `failed`), and PID reaping.
  3. `test_real_subprocess_cancellation_sigterm`: Verified active running process termination via `runs.stop_run` (SIGTERM group signaling), state transition (`running` -> `stopped`), manifest update, and dead PID verification.
  4. `test_real_subprocess_process_tree_termination`: Verified process group termination when parent process spawns a child subprocess; stopping the run terminates both parent and child with zero orphan/zombie processes.
  5. `test_real_subprocess_cli_integration`: Verified real CLI commands (`caasi run list`, `caasi run status`, `caasi run logs`, `caasi run logs --stream stderr`) against real running and completed processes.
- **Validation**:
  All 5 tests pass in 0.84 seconds.

---

## 3. Refined T2 Design Proposal: Generalized `caasi test` CLI Command

### 3.1 Design Principles & Constraints
1. **Meaningful Default Suite**: Default `caasi test` must run a substantial, confidence-giving test suite (the full test suite or comprehensive unit+smoke suite), not merely a minimal 2-second smoke check.
2. **Deterministic Local Checkout Binding**: `caasi test` must inspect its own package location (`caasi.__file__`) and locate the repository root `tests/` directory. It must refuse to run if executed from an installed site-packages without tests or must clearly report which checkout is being verified, guaranteeing it never tests global `pipx` code by mistake.
3. **No Premature Project Subcommands**: Does not assume or introduce `caasi test project`. Keeps `caasi test` strictly as a generalized `caasi` self-verification toolkit. Project-level testing will be integrated only when the project model is developed.
4. **Clean Typer Integration**: Fits standard `caasi` CLI conventions in `src/caasi/cli/test_cmd.py`, registered under the `Setup & diagnosis` taxonomy panel in `src/caasi/cli/main.py`.

### 3.2 Command Signature & Options
```text
caasi test [OPTIONS]

Options:
  --suite [full|smoke|unit]   Test tier to execute (default: full)
  --coverage                  Run with pytest-cov report enabled (opt-in)
  --filter, -k TEXT           Filter test names matching expression
  --verbose, -v               Verbose test output
  --json                      Emit structured machine-readable test summary
  --help                      Show this message and exit
```

### 3.3 Test Tiers
- **`full` (Default)**: Executes all 54 test modules (847 tests). Provides complete confidence that the active checkout is fully healthy and regression-free (~3 minutes).
- **`smoke`**: Executes only `@pytest.mark.smoke` tests (`test_real_subprocess.py`). Verifies core OS-level process management, logging, exit codes, and cancellation in < 1 second.
- **`unit`**: Executes mock-based unit tests, skipping slow or external integrations.

### 3.4 Execution Mechanics
- **Checkout Locator**:
  ```python
  import caasi
  caasi_root = Path(caasi.__file__).resolve().parents[2]
  test_dir = caasi_root / "tests"
  if not test_dir.is_dir():
      output.fail(f"Tests directory not found at {test_dir}. Ensure caasi is running from a local checkout.")
      raise typer.Exit(1)
  ```
- **Virtualenv Python Resolution**:
  Uses `sys.executable` to run `pytest` directly in the active Python environment, ensuring identical dependency isolation.
- **Subprocess Invocation**:
  Invokes `[sys.executable, "-m", "pytest", str(test_dir), ...]` with inherited or controlled environment. Passes `-p no:launch_ros -p no:launch_testing` automatically.
- **Output Rendering**:
  In human mode, streams output or renders a Rich summary table with pass/fail counts, duration, and test suite path. In `--json` mode, emits structured JSON for CI and audit pipelines.

---

## 4. Comprehensive 4-Stage Development Strategy

```text
1. caasi Source Changes (in /home/zar/Documents/phd/robot/caasi)
       │
       ▼
2. caasi's Own Tests (Unit + Real Subprocess Smoke, via caasi test / pytest)
       │ (Guarantees caasi core machinery remains 100% regression-free)
       ▼
3. caasi ↔ OpenMover Integration Validation
       │ (Validates experiment manifests, launch files, and definitions in caasi-workspace)
       ▼
4. Actual OpenMover Execution
         (Executes Isaac Sim bridges and ROS 2 controllers under caasi tracking)
```
