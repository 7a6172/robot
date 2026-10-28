# Run 10: the mission round trip — supervisor verified, vision needs site calibration

Robot on the floor in the maze, board answering **290/292 protocol frames**, `/odom` 50 Hz,
`/scan` 14 Hz, camera streaming. Brought up through caasi, in the order that works.

## The supervisor ran the whole sequence

    state -> IDLE
    state -> FOLLOW      (mission_start called; pose came from TF, not /amcl_pose)
    state -> STOP        1.3 s later
    state -> NAV
    navigating to target 1/1 (-0.10, 0.03)
    state -> DONE        1.7 s later

`/line_then_home/start` returned `success=True, 'task started: following the line'` **without any
`/amcl_pose`** — the TF fallback added in run 8 is what made that possible, and it is now verified on
hardware. nav2's `navigate_to_pose` action accepted and completed the NAV target, so the second half
of the mission works against the real stack.

The transform is confirmed working: before the start, `map -> base_link` existed while `/amcl_pose`
did not, which is exactly the case that used to deadlock.

## But the robot did not move, and the reason is the vision constants

`FOLLOW` lasted 1.3 s because the line follower latched `/reached_goal = True` immediately: its
end-of-line detector saw a near-horizontal segment and concluded the line had finished. Measured on
a live frame, with the follower's own crop and thresholds:

| mask | pixels | share of crop | median row width |
| --- | --- | --- | --- |
| ROS 1 `[10,20,10]`-`[40,50,40]` | 56 408 | **16.96 %** | **62 px** |
| tighter `[10,20,10]`-`[30,40,30]` | 19 614 | 5.90 % | 27 px |
| tighter still `[25,35,25]` | 5 017 | 1.51 % | 7 px |

A tape line a few centimetres wide should occupy a narrow band. 62 px of median width across 260
rows is a broad mid-grey region, not a line -- and a broad region contains plenty of near-horizontal
edges for `HoughLinesP(..., |slope| < 0.2)` to latch onto.

The frame's darkest pixels tell the rest of the story:

| darkest | mean BGR |
| --- | --- |
| 1 % | (6.2, 9.1, 7.3) |
| 5 % | (14.9, 17.7, 15.6) |

ROS 1's lower bound requires **green >= 20**, so the black tape at green ~9-18 is largely *excluded*,
while mid-grey floor in the 20-50 range is *included*. The constants are the ROS 1 ones, unchanged --
they simply do not describe this floor and this tape.

This is why the ROS 1 script carries `mouse_callback`: clicking the image prints
`BGR=(b, g, r)` so the operator can find the tape's range. That tuning loop was ported (the colours
are printed the same way) but it needs a display, so it cannot be run headless.

## What this means

The mission supervisor, the arbitration, the nav2 interface and the TF-based start are all verified
end to end. What remains is **site calibration of the line follower's colour thresholds**, which is
a property of the floor and the tape rather than of the migration, and which ROS 1 left to the
operator.

The constants are not parameters in the script, so tuning means either changing them or promoting
them to parameters. Both are a change to a ported behaviour, so this was left for the owner to
decide rather than guessed at.
