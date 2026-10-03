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

## 2. Test Baseline & T1 Implementation

### 2.1 Existing Test Suite Baseline
- `caasi` includes **53 test modules** in `tests/`, encompassing **842 individual unit and integration tests**.
- All core models, check ladders, run managers, provenance builders, and CLI commands are covered using `typer.testing.CliRunner` and isolated environment fixtures in `conftest.py`.

### 2.2 T1 Implementation: ROS 2 Pytest Plugin Conflict Resolution
- **Problem**: When pytest ran in a shell where ROS 2 was sourced, ROS 2 entry points (`launch_testing`, `launch_ros`) registered incompatible hooks with pytest 9, crashing collection with `PluginValidationError`.
- **Implementation**:
  Updated [caasi/pyproject.toml](file:///home/zar/Documents/phd/robot/caasi/pyproject.toml):
  ```toml
  [tool.pytest.ini_options]
  testpaths = ["tests"]
  addopts = "-p no:launch_ros -p no:launch_testing"
  ```
- **Validation**:
  Executed the complete test suite using plain `.venv/bin/pytest -q`:
  ```text
  842 passed in 183.78s (0:03:03)
  ```
  All 842 tests pass cleanly without requiring any manual flags.

---

## 3. T2 Design Proposal: Generalized `caasi test` CLI Command

### 3.1 Architectural Context in `caasi`
Existing diagnostic and verification commands in `src/caasi/cli/`:
- `doctor`: Diagnoses machine readiness and ecosystem tools.
- `check`: Evaluates preflight compatibility against requirements.
- `audit`: Verifies project structure, reproducibility, and provenance integrity.

A `caasi test` command naturally fits in the **Setup & diagnosis** group alongside `doctor`, `check`, and `audit`.

### 3.2 Proposed Command Capabilities & Scope
Rather than an OpenMover-specific test runner, `caasi test` should provide a **generalized self-test and verification facility**:

```text
caasi test [OPTIONS] [COMMAND]

Commands:
  self        Run caasi's own test suite (unit, smoke, full)
  project     Run the active project's tests (if declared in caasi.yaml)

Options:
  --suite [smoke|unit|full]   Select test tier (default: smoke)
  --coverage                  Produce test coverage report
  --json                      Emit structured machine-readable test results
```

### 3.3 Test Tiers
1. **`smoke`** (default, ~2s): Fast verification of real background process spawning, tracking, exit code recording, and status polling.
2. **`unit`** (~10s): High-speed mock-based unit tests for core libraries and CLI parsers.
3. **`full`** (~60–180s): Complete 842+ test suite.

### 3.4 Integration
- Located in `src/caasi/cli/test_cmd.py`, registered in `src/caasi/cli/main.py`.
- Invokes pytest in a clean subprocess with isolated environment parameters, eliminating ROS plugin pollution automatically.

---

## 4. T3 Investigation: Smallest Useful Real Subprocess Smoke Test

### 4.1 The Current Gap in Existing Tests
In `tests/test_runs.py` and `tests/test_run_cmd.py`, subprocess execution is mocked via `unittest.mock` or `monkeypatch`. While this validates internal logic, it **does not verify actual OS-level mechanics**:
- Writing the bash wrapper `run.sh` with executable permissions (`0o755`).
- Detached process creation via `os.setsid` and `subprocess.Popen`.
- Output streaming and redirection into `stdout.log` and `stderr.log`.
- Writing the exit code file on exit (`echo "$ec" > exit_code`).
- Real asynchronous PID liveness polling via `os.kill(pid, 0)`.
- Real process group termination via `os.killpg(pid, signal.SIGTERM)`.

### 4.2 Proposed Minimal Smoke Test Design
A dedicated test module: `tests/test_real_subprocess.py` (marked `@pytest.mark.smoke`):
- **Test 1: Normal Completion**:
  Spawn `python3 -c "import time; print('start'); time.sleep(0.3); print('done')"` as a tracked run.
  - Assert status transitions: `running` → `succeeded`.
  - Assert `exit_code` file exists and equals `0`.
  - Assert `stdout.log` contains `"start\ndone\n"`.
  - Assert `manifest.yaml` contains real valid PID.
- **Test 2: Failure Recording**:
  Spawn `python3 -c "import sys; print('error', file=sys.stderr); sys.exit(42)"`.
  - Assert status is `failed`.
  - Assert `exit_code` is `42`.
  - Assert `stderr.log` contains `"error\n"`.
- **Test 3: Process Cancellation (SIGTERM / SIGKILL)**:
  Spawn `python3 -c "import time; time.sleep(60)"`.
  - Assert initial status is `running`.
  - Call `runs.stop_run(record)`.
  - Assert status becomes `stopped` and PID is no longer alive.

*Total execution time*: ~1.5 seconds. Zero external dependencies. 100% deterministic.

---

## 5. T4 Investigation: `pytest-cov` Evaluation

- **What it provides**: Measures statement and branch coverage across `src/caasi/`, generating terminal summary tables and HTML reports highlighting untested branches.
- **Evaluation**:
  - `pytest-cov` is a standard, lightweight tool for Python packages.
  - Adding `pytest-cov>=5.0` to `[project.optional-dependencies] dev` in `pyproject.toml` is recommended.
  - It should **not** be enabled by default in `addopts` to avoid slowing down rapid test runs, but rather invoked explicitly via `pytest --cov=caasi` or `caasi test --coverage`.

---

## 6. Comprehensive Testing Strategy

To ensure absolute reliability, `caasi` development will follow a strict 4-stage pipeline:

```text
1. caasi Source Changes
       │
       ▼
2. caasi's Own Tests (Unit + Real Subprocess Smoke)
       │ (Ensures caasi's core machinery is regression-free)
       ▼
3. caasi ↔ OpenMover Integration Validation
       │ (Validates experiment manifests, launch files, and definitions in caasi-workspace)
       ▼
4. Actual OpenMover Execution
         (Executes Isaac Sim bridges and ROS 2 controllers under caasi tracking)
```

No implementation of T2, T3, or T4 will proceed until explicitly approved.
