"""Geodesic-chain expert controller for the openmover nav env (run13/run14).

Validated: 0.75 blocked-goal success on 12 seed-42 episodes (300-step budget),
0.636 over 683 episodes at 256-env scale; all successes collision-free.

Design:
  - geodesic descent chain walked downhill from the robot cell with an
    OCCUPANCY mask (the field leaks through walls via fill sweeps, so the
    chain must never enter an inflated wall cell) + dead-end detection;
  - chord-checked pure pursuit along the chain polyline: chase the farthest
    lookahead sample whose straight chord from the robot is occupancy-clear,
    so corners are never cut through walls;
  - close-and-clear goal homing; speed = cos(heading) x lidar-clearance x
    geodesic taper; PD heading control with low-pass smoothing;
  - back-up-on-contact unstuck state machine.

Stateful per env (w_prev / stuck / backup); call episode_reset(env_ids) when
episodes terminate so the state machine does not leak across resets.
"""

import math

import torch

# differential-drive kinematics (URDF: wheel_separation 0.324, radius 0.050353)
WHEEL_RADIUS = 0.050353
WHEEL_BASE = 0.324
V_CRUISE = 0.50   # m/s
OMEGA_MAX = 2.2   # rad/s
KP = 2.0          # heading proportional gain
KD = 0.6          # heading derivative gain (yaw rate damping)
SMOOTH = 0.5      # low-pass alpha on omega command
CONTACT_F = 5.0   # N: net contact force considered "pressed against something"
STUCK_N = 3       # consecutive pressed steps before backing up
BACKUP_N = 12     # steps of reverse command
BACKUP_V = -0.35
BACKUP_W = 1.2
CHAIN_LEN = 1.5    # m: how far the descent chain is walked
LOOKAHEAD = 0.85   # m: pure-pursuit arc distance along the chain polyline
GOAL_DIRECT = 1.0  # m: below this goal distance, drive straight at the goal if clear
FWD_MARGIN = 0.20  # m: clearance below which speed collapses to creep
FWD_SCALE = 0.60   # m: clearance margin over which full cruise is restored


class GeodesicExpert:
    """Stateful geodesic-chain expert, vectorized over all envs."""

    def __init__(self, wrapped):
        self.w = wrapped
        dev = wrapped.device
        n = wrapped.num_envs
        self.dev = dev
        self.ar = torch.arange(n, device=dev)
        self.MV = torch.tensor([[-1, 0], [1, 0], [0, -1], [0, 1]], device=dev)
        self.res_g = wrapped.cfg.geo_res
        self.sx_g, self.sy_g = wrapped._geo_size
        self.MC = torch.full((4,), self.res_g, device=dev)
        self.FRACS = torch.linspace(0.1, 1.0, 10, device=dev)
        self.w_prev = torch.zeros(n, 1, device=dev)
        self.stuck = torch.zeros(n, device=dev)
        self.backup = torch.zeros(n, device=dev)

    def episode_reset(self, env_ids):
        self.w_prev[env_ids] = 0.0
        self.stuck[env_ids] = 0.0
        self.backup[env_ids] = 0.0

    def _chord_clear(self, p0, p1, origins, occ, env_idx, n_fr):
        """True where segment p0->p1 crosses no inflated-wall cell."""
        rel = (p1 - p0).unsqueeze(1)  # (N, 1, 2)
        pp = p0.unsqueeze(1) + self.FRACS.view(1, -1, 1) * rel  # (N, F, 2)
        ixt, iyt = self.w._cell_idx((pp - origins.unsqueeze(1)).reshape(-1, 2))
        ob = occ[env_idx.repeat_interleave(n_fr), iyt, ixt]
        return ~ob.reshape(p0.shape[0], n_fr).any(dim=1)

    def action(self):
        w = self.w
        dev = self.dev
        ar = self.ar
        n_env = w.num_envs
        tiles = w._env_tile                          # (N,) static per env
        origins = w._terrain.env_origins[:, :2]      # (N, 2) tile centers
        occ = w._geo_occ[tiles]                      # (N, gy, gx) occupancy
        pos = w._robot.data.root_pos_w.torch[:, :2]
        q = w._robot.data.root_quat_w.torch
        yaw = torch.atan2(2.0 * (q[:, 2] * q[:, 3] + q[:, 0] * q[:, 1]),
                          1.0 - 2.0 * (q[:, 1] ** 2 + q[:, 2] ** 2))
        d_geo = w._geo_lookup(ar, pos)
        gdist = w._goal_dist()
        # ---- geodesic descent chain from the robot cell (path-committed) ----
        res_g, sx_g, sy_g = self.res_g, self.sx_g, self.sy_g
        p_tile0 = pos - origins
        cix, ciy = w._cell_idx(p_tile0)
        MAXC = int(math.ceil(CHAIN_LEN / res_g)) + 4
        acc_c = torch.zeros(n_env, device=dev)
        done_c = w._geo_field[ar, ciy, cix] <= 1e-3
        nx_list, ny_list = [cix.clone()], [ciy.clone()]
        for _ in range(MAXC):
            nx = torch.clamp(cix.unsqueeze(1) + self.MV[:, 0], 0, w._geo_gx - 1)
            ny = torch.clamp(ciy.unsqueeze(1) + self.MV[:, 1], 0, w._geo_gy - 1)
            vals = w._geo_field[ar.unsqueeze(1), ny, nx]
            # occupancy mask: the field leaks through walls (fill sweeps),
            # so descent must never step into an inflated wall cell
            vals = vals.masked_fill(occ[ar.unsqueeze(1), ny, nx], float("inf"))
            done_c = done_c | torch.isinf(vals).all(dim=-1)  # dead end
            b = torch.argmin(vals, dim=-1)
            cix = torch.where(done_c, cix, nx[ar, b])
            ciy = torch.where(done_c, ciy, ny[ar, b])
            acc_c = acc_c + torch.where(done_c, torch.zeros_like(acc_c), self.MC[b])
            done_c = done_c | (acc_c >= CHAIN_LEN) | (vals[ar, b] <= 1e-3)
            nx_list.append(cix.clone())
            ny_list.append(ciy.clone())
            if bool(done_c.all()):
                break
        ndx = torch.stack(nx_list, dim=1).float() * res_g - 0.5 * sx_g + 0.5 * res_g
        ndy = torch.stack(ny_list, dim=1).float() * res_g - 0.5 * sy_g + 0.5 * res_g
        nodes = torch.stack([ndx, ndy], dim=-1) + origins.unsqueeze(1)  # (N, M, 2)
        # ---- chord-checked pure pursuit along the chain polyline ----
        M = nodes.shape[1]
        if M < 2:
            tgt = nodes[:, 0]
        else:
            seg_len = (nodes[:, 1:] - nodes[:, :-1]).norm(dim=-1)  # (N, M-1)
            cum = torch.cat([torch.zeros(n_env, 1, device=dev),
                             seg_len.cumsum(dim=1)], dim=1)  # (N, M)
            s_max = torch.minimum((nodes[:, 0] - pos).norm(dim=-1, keepdim=True)
                                  + LOOKAHEAD, cum[:, -1:])  # (N, 1)
            S = 24
            s_grid = torch.linspace(0.0, 1.0, S, device=dev).view(1, S) * s_max
            kk = torch.clamp((cum.unsqueeze(1) < s_grid.unsqueeze(2)).sum(dim=2) - 1,
                             0, M - 2)  # (N, S)
            s0 = cum.gather(1, kk)
            s1 = cum.gather(1, kk + 1)
            ff = torch.clamp((s_grid - s0) / torch.clamp(s1 - s0, min=1e-4), 0.0, 1.0)
            pk = nodes.gather(1, kk.unsqueeze(-1).expand(-1, -1, 2))  # (N, S, 2)
            pk1 = nodes.gather(1, (kk + 1).unsqueeze(-1).expand(-1, -1, 2))
            pts = pk + ff.unsqueeze(-1) * (pk1 - pk)  # (N, S, 2)
            rel_c = (pts - pos.unsqueeze(1)).unsqueeze(2)  # (N, S, 1, 2)
            pp = pos.view(n_env, 1, 1, 2) + self.FRACS.view(1, 1, -1, 1) * rel_c
            ixt, iyt = w._cell_idx((pp - origins.view(n_env, 1, 1, 2)).reshape(-1, 2))
            ob = occ[ar.repeat_interleave(S * self.FRACS.shape[0]), iyt, ixt]
            ok = ~ob.reshape(n_env, S, self.FRACS.shape[0]).any(dim=-1)  # (N, S)
            iS = torch.arange(S, device=dev).unsqueeze(0)
            sel = torch.where(ok, iS, torch.zeros_like(iS)).amax(dim=1)
            tgt = pts[ar, sel]
        # ---- goal homing: close + chord-clear -> drive straight at the goal ----
        gb = w._goal_in_robot_frame()
        a_goal = torch.atan2(gb[:, 1], gb[:, 0])
        direct = ((gdist < GOAL_DIRECT) & (a_goal.abs() < math.pi / 2) &
                  self._chord_clear(pos, w._goal_pos_w[:, :2], origins, occ,
                                    ar, self.FRACS.shape[0]))
        tgt = torch.where(direct.unsqueeze(1), w._goal_pos_w[:, :2], tgt)
        rel_t = tgt - pos
        a_best = torch.atan2(rel_t[:, 1], rel_t[:, 0]) - yaw
        a_best = torch.atan2(torch.sin(a_best), torch.cos(a_best))
        # ---- forward clearance from the front scan (body-axis window) ----
        rng = w._scan(w._lidar_front)  # (N, R) normalized [0,1], 1 = free
        d_r = rng * w.cfg.lidar_front.max_distance  # meters
        ctr = d_r.shape[1] // 2
        fwd = d_r[:, ctr - 20:ctr + 21].min(dim=-1).values
        # ---- speed: cos(heading) x clearance taper x goal taper ----
        cos_e = torch.clamp(torch.cos(a_best), 0.0, 1.0)
        v = V_CRUISE * cos_e
        v = v * torch.clamp((fwd - FWD_MARGIN) / FWD_SCALE, 0.08, 1.0)
        v = v * (0.25 + 0.75 * torch.clamp(d_geo / 0.5, 0.0, 1.0))
        # ---- omega: PD toward the chosen heading ----
        wz_now = w._robot.data.root_ang_vel_b.torch[:, 2:3]
        w_raw = torch.clamp(KP * a_best.unsqueeze(-1) - KD * wz_now, -OMEGA_MAX, OMEGA_MAX)
        wcmd = (SMOOTH * w_raw + (1.0 - SMOOTH) * self.w_prev).squeeze(-1)
        # back-up-on-contact unstuck state machine
        cf_all = w._contact_force()
        vx_b = w._robot.data.root_lin_vel_b.torch[:, 0]
        pressed = (cf_all > CONTACT_F) & (vx_b.abs() < 0.08)
        self.stuck = torch.where(pressed, self.stuck + 1.0, torch.zeros_like(self.stuck))
        self.backup = torch.where(self.stuck >= STUCK_N,
                                  torch.full_like(self.backup, float(BACKUP_N)), self.backup)
        active = self.backup > 0
        v = torch.where(active, torch.full_like(v, BACKUP_V), v)
        wcmd = torch.where(active, torch.where(a_goal >= 0,
                                               torch.full_like(wcmd, -BACKUP_W),
                                               torch.full_like(wcmd, BACKUP_W)), wcmd)
        self.backup = torch.clamp(self.backup - 1.0, min=0.0)
        self.w_prev = wcmd.clone().unsqueeze(-1)
        wl = (v - wcmd * 0.5 * WHEEL_BASE) / WHEEL_RADIUS
        wr = (v + wcmd * 0.5 * WHEEL_BASE) / WHEEL_RADIUS
        act = torch.clamp(torch.stack([wl, wr], dim=-1) / w.cfg.wheel_max_speed, -1, 1)
        return act
