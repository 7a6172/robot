"""DOB-lite: deploy-time velocity-loop disturbance observer (transfer-engine interface).

Paper-1 concept check for the NMTE "interface adapts, weights stay frozen" claim on the
degraded-dynamics axis (Target 2 / Target 3). The frozen source policy is deployed
UNCHANGED; this shim sits between the policy and the actuators and compensates the
multiplicative thrust loss that degraded dynamics introduce (lower wheel-speed cap +
low-friction wheel slip), both of which make the realized body speed fall below the
speed the policy's actions were tuned to produce.

Mechanism (scalar plant-gain disturbance observer on the wheel-speed loop):
  - The shim sends ``a / g`` to the env for raw policy action ``a`` and disturbance
    gain ``g``. It keeps the NOMINAL actuator gain ``W_nominal`` as reference.
  - Each step it identifies the plant gain ``P`` from realized wheel joint speed:
    ``w_real = P * prev_act / g``  =>  ``q := mean_wheels(w_real / prev_act) = P / g``
    and sets the EMA target to ``g * q / W_nominal = P / W_nominal``. The current g
    cancels, so the fixed point is unbiased by the shim's own correction:
    source (P = W_nominal) -> g* = 1 (no-op); degraded (P = W_degraded) -> g* < 1.
  - ``g`` is clamped to ``[g_min, 1]`` so the interface only compensates loss, never
    over-boosts. Wheel speed captures the degraded wheel-speed cap exactly and wheel
    slip partially (slip also needs the body to lag, which wheel speed alone misses).

Design history (all logged, kept as evidence):
  - v0 (body vx / nominal-intent-speed ratio, naive EMA): biased g DOWN even on
    nominal dynamics (measured g=0.58 on the source task) because acceleration
    transients make realized < intended; the shim degenerated into a speed booster
    (source blocked success 0.287 -> 0.423). See logs/p4_dob_*_v0biased.log.
  - v1 (quasi-steady-state mask on body vx): still biased (g=0.485 on source) —
    body inertia lag survives a 3-step hold at 20 Hz.
  - v2 (this version): moved the observable to wheel joint speed (tracks the
    actuator target with ~no inertia lag) and reformulated as a plant-gain
    identifier so the closed loop has the unbiased fixed point derived above.
  Sampling discipline kept from v1: update only when the command has been held
  ~constant for the last 3 control steps, and reset g to 1.0 on episode resets.

No policy weights change. No env cfg changes. The runner must disable the RL-wrapper
action clip (``clip_actions=None``) so the corrected command can exceed +/-1 to
restore the nominal commanded wheel speed.
"""

import torch


class DobLite:
    def __init__(self, wrapped, nominal_wheel_max: float,
                 alpha: float = 0.10, g_min: float = 0.15, g_max: float = 1.0,
                 settle_tol: float = 0.08):
        self.env = wrapped
        self.n = wrapped.num_envs
        self.device = wrapped.device
        self.R = wrapped.cfg.wheel_radius
        self.W_nom = float(nominal_wheel_max)
        self.alpha, self.g_min, self.g_max = alpha, g_min, g_max
        # raw-action deadband (actions are in [-1,1]); avoids dividing by ~0
        self.a_eps = 0.05
        self.settle_tol = settle_tol
        self.wheel_idx = wrapped._wheel_idx
        self.g = torch.ones(self.n, device=self.device)   # disturbance estimate
        self.prev_act = None                              # last 3 applied commands
        self.prev2_act = None
        self.prev3_act = None
        self._gain_sum, self._gain_cnt = 0.0, 0

    def reset(self, dones: torch.Tensor) -> None:
        """Call with the wrapper's ``dones`` after each env step."""
        if not dones.any():
            return
        self.g[dones] = 1.0
        if self.prev_act is not None:
            self.prev_act[dones] = 0.0
            self.prev2_act[dones] = 0.0
            self.prev3_act[dones] = 0.0

    def action(self, a: torch.Tensor) -> torch.Tensor:
        """Map the frozen policy's raw action ``a`` (N,2) to a compensated action."""
        with torch.inference_mode():
            if self.prev_act is not None and self.prev3_act is not None:
                # Plant-gain identification on the wheel-speed loop. The shim sent
                # ``prev_act / g`` to the env last step, so the realized wheel speed
                # is ``w_real = P * prev_act / g`` with P the true plant gain
                # (degraded cap + slip). Hence ``q := mean(w_real / prev_act) = P/g``
                # and the correction target ``g * q / W_nom = P / W_nom`` is
                # independent of the current g (no algebraic-loop bias):
                #   source   -> P = W_nom -> g* = 1 (no-op),
                #   degraded -> P = W_deg -> g* = W_deg/W_nom = 0.6.
                w_real = self.env._robot.data.joint_vel.torch[:, self.wheel_idx]  # (N,2)
                valid = (self.prev_act.abs() > self.a_eps) & (w_real * self.prev_act > 0.0)
                # quasi-steady-state mask: command held ~constant for 3 steps so the
                # actuator has settled; skip transients and post-reset samples
                held = torch.maximum(
                    (self.prev_act - self.prev2_act).abs().max(dim=1).values,
                    (self.prev2_act - self.prev3_act).abs().max(dim=1).values,
                ) < self.settle_tol                                               # (N,)
                q_wheel = torch.where(valid, w_real / self.prev_act,
                                      torch.zeros_like(w_real))                   # (N,2)
                q = q_wheel.sum(dim=1) / valid.float().sum(dim=1).clamp(min=1.0)
                mask = held & valid.any(dim=1)
                if mask.any():
                    target = (self.g[mask] * q[mask] / self.W_nom).clamp(
                        self.g_min, self.g_max)
                    self.g[mask] = (1.0 - self.alpha) * self.g[mask] + self.alpha * target
                    self.g.clamp_(self.g_min, self.g_max)
            self.prev3_act = self.prev2_act
            self.prev2_act = self.prev_act
            self.prev_act = a.detach().clone()
            self._gain_sum += float(self.g.mean())
            self._gain_cnt += 1
            return a / self.g.unsqueeze(1)

    def mean_gain(self) -> float:
        return self._gain_sum / max(self._gain_cnt, 1)
