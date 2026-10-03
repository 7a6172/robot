# Caasi — Product Vision

## 1. What Caasi Is

Caasi is a project and execution management system for robotics and AI workloads.

It exists to solve a practical problem:

> **Robotics software increasingly depends on large, complex software stacks and increasingly demanding compute, while the hardware available to the developer is often limited, fragmented, or remote.**

Caasi should make those constraints manageable.

It should allow a robotics/AI project to be organized once and then executed using whatever appropriate resources are available:

* local CPU
* local GPU
* multiple local GPUs
* another workstation
* a remote workstation
* a remote GPU server
* a cluster or future scheduler
* containers
* different environments

without requiring the project itself to be fundamentally rewritten for every execution environment.

Caasi is therefore not simply a CLI wrapper around Isaac Sim, ROS 2, or another robotics tool.

It is the **management and execution layer connecting the project to the available computing resources**.

---

# 2. The Origin of Caasi

Caasi originated from a very practical hardware limitation.

A robotics project may require software such as:

* ROS 2
* Isaac Sim
* Isaac Lab
* PyTorch
* CUDA
* perception systems
* SLAM
* navigation
* motion planning
* datasets
* machine-learning models

while the available machine may have only a limited amount of:

* GPU VRAM
* system RAM
* CPU capacity
* storage
* GPU compute
* thermal/power capacity

For example, an RTX 3080 with 10 GB VRAM can run many useful workloads, but it cannot simply be treated as an unlimited GPU.

The practical question becomes:

> **What should happen when the workload is larger than the available hardware?**

The answer should not always be:

> Buy a larger machine.

It should also be:

> **Understand the workload, understand the available resources, and intelligently use what is available — locally or remotely.**

That problem is one of the fundamental motivations for Caasi.

---

# 3. Two Fundamental Responsibilities

Caasi has two primary responsibilities.

## 3.1 Organized Projects

Caasi should understand a robotics/AI project as a project rather than as a collection of unrelated commands.

A project may contain:

* robots
* ROS 2 packages
* simulation environments
* Isaac Sim scenes
* Isaac Lab tasks
* configurations
* experiments
* datasets
* models
* maps
* sensors
* controllers
* navigation systems
* perception systems
* training jobs
* evaluation jobs
* generated artifacts
* logs
* results
* dependencies
* environments
* hardware requirements

Caasi should know how these pieces relate to one another.

It should be possible to answer questions such as:

```text
What is this project?

What does this experiment require?

Which environment does this task use?

Which robot does this simulation represent?

Which datasets are required?

Which dependencies are required?

Which GPU is required?

Which results came from this run?

Can this experiment be reproduced?

Can this job run on another machine?
```

The project should have an organized, inspectable representation rather than relying entirely on undocumented shell commands and directory conventions.

---

## 3.2 Execution

Caasi should also manage execution.

Execution includes:

* local execution
* remote execution
* resource discovery
* resource matching
* scheduling
* queueing
* packaging
* transfer
* environment preparation
* launching
* monitoring
* logging
* failure handling
* artifact collection
* provenance
* recovery
* reproducibility

The project describes **what exists**.

The execution system determines **how, where, and when it should run**.

---

# 4. Hardware Constraints Are a First-Class Problem

Caasi should treat hardware limitations as part of the execution model rather than as unexpected failures.

A workload may require:

```text
GPU VRAM: 14 GB
System RAM: 32 GB
CPU: 8 cores
Storage: 100 GB
CUDA: required
Isaac Sim: required
```

while the current machine may have:

```text
GPU VRAM: 10 GB
System RAM: 48 GB
CPU: 12+ cores
Storage: sufficient
```

Caasi should be able to determine that the workload cannot simply be treated as an ordinary execution.

Depending on the workload, possible strategies may include:

* selecting a lighter configuration
* reducing concurrency
* moving data to system RAM
* using CPU execution
* changing batch size
* using a different backend
* using another local GPU
* using another machine
* queueing until a suitable resource is available
* transferring the workload to a remote machine

The exact strategy depends on the workload.

Caasi should not pretend that every workload can be magically optimized.

Instead, it should understand the constraints and make execution decisions based on evidence.

---

# 5. Local and Remote Are One Execution Model

Local and remote execution should not become two unrelated systems.

Conceptually:

```text
                    Caasi
                      │
                 Execution
                      │
        ┌─────────────┴─────────────┐
        │                           │
      Local                       Remote
        │                           │
     machine                     machine
        │                           │
        └─────────────┬─────────────┘
                      │
                    Run
```

A user should be able to describe a workload without having to redesign the workload merely because it is moving from one machine to another.

The differences should primarily be:

* available resources
* environment
* location
* transfer requirements
* scheduling
* permissions
* execution backend

The run itself should retain the same conceptual identity.

---

# 6. Resource Awareness

Caasi should understand available resources.

This includes more than detecting a GPU.

Potential resource information includes:

### Compute

* CPU model
* CPU cores/threads
* CPU availability
* GPU model
* GPU count
* GPU memory
* GPU utilization
* GPU availability
* accelerator type

### Memory

* system RAM
* available RAM
* GPU VRAM
* available VRAM
* storage capacity
* available storage

### Software

* operating system
* Python
* CUDA
* drivers
* ROS 2
* Isaac Sim
* Isaac Lab
* PyTorch
* containers
* relevant packages

### Devices

* cameras
* LiDAR
* robot hardware
* USB devices
* network interfaces
* other accelerators

### Remote state

* machine availability
* current jobs
* queued jobs
* resource reservations
* connectivity
* transfer state

Resource information should become part of the execution decision.

---

# 7. Resource Matching

A job should be able to declare requirements.

For example:

```text
GPU:
  required: true
  minimum_vram: 12 GB

RAM:
  minimum: 24 GB

CPU:
  minimum: 8 cores

software:
  ros: jazzy
  isaac_sim: required
  cuda: required
```

Caasi should compare these requirements against available execution targets.

Conceptually:

```text
Job
 │
 ▼
Requirements
 │
 ▼
Resource Resolver
 │
 ├── Local machine
 ├── Remote workstation A
 ├── Remote workstation B
 └── Future cluster
 │
 ▼
Compatible targets
 │
 ▼
Selection / queue
 │
 ▼
Execution
```

This is one of the central capabilities Caasi should eventually provide.

---

# 8. ROS 2 Is an Important Part of the Solution

Caasi should take advantage of what ROS 2 already provides.

Caasi should not become another ROS implementation.

ROS 2 already provides valuable capabilities around:

* nodes
* topics
* services
* actions
* parameters
* launch
* packages
* graphs
* composition
* middleware
* lifecycle
* distributed systems
* hardware abstraction
* simulation integration

Caasi should build on this ecosystem.

For example, if a robotics system already has ROS 2 launch files describing how its components start, Caasi should understand and orchestrate those launch mechanisms rather than replacing them with an entirely new Caasi-specific runtime.

Likewise, Caasi should use ROS 2's distributed nature when useful for remote robotics workloads.

---

# 9. ROS 2 + Caasi

The relationship should be approximately:

```text
ROS 2
  │
  ├── robot communication
  ├── nodes
  ├── topics
  ├── services
  ├── actions
  ├── launch
  └── middleware
           │
           ▼
         Caasi
           │
           ├── project organization
           ├── environment
           ├── resource management
           ├── execution
           ├── remote execution
           ├── scheduling
           ├── monitoring
           ├── provenance
           └── artifacts
```

Caasi should orchestrate the robotics system without trying to replace the robotics system.

---

# 10. Distributed Robotics

Caasi should eventually make distributed execution practical.

A robotics project might naturally split across machines.

For example:

```text
Machine A
─────────
Physical robot
ROS 2 drivers
sensors
teleoperation

        │
        │ ROS 2 / network
        ▼

Machine B
─────────
GPU
Isaac Sim
Isaac Lab
perception
training

        │
        ▼

Machine C
─────────
large dataset
training
evaluation
```

Caasi should understand this as one project with multiple execution targets.

The user should not have to manually maintain a collection of unrelated SSH sessions and shell commands to operate such a system.

---

# 11. Scheduling and Queueing

When suitable hardware is unavailable, Caasi should not necessarily fail immediately.

For example:

```text
Job A
requires 16 GB VRAM
        │
        ▼
No suitable GPU available
        │
        ▼
Queue
        │
        ▼
GPU becomes available
        │
        ▼
Execute
```

Jobs may eventually have:

* priority
* resource requirements
* deadlines
* dependencies
* estimated resource usage
* preferred machines
* fallback machines
* retry policies
* scheduling constraints

The scheduler should remain understandable and predictable.

Caasi should not hide important scheduling decisions from the user.

---

# 12. Efficient Use of Limited Hardware

Limited hardware should be treated as an optimization problem.

Caasi should help users get more useful work from the hardware they already have.

Potential strategies include:

* resource-aware job selection
* avoiding VRAM oversubscription
* scheduling workloads around GPU availability
* moving suitable workloads to CPU
* reducing unnecessary concurrency
* reusing cached assets
* avoiding unnecessary data transfers
* selecting appropriate execution targets
* using remote resources when local resources are insufficient
* queueing rather than repeatedly failing
* monitoring resource consumption
* learning from historical execution information

The exact optimization strategies should emerge from real workloads.

Caasi should not introduce complexity without demonstrated value.

---

# 13. Packaging and Transfer

Remote execution requires more than SSH.

Caasi should eventually understand what needs to move.

A project may contain:

```text
source code
configuration
dependencies
assets
datasets
models
maps
generated artifacts
logs
```

Not everything should necessarily be transferred.

Caasi should distinguish between:

* required inputs
* optional inputs
* cached data
* generated data
* reproducible data
* large immutable artifacts
* machine-local state

The execution system should be able to package and transfer what is required while avoiding unnecessary movement of large data.

Content-addressed storage, caching, incremental transfer, and shared storage may become useful mechanisms.

---

# 14. Environment Awareness

A project is not defined only by its source code.

Its execution environment matters.

Caasi should understand:

```text
Project
  +
Dependencies
  +
Environment
  +
Hardware
  =
Executable workload
```

Different machines may have different:

* drivers
* CUDA versions
* ROS versions
* Isaac versions
* Python environments
* GPUs
* system libraries
* device access

Caasi should detect compatibility before launching expensive workloads whenever practical.

---

# 15. Provenance and Reproducibility

Every meaningful execution should be understandable after it finishes.

A run should be associated with information such as:

* project
* source revision
* configuration
* environment
* hardware
* dependencies
* execution target
* command
* parameters
* start/end time
* logs
* metrics
* artifacts
* exit status
* failures

The goal is to make questions such as these answerable:

```text
What produced this result?

Where did it run?

Which GPU was used?

Which version of the project was used?

Which configuration was used?

Which environment was used?

What failed?

Can we reproduce it?
```

This is particularly important for robotics research.

---

# 16. Caasi Should Remain Thin

Caasi should not replace the tools it manages.

The underlying ecosystem remains responsible for its domain.

For example:

```text
ROS 2       → robotics middleware
Isaac Sim   → simulation
Isaac Lab   → robot learning
PyTorch     → machine learning
Nav2        → navigation
MoveIt      → manipulation
Docker      → containerization
Git         → source control
```

Caasi connects and manages these systems.

Its value comes from the layer between:

```text
Project
   ↕
Tools
   ↕
Environment
   ↕
Hardware
   ↕
Execution
```

---

# 17. Two Complementary Goals

The OpenMover work and the broader Caasi vision are not competing goals.

They should proceed simultaneously when practical.

### OpenMover

Provides:

* a real project
* real ROS 2 integration
* real Isaac Sim/Lab workloads
* real datasets
* real experiments
* real logs
* real hardware constraints
* real remote-execution requirements

It is a **dogfooding and validation environment**.

### Caasi

Provides:

* the general project model
* execution model
* resource model
* remote model
* scheduling model
* artifact model
* provenance model
* reusable infrastructure

It is the **general system being developed**.

The relationship is:

```text
                 Caasi Vision
                      │
          ┌───────────┴───────────┐
          │                       │
   General architecture      OpenMover
          │                       │
          │                 real-world test
          │                       │
          └───────────┬───────────┘
                      │
                feedback loop
                      │
                      ▼
               better Caasi
```

We should not postpone the broader Caasi design until OpenMover is finished.

Likewise, we should not design the entire Caasi system without testing it against a real project.

Both can progress together.

---

# 18. The Long-Term Model

The long-term Caasi model is:

```text
                    ┌───────────────┐
                    │    PROJECT    │
                    │               │
                    │ code          │
                    │ configs       │
                    │ tasks         │
                    │ experiments   │
                    │ datasets      │
                    │ dependencies  │
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │  REQUIREMENTS │
                    │               │
                    │ compute       │
                    │ memory        │
                    │ software      │
                    │ devices       │
                    │ data          │
                    └───────┬───────┘
                            │
                            ▼
                    ┌───────────────┐
                    │    Caasi      │
                    │               │
                    │ resolve      │
                    │ package      │
                    │ schedule     │
                    │ allocate     │
                    │ execute      │
                    │ monitor      │
                    │ record       │
                    └───────┬───────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
           LOCAL         REMOTE        CLUSTER
              │             │             │
              └─────────────┼─────────────┘
                            ▼
                         RUNS
                            │
                ┌───────────┼───────────┐
                ▼           ▼           ▼
              LOGS       ARTIFACTS   METRICS
                            │
                            ▼
                       PROVENANCE
```

The user describes the project and workload.

Caasi determines what is required.

Caasi understands what resources exist.

Caasi determines where and when the workload can run.

The underlying robotics/AI tools perform the actual work.

Caasi records what happened.

---

# 19. What Caasi Should Eventually Feel Like

The user should be able to think primarily in terms of:

> **"I have a robotics project and I want this workload to run."**

rather than:

> Which machine?
>
> Which SSH command?
>
> Which Python environment?
>
> Which ROS setup?
>
> Which Isaac installation?
>
> Is the GPU free?
>
> Do I have enough VRAM?
>
> Where are the logs?
>
> What configuration did I use?
>
> Did the remote process survive my SSH disconnect?
>
> What files need to be copied?
>
> Which result belongs to which run?

Caasi should handle the operational complexity while keeping important decisions visible and controllable.

---

# 20. Guiding Principle

The central principle of Caasi is:

> **Use the hardware, software, and robotics ecosystem that already exists as effectively as possible, while adding the missing management and execution layer needed to make complex robotics/AI projects practical, reproducible, and scalable from a constrained local machine to remote resources.**

Caasi should not assume unlimited hardware.

It should not assume a single machine.

It should not assume a single simulator.

It should not assume a single robotics framework.

It should not replace the ecosystem.

It should make the ecosystem work together.

---

# 21. Evolution

Caasi should evolve from the problems discovered through real projects.

The expected progression is:

```text
Project organization
        ↓
Environment awareness
        ↓
Local execution
        ↓
Run management
        ↓
Remote execution
        ↓
Resource matching
        ↓
Packaging and transfer
        ↓
Queueing and scheduling
        ↓
Multi-machine execution
        ↓
Advanced resource optimization
```

These are not rigid release requirements.

Real workloads should determine which capability becomes important next.

OpenMover is one of the first serious workloads through which these requirements will be discovered.

Other robotics and AI projects should eventually validate that the resulting architecture is general rather than OpenMover-specific.

---

# 22. Final Vision

Caasi should make constrained hardware less of a barrier to serious robotics and AI work.

A developer should be able to have a complex project on a modest workstation, understand what that project requires, run what fits locally, and transparently move workloads to appropriate remote resources when local hardware is insufficient.

The project should remain one project.

The execution target can change.

The hardware can change.

The environment can change.

The workload should remain organized, traceable, and reproducible.

That is the broader vision of Caasi.
