# Fleet identity and remote display

Two questions that came up while shipping this migration: how caasi tells one robot from another
when they all run the same software, and how to see a robot's screen without a monitor or a fast
machine.

## 1. Machine identity: caasi already keys on the machine, not the name

An enrolled target records hardware observations with a confidence attached. Measured on this robot:

```
name:          swjtumover05
observations:  machine_id = 2c7c442a1da846c6b70f5a2d7712d7db   (source /etc/machine-id, strong)
               hostname   = swjtumover05                         (weak)
               cpu_model  = Intel(R) N150                        (classification)
ssh keys:      ecdsa-sha2-nistp256, ssh-rsa, ssh-ed25519 (+ SHA256 fingerprints)
endpoints:     10.212.19.94:22  verified
```

The same physical box has **two** records because it dual-boots, and they are told apart by
`machine_id`, not by name:

| target | OS | machine_id |
| --- | --- | --- |
| `swjtumover05` | Ubuntu 24.04 / Jazzy | `2c7c442a…` |
| `swjtumover05-ros1` | Ubuntu 20.04 / Noetic | `69ee0285…` |

Identity rules caasi already enforces (`caasi/core/identity.py`): a name identifies a target, an
address is only a current endpoint, acceptance requires a matching **enrolled host key**, and
`machine_id`/MACs are used to *explain* a mismatch — never to weaken verification.

### What to change, and what not to

* **Keep the robot family out of the target name.** Tags already carry it: these targets are tagged
  `robot` + `swjtumover` + (`ros1`|`jazzy`). Ten robots can all be the `swjtumover` family while each
  machine keeps its own target name for addressing.
* **Name targets by machine**, `swjtumover-05`, `swjtumover-10`, … — the number belongs to the PC, as
  you said. caasi resolves address → host key → `machine_id`, so a renamed or re-addressed robot is
  still the same robot, and a *different* robot at the same address is refused.
* **Do not encode the machine into the deployment path.** A target supports `deployment_root`, so
  every robot can deploy to the same place:

  ```yaml
  targets:
    swjtumover-05:
      host: 10.212.19.94
      user: swjtumover
      tags: [robot, swjtumover, jazzy]
      deployment_root: "~/caasi/robots/swjtumover"     # same on every robot
  ```

  The directory then says what the software is, not which machine it is on. `caasi deploy --dest`
  does the same thing per invocation.

## 2. Remote display without a fast machine

The robot's session is **GNOME on Wayland**. That matters: classic VNC servers such as `x11vnc`
cannot capture a Wayland desktop — they would only see Xwayland's windows.

What is already installed and is the light option:

```
gnome-remote-desktop            installed (Ubuntu's built-in Remote Desktop)
grdctl                          /usr/bin/grdctl
gnome-remote-desktop.service          (user service)
gnome-remote-desktop-headless.service (headless variant, for a machine with no logged-in session)
```

It speaks **RDP**, and unlike old VNC servers it does not poll and re-encode full frames: the
compositor reports damaged regions and only those are encoded. That is the "streaming like a video"
behaviour you remember, and it is what keeps a weak N150 usable.

Current state on this robot (nothing enabled yet):

```
RDP:  Status: disabled   Port: 3389   Username: (empty)   Password: (empty)
      RDP server certificate is invalid
```

### Enabling it

```bash
# on the robot, as the desktop user
grdctl rdp set-credentials <user> <password>   # caasi should generate and store this
grdctl rdp disable-view-only                   # optional: allow control, not just viewing
grdctl rdp enable                              # a valid TLS certificate is generated on enable
grdctl status
```

Client side, on whatever machine you are sitting at: **Remmina** or **FreeRDP**
(`xfreerdp /v:<host> /u:<user>`). Neither is installed on the development PC; `remmina` 1.4.43 is
available from apt.

### The part worth designing: no new open port

Rather than exposing 3389 on the lab network, forward it over the SSH trust caasi already manages:

```bash
ssh -N -L 3389:localhost:3389 swjtumover@<robot>
# then point the RDP client at localhost:3389
```

That keeps the security posture identical to today's: no inbound service exposed, host-key
verification unchanged, and the credential can live with the target record.

### Proposed caasi shape

```
caasi view desktop <target>          # ensure the RDP server is enabled, open the tunnel, hand the
                                     # client a localhost endpoint
caasi view desktop <target> --status # is it enabled, is a certificate valid, is a session free
```

`caasi view` already orchestrates viewers (`rviz`, `foxglove`, `open3d`, `attach`, `run`); a
`desktop` viewer fits that model, and the SSH tunnel reuses the transport caasi already owns. It is a
change to the caasi source, so it is written down here rather than implemented unasked.

### Rejected alternatives

| option | why not |
| --- | --- |
| `x11vnc` | Wayland session; it can only see Xwayland windows, not the desktop |
| `wayvnc` | requires a wlroots compositor; GNOME is not one |
| noVNC + websockify | browser convenience, but the encoding cost lands on the robot's CPU |
| TeamViewer / AnyDesk | exactly what you wanted to avoid: heavy clients on weak hardware |
