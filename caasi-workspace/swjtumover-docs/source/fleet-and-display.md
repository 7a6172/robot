# Remote access and multiple robots

Two practical questions once more than one robot runs this software: how to tell them apart, and how
to see a robot's screen without sitting in front of it.

## Naming and identity

Give caasi a target per **machine**, and let the software name stay `swjtumover` on all of them:

```yaml
targets:
  swjtumover-05:
    host: 10.212.19.94
    user: swjtumover
    tags: [robot, swjtumover, jazzy]
    deployment_root: "~/caasi/robots/swjtumover"
  swjtumover-10:
    host: 10.212.19.104
    user: swjtumover
    tags: [robot, swjtumover, jazzy]
    deployment_root: "~/caasi/robots/swjtumover"
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

## Notes

* The display is only needed for interactive work. Bringup, mapping, navigation and the mission all
  run headless, and that is the normal mode on a robot.
* Interactive extras need the desktop session's display. `scripts/run_teleop.sh` resolves it
  automatically (the X cookie on a Wayland session is a file whose name changes per session).
* If a viewer must run on a weak machine, prefer this RDP path over browser-based viewers: the
  encoding cost stays on the machine that owns the screen.
