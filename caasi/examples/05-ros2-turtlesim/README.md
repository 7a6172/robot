# 05 — ROS 2 `turtlesim` (manual: needs a display)

**Prerequisites:** ROS 2 · **a graphical display** · GPU not required.

> ⚠️ **This example requires a display and is NOT validated automatically.**
> For the headless equivalent, see **[example 03](../03-ros2-demo-nodes/README.md)** —
> the observation commands are identical; only the nodes differ.

`turtlesim` is the example most ROS 2 users meet first, which is exactly why it is
here. **Turtlesim provides the simulator; caasi provides the observation** — and,
in this example, recording and replaying what the graph did.

---

## The commands this example teaches

`caasi ros status|node|topic|service|graph` · `caasi rviz2 --target` ·
`caasi rqt --target` · `caasi tools list` · `caasi replay` ·
`caasi teleop replay` · `caasi dataset`

---

## Walk through it

```bash
source /opt/ros/jazzy/setup.bash
ros2 run turtlesim turtlesim_node        # a window opens
```

In a second terminal:

```bash
ros2 run turtlesim turtle_teleop_key     # drive it with the arrow keys
```

Now observe — note these are the **same commands** as example 03:

```bash
caasi ros node list                      # /turtlesim
caasi ros topic list                     # /turtle1/cmd_vel, /turtle1/pose, ...
caasi ros topic echo /turtle1/pose       # live position
caasi ros service list                   # /turtle1/set_pen, /spawn, /reset, ...
caasi ros graph
```

### Recording and replaying

`ros2 bag` records; caasi records *where the record went* and replays it later:

```bash
ros2 bag record /turtle1/cmd_vel -o /tmp/turtle-bag
# ... drive the turtle ...
# Ctrl-C to stop

caasi replay /tmp/turtle-bag             # replay without re-running anything
```

### Target-aware tool invocation

If you have a robot running ROS 2, the same tools can attach to it — caasi supplies
the context, then gets out of the way:

```bash
caasi rviz2 --target <your-robot>        # runs the REAL rviz2, local GUI
caasi rqt   --target <your-robot>
caasi rosbag --target <your-robot> record /scan
```

`caasi rviz2` does **not** implement RViz. It resolves the target's ROS 2 context,
then executes the normal `rviz2` on your machine.

---

## What caasi provides vs what the ecosystem provides

| Ecosystem provides | caasi provides |
| :--- | :--- |
| `turtlesim` — the simulator and its window | Observation of the running graph |
| `ros2 bag` — the recording format | Recording *where* a bag went, and replaying it |
| `rviz2` / `rqt` — the GUI tools | Target context so a *local* GUI can attach to a *remote* graph |

**Not used in this example:** `turtle_teleop_key` invites interactive driving, and
caasi teaches nothing there — it is mentioned only because you will need it to make
the turtle move.

> **Discovery caveat.** A local GUI attaching to a *remote* graph depends on DDS
> discovery traversing the network between the two machines. Across some VPN
> topologies it does not, and the tool will show an empty graph even though caasi
> resolved the context correctly. caasi does not implement DDS discovery, tunnels or
> relays — see example 03 for the measured note.
