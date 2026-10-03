"""CBF-lite: deploy-time safety filter (transfer-engine interface, safety side).

Paper-1 concept check for the NMTE "filter keeps the frozen policy safe" claim. The
frozen source policy is deployed UNCHANGED; this shim sits between the policy and the
actuators (after DOB-lite if both are enabled — the filter gets final authority) and
projects the commanded velocity onto the admissible set of a minimal control barrier:

    h(d, v) = (d - d_margin) - v^2 / (2 a_dec) >= 0

with d the LiDAR clearance in the direction of travel, v the intended body speed. The
projection keeps the spin component of the per-wheel command untouched and only clamps
the forward component to |v| <= v_safe(d) = sqrt(2 a_dec max(d - d_margin, 0)), so the
policy can always turn in place to find a clearer heading; it just cannot drive into a
wall faster than it can stop.

Design notes (kept deliberately minimal; "concepts, not the final word"):
  - Clearances come straight from the raw raycaster hits (same semantics as env._scan:
    misses = inf -> max range), measured from the LiDAR origin. The front scan serves
    forward commands, the rear scan reverse commands.
  - v0 (min over the whole +-90 deg hemisphere) NEVER triggered on the ring map
    (0/9620 steps): the hemisphere minimum is dominated by the corridor SIDE walls
    (~0.4 m grazing hits), so the bound was always dominated by walls the robot was
    driving PAST, not the wall it was driving AT. v1 measures clearance only in a
    cone around the actual travel direction (world-frame ray angle vs. body yaw),
    which ignores grazing side-wall hits and clamps only when the commanded motion
    points at an obstacle.
  - d_margin is expressed at the LiDAR origin (front LiDAR sits 0.22 m ahead of the
    base center; hull half-diagonal is 0.327 m), so 0.30 m at the sensor covers the
    hull at any yaw plus a few cm of physical margin.
  - Speed scale uses the NOMINAL actuator gain (wheel_radius * W_nominal); with
    DOB-lite active the realized speed tracks nominal, so the same bound applies.
  - Output stays within [-1, 1] per wheel whenever the input was (|v_c| <= |v| and
    |v| + |w| = max(|a_L|, |a_R|)), so no clip changes are needed for CBF alone.
  - When the clamp never fires the shim returns the input tensor untouched, so the
    frozen baseline is reproduced bit-for-bit (verified on the ring map).
"""

import math

import torch


class CbfLite:
    def __init__(self, wrapped, v_full: float,
                 d_margin: float = 0.30, a_dec: float = 1.0,
                 cone_half_deg: float = 45.0, max_range: float = 10.0):
        self.env = wrapped
        self.n = wrapped.num_envs
        self.device = wrapped.device
        self.v_full = float(v_full)
        self.d_margin, self.a_dec, self.max_range = d_margin, a_dec, max_range
        self.cone_half = math.radians(cone_half_deg)
        self._intv, self._steps = 0, 0

    def _clearance(self, lidar, travel_dir: torch.Tensor) -> torch.Tensor:
        """Min ray distance per env inside a cone around the travel direction.

        Rays outside the cone (and misses, inf -> max_range) are set to max_range
        before the min, so an empty cone degrades to "no bound" rather than
        falsely clamping.
        """
        hits = lidar.data.ray_hits_w.torch                    # (N, R, 3), inf on miss
        origin = lidar.data.pos_w.torch.unsqueeze(1)          # (N, 1, 3)
        rel = hits - origin
        dist = torch.norm(rel, dim=-1)                        # (N, R)
        dist = torch.clamp(torch.nan_to_num(dist, posinf=self.max_range),
                           max=self.max_range)
        ray_ang = torch.atan2(rel[..., 1], rel[..., 0])       # (N, R) world frame
        d_ang = ray_ang - travel_dir.unsqueeze(1)
        in_cone = torch.atan2(torch.sin(d_ang), torch.cos(d_ang)).abs() <= self.cone_half
        dist = torch.where(in_cone, dist, torch.full_like(dist, self.max_range))
        return dist.min(dim=-1).values                        # (N,)

    def action(self, a: torch.Tensor) -> torch.Tensor:
        """Project per-wheel actions (N,2) onto the stoppable-velocity set."""
        with torch.inference_mode():
            v = 0.5 * (a[:, 0] + a[:, 1])          # forward component (action units)
            w = 0.5 * (a[:, 1] - a[:, 0])          # spin component, kept untouched
            fwd = v >= 0.0
            # body yaw from root quat (xyzw), same formula as the env
            q = self.env._robot.data.root_quat_w.torch
            yaw = torch.atan2(2.0 * (q[:, 2] * q[:, 3] + q[:, 0] * q[:, 1]),
                              1.0 - 2.0 * (q[:, 1] ** 2 + q[:, 2] ** 2))
            travel = torch.where(fwd, yaw, yaw + math.pi)
            d = torch.where(fwd,
                            self._clearance(self.env._lidar_front, travel),
                            self._clearance(self.env._lidar_rear, travel))  # (N,)
            v_phys = v * self.v_full                                        # m/s
            v_safe = torch.sqrt(2.0 * self.a_dec *
                                torch.clamp(d - self.d_margin, min=0.0))    # m/s
            v_phys_c = torch.clamp(v_phys, -v_safe, v_safe)
            changed = (v_phys_c - v_phys).abs() > 1e-6
            self._intv += int(changed.sum().item())
            self._steps += self.n
            if not changed.any():
                return a  # exact no-op: keep the frozen command bit-for-bit
            v_c = torch.where(changed, v_phys_c / self.v_full, v)
            return torch.stack([v_c - w, v_c + w], dim=1)

    def intervention_rate(self) -> float:
        return self._intv / max(self._steps, 1)

    def stats(self) -> tuple[int, int]:
        return self._intv, self._steps
