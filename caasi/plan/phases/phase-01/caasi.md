# Existing Caasi Is the Starting Point

Caasi is **not a greenfield project**.

A substantial amount of Caasi has already been implemented, tested, documented, and organized before this OpenMover exercise.

The OpenMover work must therefore begin from the existing Caasi implementation.

The objective is to **use, validate, integrate, improve, and extend what already exists**, not to replace it with a new system simply because a different design appears cleaner.

---

## 1. Existing Functionality Comes First

Before implementing anything new:

1. inspect the existing Caasi implementation;
2. read the relevant Caasi documentation;
3. identify existing commands and capabilities;
4. determine how they are currently intended to work;
5. use the existing capability when it is appropriate;
6. test it against the real OpenMover project.

Do not recreate functionality that Caasi already provides.

Do not create parallel implementations merely because the existing implementation is not yet perfect.

If existing functionality needs improvement, first understand why it was designed the way it is.

---

## 2. A Gap Is Not Automatic Permission to Implement

When something cannot currently be done, treat that as a **Caasi gap**, not an automatic implementation task.

The process is:

```text
OpenMover requirement
        ↓
Check existing Caasi
        ↓
Existing capability?
    ┌───┴───┐
   YES      NO
    │        │
    ▼        ▼
Use it    Document gap
             │
             ▼
        Propose solution
             │
             ▼
          Ask user
             │
       ┌─────┴─────┐
       │           │
    Approved     Not approved
       │           │
       ▼           ▼
 Implement       Continue with
   change        existing approach
```

The agent must not interpret:

> "Caasi doesn't currently support this"

as:

> "I am authorized to add it."

---

# 3. Existing Design Has Priority

Before proposing a new abstraction, inspect whether an existing Caasi abstraction can already represent the requirement.

For example, do not automatically create:

* a new project system
* a new job system
* a new scheduler
* a new environment system
* a new artifact system
* a new remote protocol
* a new configuration format

if an existing Caasi component can reasonably be extended.

The preferred order is:

1. use existing capability;
2. configure existing capability;
3. extend existing capability if necessary;
4. only introduce a new abstraction when there is a demonstrated architectural reason.

Any significant extension or new abstraction requires discussion and approval first.

---

# 4. Documentation Is Part of the Existing System

Caasi documentation under:

```text
/caasi/docs/
```

is part of the product.

When Caasi functionality is changed or added, the corresponding documentation must also be updated.

Do not create a separate undocumented system inside the OpenMover project.

The general rule is:

```text
Caasi implementation
        ↕
Caasi documentation
        ↕
OpenMover integration
```

All user-facing Caasi capabilities should be represented in `/caasi/docs/` according to the existing documentation structure and conventions.

---

# 5. Do Not Create a Second Caasi Documentation System

The `/plan` directory is the persistent planning and development memory for this exercise.

It is **not a replacement for `/caasi/docs`**.

Use:

```text
/plan/
    planning
    decisions
    current state
    audits
    vision
    development history
```

for the development process.

Use:

```text
/caasi/docs/
    actual Caasi documentation
    commands
    behavior
    architecture
    usage
    configuration
    workflows
```

for the Caasi product itself.

Information should be placed in the appropriate location rather than duplicated unnecessarily.

---

# 6. Documentation Must Reflect Reality

Do not document functionality merely because it is planned.

Documentation should clearly correspond to actual implementation.

When appropriate, distinguish between:

* implemented
* partially implemented
* experimental
* planned
* future

Do not make Caasi appear more capable than it actually is.

Likewise, when a capability becomes implemented and stable, update the appropriate `/caasi/docs/` documentation so future agents and users can discover it.

---

# 7. Preserve Existing Caasi Behavior

When modifying Caasi, consider existing users and commands.

Do not casually:

* remove commands
* change command semantics
* rename interfaces
* change configuration formats
* break existing project files
* invalidate existing runs
* rewrite working components
* remove compatibility
* replace working implementations

If a breaking change appears necessary, stop and discuss it before implementation.

Prefer additive and backward-compatible changes when practical.

---

# 8. The OpenMover Exercise Is an Integration Test

OpenMover should be treated as a demanding real-world test of the existing Caasi architecture.

The first question should always be:

> **"Can the existing Caasi already do this?"**

not:

> **"How should we build this?"**

Only after establishing that the existing system is insufficient should architectural discussion begin.

This prevents the dogfooding exercise from becoming an uncontrolled rewrite.

---

# 9. Improvements Should Generalize

When a missing capability is approved for implementation, it should be designed as a Caasi capability rather than as an OpenMover-specific hack.

For example:

Bad:

```text
Add special OpenMover command.
```

Potentially appropriate:

```text
Add generic resource requirement support,
then use it for OpenMover.
```

The goal is:

```text
Real OpenMover requirement
        ↓
General Caasi capability
        ↓
OpenMover uses it
        ↓
Other projects can use it
```

OpenMover is the test case, not the reason to hard-code OpenMover-specific behavior into Caasi.

---

# 10. No Autonomous Scope Expansion

The agent must not turn a single missing feature into an uncontrolled redesign.

If implementing something appears to require:

* a new architecture
* a new subsystem
* a major schema change
* a new dependency
* a new execution model
* a breaking change
* significant refactoring

stop and present the proposal before proceeding.

Small implementation details within an already-approved design can be handled normally.

Architectural decisions require discussion.

---

# 11. Caasi Documentation and Development Move Together

Whenever an approved Caasi capability is implemented:

```text
Design
  ↓
Implementation
  ↓
Tests
  ↓
Documentation
  ↓
OpenMover validation
  ↓
Git commit
  ↓
Plan/current update
```

The result should leave both:

* the Caasi repository
* the persistent project plan

in a state where another agent can understand what changed.

---

# 12. Core Principle

> **Build on what exists. Do not rebuild what already works. Identify gaps from real requirements. Discuss proposed changes before implementation. Implement approved general capabilities. Document them in Caasi's existing documentation.**

Caasi should evolve continuously, but evolution should be deliberate rather than autonomous.

The existing Caasi system is the foundation.

OpenMover is the real-world test.

The user remains the decision-maker for significant architectural changes.
