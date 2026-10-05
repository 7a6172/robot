# Phase 7: 0.4.0 Documentation Checkpoint — Plan for Review

**Status:** Plan. **Nothing modified yet.** Awaiting approval.
**Principle:** `existing HTML docs → audit → update → expand → 0.4.0 docs`.
**Not:** replacing the site with a new documentation system.

---

## 1. The existing site — inspected, not assumed

| Property | Finding |
| :--- | :--- |
| Form | **static HTML, no build step** — `docs/*.html` sit directly in the repo |
| Pages | **16**: `index`, `environment`, `configuration`, `runs`, `observability`, `projects`, `simulation`, `training`, `data`, `review`, `synthetic`, `ros`, `platform`, `accelerated`, `native`, `remote` |
| Total size | **7,346 lines** |
| Shared assets | `assets/{style.css, sidebar.js, theme.js, copy.js}` — no framework |
| Navigation | `sidebar.js` holds the whole tree as data (11 groups), rendered client-side |
| Page anatomy | topbar (brand + **version badge** + tagline) → `main` → `page-nav` (prev/next) → `doc-footer` |
| Rich components | `.callout note/tip/warn`, `.cards`/`.card`, `.pill`, `pre.term`/`pre.syn`, `.copy-cmd` |
| Publishing | GitLab Pages serves `docs/` directly (`.gitlab-ci.yml`) — **no build to maintain** |

**Conclusion: the architecture is sound and appropriate.** It needs content, not
replacement. A framework would be a regression for a static, dependency-free site.

---

## 2. Audit findings — what is actually wrong

### 2.1 Every page is versioned 0.3.0

**All 16 pages** carry `<span class="badge">v0.3.0</span>`, and the footer reads
*"Caasi CLI 0.3.0"*. Three pages (`data`, `observability`, `remote`) mention `v0.4.0`
in their **body text** — a partially-started update.

### 2.2 The 0.4.0 control-plane surface is entirely undocumented

Measured against the live CLI (57 root commands / 253 paths):

| Command | Pages documenting it |
| :--- | ---: |
| `caasi target` (incl. `select`, `occupancy`, `runtime`) | **0** |
| `caasi workload` | **0** |
| `caasi runtime` (the lifecycle) | **0** |
| `caasi tools` (target-aware invocation, F3) | **0** — the 10 `tools` hits on `index.html` are the *config tool registry*, unrelated |
| `caasi deploy` | **0** |
| `caasi build` | **1 incidental mention** |

The `index.html` **command map** lists `doctor check info version init setup start
logs audit --fix run inspect train sensor vision replay ros2 nav moveit control
perception slam mapping motion nitros pipeline synth dataset generate sdg shell` —
**no target, workload, runtime, deploy, occupancy, or tools**.

### 2.3 The examples catalog is not integrated

`examples/` (7 projects + cookbook, `README.md` index, `COVERAGE.md` matrix) exists
and is validated, but **no page links to it**. The sidebar has no Examples section.

### 2.4 No limitations / deferred-capabilities page

The site documents neither the **known limitations** (DDS-over-Tailscale, the idle
race, `remotes:` deprecation) nor the **deliberately deferred** capabilities
(queues, scheduling, reservations). A reader cannot tell what caasi does *not* do or
*why*.

### 2.5 `platform.html` is mis-titled for its content

It is named like a platform overview but contains only `physics`, `warp`, `groot`,
`cosmos`, `scene reconstruct` — foundation-model content, not the target/control
plane a reader would expect under that name.

### 2.6 `remote.html` predates targets

It covers the **legacy `caasi remote`** shim but **not** `caasi target`, which is now
the canonical model — so the site's remote story is both outdated and inconsistent
with the deprecation recorded in the code.

---

## 3. Proposed new pages (within the existing structure)

Five new pages, each matching the current page anatomy (topbar + badge + sidebar +
`.callout`s + `page-nav`).

| New page | Content | Closes |
| :--- | :--- | :--- |
| **`targets.html`** | `target list/inspect/check/select/occupancy/runtime`; the three verdict states; `--where any\|idle\|prefer:<tag>`; selection vs scheduling; the idle-race limitation | §2.2 |
| **`workloads.html`** | workload model; the closed `steps` vocabulary; the composed chain; **the deployment requirement for `run`** as a documented prerequisite; `--target`/`--where` exclusivity | §2.2 |
| **`lifecycle.html`** | `deploy` → target-native `build` → `runtime` install/enable/start/status/verify/update/rollback; revision identity; honest rollback | §2.2 |
| **`examples.html`** | the catalog as a user-facing section; the seven examples + cookbook; prerequisites; **CI / opt-in / manual** tiers; links into `examples/` and `COVERAGE.md` | §2.3 |
| **`limitations.html`** | what caasi does **not** do; the deferred capabilities and *why*; the environmental limitations; the `remotes:` deprecation; caasi vs ecosystem vs delegated | §2.4 |

### 3.1 Existing pages to update (not replace)

| Page | Change |
| :--- | :--- |
| **all 16** | version badge + footer → `0.4.0` |
| `index.html` | quickstart extended through the 0.4.0 chain; **command map completed**; the five verbs kept |
| `remote.html` | lead with `caasi target` as canonical; mark `caasi remote` **deprecated** |
| `runs.html` | add the deployment prerequisite for target-aware runs; composed-run provenance |
| `ros.html` | add `--target`/`--domain` for remote observation and the tool-invocation pattern |
| `platform.html` | retitle/reframe so it no longer implies it covers the platform; point at `targets.html` |
| `observability.html` | link the occupancy query; note `target runtime` |
| `projects.html` | note `workload`/`examples` alongside experiments |
| `configuration.html` | document `tools:` for **target-aware invocation** (distinct from the tool registry) |

### 3.2 Navigation (in `sidebar.js`)

Add two groups, keeping the existing 11 groups and their order:

```js
{ title: "Control plane", items: [
    { href: "targets.html",     label: "Targets & selection" },
    { href: "workloads.html",   label: "Workloads & execution" },
    { href: "lifecycle.html",   label: "Deploy & runtime lifecycle" },
]},
{ title: "Examples & reference", items: [
    { href: "examples.html",    label: "Examples & command index" },
    { href: "limitations.html", label: "Limitations & what's deferred" },
]},
```

**Placement rationale:** "Control plane" sits after **Projects** (a project is what
you have; a target is where it runs) and before **Simulation & Training**.
"Examples & reference" sits near the end, before **Advanced**.

### 3.3 Explicit boundary documentation

Every relevant page gets a short, consistent statement of the four categories the
checkpoint asks for:

| Category | Example wording |
| :--- | :--- |
| **caasi manages** | project identity, target selection, lifecycle intent, verification, provenance |
| **ecosystem owns** | ROS 2/DDS, colcon, Docker, systemd, Isaac, `nvidia-smi`, RViz |
| **caasi delegates** | `ros2` CLI, `systemctl`, `docker`, `nvidia-smi`, upstream launch entry points |
| **supported / opt-in / deferred** | stated per feature, with the reason for deferral |

---

## 4. What will NOT change

- **The site is not replaced** and no framework is introduced.
- **The visual design language stays** (`style.css` untouched unless a concrete
  defect appears).
- **The `sidebar.js` data-driven nav stays** — extended, not rewritten.
- **The static, no-build-step property stays** (GitLab Pages publishing unaffected).
- **No capability is added** to make documentation easier. Prerequisites are
  documented as they are — including the **deployment requirement for `run`**, which
  will be stated plainly rather than hidden.

---

## 5. Verification after the docs pass

1. every page renders (open the HTML / check links resolve);
2. **no stale `v0.3.0` references remain**;
3. the command map covers the live CLI — cross-checked against `examples/COVERAGE.md`;
4. examples are linked from the docs and the links resolve;
5. full test suite;
6. fresh-install and upgrade checks;
7. changelog + 0.4.0 release report;
8. confirm the known test failure is still pre-existing and unrelated.

---

## 6. Proposed order

1. `targets.html`, `workloads.html`, `lifecycle.html` (the missing control plane).
2. `examples.html` + `limitations.html`.
3. Sidebar + version badges + command map (the cross-cutting edits).
4. Updates to the eight existing pages in §3.1.
5. Release-hardening verification (§5) — separately reported.

**Awaiting approval before any file is modified.**
