#include <navigation/navigation/navigation_handler.h>

#define NODE_NAME "navigation_handler"
#define TAG "导航控制器"

// 功能函数
// 检查类型
navigation_mode get_navigation_mode(string cmd, string localization_sources)
{
    navigation_mode ret = navigation_mode::UNKNOW;

    if (cmd == NAV_CMD_NAV_TO)
    {
        if (localization_sources.find(LOCALIZATION_MAP) != localization_sources.npos)
        {
            ret = navigation_mode::NAVIGATION_MAP;
        }
        else if (localization_sources.find(LOCALIZATION_ODOM) != localization_sources.npos)
        {
            ret = navigation_mode::NAVIGATION_ODOM;
        }
    }
    else if (cmd == NAV_CMD_MOVE)
    {
        if (localization_sources.find(LOCALIZATION_MAP) != localization_sources.npos)
        {
            ret = navigation_mode::MOVE_MAP;
        }
        else if (localization_sources.find(LOCALIZATION_ODOM) != localization_sources.npos)
        {
            ret = navigation_mode::MOVE_ODOM;
        }
    }

    return ret;
}

// 设置运动学参数
void set_kinematic_params(openmover_msgs::nav_to_request::Request &req)
{
    if (req.twist.linear.x > 0 && req.twist.angular.z > 0)
    {
        mover_controller->set_kinematic_params(req.twist.linear.x, req.twist.angular.z);
        path_follower_controller->set_kinematic_params(req.twist.linear.x, req.twist.angular.z);
    }
    else if (req.twist.linear.x > 0)
    {
        mover_controller->set_kinematic_params(req.twist.linear.x, max_yaw_vel);
        path_follower_controller->set_kinematic_params(req.twist.linear.x, max_yaw_vel);
    }
    else if (req.twist.angular.z > 0)
    {
        mover_controller->set_kinematic_params(max_x_vel, req.twist.angular.z);
        path_follower_controller->set_kinematic_params(max_x_vel, req.twist.angular.z);
    }
    else
    {
        mover_controller->set_kinematic_params(max_x_vel, max_yaw_vel);
        path_follower_controller->set_kinematic_params(max_x_vel, max_yaw_vel);
    }
}

// 设置容差参数
void set_tolerance_params(openmover_msgs::nav_to_request::Request &req)
{
    if (req.xy_tolerance > 0 && req.yaw_tolerance > 0)
    {
        path_follower_controller->set_tolerance_params(req.xy_tolerance, req.yaw_tolerance);
    }
    else if (req.xy_tolerance > 0)
    {
        path_follower_controller->set_tolerance_params(req.xy_tolerance, yaw_tolerance);
    }
    else if (req.yaw_tolerance > 0)
    {
        path_follower_controller->set_tolerance_params(xy_tolerance, req.yaw_tolerance);
    }
    else
    {
        path_follower_controller->set_tolerance_params(xy_tolerance, yaw_tolerance);
    }
}

// 创建计划
void make_plan(openmover_msgs::nav_to_request::Response &res, float nav_to_distance, float nav_to_angle)
{
    // 尝试创建计划
    if (mover_controller->make_plan(mode == navigation_mode::MOVE_ODOM ? odom_data : pose_data,
                                    nav_to_distance, nav_to_angle, nav_to_request_data.ignore_obstacle, false))
    {
        ROS_INFO("%s：速度规划完成，准备开始运行。", TAG);

        // 清除状态
        openmover_msgs::nav_to_state nav_to_state_data;

        for (int i = 0; i < 3; i++)
        {
            nav_to_state_data.header.stamp = ros::Time::now();
            nav_to_state_data.pose = pose_data.pose;
            nav_to_state_data.twist = odom_twist_data.twist;
            nav_to_state_data.state = NAV_STATE_RUNNING;

            nav_to_state_pub.publish(nav_to_state_data);

            ros::Duration(1.0 / control_freq).sleep();
        }
    }
    else
    {
        ROS_ERROR("%s：速度规划失败。", TAG);

        // 创建失败
        res.result = CMD_RESPONSE_ERROR;
    }
}

vector<geometry_msgs::PoseStamped> make_global_plan(openmover_msgs::nav_to_request::Request &req, geometry_msgs::Pose from, geometry_msgs::Pose to)
{
    vector<geometry_msgs::PoseStamped> ret;

    navfn::MakeNavPlan make_plan;

    // 清空路径
    ret.clear();

    // 检查是否需要规划
    bool global_plan_flag = (mode == navigation_mode::NAVIGATION_MAP &&
                             req.use_global_planner &&
                             use_global_planner &&
                             path_follower::distance(from, to) > max(0.1f, xy_tolerance));

    replan_flag = always_replan & global_plan_flag;

    // 若需要规划且服务存在，规划全局路径
    if (global_plan_flag)
    {
        make_plan.request.start.header.frame_id = LOCALIZATION_MAP;
        make_plan.request.start.header.stamp = ros::Time::now();
        make_plan.request.start.pose.orientation = from.orientation;
        make_plan.request.start.pose.position = from.position;

        make_plan.request.goal.header.frame_id = LOCALIZATION_MAP;
        make_plan.request.goal.header.stamp = ros::Time::now();
        make_plan.request.goal.pose.orientation = to.orientation;
        make_plan.request.goal.pose.position = to.position;

        // 尝试若干次，直到规划成功
        tuple<bool, vector<geometry_msgs::PoseStamped>, vector<geometry_msgs::PoseStamped>> plan_result =
            make_tuple<bool, vector<geometry_msgs::PoseStamped>, vector<geometry_msgs::PoseStamped>>(false, vector<geometry_msgs::PoseStamped>(), vector<geometry_msgs::PoseStamped>());
        int try_count = 0;

        while (!get<0>(plan_result) &&
               try_count < max_global_plan_try_count)
        {
            if (try_count >= 1)
            {
                ROS_WARN("%s：全局路径规划失败，正在进行第 %d 次重试。", TAG, try_count);
            }

            // 调用规划服务
            // plan_result = global_planner_instance->plan(make_plan.request.start, make_plan.request.goal,
            //                                             map_data,
            //                                             planner_min_dist_to_obs, true, 1, true, 2.0, 8, map_occupied_threshold);
            // plan_result = global_planner_instance->plan(make_plan.request.start, make_plan.request.goal,
            //                                             map_data,
            //                                             planner_min_dist_to_obs, true, 1, false, 1.0, 8, map_occupied_threshold);
            plan_result = global_planner_static_instance->plan(make_plan.request.start, make_plan.request.goal,
                                                               map_data,
                                                               planner_min_dist_to_obs, true, 1, false, 1.0, 8, map_occupied_threshold);

            // 开始计数
            try_count++;

            // 防止服务阻塞
            ros::Duration(SERVICE_RETRY_DURATION).sleep();
        }

        // 若找到路径，则保存路径
        if (get<0>(plan_result))
        {
            ret = get<1>(plan_result);
        }
    }
    // 若不需要规划，则插补路径
    else
    {
        // 获取目标点
        geometry_msgs::PoseStamped goal;

        goal.header.frame_id = (mode == navigation_mode::NAVIGATION_ODOM ? LOCALIZATION_ODOM : LOCALIZATION_MAP);
        goal.header.stamp = ros::Time::now();
        goal.pose = to;

        // 插补直线路径
        double distance = sqrt(pow(goal.pose.position.x - from.position.x, 2) +
                               sqrt(pow(goal.pose.position.y - from.position.x, 2)));

        int step = (int)(distance / 0.01);

        if (step > 5)
        {
            ROS_INFO("%s：满足直线插补条件，进行直线插补。", TAG);

            nav_msgs::Path linear_path;
            geometry_msgs::PoseStamped start_pose;

            start_pose.header.frame_id = (mode == navigation_mode::NAVIGATION_ODOM ? LOCALIZATION_ODOM : LOCALIZATION_MAP);
            start_pose.header.stamp = ros::Time::now();
            start_pose.pose = from;

            ret.push_back(start_pose);
            linear_path.poses.push_back(start_pose);

            linear_path.header.frame_id = (mode == navigation_mode::NAVIGATION_ODOM ? LOCALIZATION_ODOM : LOCALIZATION_MAP);
            linear_path.header.stamp = ros::Time::now();

            double delta_x = (goal.pose.position.x - from.position.x) / step;
            double delta_y = (goal.pose.position.y - from.position.y) / step;

            for (int i = 5; i < step - 1; i++)
            {
                geometry_msgs::PoseStamped traj_pose;

                traj_pose.header.frame_id = (mode == navigation_mode::NAVIGATION_ODOM ? LOCALIZATION_ODOM : LOCALIZATION_MAP);
                traj_pose.header.stamp = ros::Time::now();
                traj_pose.pose.position.x = from.position.x + (i + 1) * delta_x;
                traj_pose.pose.position.y = from.position.y + (i + 1) * delta_y;
                traj_pose.pose.orientation = tf::createQuaternionMsgFromYaw(0);

                linear_path.poses.push_back(traj_pose);
                ret.push_back(traj_pose);
            }

            linear_path.poses.push_back(goal);

            linear_path_pub.publish(linear_path);
        }

        ret.push_back(goal);
    }

    return ret;
}

void make_plan(openmover_msgs::nav_to_request::Response &res, openmover_msgs::nav_to_request::Request &req)
{
    // 尝试创建计划
    if (mode == navigation_mode::NAVIGATION_MAP || mode == navigation_mode::NAVIGATION_ODOM)
    {
        if (req.use_planned_path &&
            req.planned_path.size() > 0)
        {
            ROS_INFO("%s：使用先验路径。", TAG);
        }
        else
        {
            ROS_INFO("%s：不使用先验路径，进行实时全局路径规划。", TAG);

            req.planned_path = make_global_plan(req, pose_data.pose.pose, req.pose);
        }

        if (path_follower_controller->make_plan(mode == navigation_mode::NAVIGATION_ODOM ? odom_data : pose_data,
                                                req.planned_path, req.ignore_obstacle, replan_flag))
        {
            ROS_INFO("%s：局部路径规划完成，准备开始运行。", TAG);

            // 清除状态
            openmover_msgs::nav_to_state nav_to_state_data;

            for (int i = 0; i < 3; i++)
            {
                nav_to_state_data.header.stamp = ros::Time::now();
                nav_to_state_data.pose = (mode == navigation_mode::NAVIGATION_ODOM ? odom_data.pose : pose_data.pose);
                nav_to_state_data.twist = odom_twist_data.twist;
                nav_to_state_data.state = NAV_STATE_RUNNING;

                nav_to_state_pub.publish(nav_to_state_data);

                ros::Duration(1.0 / control_freq).sleep();
            }
        }
        else
        {
            ROS_ERROR("%s：局部路径规划失败。", TAG);

            // 创建失败
            res.result = CMD_RESPONSE_ERROR;
        }
    }
}

// 设置速度控制模式
bool set_cmd_vel_mode(bool manual)
{
    bool ret = false;

    openmover_msgs::cmd_vel_mode_request cmd_vel_mode;

    cmd_vel_mode.request.manual = manual;

    if (cmd_vel_mode_client.waitForExistence())
    {
        ret = cmd_vel_mode_client.call(cmd_vel_mode);

        if (ret)
        {
            ret = cmd_vel_mode.response.result == CMD_RESPONSE_OK;
        }
    }

    return ret;
}

// 回调函数
// 全局位姿回调函数
void pose_callback(const geometry_msgs::PoseWithCovarianceStamped::ConstPtr &msg)
{
    pose_data = *msg;

    if (ros::Time::now() >= pose_data_last_received_time)
    {
        pose_data_last_received_time = ros::Time::now();
    }

    pose_received = true;
}

// 里程计回调函数
void odom_callback(const geometry_msgs::PoseWithCovarianceStamped::ConstPtr &msg)
{
    odom_data = *msg;

    if (ros::Time::now() >= odom_data_last_received_time)
    {
        odom_data_last_received_time = ros::Time::now();
    }

    odom_received = true;
}

// 里程计速度回调函数
void odom_twist_callback(const geometry_msgs::TwistWithCovarianceStamped::ConstPtr &msg)
{
    odom_twist_data = *msg;

    if (ros::Time::now() >= odom_data_last_received_time)
    {
        odom_data_last_received_time = ros::Time::now();
    }

    odom_twist_received = true;
}

// 障碍物回调函数
void obstacle_callback(const openmover_msgs::obstacle::ConstPtr &msg)
{
    obstacle_data = *msg;

    if (ros::Time::now() >= obstacle_data_last_received_time)
    {
        obstacle_data_last_received_time = ros::Time::now();
    }

    obstacle_received = true;
}

// nav_to_request回调函数
bool nav_to_request_callback(openmover_msgs::nav_to_request::Request &req, openmover_msgs::nav_to_request::Response &res)
{
    bool ret = false;

    // 可执行导航
    if ((req.cmd == NAV_CMD_NAV_TO || req.cmd == NAV_CMD_MOVE) &&
        state == navigation_state::READY && !emergency_data.data)
    {
        // 保存指令
        nav_to_request_data = req;

        // 检查指令类型
        mode = get_navigation_mode(req.cmd, req.localization_sources);

        if ((mode == navigation_mode::NAVIGATION_MAP && pose_received) ||
            (mode == navigation_mode::NAVIGATION_ODOM && odom_received))
        {
            // 接受计划
            res.result = CMD_RESPONSE_OK;

            ROS_INFO("%s：自主导航任务创建成功，开始规划速度。", TAG);

            // 执行计划
            set_kinematic_params(req);
            set_tolerance_params(req);
            make_plan(res, req);

            // 需要按钮控制
            button_required = req.button_required;

            // 清空消息状态
            odom_received = false;
            pose_received = false;
            obstacle_received = false;

            cmd_received_time = ros::Time::now();
        }
        else if ((mode == navigation_mode::MOVE_ODOM && odom_received) ||
                 (mode == navigation_mode::MOVE_MAP && pose_received))
        {
            // 接受计划
            res.result = CMD_RESPONSE_OK;

            ROS_INFO("%s：移动任务创建成功，开始规划速度。", TAG);

            replan_flag = false;

            // 执行计划
            set_kinematic_params(req);
            make_plan(res,
                      nav_to_request_data.pose.position.x,
                      nav_to_request_data.pose.position.z);

            // 需要按钮控制
            button_required = req.button_required;

            // 清空消息状态
            odom_received = false;
            pose_received = false;
            obstacle_received = false;

            cmd_received_time = ros::Time::now();
        }
        // 指令错误
        else
        {
            res.result = CMD_RESPONSE_OK;

            state = navigation_state::READY;
        }
    }
    // 暂停会话
    else if (req.cmd == NAV_CMD_PAUSE)
    {
        // 接受计划
        res.result = CMD_RESPONSE_OK;

        // ROS_WARN("%s：任务尝试暂停。", TAG);

        if (mode == navigation_mode::NAVIGATION_MAP ||
            mode == navigation_mode::NAVIGATION_ODOM)
        {
            path_follower_controller->pause_session();
        }
        else if (mode == navigation_mode::MOVE_MAP ||
                 mode == navigation_mode::MOVE_ODOM)
        {
            mover_controller->pause_session();
        }
    }
    // 继续会话
    else if (req.cmd == NAV_CMD_CONTINUE)
    {
        // 接受计划
        res.result = CMD_RESPONSE_OK;

        // ROS_WARN("%s：任务尝试继续。", TAG);

        if (mode == navigation_mode::NAVIGATION_MAP ||
            mode == navigation_mode::NAVIGATION_ODOM)
        {
            path_follower_controller->continue_session();
        }
        else if (mode == navigation_mode::MOVE_MAP ||
                 mode == navigation_mode::MOVE_ODOM)
        {
            mover_controller->continue_session();
        }
    }
    // 可执行取消导航任务指令
    else if (req.cmd == NAV_CMD_CANCEL)
    {
        res.result = CMD_RESPONSE_OK;

        if (mode == navigation_mode::NAVIGATION_MAP ||
            mode == navigation_mode::NAVIGATION_ODOM)
        {
            path_follower_controller->reset_state();

            openmover_msgs::nav_to_state nav_to_state_data;
            nav_to_state_data.header.stamp = ros::Time::now();
            nav_to_state_data.state = NAV_STATE_REACHED;

            nav_to_state_pub.publish(nav_to_state_data);
        }
        else if (mode == navigation_mode::MOVE_MAP ||
                 mode == navigation_mode::MOVE_ODOM)
        {
            mover_controller->reset_state();

            openmover_msgs::nav_to_state nav_to_state_data;
            nav_to_state_data.header.stamp = ros::Time::now();
            nav_to_state_data.state = NAV_STATE_REACHED;

            nav_to_state_pub.publish(nav_to_state_data);
        }

        // 手动控制
        if (request_from_simple_goal)
        {
            ROS_INFO("%s：切换为手动控制模式。", TAG);

            set_cmd_vel_mode(true);

            request_from_simple_goal = false;
        }
    }
    // 正忙
    else if ((req.cmd == NAV_CMD_NAV_TO || req.cmd == NAV_CMD_MOVE) &&
             state != navigation_state::READY)
    {
        res.result = CMD_RESPONSE_BUSY;
    }
    // 错误
    else
    {
        res.result = CMD_RESPONSE_ERROR;
    }

    ret = true;

    return ret;
}

// nav_to_simple_request回调函数
bool nav_to_simple_request_callback(openmover_msgs::nav_to_simple_request::Request &req, openmover_msgs::nav_to_simple_request::Response &res)
{
    bool ret = false;

    openmover_msgs::nav_to_request::Request request;
    openmover_msgs::nav_to_request::Response response;

    request.cmd = req.request.cmd;
    request.ignore_obstacle = req.request.ignore_obstacle;
    request.localization_sources = req.request.localization_sources;
    request.use_global_planner = req.request.use_global_planner;
    request.use_planned_path = req.request.use_planned_path;

    request.pose.position.x = req.request.x;
    request.pose.position.y = req.request.y;
    request.pose.orientation = tf::createQuaternionMsgFromYaw(angles::from_degrees(req.request.yaw));

    request.twist.linear.x = req.request.vxmax;
    request.twist.angular.z = angles::from_degrees(req.request.vyawmax);

    request.xy_tolerance = req.request.xy_tolerance;
    request.yaw_tolerance = req.request.yaw_tolerance;

    if (!request.use_planned_path || (req.request.planned_path_x.size() == req.request.planned_path_y.size() &&
                                      req.request.planned_path_x.size() == req.request.planned_path_yaw.size()))
    {
        if (request.use_planned_path)
        {
            request.planned_path.clear();

            for (int i = 0; i < req.request.planned_path_x.size(); i++)
            {
                geometry_msgs::PoseStamped pose;

                pose.header.frame_id = LOCALIZATION_MAP;
                pose.header.stamp = ros::Time::now();
                pose.pose.position.x = req.request.planned_path_x[i];
                pose.pose.position.y = req.request.planned_path_y[i];
                pose.pose.orientation = tf::createQuaternionMsgFromYaw(angles::from_degrees(req.request.planned_path_yaw[i]));

                request.planned_path.push_back(pose);
            }
        }

        // 标记请求来自简易导航目标
        request_from_simple_goal = true;

        request.button_required = req.request.button_required;

        ret = nav_to_request_callback(request, response);

        res.result = response.result;
    }
    else
    {
        res.result = CMD_RESPONSE_ERROR;

        ret = true;
    }

    return ret;
}

// simple_goal 回调函数
void simple_goal_callback(const geometry_msgs::PoseStamped::ConstPtr &msg)
{
    ROS_INFO("%s：接收到简易导航目标请求。", TAG);

    // 简单目标服务，内联调用服务
    openmover_msgs::nav_to_request::Request request;
    openmover_msgs::nav_to_request::Response response;

    request.cmd = NAV_CMD_NAV_TO;
    request.localization_sources = string(LOCALIZATION_ODOM) + string(LOCALIZATION_MAP);
    request.pose = msg->pose;
    request.twist.linear.x = max_x_vel;
    request.twist.angular.z = max_yaw_vel;
    request.use_global_planner = true;
    request.ignore_obstacle = false;

    // 标记请求来自简易导航目标
    request_from_simple_goal = true;

    if (nav_to_request_callback(request, response) &&
        response.result == CMD_RESPONSE_OK)
    {
        ROS_INFO("%s：简易导航目标已传送。", TAG);
    }
    else
    {
        ROS_WARN("%s：当前无法接收简易导航目标。", TAG);
    }
}

void button_callback(const std_msgs::Bool::ConstPtr &msg)
{
    button_data.data = msg->data;

    button_received = true;
}

void map_callback(const nav_msgs::OccupancyGrid::ConstPtr &msg)
{
    map_data = *msg;

    map_received = true;
}

void emergency_callback(const std_msgs::Bool::ConstPtr &msg)
{
    emergency_data = *msg;

    emergency_data_received = true;
}

int main(int argc, char **argv)
{
    // 初始化ROS节点
    ros::init(argc, argv, NODE_NAME);

    // 设置控制台本地化，以显示中文
    setlocale(LC_CTYPE, "zh_CN.utf8");

    // 打印调试信息
    ROS_INFO("%s：节点已启动。", TAG);

    // 定义ROS节点处理程序
    ros::NodeHandle node_handle;

    // 定义ROS参数获取程序
    ros::NodeHandle node_handle_param("~/navigation");
    ros::NodeHandle node_handle_param_global("~");

    // 全局规划器
    ROS_INFO("%s：正在初始化全局规划器...", TAG);

    tf2_ros::Buffer buffer_global(ros::Duration(10));
    tf2_ros::TransformListener tf_global(buffer_global);
    tf2_ros::Buffer buffer_global_static(ros::Duration(10));
    tf2_ros::TransformListener tf_global_static(buffer_global_static);

    costmap_2d::Costmap2DROS lcr_global("global_costmap", buffer_global);
    costmap_2d::Costmap2DROS lcr_global_static("global_costmap_static", buffer_global_static);

    global_planner_instance = make_shared<planner_with_costmap>("global_planner", &lcr_global, ros::Time::now());
    global_planner_static_instance = make_shared<planner_with_costmap>("global_planner_static", &lcr_global_static, ros::Time::now());

    ROS_INFO("%s：全局规划器初始化成功。", TAG);

    // 获取参数
    // 通用部分
    node_handle_param.param<float>("control_freq", control_freq, 50);

    node_handle_param.param<float>("max_x_vel", max_x_vel, 0.8);
    node_handle_param.param<float>("min_x_vel", min_x_vel, 0.02);
    node_handle_param.param<float>("max_x_acc", max_x_acc, 0.6);

    node_handle_param.param<float>("max_yaw_vel", max_yaw_vel, 0.3);
    node_handle_param.param<float>("min_yaw_vel", min_yaw_vel, 0.05);
    node_handle_param.param<float>("max_yaw_acc", max_yaw_acc, 0.3);

    node_handle_param.param<float>("velocity_dec_line_offset_time", velocity_dec_line_offset_time, 0.2);
    node_handle_param.param<float>("velocity_dec_angle_offset_time", velocity_dec_angle_offset_time, 0.2);

    node_handle_param.param<float>("strighting_stop_distance", strighting_stop_distance, 1.0);
    node_handle_param.param<float>("turning_stop_distance", turning_stop_distance, 0.1);
    node_handle_param.param<float>("ignore_obstacle_dist", ignore_obstacle_dist, 0.08f);

    node_handle_param.param<float>("obstacle_acc_ratio", obstacle_acc_ratio, 1.5);
    node_handle_param.param<float>("collision_vel_dec_ratio", collision_vel_dec_ratio, 1.2);
    node_handle_param.param<int>("collision_trajectory_sampling_ratio", collision_trajectory_sampling_ratio, 1);
    node_handle_param.param<int>("collision_plan_try_count", collision_plan_try_count, 3);
    node_handle_param.param<int>("collision_path_sampling_ratio", collision_path_sampling_ratio, 3);
    node_handle_param.param<float>("collision_path_dist_error_tolerance", collision_path_dist_error_tolerance, 0.2);
    node_handle_param.param<float>("collision_path_angle_error_tolerance", collision_path_angle_error_tolerance, 0.087);
    node_handle_param.param<float>("collision_obstacle_detection_area_padding_ratio", collision_obstacle_detection_area_padding_ratio, 1.2);
    node_handle_param.param<int>("collision_narrow_section_padding", collision_narrow_section_padding, 20);

    node_handle_param.param<float>("strighting_tolerance", strighting_tolerance, 0.01);
    node_handle_param.param<float>("turning_tolerance", turning_tolerance, 0.02);

    node_handle_param.param<float>("sensor_msg_timeout", sensor_msg_timeout, 1.0);

    // 自主导航部分
    node_handle_param.param<int>("map_free_threshold", map_free_threshold, 30);
    node_handle_param.param<int>("map_occupied_threshold", map_occupied_threshold, 55);

    node_handle_param.param<bool>("use_global_planner", use_global_planner, false);
    node_handle_param.param<bool>("always_replan", always_replan, true);

    node_handle_param.param<float>("planner_min_dist_to_obs", planner_min_dist_to_obs, 0.25);

    node_handle_param.param<bool>("allow_reverse_drive", allow_reverse_drive, false);
    node_handle_param.param<bool>("use_advanced_evaluation", use_advanced_evaluation, true);
    node_handle_param.param<bool>("use_kinematic_limits", use_kinematic_limits, true);
    node_handle_param.param<bool>("use_find_mode_follower", use_find_mode_follower, true);

    node_handle_param.param<float>("find_mode_x_vel", find_mode_x_vel, 0.2);
    node_handle_param.param<float>("find_mode_yaw_vel", find_mode_yaw_vel, 0.3);
    node_handle_param.param<float>("find_mode_radius", find_mode_radius, 2.0);
    node_handle_param.param<float>("find_mode_min_dist_timeout", find_mode_min_dist_timeout, 1.0);

    node_handle_param.param<bool>("enable_near_angle_correct", enable_near_angle_correct, true);

    node_handle_param.param<float>("angle_diff_to_forward", angle_diff_to_forward, 0.1);
    node_handle_param.param<float>("angle_diff_to_rotate", angle_diff_to_rotate, 1.2);

    node_handle_param.param<float>("xy_tolerance", xy_tolerance, 0.01);
    node_handle_param.param<float>("yaw_tolerance", yaw_tolerance, 0.01);

    node_handle_param.param<float>("chassis_radius", chassis_radius, 0.4);

    node_handle_param.param<float>("sim_time", sim_time, 2.0);
    node_handle_param.param<float>("find_mode_sim_time", find_mode_sim_time, 1.0);
    node_handle_param.param<int>("sim_vx_space_size", sim_vx_space_size, 10);
    node_handle_param.param<int>("sim_vyaw_space_size", sim_vyaw_space_size, 20);
    node_handle_param.param<int>("trajectory_sim_step", trajectory_sim_step, 20);
    node_handle_param.param<float>("follow_point_weight", follow_point_weight, 1.0);
    node_handle_param.param<float>("follow_path_weight", follow_path_weight, 1.0);

    node_handle_param.param<int>("max_global_plan_try_count", max_global_plan_try_count, 2);

    // 足迹部分
    XmlRpc::XmlRpcValue footprint_param;
    node_handle_param_global.getParam("footprint", footprint_param);

    for (int i = 0; i < footprint_param.size(); i++)
    {
        vector<float> point_vector;

        for (int j = 0; j < footprint_param[i].size(); j++)
        {
            point_vector.push_back(double(footprint_param[i][j]));
        }

        geometry_msgs::Point32 point;

        point.x = point_vector[0];
        point.y = point_vector[1];

        footprint_polygon.points.push_back(point);
    }

    // pose 订阅器
    ros::Subscriber pose_sub = node_handle.subscribe("openmover/localization/pose", 2, pose_callback);
    // odom 订阅器
    ros::Subscriber odom_sub = node_handle.subscribe("openmover/localization/odom", 2, odom_callback);
    // odom_twist 订阅器
    ros::Subscriber odom_twist_sub = node_handle.subscribe("openmover/localization/twist", 2, odom_twist_callback);
    // obstacle 订阅器
    ros::Subscriber obstacle_sub = node_handle.subscribe("openmover/navigation/obstacle", 1, obstacle_callback);
    // simple_goal 订阅器
    ros::Subscriber simple_goal_sub = node_handle.subscribe("openmover/navigation/simple_goal", 2, simple_goal_callback);
    // button 订阅器
    ros::Subscriber button_sub = node_handle.subscribe("openmover/hardware/button", 1, button_callback);
    // map 订阅器
    ros::Subscriber map_sub = node_handle.subscribe("openmover/mapping/map", 1, map_callback);
    // emergency 订阅器
    ros::Subscriber emergency_sub = node_handle.subscribe("openmover/hardware/emergency", 1, emergency_callback);
    // nav_to_request 服务订阅器
    ros::ServiceServer nav_to_server = node_handle.advertiseService("openmover/navigation/request", nav_to_request_callback);
    // nav_to_simple_request 服务订阅器
    ros::ServiceServer nav_to_simple_server = node_handle.advertiseService("openmover/navigation/simple_request", nav_to_simple_request_callback);

    // cmd_vel 话题发布器
    ros::Publisher cmd_vel_pub = node_handle.advertise<geometry_msgs::Twist>("openmover/control/cmd_vel", 1);
    // nav_to_state 话题发布器
    nav_to_state_pub = node_handle.advertise<openmover_msgs::nav_to_state>("openmover/navigation/state", 1, true);
    // 插补发布器
    linear_path_pub = node_handle.advertise<nav_msgs::Path>("openmover/navigation/linear_path", 1);
    // 接管速度服务
    cmd_vel_mode_client = node_handle.serviceClient<openmover_msgs::cmd_vel_mode_request>("openmover/control/cmd_vel_mode/request");

    // 定义传感器数据超时周期
    ros::Duration sensor_msg_timeout_duration(sensor_msg_timeout);

    // 定义移动控制器
    mover_controller = unique_ptr<mover>(new mover(max_x_vel, min_x_vel, max_x_acc,
                                                   max_yaw_vel, min_yaw_vel, max_yaw_acc,
                                                   velocity_dec_line_offset_time,
                                                   velocity_dec_angle_offset_time,
                                                   find_mode_min_dist_timeout,
                                                   strighting_tolerance, turning_tolerance,
                                                   strighting_stop_distance, turning_stop_distance, ignore_obstacle_dist,
                                                   obstacle_acc_ratio,
                                                   control_freq));

    // 定义导航控制器
    path_follower_controller = unique_ptr<path_follower>(new path_follower(max_x_vel, min_x_vel, max_x_acc, max_yaw_vel, min_yaw_vel, max_yaw_acc, allow_reverse_drive,
                                                                           use_advanced_evaluation, use_kinematic_limits, use_find_mode_follower,
                                                                           velocity_dec_angle_offset_time,
                                                                           find_mode_x_vel, find_mode_yaw_vel, find_mode_radius, find_mode_min_dist_timeout, enable_near_angle_correct,
                                                                           angle_diff_to_forward, angle_diff_to_rotate,
                                                                           xy_tolerance, yaw_tolerance,
                                                                           chassis_radius,
                                                                           sim_time, find_mode_sim_time, sim_vx_space_size, sim_vyaw_space_size, trajectory_sim_step, follow_point_weight, follow_path_weight,
                                                                           strighting_stop_distance, turning_stop_distance, ignore_obstacle_dist,
                                                                           obstacle_acc_ratio, collision_vel_dec_ratio,
                                                                           collision_plan_try_count, collision_trajectory_sampling_ratio, collision_path_sampling_ratio,
                                                                           collision_path_dist_error_tolerance, collision_path_angle_error_tolerance,
                                                                           collision_obstacle_detection_area_padding_ratio, collision_narrow_section_padding,
                                                                           footprint_polygon,
                                                                           control_freq,
                                                                           global_planner_instance,
                                                                           map_occupied_threshold,
                                                                           planner_min_dist_to_obs));

    try
    {
        auto grid = ros::topic::waitForMessage<nav_msgs::OccupancyGrid>("openmover/mapping/map", ros::Duration(60.0));

        if (grid != NULL)
        {
            map_data = *grid;

            map_received = true;
        }
    }
    catch (...)
    {
        cout << "could not get global map." << endl;
    }

    // 定义ROS节点循环频率控制器
    ros::Rate loop_rate(control_freq);

    while (node_handle.ok())
    {
        // 注册回调
        ros::spinOnce();

        // 初始化数据
        nav_to_state_data.header.stamp = ros::Time::now();
        nav_to_state_data.twist = odom_twist_data.twist;

        if (mode == navigation_mode::NAVIGATION_ODOM)
        {
            nav_to_state_data.pose = odom_data.pose;
        }
        else
        {
            nav_to_state_data.pose = pose_data.pose;
        }

        nav_to_state_data.pos.x = nav_to_state_data.pose.pose.position.x;
        nav_to_state_data.pos.y = nav_to_state_data.pose.pose.position.y;
        nav_to_state_data.pos.z = nav_to_state_data.pose.pose.position.z;

        tf::Quaternion quat;

        quat.setW(nav_to_state_data.pose.pose.orientation.w);
        quat.setX(nav_to_state_data.pose.pose.orientation.x);
        quat.setY(nav_to_state_data.pose.pose.orientation.y);
        quat.setZ(nav_to_state_data.pose.pose.orientation.z);

        double roll = 0, pitch = 0, yaw = 0;

        tf::Matrix3x3(quat).getRPY(roll, pitch, yaw);

        nav_to_state_data.pos.roll = roll * 180.0 / M_PI;
        nav_to_state_data.pos.pitch = pitch * 180.0 / M_PI;
        nav_to_state_data.pos.yaw = yaw * 180.0 / M_PI;

        nav_to_state_data.vel.vx = nav_to_state_data.twist.twist.linear.x;
        nav_to_state_data.vel.vyaw = nav_to_state_data.twist.twist.angular.z;

        // 导航策略消息循环
        static ros::Time current_time = ros::Time::now();

        if (ros::Time::now() >= current_time)
        {
            current_time = ros::Time::now();
        }

        twist_data.linear.x = 0;
        twist_data.angular.z = 0;

        if (mode == navigation_mode::NAVIGATION_MAP ||
            mode == navigation_mode::NAVIGATION_ODOM)
        {
            if (!odom_received ||
                !pose_received ||
                !obstacle_received ||
                !map_received)
            {
                if (current_time - cmd_received_time > sensor_msg_timeout_duration)
                {
                    path_follower_controller->reset_state();

                    state = navigation_state::ERROR;
                }
                else
                {
                    nav_to_state_data.state = NAV_STATE_RUNNING;
                    nav_to_state_pub.publish(nav_to_state_data);

                    loop_rate.sleep();

                    continue;
                }
            }
            else
            {
                state = path_follower_controller->loop((mode == navigation_mode::NAVIGATION_ODOM ? odom_data : pose_data),
                                                       odom_twist_data, obstacle_data, footprint_polygon, map_data);

                obstacle_state_data = path_follower_controller->get_obstacle_state();

                if (current_time - odom_data_last_received_time > sensor_msg_timeout_duration ||
                    current_time - pose_data_last_received_time > sensor_msg_timeout_duration ||
                    current_time - obstacle_data_last_received_time > sensor_msg_timeout_duration)
                {
                    path_follower_controller->reset_state();

                    if (request_from_simple_goal)
                    {
                        ROS_INFO("%s：切换为手动控制模式。", TAG);

                        set_cmd_vel_mode(true);

                        request_from_simple_goal = false;
                    }

                    state = navigation_state::ERROR;
                }
                else if (state == navigation_state::REACHED)
                {
                    path_follower_controller->reset_state();

                    if (request_from_simple_goal)
                    {
                        ROS_INFO("%s：切换为手动控制模式。", TAG);

                        set_cmd_vel_mode(true);

                        request_from_simple_goal = false;
                    }
                }
                else
                {
                    if (state == navigation_state::PROCESSING)
                    {
                        if ((button_required && button_data.data) ||
                            !button_required)
                        {
                            if (request_from_simple_goal)
                            {
                                ROS_INFO("%s：切换为自动控制模式。", TAG);

                                set_cmd_vel_mode(false);
                            }

                            if (button_required)
                            {
                                ros::Duration(2.0).sleep();
                            }

                            path_follower_controller->start_session();

                            button_required = false;
                        }
                    }

                    twist_data = path_follower_controller->get_current_twist();
                }
            }
        }
        else if (mode == navigation_mode::MOVE_MAP ||
                 mode == navigation_mode::MOVE_ODOM)
        {
            if (!odom_received ||
                !pose_received ||
                !obstacle_received ||
                !map_received)
            {
                if (current_time - cmd_received_time > sensor_msg_timeout_duration)
                {
                    mover_controller->reset_state();

                    state = navigation_state::ERROR;
                }
                else
                {
                    nav_to_state_data.state = NAV_STATE_RUNNING;
                    nav_to_state_pub.publish(nav_to_state_data);

                    loop_rate.sleep();

                    continue;
                }
            }
            else
            {
                state = mover_controller->loop((mode == navigation_mode::MOVE_ODOM ? odom_data : pose_data),
                                               odom_twist_data, obstacle_data);

                obstacle_state_data = mover_controller->get_obstacle_state();

                if (current_time - odom_data_last_received_time > sensor_msg_timeout_duration ||
                    current_time - pose_data_last_received_time > sensor_msg_timeout_duration ||
                    current_time - obstacle_data_last_received_time > sensor_msg_timeout_duration)
                {
                    mover_controller->reset_state();

                    if (request_from_simple_goal)
                    {
                        ROS_INFO("%s：切换为手动控制模式。", TAG);

                        set_cmd_vel_mode(true);

                        request_from_simple_goal = false;
                    }

                    state = navigation_state::ERROR;
                }
                else if (state == navigation_state::REACHED)
                {
                    mover_controller->reset_state();

                    if (request_from_simple_goal)
                    {
                        ROS_INFO("%s：切换为手动控制模式。", TAG);

                        set_cmd_vel_mode(true);

                        request_from_simple_goal = false;
                    }
                }
                else
                {
                    if (state == navigation_state::PROCESSING)
                    {
                        if ((button_required && button_data.data) ||
                            !button_required)
                        {
                            if (request_from_simple_goal)
                            {
                                ROS_INFO("%s：切换为自动控制模式。", TAG);

                                set_cmd_vel_mode(false);
                            }

                            if (button_required)
                            {
                                ros::Duration(2.0).sleep();
                            }

                            mover_controller->start_session();

                            button_required = false;
                        }
                    }

                    twist_data = mover_controller->get_current_twist();
                }
            }
        }

        // 0-3 对应 前后左右
        nav_to_state_data.obstacle[0] = obstacle_state_data == block_state::FORWARD;
        nav_to_state_data.obstacle[1] = obstacle_state_data == block_state::BACKWARD;
        nav_to_state_data.obstacle[2] = obstacle_state_data == block_state::LEFT;
        nav_to_state_data.obstacle[3] = obstacle_state_data == block_state::RIGHT;

        // 按状态发布消息
        switch (state)
        {
        case navigation_state::STRIGHTING:
        case navigation_state::TURNING:
        case navigation_state::RUNNING:
        case navigation_state::STRIGHTING_RECOVERY:
        case navigation_state::TURNING_RECOVERY:
        {
            nav_to_state_data.state = NAV_STATE_RUNNING;
            nav_to_state_pub.publish(nav_to_state_data);

            break;
        }
        case navigation_state::BLOCKED:
        {
            nav_to_state_data.state = NAV_STATE_BLOCKED;
            nav_to_state_pub.publish(nav_to_state_data);

            break;
        }
        case navigation_state::PAUSING:
        case navigation_state::PROCESSING:
        {
            nav_to_state_data.state = NAV_STATE_PAUSE;
            nav_to_state_pub.publish(nav_to_state_data);

            break;
        }
        case navigation_state::REACHED:
        {
            nav_to_state_data.state = NAV_STATE_REACHED;
            nav_to_state_pub.publish(nav_to_state_data);

            ROS_INFO("%s：已到达目标容差内，导航完成。", TAG);

            break;
        }
        case navigation_state::READY:
        {
            mode = navigation_mode::UNKNOW;

            nav_to_state_data.state = NAV_STATE_REACHED;
            nav_to_state_pub.publish(nav_to_state_data);

            break;
        }
        case navigation_state::ERROR:
        {
            nav_to_state_data.state = NAV_STATE_ERROR;
            nav_to_state_pub.publish(nav_to_state_data);

            ROS_ERROR("%s：数据异常或传感器失效，导航失败。", TAG);

            state = navigation_state::READY;
            mode = navigation_mode::UNKNOW;

            break;
        }
        }

        nav_to_state_data.cmd_twist.twist = twist_data;
        nav_to_state_data.cmd_vel.vx = twist_data.linear.x;
        nav_to_state_data.cmd_vel.vyaw = twist_data.angular.z;

        // 发布速度
        cmd_vel_pub.publish(twist_data);

#if NAV_DEBUG
        if (state == navigation_state::running ||
            state == navigation_state::strighting ||
            state == navigation_state::turning ||
            state == navigation_state::strighting_recovery ||
            state == navigation_state::turning_recovery)
        {
            ROS_WARN("%s：vx：%lf，vyaw：%lf", TAG,
                     twist_data.linear.x,
                     twist_data.angular.z);
        }
#endif

        // 循环频率控制
        loop_rate.sleep();
    }

    // 释放对象
    if (mover_controller != NULL)
    {
        mover_controller.reset();
    }

    if (path_follower_controller != NULL)
    {
        path_follower_controller.reset();
    }

    return 0;
}
