# Remote access and multiple robots

Two practical questions once more than one robot runs this software: how to tell them apart, and how
to see a robot's screen without sitting in front of it.

## Naming and identity

Give caasi a target per **machine**, and let the software name stay `swjtumover` on all of them:

```yaml
targets:
  swjtumover05:
    host: 10.212.19.94
    user: swjtumover
    tags: [robot, swjtumover, jazzy]
    deployment_root: "~/caasi/robots/swjtumover"
  swjtumover10:
    host: 10.212.19.105
    user: swjtumover
    tags: [robot, swjtumover, jazzy]
    deployment_root: "~/caasi/robots/swjtumover"
```

A machine that runs *simulation* rather than a robot is a target too — the same commands reach it:

```yaml
targets:
  gpu-01:
    host: 10.212.19.50
    user: dev
    tags: [gpu, workstation, isaac]
    # no deployment_root: a non-robot target uses ~/caasi/workspaces/gpu-01
```

```bash
caasi choose target gpu-01        # run the simulator there instead of on the robot
caasi node inspect gpu-01         # GPU model, VRAM, Isaac Sim / Isaac Lab availability
caasi choose target swjtumover05  # back to the hardware
```

Why this shape:

* **the tag says what it is** — `swjtumover` identifies the robot family, so every machine running
  this software is found with one query regardless of its number;
* **the target name says which machine** — used for addressing, nothing else;
* **`deployment_root` keeps the on-robot path constant** — every robot deploys to
  `~/caasi/robots/swjtumover`, so documentation, scripts and muscle memory are identical everywhere.

caasi does not rely on the name to recognise a machine. Enrolment records the machine itself:

```
machine_id = 2c7c442a1da846c6b70f5a2d7712d7db   (/etc/machine-id, strong)
cpu_model  = Intel(R) N150
ssh keys:  ecdsa / rsa / ed25519 with SHA256 fingerprints
endpoint:  10.212.19.94:22, verified
```

A renamed robot or a changed address is still the same robot, because acceptance requires a matching
enrolled host key. A different machine answering on a reused address is refused.

The same physical box can carry two targets when it dual-boots (one per operating system); they are
distinguished by machine id, which is exactly what that field is for.

### Working on one of several robots

Every command takes `-t <target>`. Fix the one you are working on and stop repeating it:

```bash
caasi choose target swjtumover05      # from now on, "the robot"
caasi choose target swjtumover10      # later, another one
caasi choose                          # which one is active, and where that came from
```

`caasi choose` prints the machine it is about to act on, so switching between robots is visible rather
than remembered. `eval "$(caasi choose --session target swjtumover10)"` switches for one terminal only —
handy when two robots are on the bench at once.

### Keeping two robots' topics apart

ROS 2 has no built-in isolation: two robots on one network, both on domain 0, see each other's topics.
Give each its own domain when you provision it:

```bash
caasi exec -t swjtumover05 -- \
  bash ~/caasi/robots/swjtumover/scripts/provision.sh --apply --domain 5
```

This writes `export ROS_DOMAIN_ID=5` into the robot's `~/.bashrc` with the same guards as the ROS 2
lines, so every terminal on that robot uses its own domain. It also lets `caasi rviz2` attach without
being told the domain explicitly: an unknown domain is refused rather than assumed, because an assumed
domain silently shows an empty graph.

## Seeing the robot's screen remotely

The robot runs GNOME on Wayland, so classic VNC servers do not apply — they can only capture X11
windows, not the desktop. GNOME's own remote desktop is already part of the system and streams only
the regions that change, which keeps it usable on modest hardware.

Enable it once, on the robot, as the desktop user:

```bash
grdctl rdp set-credentials <user> <password>
grdctl rdp disable-view-only      # omit to stay read-only
grdctl rdp enable
grdctl status                     # expect Status: enabled, Port: 3389
```

Then reach it without exposing a port on the network, by tunnelling over the SSH access caasi already
manages:

```bash
ssh -N -L 3389:localhost:3389 <user>@<robot>
```

and point a client at `localhost:3389`:

* Remmina — `remmina -c rdp://localhost:3389`
* FreeRDP — `xfreerdp /v:localhost:3389 /u:<user>`

Install one of them on the machine you sit at (`apt install remmina` or `freerdp3-x11`).

`grdctl status` is also the health check: if it reports a missing or invalid certificate, re-running
`grdctl rdp enable` regenerates one.

### rviz on your own machine instead

For data rather than a desktop, caasi can run rviz where you sit, against the robot's ROS 2 system:

```bash
caasi choose target swjtumover05
caasi rviz2
caasi rviz2 --domain 5      # when --domain was given at provisioning time
```

caasi resolves the target's distro, install path and domain, then runs the real `rviz2` locally — it
implements none of it. This depends on ROS 2 discovery reaching across the network between the two
machines, which it does on one LAN and does **not** across two LANs joined only by a VPN such as
Tailscale: there the graph appears empty even though the target was resolved correctly. That is a
network fact rather than something caasi can arrange, and the RDP route above is the answer
when you hit it.

## Notes

* The display is only needed for interactive work. Bringup, mapping, navigation and the mission all
  run headless, and that is the normal mode on a robot.
* Interactive extras need the desktop session's display. `scripts/run_teleop.sh` resolves it
  automatically (the X cookie on a Wayland session is a file whose name changes per session).
* If a viewer must run on a weak machine, prefer this RDP path over browser-based viewers: the
  encoding cost stays on the machine that owns the screen.
