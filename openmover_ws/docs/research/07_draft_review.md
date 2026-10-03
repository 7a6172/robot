# 07 — Review of the Existing Draft & Deck

Files reviewed: `/home/zar/Documents/phd/robot/draft/draft.pdf` (paper skeleton) and
`/home/zar/Documents/phd/robot/draft/presentation.pdf` (progress-report deck).
A plain-text extraction of the draft exists at `/home/zar/Documents/phd/robot/draft/draft_text.txt`.

## What the draft contains

- Title direction: *Neuro-Mathematical Transfer Engine (NMTE): A Mathematical Framework for
  Cross-Embodiment Sim-to-Real Adaptation in Industrial Robotics*.
- Five gaps from 2023–2026 literature (see `02_nmte_framework.md` for the table).
- Four pillars: Koopman lifting (III-A), Gromov-Wasserstein OT (III-B), DOB-CBF safety (III-C),
  energy-aware edge execution (III-D).
- Roadmap phases A–D corresponding to the pillars.
- Deck: June 2026 progress report (author name / student ID / advisor present in deck),
  presents the 5-gap motivation and the engine architecture as "the whole research".

Assessment: the draft reads as ~70% done — a framework/position paper skeleton with **no
implementation and no experiments**. That is exactly what the first conference paper is for.

## Fix list (cheap, do before any submission)

| # | Issue | Fix |
|---|---|---|
| 1 | **Citation mismatch**: text says "He et al. [1] … iCEM+TL" but reference [1] is Abe et al., *Cross-Embodiment Offline RL* | Correct the text or the reference list; one bad citation makes reviewers check all of them |
| 2 | Several arXiv IDs look like placeholders/unverified | Verify every reference exists and matches its in-text claim |
| 3 | **"100% mathematically certifiable safety"** (deck p.9) | Replace with "forward invariance under bounded disturbance"; CBF guarantees depend on correct `h(x)` and the bounded-disturbance assumption |
| 4 | ">500 Hz control loop" claim borrowed from a hydraulic-quadruped citation while our loop runs ~20 Hz | Reframe: "QP solves in µs at any required rate"; state actual loop rates |
| 5 | Placeholder authors, empty conclusion/acknowledgment | Complete before submission |
| 6 | Abstract promises arms and quadrupeds as validation platforms, but available hardware is neither | Re-scope validation to "ground mobile robot + simulated generality", state arm/quadruped as future work |

## How paper one fills the draft's empty sections

- Paper 1's experiments become the draft's missing experiments section — but scoped to one
  platform and simulation-first, per `03_paper_one_scope.md`.
- The five-gap framework survives intact as the roadmap figure: gaps 1&2&4&5 get mechanism-level
  evidence on the AMR (dynamics + safety + edge); gap 3 (GW) stays honestly future.
- The "industrial robotics / warehouse" setting in the draft's title aligns naturally: the robot
  IS a warehouse-class AMR, and the yard scenario keeps the railway-industry thread.

## What must NOT change in the draft

- The freeze/adapt rule and the four-pillar structure — paper 1 is an instantiation of them.
- The gap numbering — the roadmap figure references it, and future papers map onto the same gaps.
