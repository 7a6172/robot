# Phase 7 Report: Exit-Code Guard and the Remaining Open Work

**Status:** Completed & Empirically Verified
**Date:** October 2026
**Origin:** a survey for the next genuinely-open gap, after M3 was accepted

---

## 1. How the work was chosen

Rather than start a new capability, the surfaces were surveyed to find what is
**concretely open** versus merely aspirational. The conclusion was that the
capability set is complete for the current evidence, and that the one real defect
was a **correctness** bug, not a missing feature.

| Candidate | Verdict |
| :--- | :--- |
| R8 scheduling / queues / reservations | **deferred** — no observed contention |
| R9 third artifact destination | **deferred** — R9 says *"eventually"*, and **no real use case has needed it**; `target_local` and `workstation` cover every case actually encountered |
| R10 web UI | **deferred** by requirement |
| G4 `remotes:` shim | independent cleanup, unchanged |
| DDS-over-Tailscale | environmental, unchanged |
| idle race | by design, unchanged |
| **Exit-code defect** | **a real, live bug — fixed here** |

**The finding: the smallest genuinely-open item was a defect, not a feature.** So
this stage is a correctness fix plus a durable guard, with **no new capability and
no scope expansion**.

---

## 2. The defect

`output.fail()` **raises its own `Exit(1)`**. A `raise typer.Exit(N)` written after
it is therefore **unreachable**, and the command exits **1** while the author
intended `N`.

The error *message* is correct — only the exit code is wrong. **That is exactly why
it is dangerous: it looks right in a terminal and is only visible by measuring the
exit code.**

This class had already been hit **three times**:

| Where | Intended | Got |
| :--- | :--- | :--- |
| F3 (`tools_cmd`) | 3 | 1 — fixed then |
| `--where` "nothing fits" | 3 | 1 — fixed then |
| **`workload run` incompatible target** | **3** | **1 — missed until now** |

The third instance was found by a **static survey of the CLI**, not by testing:
every `output.fail(...)` call site was checked for a following `raise`.

### 2.1 The fix

```python
if not proceed:
    output.fail(
        reason or _("workload.incompatible", target=target_obj.name),
        exit_code=3,
    )
```

Verified on a real target: with a workload requiring 4 GPUs against the
workstation's single RTX 3080, the refusal now exits **3**, with the same message:

```console
Error: target 'local' does not satisfy 'gpu' (target reports 1 GPU(s), 4 required)
```

### 2.2 Scope measured, not assumed

The survey found **76** unreachable `raise` statements after `output.fail(...)`.
Only **one** was a genuine defect — the others use `Exit(1)`, which matches what
`fail()` already raises, so they are **dead but harmless**.

They were **deliberately not touched**: churning 75 harmless sites would be
unrelated cleanup, and the instruction is to keep changes narrow. What matters is
that no *incorrect* one remains.

---

## 3. The durable guard

Fixing one instance does not prevent a fourth. A **static guard test** now checks
every `output.fail(...)` call site in the CLI for a following `raise typer.Exit(N)`
with `N != 1`:

```python
def test_no_unreachable_exit_after_output_fail():
    ...
    assert not offenders, (
        "unreachable `raise typer.Exit(N)` after `output.fail(...)`; pass "
        "exit_code=N to fail() instead:\n  " + "\n  ".join(offenders)
    )
```

**The guard was verified to work** by temporarily reintroducing the defect: the
test **failed** with the exact offending location, and passed again once restored.
A guard that has never been seen to fail is not evidence of anything.

It covers the whole CLI, so the next occurrence fails in a test rather than in a
user's shell.

---

## 4. Tests

**1 new test** (`tests/test_misc.py::test_no_unreachable_exit_after_output_fail`)
— a static CLI-wide guard, demonstrated to detect the class it prevents.

**Full suite: 1224 passed, 1 failed** — the pre-existing `test_perception_cmd.py`
terminal-width artifact.

---

## 5. Files changed

| File | Change |
| :--- | :--- |
| `src/caasi/cli/workload_cmd.py` | incompatible-target refusal passes `exit_code=3` |
| `tests/test_misc.py` | static guard against the unreachable-exit class |

Reference trees unchanged: `openmover_robot` `f17c242a…`, `openmover_ws`
`1e09f5de…`, `caasi-workspace/openmover` 0 dirty. Fixture removed.

---

## 6. State of the open work

| Item | Status | Why |
| :--- | :--- | :--- |
| G4 `remotes:` shim | **open / cleanup** | needs a migration path; independent |
| DDS-over-Tailscale | **open / environmental** | not a caasi defect; working around it would breach scope |
| Idle race | **open / by design** | occupancy is an observation; solving it needs reservations |
| R9 third destination | **deferred** | no real use case has needed one |
| R10 web UI | **deferred** | by requirement |
| R8 scheduling remainder | **deferred** | pending **observed contention** and a real second-target case |

**Nothing here is a feature waiting to be built.** Each is either deliberately
deferred against evidence, environmental, or by design.

---

## 7. Conclusion

> **The currently justified capability set is complete for the evidence gathered so
> far.**

The control-plane lifecycle (select → deploy → build → run → observe → collect →
provenance), heterogeneous targets, runtime and tool observability, the persistent
runtime lifecycle, and occupancy are all implemented and validated end to end
against the two real machines.

What remains is either **deferred against evidence**, **environmental**, or
**cleanup** — not capability waiting to be built.

### 7.1 The next expansion must be justified by new evidence

Development does **not** continue merely to keep moving. The next meaningful
expansion should be justified by **new evidence** — for example:

- **a second real project** (a different ROS 2 / Isaac project, proving the model
  generalises beyond one codebase), or
- **a genuine multi-target workload** (work that actually must span machines,
  which is what would justify revisiting the deferred scheduling remainder),

rather than by an **architectural desire to fill the remaining roadmap**.

### 7.2 Status of the remaining roadmap

| Item | Disposition |
| :--- | :--- |
| R8 scheduling / queues / reservations | **deferred** — awaiting observed contention, not an implementation gap |
| R9 third artifact destination | **deferred** — the requirement says *eventually*; no use case has needed one |
| R10 monitoring web UI | **deferred** by requirement |
| G4 `remotes:` shim | **cleanup** — independent, needs a migration path |
| DDS-over-Tailscale | **environmental** — not a caasi defect |
| Idle race | **by design** — solving it needs reservations, which are out of scope |

**No further capability work is started.** The state is preserved as-is.
