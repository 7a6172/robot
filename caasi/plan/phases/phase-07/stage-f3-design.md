# Phase 7 Stage F3 Design: Target-Aware Tool Invocation

**Status:** Design only. **Nothing implemented.**
**Date:** October 2026
**Requirement:** **R2** — target-aware existing tools
**Traceability:** [`traceability.md`](traceability.md)
**Reports:** F1 acceptance review [`stage-f1-acceptance-review.md`](stage-f1-acceptance-review.md)

---

## 1. The principle

> **caasi supplies context, then gets out of the way.**

caasi must not reimplement existing tools or their domain protocols. The eventual
interface may look like:

```bash
caasi rviz2 --target robot-01
caasi rqt --target robot-01
caasi rosbag record --target robot-01 /scan
```

Each means: **resolve the target, configure the context the tool needs, then
execute the normal existing tool.** There is no RViz implementation, no rqt
subsystem, and no rosbag reimplementation.

**The test:** if the tool were replaced by a different tool tomorrow, the mechanism
should be unchanged.

---

## 2. What "target context" is

Target context is **the set of facts a local tool needs in order to operate against
a target's ROS 2 system**. It is resolved from the target, not assumed.

| Context element | Source | Class |
| :--- | :--- | :--- |
| ROS distro + install root | target ROS environment probe | **measured** |
| Whether a `ros2` CLI exists at all | target probe | **measured** |
| `RMW_IMPLEMENTATION` if the target sets it | target probe | **measured** |
| Overlay / workspace to source | deployment record + target filesystem | **measured** |
| **`ROS_DOMAIN_ID`** | **target-side value or explicit `--domain`** | **hazard — see §3** |
| Network reachability | existing target probe | **measured** |
| DDS discovery topology | **the DDS implementation's job** | **not caasi's** |

### 2.1 Authoritative vs unverified

Applying the rule that absence of evidence is not evidence of absence:

| Situation | Treatment |
| :--- | :--- |
| Target was probed and reports a value | **authoritative** — use it |
| Target was probed and reports **nothing** (e.g. no `RMW_IMPLEMENTATION` set) | **unset**, which is a real answer — do **not** substitute a local value |
| Target could **not** be probed | **unverified** — say so, and either refuse or proceed only with an explicit operator override |

Substituting the workstation's `RMW_IMPLEMENTATION` because the target has none
would silently change the target's DDS behaviour. That must never happen by
default.

---

## 3. The domain-ID hazard (the one genuinely subtle part)

A GUI tool on the workstation can only see a robot's ROS graph if **the DDS
domain and discovery match**. This is the element most likely to be got wrong, and
the design must not paper over it:

- If the local tool uses the workstation's default domain while the robot runs on
  another, **the tool starts, shows an empty graph, and looks like it works.** That
  is precisely the "empty graph mistaken for a valid observation" failure E2 already
  guarded against with `--domain`.
- caasi therefore **resolves or requires** the domain, and **states which was used**.

Rules:

1. An explicit `--domain` **wins**, always.
2. Otherwise the target's own value is used **if the target actually reports one**.
3. Otherwise the domain is **unknown**, and the tool must either be run with
   `--domain` or told explicitly to use a default — **never silently defaulted**.
4. Cross-machine DDS discovery is **the DDS implementation's responsibility.**
   caasi sets the environment; it does not implement discovery, add multicast
   relays, or invent a bridge.

This is where "caasi supplies context, then gets out of the way" is tested hardest:
caasi's job ends at a correct environment.

---

## 4. Architecture: a thin, declarative wrapper

### 4.1 One generic mechanism

```
caasi <tool> --target <target> [tool args...]
```

A registry maps a tool name to its invocation, and everything else is shared:

```yaml
# caasi.yaml (project) or caasi config — declarative, not code
tools:
  rviz2:
    invoke: rviz2
    needs: ros2
    environment:
      - ROS_DOMAIN_ID={{context.domain_id}}
      - RMW_IMPLEMENTATION={{context.rmw}}
  rqt:
    invoke: rqt
    needs: ros2
    environment:
      - ROS_DOMAIN_ID={{context.domain_id}}
  rosbag:
    invoke: ros2 bag
    needs: ros2
    environment:
      - ROS_DOMAIN_ID={{context.domain_id}}
```

**Nothing above is RViz-specific.** The mechanism resolves a `context` and
substitutes it; a new tool is a new entry, not new code.

### 4.2 Flow

```text
1. resolve target              (find_target — name, never chosen for you)
2. probe target context        (reuse the E2 ROS probe; measured facts)
3. resolve the domain          (explicit > target-reported > refuse/override)
4. build the environment       (from the registry entry + context)
5. exec the real tool          (exec, not a subprocess wrapper)
6. report what context was used
```

Step 5 is deliberate: **`exec`** so the tool replaces caasi's process and behaves
exactly as if the operator had run it. caasi does not manage the tool's lifecycle.

### 4.3 Errors

Following the established discipline:

| Failure | Behaviour |
| :--- | :--- |
| Unknown tool | refuse, listing the registry |
| Target unreachable | refuse, with the transport reason |
| Target has no ROS 2 | refuse, saying so — a GUI tool against a ROS-less target is meaningless |
| Domain unresolved | refuse and explain, or require an explicit override |
| Tool binary absent locally | refuse, naming the binary — the tool runs **locally** |
| Tool exits non-zero | caasi exits with the **tool's own code**, unmodified |

---

## 5. How a local GUI tool sees a remote ROS 2 system

Worth stating because it constrains the design: **the tool runs locally; the ROS
graph is remote.** caasi's contribution is only:

- environment (`ROS_DOMAIN_ID`, `RMW_IMPLEMENTATION`, `ROS_DISTRO`),
- the correct overlay sourcing **when the tool needs the project's messages/types**,
- a truthful statement of which domain/discovery was used.

Everything beyond that — multicast, DDS discovery across subnets, DDS
configuration, tunnels — is **the DDS implementation's responsibility**, and if
discovery cannot work across a given network that is a deployment/network fact to
report, not something caasi should invent around. Over Tailscale this may simply
not work, and the design must **report that honestly rather than appear to work
with an empty graph.**

**A design consequence:** the tool's *success* cannot be inferred from "the process
started". The wrapper therefore reports the resolved context explicitly so an
operator can tell "connected" from "connected to nothing".

---

## 6. Pass-through of ordinary CLI tools

For a tool like `rosbag`, the arguments belong to the tool, not to caasi:

```bash
caasi rosbag record --target robot-01 /scan /tf
```

Everything after the known caasi options **must reach the tool unchanged** —
including flags caasi does not recognise, and including `--` to remove ambiguity.
caasi parses only its own options and passes the rest verbatim. This mirrors how
the CLI already treats upstream tools: expose them, don't absorb them.

---

## 7. Scope boundaries

**In scope for F3 (small):**

- one generic `caasi <tool> --target <t>` mechanism (`exec` of the real tool);
- a declarative registry with **one or two** representative entries;
- target-context resolution reusing the existing E2 ROS probe;
- explicit domain resolution with refusal rather than silent defaulting;
- honest reporting of the context used;
- validation against `local` and `u24-307`.

**Explicitly NOT in scope** (stated so the design cannot drift):

- automatic target selection, forwarding, queues, scheduling, multi-target
  orchestration;
- new ROS/DDS functionality, discovery bridges, tunnels or multicast relays;
- an RViz replacement, a rqt subsystem, or any tool reimplementation;
- remote GUI management (no remote display, no X forwarding);
- a web UI;
- **G4 cleanup** (`remotes:` retirement);
- lifecycle/daemonising of the launched tool — F3 launches it and gets out of the
  way.

---

## 8. Validation plan (against the two real machines)

| Check | Expectation |
| :--- | :--- |
| `caasi <tool> --target local` | resolves context from the workstation, reports the domain used, runs the tool |
| Unknown tool | refused, listing the registry |
| Unreachable target (`u24-307` with the relay down) | refused with the transport reason |
| Target without ROS 2 | refused, saying ROS 2 was not detected |
| **Domain unresolved** | **refused** (or requires an explicit `--domain`) — **never silently defaulted**; this is the empty-graph guard |
| Explicit `--domain` | honoured and echoed back |
| Argument pass-through | tool receives unrecognised flags unchanged |
| Tool non-zero exit | caasi returns the tool's own exit code |
| `u24-307` context resolution | the target's **measured** distro/RMW are used, not the workstation's |

**The negative cases carry the weight.** The positive case (a GUI window appears)
is the easy one; the ones that matter are that caasi **refuses rather than
pretending** — no silent domain default, no fabricated ROS context, no success
inferred from a started process.

**Honest expectation to record up front:** for a **remote GUI tool across
Tailscale**, DDS discovery may not work even when the environment is correct. If it
does not, the finding is *"the environment is resolved correctly but DDS discovery
does not traverse this network"* — reported as a network/DDS fact, **not** worked
around, and **not** claimed as working.

---

## 9. Representative proof cases (to be implemented later, not now)

Two, chosen to prove generality rather than to build a subsystem:

1. **`rviz2`** — the GUI case, where the domain/discovery question is unavoidable.
2. **`rosbag record`** — the ordinary-CLI case, where argument pass-through and the
   tool's own exit code are the point.

If both work through **one** mechanism with no per-tool code, the mechanism is
generically sufficient. If either needs special handling, the design is wrong.

---

## 10. Newly discovered gaps

Recorded from the F1 acceptance review and this design pass:

| Item | Status |
| :--- | :--- |
| **Duplicated requirement ladder** (`check.py` vs `selection.py`) | **Open consolidation item.** Agrees for default projects; diverges under `check.strict`. Not blocking F3. |
| **G4** `remotes:` shim retirement | **Open / cleanup**, excluded from F3 by instruction |
| **Local build/run destination mismatch** | **Open, pre-existing**, carried forward from F2 |
| **No `caasi check --target`** | By design: F1 added `target select` instead. Worth noting that the two commands answer adjacent questions and the consolidation item above would unify them. |

Nothing in this design requires changing F1 or F2.
