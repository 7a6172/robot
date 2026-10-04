# Stage D Gap: `deploy --status` cannot find a deployment it just created

**Status:** Identified during Phase 7 Stage D (real remote target validation)
**Severity:** `deploy --status` mis-reports "no deployment" for a live, verified deployment
**Scope:** `caasi.core.deploy.get_deployment_status` / `caasi.cli.deploy_cmd`
**Related:** `stage-d-gap-ssh-timeout.md`, `stage-d-gap-run-timeouts.md` (same Stage D session)

---

## 1. What Stage D exposed

Immediately after a **verified** deployment to the real target, `--status`
reported that no deployment existed:

```console
$ caasi deploy u24-307 --status
No active caasi deployment found on target 'u24-307'.
```

while the target plainly had one:

```console
$ ssh u24-307 ls -la /home/zar/caasi-deployments/openmover/.caasi-deployment.json
-rw-rw-r-- 1 zar zar 8406 ... .caasi-deployment.json
# status field inside: "verified"
```

and a run had just been launched, built and stopped through that very
deployment — so the deployment was not merely present but in active use.

## 2. Root cause

Two functions compute the remote destination differently.

`resolve_deployment_destination` — used when *writing* the deployment — appends
the project name:

```python
    root = target.deployment_root or f"~/deployments/{project_name}"
    if not root.endswith(project_name):
        return f"{root.rstrip('/')}/{project_name}"     # -> .../caasi-deployments/openmover
    return root
```

`get_deployment_status` — used by `--status` to *read* it — does not:

```python
    dest = destination_path or (target.deployment_root or "~")
    ...
    cmd = ssh_prefix + [f"cat '{dest.rstrip('/')}/.caasi-deployment.json' 2>/dev/null"]
```

With no explicit `--dest`, `dest` becomes `/home/zar/caasi-deployments`, so it
looks for `/home/zar/caasi-deployments/.caasi-deployment.json`, which does not
exist. The real file is one level deeper, under the project name.

## 3. Empirical confirmation

Passing the destination explicitly finds it at once:

```console
$ caasi deploy u24-307 --status --dest /home/zar/caasi-deployments/openmover
Active Deployment on u24-307:
  Deployment ID:  deploy-openmover-20261004-100729-8c304a34
  Status:         VERIFIED
  Files Count:    835 (40.4 MiB)
```

This isolates the defect to default path resolution, not to transfer, metadata
format, or connectivity.

## 4. Why this is a genuine general gap

- It affects **every** project whose destination is
  `<deployment_root>/<project_name>` — i.e. the documented default layout. It is
  not specific to `u24-307`, SSH, or latency.
- Stage A/B/C2 did not surface it because those stages exercised `deploy` and
  `deploy --dry-run` (which compute the destination correctly) and verified the
  deployed tree directly on the target, rather than asking `--status` to resolve
  the same path independently.
- The failure is **silently wrong in a dangerous direction**: it reports absence
  for something that is present and in use. An operator could conclude the
  project was never deployed and re-deploy unnecessarily, or distrust a
  perfectly good deployment.
- It is a divergence between two path computations that should agree — the
  classic single-source-of-truth defect.

## 5. Smallest general solution proposed

Make the read path use the same resolver as the write path. No new concept:

1. `get_deployment_status(target, destination_path, config)` — when
   `destination_path` is not supplied, derive it with
   `resolve_deployment_destination(target, project_name)` instead of falling
   back to the bare `deployment_root`. The project name is available from the
   project manifest via the existing project discovery used by the CLI.

2. Where the project name cannot be determined, keep the current
   `deployment_root` fallback so behaviour degrades rather than crashes.

3. Leave the explicit `--dest` override working exactly as it does today (it is
   already correct and is how the diagnosis was confirmed).

**Deliberately out of scope:** changing the destination layout, adding a
deployment registry/lookup service, or any host-side caching. Those are larger
design questions and must not be pulled in by this fix.

## 6. Decision

Implement (1) and (2) as the smallest general fix, with a regression test, then
re-run `caasi deploy u24-307 --status` (with no `--dest`) on the real machine to
confirm it reports the verified deployment.
