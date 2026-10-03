#ifndef NAVIGATION_STATE_CODE
#define NAVIGATION_STATE_CODE

// 定义任务执行过程返回值
#define NAV_STATE_RUNNING "running"
#define NAV_STATE_BLOCKED "blocked"
#define NAV_STATE_PAUSE "pausing"
#define NAV_STATE_RECOVERY "recovery"
#define NAV_STATE_REACHED "reached"
#define NAV_STATE_ERROR "error"

// 定义导航任务指令字
#define NAV_CMD_NAV_TO "nav_to"
#define NAV_CMD_MOVE "move"
#define NAV_CMD_PAUSE "pause"
#define NAV_CMD_CONTINUE "continue"
#define NAV_CMD_CANCEL "cancel"

// 定义升降平台执行过程返回值
#define LIFT_PLAT_STATE_KEEP "keep"
#define LIFT_PLAT_STATE_GOUP "goup"
#define LIFT_PLAT_STATE_GODOWN "godown"
#define LIFT_PLAT_STATE_UP "up"
#define LIFT_PLAT_STATE_DOWN "down"

// 定义升降平台任务指令字
#define LIFT_PLAT_CMD_KEEP "keep"
#define LIFT_PLAT_CMD_UP "up"
#define LIFT_PLAT_CMD_DOWN "down"

// 定义旋转平台执行过程返回值
#define ROT_PLAT_STATE_REACHED "reached"
#define ROT_PLAT_STATE_ROTATE "rotate"

// 定义旋转平台任务指令字
#define ROT_PLAT_CMD_ROTATE "rotate"

namespace navigation_ns
{
    enum navigation_state
    {
        READY = 0,
        PROCESSING = 1,
        RUNNING = 2,
        STRIGHTING = 3,
        TURNING = 4,
        PAUSING = 5,
        BLOCKED = 6,
        STRIGHTING_RECOVERY = 7,
        TURNING_RECOVERY = 8,
        REACHED = 9,
        REACHED_LAST = 10,
        ERROR = 11
    };

    enum block_state
    {
        FORWARD = 0,
        BACKWARD = 1,
        LEFT = 2,
        RIGHT = 3,
        CLEAR = 4
    };
}

#endif