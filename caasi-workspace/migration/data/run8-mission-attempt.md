# Run 8: first attempt at the full mission round trip (stopped on low battery)

Robot on the floor in the maze, board answering the protocol at 288/291, `/odom` 50 Hz, `/scan`
14 Hz, camera streaming, mission launch up with 21 nodes and the mission in IDLE. The round trip
itself was not completed: the battery was too low to keep the stack running, and the owner took the
robot back to charge.

## What the attempt found

### The mission could never have started on ROS 2 (defect 15, fixed)

`~start` requires a home pose and refuses without one — the same precondition ROS 1 had
("尚未收到 /amcl_pose，请先完成初始定位"). On ROS 1 that was never a problem because **amcl published
`/amcl_pose` continuously**. nav2's amcl publishes it only when its filter updates, i.e. once the
robot has already moved -- and the follower that moves it is enabled by the mission that cannot
start. A genuine deadlock, invisible until someone tried it:

    /line_then_home/start -> success=False, 'no /amcl_pose received yet, cannot start'
    map -> odom exists, map -> base_link exists, /amcl_pose: not published

Setting an initial pose was not enough: it produced `map -> odom` but no `/amcl_pose`.

Fixed by falling back to the transform, which carries the same information the pose message does:
`pose_from_tf()` looks up `map -> base_link` (bounded by `tf_timeout`) and uses it as the home pose
when `/amcl_pose` has not arrived, logging that it did so. `/amcl_pose` stays the primary path.
Unit-tested both ways (a good lookup, and a missing chain returning `None` instead of raising).

**Not yet verified on hardware** -- it needs the battery.

### The mission node blocks external nudges, by design

Trying to trigger an amcl update by publishing `/cmd_vel` did nothing: odometry stayed at zero.
The mission node owns `/cmd_vel` and holds it at zero while IDLE, which is exactly the arbitration
the migration preserves. So there is no way to "nudge" the robot to satisfy a pose precondition,
which is what made defect 15 fatal rather than inconvenient.

### nav2's lifecycle manager is unreliable on this robot under load

    [map_server] failed to send response to /map_server/change_state (timeout):
                 client will not receive response

That is an RMW-level response timeout, not a resource problem: `/dev/shm` held 12 MB of 3.8 GB and
the run logged no SHM errors (an earlier run did, from stale segments after `kill -9`). With the
manager waiting, the whole nav2 stack stays `unconfigured` and the robot looks half-alive.

Manual transitions were also unreliable: `ros2 lifecycle set /map_server configure` answered
`shutdown [6]` while `get` still reported `inactive`. The practical route is a clean restart of the
stack (which brought all seven nodes to `active` in run 5) rather than fighting it in place.

Operational note for the next attempt: bring the stack up **without the camera** first, let nav2
reach `active`, then start the camera before calling `~start`. With the camera running at 30 Hz
during bringup, each configure transition took tens of seconds and the manager stalled.

## State left behind

Nothing running, no stray directories, robot left for charging.
