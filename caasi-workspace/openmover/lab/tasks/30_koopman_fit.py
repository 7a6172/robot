"""Koopman fit v0 — offline EDMD-style lifted-linear fit (concept arm).

NO SIMULATOR: pure torch, runs on the transition files written by
29_koopman_collect.py. Concept check for the NMTE dynamics handle:

  1. fit a lifted-linear model  psi(s_{t+1}) ~= A psi(s_t) + B u_t  on
     SOURCE transitions (quadratic lift of [vx, wz, wl, wr]);
  2. evaluate one-step prediction on SOURCE (sanity) and on DEGRADED data
     with the FROZEN source fit -> the transfer gap the adaptation layer
     (DOB-lite in the paper, lifting adaptation in the draft) must close;
  3. fit on DEGRADED data alone -> the adapted upper bound;
  4. baselines: persistence (s_{t+1} = s_t) and unlifted affine fit, to show
     what the lift itself buys.

The numbers here are a pipeline proof-of-existence, not a controller.
Per the program caveat the component names are placeholders: what must hold
is the IDEA (freeze the learned structure, adapt a small interface).

Run:
    ~/isaaclab/isaaclab.sh -p \
        /home/zar/Documents/phd/robot/openmover_ws/isaac/lab/30_koopman_fit.py \
        --source .../logs/koopman_data/source.pt \
        --degraded .../logs/koopman_data/degraded.pt \
        --out_dir .../logs/koopman_data
"""

import argparse
import json
from pathlib import Path

import torch

STATE_NAMES = ["vx", "wz", "wl", "wr"]


def lift(s: torch.Tensor) -> torch.Tensor:
    """Quadratic EDMD lift of s=(vx,wz,wl,wr): 12 observables."""
    vx, wz, wl, wr = s.unbind(-1)
    return torch.stack([
        torch.ones_like(vx), vx, wz, wl, wr,
        vx * vx, wz * wz, wl * wl, wr * wr,
        vx * wz, vx * wl, wz * wr,
    ], dim=1)


def fit_theta(z: torch.Tensor, u: torch.Tensor, zn: torch.Tensor,
              lam: float = 1e-3):
    """Least-squares solve on standardized INPUT features: zn ~= aug_n @ Theta^T.

    The raw quadratic lift is badly conditioned here (features span ~1e0..1e3
    and the first un-standardized fit blew up to R^2 ~ -1e6 on vx), so the
    inputs aug = [z, u] are centered/scaled by their TRAIN statistics. The
    target zn stays in natural lift units so predictions need no
    de-standardization. Returns (Theta, mu, sigma)."""
    aug = torch.cat([z, u], dim=1)              # (T, L+2)
    mu = aug.mean(dim=0)
    sigma = aug.std(dim=0).clamp(min=1e-6)
    aug_n = (aug - mu) / sigma
    A = aug_n.T @ aug_n + lam * torch.eye(aug_n.shape[1], dtype=aug_n.dtype)
    B = aug_n.T @ zn                            # (L+2, L)
    theta = torch.linalg.solve(A, B).T          # (L, L+2)
    return theta, mu, sigma


def predict_s_next(theta, mu, sigma, s: torch.Tensor,
                   u: torch.Tensor) -> torch.Tensor:
    """One-step prediction of the STATE part (first 4 lift components)."""
    aug = torch.cat([lift(s), u], dim=1)
    aug_n = (aug - mu) / sigma
    zn = aug_n @ theta.T                        # natural lift units
    return zn[:, 1:5]  # psi components [1, vx, wz, wl, wr, ...]


def metrics(pred: torch.Tensor, truth: torch.Tensor) -> dict:
    err = pred - truth
    rmse = err.pow(2).mean(dim=0).sqrt()
    ss_res = err.pow(2).sum(dim=0)
    ss_tot = (truth - truth.mean(dim=0)).pow(2).sum(dim=0).clamp(min=1e-12)
    return {"rmse": rmse.tolist(), "r2": (1.0 - ss_res / ss_tot).tolist()}


def main():
    ap = argparse.ArgumentParser()
    base = Path(__file__).resolve().parent / "logs" / "koopman_data"
    ap.add_argument("--source", type=str, default=str(base / "source.pt"))
    ap.add_argument("--degraded", type=str, default=str(base / "degraded.pt"))
    ap.add_argument("--out_dir", type=str, default=str(base))
    ap.add_argument("--val_frac", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    src = torch.load(args.source, weights_only=True)
    deg = torch.load(args.degraded, weights_only=True)
    print(f"[fit] source:   {args.source}\n      task={src['task']} "
          f"N={src['s'].shape[0]} dt={src['dt']} wheel_max={src['wheel_max_speed']}")
    print(f"[fit] degraded: {args.degraded}\n      task={deg['task']} "
          f"N={deg['s'].shape[0]} dt={deg['dt']} wheel_max={deg['wheel_max_speed']}")

    g = torch.Generator().manual_seed(args.seed)

    def split(d):
        n = d["s"].shape[0]
        perm = torch.randperm(n, generator=g)
        k = int(n * args.val_frac)
        tr, va = perm[k:], perm[:k]
        return {x: d[x] for x in ("s", "u", "s_next")}, tr, va

    sd, str_, sva = split(src)
    dd, dtr, dva = split(deg)

    results = {"meta": {
        "source_task": src["task"], "degraded_task": deg["task"],
        "n_source": src["s"].shape[0], "n_degraded": deg["s"].shape[0],
        "wheel_max_source": src["wheel_max_speed"],
        "wheel_max_degraded": deg["wheel_max_speed"],
        "state_fields": STATE_NAMES,
    }}

    # --- fits -----------------------------------------------------------
    theta_src, mu_src, sig_src = fit_theta(lift(sd["s"][str_]), sd["u"][str_],
                                           lift(sd["s_next"][str_]))
    theta_deg, mu_deg, sig_deg = fit_theta(lift(dd["s"][dtr]), dd["u"][dtr],
                                           lift(dd["s_next"][dtr]))
    # unlifted affine baseline (state + action -> next state)
    def fit_affine(s, u, sn):
        aug = torch.cat([s, u, torch.ones(s.shape[0], 1)], dim=1)
        A = aug.T @ aug + 1e-4 * torch.eye(aug.shape[1])
        return torch.linalg.solve(A, aug.T @ sn).T
    aff_src = fit_affine(sd["s"][str_], sd["u"][str_], sd["s_next"][str_])

    def eval_model(name, predict):
        rows = {}
        for tag, d, idx in (("source_val", sd, sva), ("degraded_val", dd, dva)):
            pred = predict(d["s"][idx], d["u"][idx])
            rows[tag] = metrics(pred, d["s_next"][idx])
        results[name] = rows
        print(f"\n[fit] {name}")
        for tag, rows_ in rows.items():
            rm = ", ".join(f"{n_}={r:.4f}" for n_, r in
                           zip(STATE_NAMES, rows_["rmse"]))
            r2 = ", ".join(f"{n_}={r:.3f}" for n_, r in
                           zip(STATE_NAMES, rows_["r2"]))
            print(f"      {tag:13s} RMSE[{rm}]")
            print(f"      {'':13s} R^2  [{r2}]")

    eval_model("lifted_fit_source",
               lambda s, u: predict_s_next(theta_src, mu_src, sig_src, s, u))
    eval_model("lifted_fit_degraded",
               lambda s, u: predict_s_next(theta_deg, mu_deg, sig_deg, s, u))
    eval_model("affine_nolift_source",
               lambda s, u: torch.cat([s, u, torch.ones(s.shape[0], 1)],
                                      dim=1) @ aff_src.T)
    eval_model("persistence", lambda s, u: s)

    # frozen source fit on degraded data = THE transfer-gap number
    gap_src = results["lifted_fit_source"]["degraded_val"]["r2"]
    gap_deg = results["lifted_fit_degraded"]["degraded_val"]["r2"]
    print("\n[fit] TRANSFER GAP (one-step prediction on degraded data):")
    print(f"      frozen source lift  R^2 = {gap_src}")
    print(f"      adapted (refit)     R^2 = {gap_deg}")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    torch.save({"theta": theta_src, "mu": mu_src, "sigma": sig_src,
                "lift": "quadratic_12",
                "state_fields": STATE_NAMES}, out_dir / "K_source.pt")
    torch.save({"theta": theta_deg, "mu": mu_deg, "sigma": sig_deg,
                "lift": "quadratic_12",
                "state_fields": STATE_NAMES}, out_dir / "K_degraded.pt")
    with open(out_dir / "fit_summary.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n[fit] saved K_source.pt, K_degraded.pt, fit_summary.json -> {out_dir}")


if __name__ == "__main__":
    main()
