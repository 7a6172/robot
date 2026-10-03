# Caasi OpenMover Rework — Agent Operating Plan

## 1. Purpose

This is a real-world dogfooding and development exercise for **Caasi**.

The objective is to take the existing OpenMover robotics research project and create a new, Caasi-managed working project that provides better:

* project organization
* dependency and environment management
* experiment management
* local execution
* remote execution
* resource management
* scheduling and queuing
* logging and monitoring
* artifact and data management
* reproducibility
* provenance
* packaging and transfer

OpenMover is the real robot/project used in the associated robotics research.

This is **not** a toy example and is not merely a test of whether Caasi can launch Isaac Sim.

The OpenMover project should be used to discover what Caasi needs to become a practical project and execution manager for real robotics/AI work.

---

# 2. Absolute Safety Boundaries

There are three important locations.

## `/caasi`

This is the Caasi source repository.

It may be modified **only when explicitly approved by the user**.

If a missing Caasi capability is discovered:

1. document the problem;
2. explain what capability is missing;
3. propose a design;
4. wait for approval;
5. only then modify Caasi.

Do not redesign Caasi autonomously simply because something is inconvenient.

---

## `/openmover_robot`

This is the original ROS1 OpenMover project.

**STRICT READ-ONLY.**

Never:

* edit files
* delete files
* rename files
* move files
* generate files inside it
* run commands that intentionally modify its contents
* build into it if that changes the source tree
* create generated artifacts inside it

It may be inspected and used as a reference.

If files are needed for the new project, copy them into the Caasi working directory.

---

## `/openmover_ws`

This is the existing complete ROS2 + Isaac Sim + Isaac Lab OpenMover environment.

It contains the existing research/project material, including source code, configurations, experiments, maps, logs, runs, results, assets, datasets, and other accumulated project data.

**STRICT READ-ONLY.**

Treat it as an existing reference/source environment.

Do not clean it up.

Do not reorganize it.

Do not "fix" it in place.

Do not delete old runs, logs, generated data, maps, experiments, or other material.

If something needs to be changed, copied, adapted, or reorganized, do so in the new Caasi-managed project.

---

## New Caasi OpenMover workspace 

`/caasi-workspace/openmover_ws/`

Create a separate new directory for the Caasi-managed version of OpenMover.

This directory is the primary working area.

Files may be copied from `/openmover_robot` and `/openmover_ws` into it and modified there.

The exact location should be recorded in `plan/current.md`.

The new workspace should become the project that Caasi manages and executes.

---

# 3. First Action: Git Checkpoint

Before doing meaningful work, establish a Git recovery point.

The first step is to inspect the current Caasi repository state and create a commit representing the starting point.

Do not assume the repository is clean.

Run:

```bash
git status
git diff
git log -5 --oneline
```

Then establish a clearly named baseline commit.

If there are existing uncommitted changes that belong to the user, do not destroy or overwrite them. Record the situation and ask before doing anything that could alter them.

The purpose of the first commit is:

> **A known point from which the entire Caasi development exercise can be recovered.**

After this point, meaningful Caasi changes must be committed in logical checkpoints.

Never use Git history destructively merely to make the repository look clean.

---

# 4. Persistent Agent Memory

The agent must not rely on its conversation context as the source of truth.

The `/plan` directory is the persistent project memory.

Use it continuously.

Recommended structure:

```text
/caasi/plan/
├── plan.md
├── current.md
├── temporary.md
│
├── phases/
│   ├── phase-01-discovery.md
│   ├── phase-02-project-model.md
│   ├── phase-03-execution.md
│   └── ...
│
├── audits/
│   ├── ...
│
├── logs/
│   ├── ...
│
├── vision/
│   ├── ...
│
└── reference/
    ├── ...
```

The structure may evolve as the project becomes clearer. YOU MUST READ THE `/plan` FOLDER TO UNDERSTAND THE PROJECT FIRST.

Do not create large amounts of documentation merely for documentation's sake. The purpose is to preserve decisions, evidence, state, and reasoning that would otherwise disappear when the agent's context window changes.

---

# 5. `plan.md`

`plan.md` is the long-term operating document.

It should contain:

* project purpose
* safety boundaries
* major objectives
* architectural principles
* important rules
* phase structure
* decision-making rules
* relationship between OpenMover and Caasi
* persistent documentation rules
* approval requirements
* Git/checkpoint policy

Do not turn `plan.md` into a running activity log.

It should remain relatively stable.

If the fundamental strategy changes, update it deliberately and commit the change.

---

# 6. `current.md`

`current.md` is the most important short-term state document.

It should always answer:

```text
Where are we?
What has been completed?
What are we doing now?
What is the next concrete step?
What remains unresolved?
What decisions are waiting for the user?
What Caasi gaps have been discovered?
What files/directories are currently relevant?
What was the last checkpoint?
```

Update it whenever the working state materially changes.

An agent starting with an empty conversation should be able to read:

```text
plan.md
current.md
```

and understand the current project state without needing previous conversation history.

---

# 7. `temporary.md`

`temporary.md` contains short-lived information useful during active work.

Examples:

* temporary investigation notes
* command output summaries
* hypotheses
* things currently being checked
* temporary paths
* intermediate observations
* questions to resolve later

Temporary information must not become the only record of an important decision.

When something becomes important or permanent, move it into the appropriate:

* `plan.md`
* `current.md`
* phase document
* audit
* vision document
* reference document

`temporary.md` may be periodically cleaned up.

---

# 8. Phases

Large work should be divided into explicit phases.

A phase should normally contain:

```text
Goal
Scope
Inputs
Work performed
Findings
Decisions
Caasi gaps discovered
Implementation performed
Tests
Result
Next phase
```

Do not attempt to solve the entire Caasi architecture in one pass.

The real OpenMover project should progressively reveal the requirements.

A phase can be completed when its objective is sufficiently understood and recorded, even if later phases reveal additional improvements.

---

# 9. Audits

Use `/plan/audits/` for structured assessments.

Examples:

* initial OpenMover inventory
* Caasi capability audit
* project-model audit
* dependency audit
* environment audit
* execution audit
* remote execution audit
* resource-management audit
* reproducibility audit
* data/artifact audit
* documentation-vs-implementation audit

Audits should distinguish between:

```text
Caasi already supports this
Caasi partially supports this
Caasi can represent this but cannot execute it
Caasi cannot currently represent this
External tool must handle this
Not required
Unknown / needs investigation
```

Do not claim functionality merely because documentation describes it.

Verify actual implementation and behavior.

---

# 10. Logs

Use `/plan/logs/` for important chronological records.

Logs should capture meaningful events such as:

* major discoveries
* important failures
* environment problems
* successful integration tests
* architecture changes
* user decisions
* Caasi changes
* rejected approaches
* significant experiments

Do not copy enormous raw command output into plan documents.

Summarize the useful information and retain references to raw logs/artifacts when appropriate.

---

# 11. Vision

Use `/plan/vision/` for longer-term architectural ideas that are not yet implementation tasks.

Examples:

* project architecture
* execution architecture
* remote execution architecture
* scheduler/resource architecture
* artifact architecture
* environment architecture
* future Caasi UX
* multi-machine execution
* reproducibility model

A vision document is not automatically an implementation requirement.

Ideas remain proposals until explicitly accepted.

---

# 12. Reference

Use `/plan/reference/` for durable external/project information that the agent repeatedly needs.

Examples:

* OpenMover architecture
* existing directory structure
* important commands
* environment details
* Isaac configuration
* ROS package relationships
* experiment inventory
* dataset inventory
* important research-paper information
* known machine requirements

Reference material should describe facts rather than become a place for arbitrary temporary notes.

---

# 13. Work From Reality

The existing OpenMover project is the primary real-world input.

Inspect it before designing abstractions.

Do not invent a project model based only on what seems theoretically clean.

Determine:

* what actually exists
* how it is currently organized
* which components depend on which others
* what is source
* what is generated
* what is configuration
* what is data
* what is an artifact
* what is environment-specific
* what is reproducible
* what is expensive to regenerate
* what needs to move to another machine
* what should remain local
* what is needed to execute an experiment
* what information is currently implicit

The goal is to make Caasi fit real work, not to force the real project into an arbitrary abstraction.

---

# 14. Copy, Don't Mutate

When bringing OpenMover into the Caasi-managed project:

```text
/openmover_robot
/openmover_ws
        │
        │ inspect
        │ copy/import
        ▼
Caasi-managed OpenMover project
```

The new project may reorganize and modify copied material.

Preserve enough information to understand where imported material originated.

When practical, record:

* original source path
* import/copy date
* source revision if available
* whether the item is copied or generated
* whether it is expected to remain synchronized with the source

Do not establish a live write relationship to the read-only source directories.

---

# 15. Use Caasi First

When performing project-management or execution operations, prefer Caasi capabilities when they exist.

The purpose of this exercise is to test Caasi itself.

Do not bypass Caasi unnecessarily by manually implementing functionality that Caasi already provides.

For example, if Caasi can:

* initialize a project
* register a robot
* register a task
* inspect environments
* validate dependencies
* start runs
* manage logs
* capture provenance
* inspect artifacts

then use those capabilities.

However, do not force unrelated operations through Caasi merely for the sake of saying Caasi was used.

The underlying robotics ecosystem remains responsible for its own domain:

* ROS remains ROS
* Isaac Sim remains Isaac Sim
* Isaac Lab remains Isaac Lab
* PyTorch remains PyTorch
* datasets remain datasets
* robot source remains robot source

Caasi should organize, connect, configure, invoke, monitor, and record these components.

---

# 16. Discovering Caasi Gaps

When Caasi cannot properly perform something required by the OpenMover project, do not immediately create a workaround inside Caasi.

Record:

```text
Problem:
What are we trying to do?

Current Caasi behavior:
What can Caasi currently do?

Gap:
What is missing?

Why it matters:
Why is this required for OpenMover?

Possible design:
How could Caasi support it?

Alternatives:
Could this remain outside Caasi?

Recommendation:
What should we do?

Approval:
Pending / Approved / Rejected
```

Then ask the user when an architectural or implementation decision is required.

---

# 17. Approval Boundary

The agent has permission to:

* inspect the read-only OpenMover sources
* create and modify the new Caasi OpenMover workspace
* run experiments there
* copy required files there
* test Caasi
* inspect Caasi source
* document findings
* create plans and audits
* propose Caasi changes

The agent does **not** have autonomous permission to:

* modify `/openmover_robot`
* modify `/openmover_ws`
* make architectural changes to Caasi
* add major Caasi capabilities merely because they appear useful
* remove existing Caasi functionality
* perform destructive migrations
* rewrite project history
* discard existing research data

When in doubt, stop and ask.

---

# 18. Git Checkpoints

Use Git as another layer of persistent memory.

Meaningful Caasi changes should be committed.

Examples:

```text
baseline: before OpenMover dogfooding
docs: record OpenMover project inventory
feat(project): add dependency relationship support
feat(run): add resource requirements
feat(remote): add artifact transfer
fix(run): preserve remote provenance
test: validate OpenMover execution workflow
```

The exact commit style may evolve with the repository's existing conventions.

The important rule is:

> **Do not accumulate a huge opaque set of unrelated changes before committing.**

After completing a meaningful piece of work:

1. update the relevant plan documents;
2. test the change;
3. inspect the diff;
4. commit it;
5. record the commit in `current.md`.

Git history should make it possible to understand how Caasi evolved during this exercise.

---

# 19. Context-Window Independence

Assume that the next agent instance may know nothing about this conversation.

At every meaningful checkpoint, enough information must exist on disk for another agent to continue.

At minimum:

```text
/plan/plan.md
/plan/current.md
```

must describe the current state.

Important details should not exist only in:

* chat history
* agent memory
* terminal scrollback
* temporary reasoning
* undocumented assumptions

If an important discovery is made, record it.

If an important decision is made, record it.

If an approach fails, record why.

If an approach is rejected, record why.

---

# 20. Before Stopping Work

Before ending a meaningful work session:

1. finish or document the current operation;
2. update `current.md`;
3. record important findings;
4. record unresolved questions;
5. record the exact next step;
6. update phase/audit/reference documents when appropriate;
7. inspect Git status;
8. commit completed Caasi changes when appropriate;
9. record the relevant commit hash in `current.md`.

The next agent should not have to reconstruct what happened from Git diffs alone.

---

# 21. When Starting a New Session

Before doing substantial work:

```text
1. Read plan/plan.md
2. Read plan/current.md
3. Read relevant phase documents
4. Read relevant audits/reference documents
5. Inspect git status
6. Inspect recent commits
7. Continue from the documented next step
```

Do not redo completed work merely because it is not present in the current context.

Do not assume undocumented work was completed.

Use the repository and plan documents as the source of truth.

---

# 22. The Real Goal

The goal is not to maximize the number of Caasi commands.

The goal is to determine whether Caasi can become a practical manager for a real robotics/AI project.

The target lifecycle is approximately:

```text
Existing project
      ↓
Understand
      ↓
Import / organize
      ↓
Resolve dependencies
      ↓
Validate environment
      ↓
Define execution
      ↓
Select resources
      ↓
Package / transfer
      ↓
Queue / schedule
      ↓
Execute
      ↓
Monitor
      ↓
Logs / metrics
      ↓
Artifacts
      ↓
Provenance
      ↓
Reproduce / inspect
```

Local and remote execution should ultimately follow the same conceptual model.

---

# 23. Dogfooding Principle

Every significant capability added to Caasi should be tested against the OpenMover project when applicable.

Likewise, every significant difficulty encountered while managing OpenMover should be considered evidence about Caasi's design.

The project should therefore create a feedback loop:

```text
Real OpenMover requirement
        ↓
Try existing Caasi
        ↓
Works
  │
  └──────────────→ record/test

Doesn't work
        ↓
Document gap
        ↓
Discuss design
        ↓
User approval
        ↓
Implement Caasi change
        ↓
Test against OpenMover
        ↓
Commit
        ↓
Continue
```

This is the primary development loop for this exercise.

---

# 24. Definition of Success

This exercise is successful when the resulting Caasi-managed OpenMover project can progressively provide a coherent way to:

* understand and organize the project
* represent its components and relationships
* manage dependencies and environments
* manage experiments and tasks
* execute locally
* execute remotely
* select appropriate resources
* wait when resources are unavailable
* monitor execution
* retain logs
* retain artifacts
* preserve provenance
* package and transfer required project/data state
* reproduce important runs
* understand failures
* recover from interrupted execution
* manage the project without requiring the original ROS/Isaac projects to be modified

Not all of these capabilities need to exist immediately.

Missing capabilities should be discovered, documented, discussed, and implemented incrementally.

---

# 25. Current Principle

**Do not design everything upfront.**

Start with the real OpenMover project.

Understand it.

Try to represent it with Caasi.

Try to execute it.

Observe what works and what does not.

Use those findings to guide Caasi development.

The project itself is the test.

The Caasi repository is the system being improved.

The `/plan` directory is the persistent memory connecting the work across agents, sessions, and context windows.
