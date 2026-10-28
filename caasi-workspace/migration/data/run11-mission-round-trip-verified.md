# Run 11: the mission round trip, verified with the robot moving

Board answering **291/292** protocol frames. Everything through caasi: mission launch, pose,
camera, then `experiments/mission_start.yaml`.

## The sequence, measured

`/line_then_home/start` -> `success=True, 'task started: following the line'`, again with **no
`/amcl_pose`** -- the TF fallback is what makes the start possible on ROS 2.

| t | state | `/cmd_vel` | odometry | front clearance |
| --- | --- | --- | --- | --- |
| +18 s | FOLLOW | **v=+0.12**, w=+0.02 | (0.05, 0.00) | 0.72 m |
| +20 s | FOLLOW | **v=+0.12**, w=**-0.23** | (0.28, 0.02) | 0.38 m |
| +22 s | FOLLOW | **v=+0.12**, w=-0.11 | (0.50, 0.10) | 0.28 m |
| +24 s | FOLLOW | 0 | (0.53, 0.11) | **0.27 m** -- body-aware stop engaged |
| +58 s | NAV | 0 | (0.53, 0.11) | follow timeout reached |
| +60 s | NAV | **v=-0.12**, w=-0.26 | (0.40, 0.09) | **reversing** out |
| +62 s | DONE | 0 | (0.10, 0.09) | back at the home pose |

Mission log:

    state -> IDLE
    state -> FOLLOW
    line-following timed out, moving to the stop stage
    state -> STOP
    state -> NAV
    navigating to target 1/1 (0.22, 0.01)
    state -> DONE

## What this actually demonstrates

* **The line follower drives and steers.** 0.12 m/s with the steering term changing (-0.23, -0.11)
  as the tape curved; the robot travelled 0.5 m along it.
* **The body-aware obstacle stop works on a real obstacle.** Front clearance fell to 0.27 m and the
  follower held zero -- its threshold is 0.16 m body + 0.12 m margin = 0.28 m. This is the safety
  addition made after the earlier contact, doing exactly its job.
* **The mission's timeout path works.** The follow phase ended on its own 40 s timeout, one of the
  paths the ROS 1 supervisor already had.
* **The arbitration holds.** Only the mission published `/cmd_vel`; the line follower fed
  `/cmd_vel/line` and nav2 fed `/cmd_vel/nav`.
* **nav2 reverses.** The NAV phase commanded **-0.12 m/s** to manoeuvre out of the corner -- the
  capability that DWB lacked before defect 10 was fixed.
* **The mission ends at the captured home pose**, from the TF-based start.

## Calibration that made it possible

Measured on a live frame, not guessed:

| crop | mask pixels | rows containing a >=100 px horizontal run |
| --- | --- | --- |
| ROS 1 (to the image bottom) | 58 527 (17.6 %) | **59** |
| stops 70 px above the bottom | 9 740 (4.0 %) | **0** |

The near rows are where the tape widens into the field of view, and 59 rows containing a long
horizontal run is what made `HoughLinesP` declare the line finished on the first frames (FOLLOW
lasted 1.3 s in run 10, 5 s once the crop was trimmed but the end test was still active). Stopping
the crop 70 px above the bottom removed those rows, and the follower then saw the tape and drove.

The crop, the colour range, the end-of-line frame count and the follow timeout are all launch
arguments now, defaulting to the ROS 1 values, so this calibration lives in
`experiments/mission_demo.yaml` rather than in edited constants.

## State left behind

Runs stopped, nothing running, port 7000 free, temporary files removed from the robot.
