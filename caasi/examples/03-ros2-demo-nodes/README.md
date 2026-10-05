# 03 — Observing a real ROS 2 system

**Prerequisites:** a ROS 2 installation (`/opt/ros/<distro>`), no GPU, **no
display** (these nodes are headless).

**ROS 2 provides the example; caasi provides the observation around it.** The nodes
below are `demo_nodes_py` — the canonical ROS 2 tutorial package, shipped with every
ROS 2 install. caasi does not reimplement them and does not wrap them in a
subsystem; it shows you what is running and records what you ran.

---

## Start the canonical example

```bash
source /opt/ros/jazzy/setup.bash
ros2 run demo_nodes_py talker      # in one terminal
ros2 run demo_nodes_py listener    # in another
```

That is entirely ROS 2 — nothing caasi-specific yet. Now observe it through caasi:

```bash
caasi ros status                   # is a graph running at all?
caasi ros node list                # /talker, /listener
caasi ros topic list               # /chatter
caasi ros topic echo /chatter      # see the actual messages
caasi ros graph                    # how they connect
caasi ros service list             # services, if any
```

### A service, too

```bash
ros2 run demo_nodes_py add_two_ints_server
ros2 run demo_nodes_py add_two_ints_client 3 4
caasi ros node list                # the server node appears
```

---

## The commands this example teaches

`caasi ros status` · `ros node` · `ros topic` · `ros service` · `ros graph` ·
`ros list` · `ros --domain` · `ros … --target` · `caasi tools list` ·
`caasi target runtime` · `caasi pipeline` · `caasi control status`

### Watching the same system on another machine

If you have a second target with ROS 2, the same queries work remotely:

```bash
caasi ros node list --target <your-target> --domain <n>
```

`--domain` is required for remote queries on purpose: a runtime may live on a
non-default domain, and querying the wrong one returns an **empty graph that looks
like a healthy but idle system**. Requiring the domain makes that failure mode
impossible to hit silently.

> **A real limitation, measured:** if the two machines are on different LANs and
> reachable only over a VPN such as Tailscale, **DDS multicast discovery may not
> traverse the link**. caasi will resolve the context correctly and the graph will
> still appear empty — because it *is* empty from that vantage point. That is a
> network/DDS fact, not a caasi defect, and caasi does not tunnel or relay DDS.

---

## What caasi provides vs what ROS 2 provides

| ROS 2 provides | caasi provides |
| :--- | :--- |
| The `demo_nodes_py` talker, listener and service nodes | Consistency across local and remote queries |
| The pub/sub and service behaviour | An explicit `--domain`, so an empty graph cannot be mistaken for a valid one |
| `ros2` CLI semantics underneath | A single entry point alongside caasi's other observability commands |

caasi delegates to `ros2`; it never speaks `rclpy` itself.
