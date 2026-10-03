# Research Documentation — Start Here

This folder is the **working knowledge base of the research program**: everything discussed,
decided, scoped, and planned about the PhD direction, the first conference paper, and the
simulation strategy. It is written for **both humans and AI agents** — agents should read these
files before being asked to implement or plan anything research-related, so they inherit the full
context without re-deriving it.

## Reading order

| # | File | What it contains |
|---|---|---|
| 1 | [01_research_program.md](01_research_program.md) | The big picture: vision, assets, paper arc, context |
| 2 | [02_nmte_framework.md](02_nmte_framework.md) | The NMTE framework (the draft's four pillars, five gaps, roadmap) |
| 3 | [03_paper_one_scope.md](03_paper_one_scope.md) | **The key document**: first conference paper — claim, scope, experiments, venues |
| 4 | [04_isaac_sim_strategy.md](04_isaac_sim_strategy.md) | Isaac Sim/Lab facts, hardware reality, integration phases |
| 5 | [05_transfer_learning_notes.md](05_transfer_learning_notes.md) | Sim-to-real & transfer learning background + parent/tethered architecture |
| 6 | [06_validation_plan.md](06_validation_plan.md) | What must be verified before any learning: robot characterization, sim twin, fidelity |
| 7 | [07_draft_review.md](07_draft_review.md) | Analysis of the existing draft paper & progress-report deck, with fix list |
| 8 | [08_decisions_log.md](08_decisions_log.md) | Every decision made, with rationale — the memory of the discussion |

## The program in one paragraph

The PhD program builds a **transfer engine**: a framework in which robot skills learned in
simulation transfer across **environments** (unseen worlds), **dynamics regimes** (degraded
friction, latency, payloads), **compute placements** (from a GPU workstation down to a laptop-class
robot PC), and eventually **embodiments** (other robot types). The thesis framework is specified in
the NMTE draft (`/home/zar/Documents/phd/robot/draft/`); the first conference paper demonstrates the
engine's core mechanism — *freeze the structure, adapt the interface* — on the one robot currently
available (a small differential-drive, 2D-LiDAR, warehouse-class robot), with simulation-first
results: train in randomized environments, then drop the frozen artifacts into unseen factorized
target domains (including a railway-maintenance yard scenario) and measure what transfers with how
little adaptation. Everything built for that paper (data factory, training pipeline, deployment
nodes, evaluation harness) is deliberately reusable for the whole future program.

## One-sentence core claim (agreed wording)

> **Learning transfers; hardware is just the interface.** The same learned knowledge can drive one
> robot or many — eventually robots of different kinds — because the transfer engine separates what
> must be learned (dynamics structure, safety) from what must be adapted (the embodiment interface).

## Status snapshot

- Framework: **specified on paper** (NMTE draft + deck), no implementation yet.
- Robot stack: **ROS 2 Jazzy port complete** (this workspace), simulation pipeline working in Gazebo.
- Isaac Sim: **not installed** — strategy decided, phased integration planned.
- First paper: **scoped** (see `03_paper_one_scope.md`), simulation-first, mid-tier venue target.
- Real robot: available, **untested** on the research tasks; characterization protocol written.

## Relationship to other documentation

- `docs/knowledge/` — system knowledge base (how the robot stack works). Read `09_research_directions.md`
  there for the short version; these files are the long version.
- `docs/*.html` — stable, human-facing project documentation (build, usage, audit, changelog).
- `/home/zar/Documents/phd/robot/draft/` — the NMTE draft paper and progress-report deck (source material).
