// 2022-6-30 0.0.0.1A

#ifndef FLOW_STATE_CODE
#define FLOW_STATE_CODE

// 定义任务执行过程返回值
#define FLOW_STATE_RUNNING "running"
#define FLOW_STATE_BLOCKED "blocked"
#define FLOW_STATE_PAUSE "pause"
#define FLOW_STATE_END "end"
#define FLOW_STATE_ERROR "error"

namespace flow_ns
{
    enum flow_state
    {
        REACHED,
        RUNNING,
        PAUSE,
        BLOCKED,
        ERROR,
        END
    };
};

#endif