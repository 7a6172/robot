#include "navigation/navigation/navigation_handler.h"

#include <angles/angles.h>
#include <tf2/LinearMath/Quaternion.h>
#include <tf2/LinearMath/Matrix3x3.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.hpp>
#include <iostream>
#include <tuple>
#include "navigation/utils/math_utils.h"
#include "openmover/topic_utils.hpp"

#define NODE_NAME "navigation_handler"
#define TAG "导航控制器"

// 代价地图与全局规划器名称（与 ROS 1 保持一致）
#define COSTMAP_NAME "global_costmap"
#define COSTMAP_NAME_STATIC "global_costmap_static"
#define PLANNER_NAME "global_planner"
#define PLANNER_NAME_STATIC "global_planner_static"

using namespace std;

// GetPlan 服务计时基准（替代 ROS 1 global_planner_handler 的 time_ 成员）
static rclcpp::Time planner_service_time = rclcpp::Time(0, 0, RCL_ROS_TIME);

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
void set_kinematic_params(openmover_msgs::srv::NavToRequest::Request &req)
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
void set_tolerance_params(openmover_msgs::srv::NavToRequest::Request &req)
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

// 创建计划（移动模式：相对距离/角度）
void make_plan(openmover_msgs::srv::NavToRequest::Response &res, float nav_to_distance, float nav_to_angle)
{
    // 尝试创建计划
    if (mover_controller->make_plan(mode == navigation_mode::MOVE_ODOM ? odom_data : pose_data,
                                    nav_to_distance, nav_to_angle, nav_to_request_data.ignore_obstacle, false))
    {
        RCLCPP_INFO(node->get_logger(), "%s：速度规划完成，准备开始运行。", TAG);

        // 清除状态
        openmover_msgs::msg::NavToState nav_to_state_data;

        for (int i = 0; i < 3; i++)
        {
            nav_to_state_data.header.stamp = node->now();
            nav_to_state_data.pose = pose_data.pose;
            nav_to_state_data.twist = odom_twist_data.twist;
            nav_to_state_data.state = NAV_STATE_RUNNING;

            nav_to_state_pub->publish(nav_to_state_data);

            rclcpp::sleep_for(std::chrono::duration_cast<std::chrono::nanoseconds>(
                std::chrono::duration<double>(1.0 / control_freq)));
        }
    }
    else
    {
        RCLCPP_ERROR(node->get_logger(), "%s：速度规划失败。", TAG);

        // 创建失败
        res.result = CMD_RESPONSE_ERROR;
    }
}

vector<geometry_msgs::msg::PoseStamped> make_global_plan(openmover_msgs::srv::NavToRequest::Request &req,
                                                         geometry_msgs::msg::Pose from, geometry_msgs::msg::Pose to)
{
    vector<geometry_msgs::msg::PoseStamped> ret;

    // 清空路径
    ret.clear();

    // 检查是否需要规划
    bool global_plan_flag = (mode == navigation_mode::NAVIGATION_MAP &&
                             req.use_global_planner &&
                             use_global_planner &&
                             path_follower::distance(from, to) > max(0.1f, xy_tolerance));

    replan_flag = always_replan & global_plan_flag;

    // 若需要规划，规划全局路径
    if (global_plan_flag)
    {
        geometry_msgs::msg::PoseStamped start;
        geometry_msgs::msg::PoseStamped goal;

        start.header.frame_id = LOCALIZATION_MAP;
        start.header.stamp = node->now();
        start.pose.orientation = from.orientation;
        start.pose.position = from.position;

        goal.header.frame_id = LOCALIZATION_MAP;
        goal.header.stamp = node->now();
        goal.pose.orientation = to.orientation;
        goal.pose.position = to.position;

        // 尝试若干次，直到规划成功
        tuple<bool, vector<geometry_msgs::msg::PoseStamped>, vector<geometry_msgs::msg::PoseStamped>> plan_result =
            make_tuple(false, vector<geometry_msgs::msg::PoseStamped>(), vector<geometry_msgs::msg::PoseStamped>());
        int try_count = 0;

        while (!get<0>(plan_result) &&
               try_count < max_global_plan_try_count)
        {
            if (try_count >= 1)
            {
                RCLCPP_WARN(node->get_logger(), "%s：全局路径规划失败，正在进行第 %d 次重试。", TAG, try_count);
            }

            // 调用规划器
            plan_result = global_planner_static_instance->plan(start, goal,
                                                               map_data,
                                                               planner_min_dist_to_obs, true, 1, false, 1.0, 8, map_occupied_threshold);

            // 开始计数
            try_count++;

            // 防止服务阻塞
            rclcpp::sleep_for(std::chrono::duration_cast<std::chrono::nanoseconds>(
                std::chrono::duration<double>(SERVICE_RETRY_DURATION)));
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
        geometry_msgs::msg::PoseStamped goal;

        goal.header.frame_id = (mode == navigation_mode::NAVIGATION_ODOM ? LOCALIZATION_ODOM : LOCALIZATION_MAP);
        goal.header.stamp = node->now();
        goal.pose = to;

        // 插补直线路径（保持与 ROS 1 原实现相同的表达式）
        double distance = sqrt(pow(goal.pose.position.x - from.position.x, 2) +
                               sqrt(pow(goal.pose.position.y - from.position.x, 2)));

        int step = (int)(distance / 0.01);

        if (step > 5)
        {
            RCLCPP_INFO(node->get_logger(), "%s：满足直线插补条件，进行直线插补。", TAG);

            nav_msgs::msg::Path linear_path;
            geometry_msgs::msg::PoseStamped start_pose;

            start_pose.header.frame_id = (mode == navigation_mode::NAVIGATION_ODOM ? LOCALIZATION_ODOM : LOCALIZATION_MAP);
            start_pose.header.stamp = node->now();
            start_pose.pose = from;

            ret.push_back(start_pose);
            linear_path.poses.push_back(start_pose);

            linear_path.header.frame_id = (mode == navigation_mode::NAVIGATION_ODOM ? LOCALIZATION_ODOM : LOCALIZATION_MAP);
            linear_path.header.stamp = node->now();

            double delta_x = (goal.pose.position.x - from.position.x) / step;
            double delta_y = (goal.pose.position.y - from.position.y) / step;

            for (int i = 5; i < step - 1; i++)
            {
                geometry_msgs::msg::PoseStamped traj_pose;

                traj_pose.header.frame_id = (mode == navigation_mode::NAVIGATION_ODOM ? LOCALIZATION_ODOM : LOCALIZATION_MAP);
                traj_pose.header.stamp = node->now();
                traj_pose.pose.position.x = from.position.x + (i + 1) * delta_x;
                traj_pose.pose.position.y = from.position.y + (i + 1) * delta_y;
                traj_pose.pose.orientation = quaternion_msg_from_yaw(0);

                linear_path.poses.push_back(traj_pose);
                ret.push_back(traj_pose);
            }

            linear_path.poses.push_back(goal);

            linear_path_pub->publish(linear_path);
        }

        ret.push_back(goal);
    }

    return ret;
}

void make_plan(openmover_msgs::srv::NavToRequest::Response &res, openmover_msgs::srv::NavToRequest::Request &req)
{
    // 尝试创建计划
    if (mode == navigation_mode::NAVIGATION_MAP || mode == navigation_mode::NAVIGATION_ODOM)
    {
        if (req.use_planned_path &&
            req.planned_path.size() > 0)
        {
            RCLCPP_INFO(node->get_logger(), "%s：使用先验路径。", TAG);
        }
        else
        {
            RCLCPP_INFO(node->get_logger(), "%s：不使用先验路径，进行实时全局路径规划。", TAG);

            req.planned_path = make_global_plan(req, pose_data.pose.pose, req.pose);
        }

        if (path_follower_controller->make_plan(mode == navigation_mode::NAVIGATION_ODOM ? odom_data : pose_data,
                                                req.planned_path, req.ignore_obstacle, replan_flag))
        {
            RCLCPP_INFO(node->get_logger(), "%s：局部路径规划完成，准备开始运行。", TAG);

            // 清除状态
            openmover_msgs::msg::NavToState nav_to_state_data;

            for (int i = 0; i < 3; i++)
            {
                nav_to_state_data.header.stamp = node->now();
                nav_to_state_data.pose = (mode == navigation_mode::NAVIGATION_ODOM ? odom_data.pose : pose_data.pose);
                nav_to_state_data.twist = odom_twist_data.twist;
                nav_to_state_data.state = NAV_STATE_RUNNING;

                nav_to_state_pub->publish(nav_to_state_data);

                rclcpp::sleep_for(std::chrono::duration_cast<std::chrono::nanoseconds>(
                    std::chrono::duration<double>(1.0 / control_freq)));
            }
        }
        else
        {
            RCLCPP_ERROR(node->get_logger(), "%s：局部路径规划失败。", TAG);

            // 创建失败
            res.result = CMD_RESPONSE_ERROR;
        }
    }
}

// 设置速度控制模式
bool set_cmd_vel_mode(bool manual)
{
    bool ret = false;

    auto cmd_vel_mode = std::make_shared<openmover_msgs::srv::CmdVelModeRequest::Request>();

    cmd_vel_mode->manual = manual;

    // ROS 1 的 waitForExistence() 无限等待，这里保持一致
    if (cmd_vel_mode_client->wait_for_service())
    {
        auto future = cmd_vel_mode_client->async_send_request(cmd_vel_mode);

        if (rclcpp::spin_until_future_complete(client_node, future) == rclcpp::FutureReturnCode::SUCCESS)
        {
            ret = future.get()->result == CMD_RESPONSE_OK;
        }
    }

    return ret;
}

// 回调函数
// 全局位姿回调函数
void pose_callback(const geometry_msgs::msg::PoseWithCovarianceStamped::SharedPtr msg)
{
    pose_data = *msg;

    if (node->now() >= pose_data_last_received_time)
    {
        pose_data_last_received_time = node->now();
    }

    pose_received = true;
}

// 里程计回调函数
void odom_callback(const geometry_msgs::msg::PoseWithCovarianceStamped::SharedPtr msg)
{
    odom_data = *msg;

    if (node->now() >= odom_data_last_received_time)
    {
        odom_data_last_received_time = node->now();
    }

    odom_received = true;
}

// 里程计速度回调函数
void odom_twist_callback(const geometry_msgs::msg::TwistWithCovarianceStamped::SharedPtr msg)
{
    odom_twist_data = *msg;

    if (node->now() >= odom_data_last_received_time)
    {
        odom_data_last_received_time = node->now();
    }

    odom_twist_received = true;
}

// 障碍物回调函数
void obstacle_callback(const openmover_msgs::msg::Obstacle::SharedPtr msg)
{
    obstacle_data = *msg;

    if (node->now() >= obstacle_data_last_received_time)
    {
        obstacle_data_last_received_time = node->now();
    }

    obstacle_received = true;
}

// nav_to_request 逻辑（服务回调、simple_goal 回调共用）
void nav_to_request_logic(openmover_msgs::srv::NavToRequest::Request &req,
                          openmover_msgs::srv::NavToRequest::Response &res)
{
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

            RCLCPP_INFO(node->get_logger(), "%s：自主导航任务创建成功，开始规划速度。", TAG);

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

            cmd_received_time = node->now();
        }
        else if ((mode == navigation_mode::MOVE_ODOM && odom_received) ||
                 (mode == navigation_mode::MOVE_MAP && pose_received))
        {
            // 接受计划
            res.result = CMD_RESPONSE_OK;

            RCLCPP_INFO(node->get_logger(), "%s：移动任务创建成功，开始规划速度。", TAG);

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

            cmd_received_time = node->now();
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

            openmover_msgs::msg::NavToState nav_to_state_data;
            nav_to_state_data.header.stamp = node->now();
            nav_to_state_data.state = NAV_STATE_REACHED;

            nav_to_state_pub->publish(nav_to_state_data);
        }
        else if (mode == navigation_mode::MOVE_MAP ||
                 mode == navigation_mode::MOVE_ODOM)
        {
            mover_controller->reset_state();

            openmover_msgs::msg::NavToState nav_to_state_data;
            nav_to_state_data.header.stamp = node->now();
            nav_to_state_data.state = NAV_STATE_REACHED;

            nav_to_state_pub->publish(nav_to_state_data);
        }

        // 手动控制
        if (request_from_simple_goal)
        {
            RCLCPP_INFO(node->get_logger(), "%s：切换为手动控制模式。", TAG);

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
}

// nav_to_request 服务回调函数
void nav_to_request_callback(const std::shared_ptr<openmover_msgs::srv::NavToRequest::Request> request,
                             std::shared_ptr<openmover_msgs::srv::NavToRequest::Response> response)
{
    nav_to_request_logic(*request, *response);
}

// nav_to_simple_request 服务回调函数
void nav_to_simple_request_callback(const std::shared_ptr<openmover_msgs::srv::NavToSimpleRequest::Request> request,
                                    std::shared_ptr<openmover_msgs::srv::NavToSimpleRequest::Response> response)
{
    openmover_msgs::srv::NavToRequest::Request req;
    openmover_msgs::srv::NavToRequest::Response res;

    req.cmd = request->request.cmd;
    req.ignore_obstacle = request->request.ignore_obstacle;
    req.localization_sources = request->request.localization_sources;
    req.use_global_planner = request->request.use_global_planner;
    req.use_planned_path = request->request.use_planned_path;

    req.pose.position.x = request->request.x;
    req.pose.position.y = request->request.y;
    req.pose.orientation = quaternion_msg_from_yaw(angles::from_degrees(request->request.yaw));

    req.twist.linear.x = request->request.vxmax;
    req.twist.angular.z = angles::from_degrees(request->request.vyawmax);

    req.xy_tolerance = request->request.xy_tolerance;
    req.yaw_tolerance = request->request.yaw_tolerance;

    if (!req.use_planned_path || (request->request.planned_path_x.size() == request->request.planned_path_y.size() &&
                                  request->request.planned_path_x.size() == request->request.planned_path_yaw.size()))
    {
        if (req.use_planned_path)
        {
            req.planned_path.clear();

            for (size_t i = 0; i < request->request.planned_path_x.size(); i++)
            {
                geometry_msgs::msg::PoseStamped pose;

                pose.header.frame_id = LOCALIZATION_MAP;
                pose.header.stamp = node->now();
                pose.pose.position.x = request->request.planned_path_x[i];
                pose.pose.position.y = request->request.planned_path_y[i];
                pose.pose.orientation = quaternion_msg_from_yaw(angles::from_degrees(request->request.planned_path_yaw[i]));

                req.planned_path.push_back(pose);
            }
        }

        // 标记请求来自简易导航目标
        request_from_simple_goal = true;

        req.button_required = request->request.button_required;

        nav_to_request_logic(req, res);

        response->result = res.result;
    }
    else
    {
        response->result = CMD_RESPONSE_ERROR;
    }
}

// simple_goal 回调函数
void simple_goal_callback(const geometry_msgs::msg::PoseStamped::SharedPtr msg)
{
    RCLCPP_INFO(node->get_logger(), "%s：接收到简易导航目标请求。", TAG);

    // 简单目标服务，内联调用服务
    openmover_msgs::srv::NavToRequest::Request request;
    openmover_msgs::srv::NavToRequest::Response response;

    request.cmd = NAV_CMD_NAV_TO;
    request.localization_sources = string(LOCALIZATION_ODOM) + string(LOCALIZATION_MAP);
    request.pose = msg->pose;
    request.twist.linear.x = max_x_vel;
    request.twist.angular.z = max_yaw_vel;
    request.use_global_planner = true;
    request.ignore_obstacle = false;

    // 标记请求来自简易导航目标
    request_from_simple_goal = true;

    nav_to_request_logic(request, response);

    if (response.result == CMD_RESPONSE_OK)
    {
        RCLCPP_INFO(node->get_logger(), "%s：简易导航目标已传送。", TAG);
    }
    else
    {
        RCLCPP_WARN(node->get_logger(), "%s：当前无法接收简易导航目标。", TAG);
    }
}

void button_callback(const std_msgs::msg::Bool::SharedPtr msg)
{
    button_data.data = msg->data;

    button_received = true;
}

void map_callback(const nav_msgs::msg::OccupancyGrid::SharedPtr msg)
{
    map_data = *msg;

    map_received = true;
}

void emergency_callback(const std_msgs::msg::Bool::SharedPtr msg)
{
    emergency_data = *msg;

    emergency_data_received = true;
}

// GetPlan 服务回调（替代 ROS 1 的 global_planner_handler 节点）
void make_plan_service_callback(const std::shared_ptr<nav_msgs::srv::GetPlan::Request> request,
                                std::shared_ptr<nav_msgs::srv::GetPlan::Response> response)
{
    RCLCPP_INFO(node->get_logger(), "%s：开始规划全局路径。", TAG);

    geometry_msgs::msg::PoseStamped start = request->start;
    geometry_msgs::msg::PoseStamped goal = request->goal;

    start.header.frame_id = LOCALIZATION_MAP;
    goal.header.frame_id = LOCALIZATION_MAP;

    // 判断 costmap 是否可用
    while (!lcr_global->isCurrent())
    {
        if (!rclcpp::ok())
        {
            return;
        }

        rclcpp::sleep_for(std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::duration<double>(COST_MAP_WAIT_UPDATE_DURATION)));
    }

    // 判断是否已等待代价地图
    if (node->now() - planner_service_time < rclcpp::Duration::from_seconds(COST_MAP_WAIT_DURATION))
    {
        rclcpp::sleep_for(std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::duration<double>(COST_MAP_WAIT_DURATION)));
    }

    vector<geometry_msgs::msg::PoseStamped> path;
    vector<geometry_msgs::msg::PoseStamped> polyline_path;

    bool success = global_planner_instance->make_plan(start, goal, (double)request->tolerance,
                                                      path, polyline_path,
                                                      global_planner_instance->min_dist_to_obs_default_,
                                                      true, 1, false, 2.0, 8,
                                                      global_planner_instance->occupied_threshold_default_);

    // nav_msgs::srv::GetPlan 的响应只有 plan 字段，规划失败时返回空路径
    if (success)
    {
        RCLCPP_INFO(node->get_logger(), "%s：全局路径规划成功。", TAG);

        response->plan.header.stamp = node->now();
        response->plan.header.frame_id = LOCALIZATION_MAP;
        response->plan.poses = path;
    }
    else
    {
        RCLCPP_WARN(node->get_logger(), "%s：全局路径规划失败。", TAG);

        response->plan.header.stamp = node->now();
        response->plan.header.frame_id = LOCALIZATION_MAP;
        response->plan.poses.clear();
    }
}

int main(int argc, char **argv)
{
    // 初始化 ROS 2 节点
    rclcpp::init(argc, argv);

    // 设置控制台本地化，以显示中文
    setlocale(LC_CTYPE, "zh_CN.utf8");

    // 打印调试信息
    RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "%s：节点已启动。", TAG);

    // 主节点与服务客户端节点（客户端单独使用一个节点，避免主执行器阻塞）
    node = rclcpp::Node::make_shared(NODE_NAME);
    client_node = rclcpp::Node::make_shared(string(NODE_NAME) + "_client");

    executor = std::make_unique<rclcpp::executors::SingleThreadedExecutor>();
    executor->add_node(node);

    // 全局规划器
    RCLCPP_INFO(node->get_logger(), "%s：正在初始化全局规划器...", TAG);

    lcr_global = make_shared<nav2_costmap_2d::Costmap2DROS>(COSTMAP_NAME, false);
    lcr_global_static = make_shared<nav2_costmap_2d::Costmap2DROS>(COSTMAP_NAME_STATIC, false);

    // 配置代价地图参数（静态层回退到全局 map_topic 参数；代价地图节点位于自身命名空间内，故使用绝对话题名）
    lcr_global->set_parameter(rclcpp::Parameter("map_topic", string("/openmover/mapping/map")));
    lcr_global_static->set_parameter(rclcpp::Parameter("map_topic", string("/openmover/mapping/map")));
    lcr_global->set_parameter(rclcpp::Parameter("robot_base_frame", string(LOCALIZATION_BASE_LINK)));
    lcr_global_static->set_parameter(rclcpp::Parameter("robot_base_frame", string(LOCALIZATION_BASE_LINK)));

    lcr_global->configure();
    lcr_global_static->configure();

    // 每个代价地图由专属线程驱动（与 nav2 planner_server 的用法一致）
    global_costmap_thread = make_unique<nav2_util::NodeThread>(lcr_global);
    global_costmap_static_thread = make_unique<nav2_util::NodeThread>(lcr_global_static);

    lcr_global->activate();
    lcr_global_static->activate();

    planner_service_time = node->now();

    global_planner_instance = make_shared<planner_with_costmap>(PLANNER_NAME, lcr_global.get(), node->now(), node.get());
    global_planner_static_instance = make_shared<planner_with_costmap>(PLANNER_NAME_STATIC, lcr_global_static.get(), node->now(), node.get());

    RCLCPP_INFO(node->get_logger(), "%s：全局规划器初始化成功。", TAG);

    // 获取参数（默认值与 ROS 1 保持一致）
    // 通用部分
    control_freq = node->declare_parameter("navigation.control_freq", 50.0);

    max_x_vel = node->declare_parameter("navigation.max_x_vel", 0.8);
    min_x_vel = node->declare_parameter("navigation.min_x_vel", 0.02);
    max_x_acc = node->declare_parameter("navigation.max_x_acc", 0.6);

    max_yaw_vel = node->declare_parameter("navigation.max_yaw_vel", 0.3);
    min_yaw_vel = node->declare_parameter("navigation.min_yaw_vel", 0.05);
    max_yaw_acc = node->declare_parameter("navigation.max_yaw_acc", 0.3);

    velocity_dec_line_offset_time = node->declare_parameter("navigation.velocity_dec_line_offset_time", 0.2);
    velocity_dec_angle_offset_time = node->declare_parameter("navigation.velocity_dec_angle_offset_time", 0.2);

    strighting_stop_distance = node->declare_parameter("navigation.strighting_stop_distance", 1.0);
    turning_stop_distance = node->declare_parameter("navigation.turning_stop_distance", 0.1);
    ignore_obstacle_dist = node->declare_parameter("navigation.ignore_obstacle_dist", 0.08);

    obstacle_acc_ratio = node->declare_parameter("navigation.obstacle_acc_ratio", 1.5);
    collision_vel_dec_ratio = node->declare_parameter("navigation.collision_vel_dec_ratio", 1.2);
    collision_trajectory_sampling_ratio = node->declare_parameter("navigation.collision_trajectory_sampling_ratio", 1);
    collision_plan_try_count = node->declare_parameter("navigation.collision_plan_try_count", 3);
    collision_path_sampling_ratio = node->declare_parameter("navigation.collision_path_sampling_ratio", 3);
    collision_path_dist_error_tolerance = node->declare_parameter("navigation.collision_path_dist_error_tolerance", 0.2);
    collision_path_angle_error_tolerance = node->declare_parameter("navigation.collision_path_angle_error_tolerance", 0.087);
    collision_obstacle_detection_area_padding_ratio = node->declare_parameter("navigation.collision_obstacle_detection_area_padding_ratio", 1.2);
    collision_narrow_section_padding = node->declare_parameter("navigation.collision_narrow_section_padding", 20);

    strighting_tolerance = node->declare_parameter("navigation.strighting_tolerance", 0.01);
    turning_tolerance = node->declare_parameter("navigation.turning_tolerance", 0.02);

    sensor_msg_timeout = node->declare_parameter("navigation.sensor_msg_timeout", 1.0);

    // 自主导航部分
    map_free_threshold = node->declare_parameter("navigation.map_free_threshold", 30);
    map_occupied_threshold = node->declare_parameter("navigation.map_occupied_threshold", 55);

    use_global_planner = node->declare_parameter("navigation.use_global_planner", false);
    always_replan = node->declare_parameter("navigation.always_replan", true);

    planner_min_dist_to_obs = node->declare_parameter("navigation.planner_min_dist_to_obs", 0.25);

    allow_reverse_drive = node->declare_parameter("navigation.allow_reverse_drive", false);
    use_advanced_evaluation = node->declare_parameter("navigation.use_advanced_evaluation", true);
    use_kinematic_limits = node->declare_parameter("navigation.use_kinematic_limits", true);
    use_find_mode_follower = node->declare_parameter("navigation.use_find_mode_follower", true);

    find_mode_x_vel = node->declare_parameter("navigation.find_mode_x_vel", 0.2);
    find_mode_yaw_vel = node->declare_parameter("navigation.find_mode_yaw_vel", 0.3);
    find_mode_radius = node->declare_parameter("navigation.find_mode_radius", 2.0);
    find_mode_min_dist_timeout = node->declare_parameter("navigation.find_mode_min_dist_timeout", 1.0);

    enable_near_angle_correct = node->declare_parameter("navigation.enable_near_angle_correct", true);

    angle_diff_to_forward = node->declare_parameter("navigation.angle_diff_to_forward", 0.1);
    angle_diff_to_rotate = node->declare_parameter("navigation.angle_diff_to_rotate", 1.2);

    xy_tolerance = node->declare_parameter("navigation.xy_tolerance", 0.01);
    yaw_tolerance = node->declare_parameter("navigation.yaw_tolerance", 0.01);

    chassis_radius = node->declare_parameter("navigation.chassis_radius", 0.4);

    sim_time = node->declare_parameter("navigation.sim_time", 2.0);
    find_mode_sim_time = node->declare_parameter("navigation.find_mode_sim_time", 1.0);
    sim_vx_space_size = node->declare_parameter("navigation.sim_vx_space_size", 10);
    sim_vyaw_space_size = node->declare_parameter("navigation.sim_vyaw_space_size", 20);
    trajectory_sim_step = node->declare_parameter("navigation.trajectory_sim_step", 20);
    follow_point_weight = node->declare_parameter("navigation.follow_point_weight", 1.0);
    follow_path_weight = node->declare_parameter("navigation.follow_path_weight", 1.0);

    max_global_plan_try_count = node->declare_parameter("navigation.max_global_plan_try_count", 2);

    // 足迹部分（ROS 2 参数不支持嵌套数组，使用扁平数组 [x1,y1,x2,y2,...]）
    std::vector<double> footprint_param;
    footprint_param = node->declare_parameter("footprint", std::vector<double>());

    for (size_t i = 0; i + 1 < footprint_param.size(); i += 2)
    {
        geometry_msgs::msg::Point32 point;

        point.x = footprint_param[i];
        point.y = footprint_param[i + 1];

        footprint_polygon.points.push_back(point);
    }

    // pose 订阅器
    auto pose_sub = node->create_subscription<geometry_msgs::msg::PoseWithCovarianceStamped>(
        "openmover/localization/pose", 2, pose_callback);
    // odom 订阅器
    auto odom_sub = node->create_subscription<geometry_msgs::msg::PoseWithCovarianceStamped>(
        "openmover/localization/odom", 2, odom_callback);
    // odom_twist 订阅器
    auto odom_twist_sub = node->create_subscription<geometry_msgs::msg::TwistWithCovarianceStamped>(
        "openmover/localization/twist", 2, odom_twist_callback);
    // obstacle 订阅器
    auto obstacle_sub = node->create_subscription<openmover_msgs::msg::Obstacle>(
        "openmover/navigation/obstacle", 1, obstacle_callback);
    // simple_goal 订阅器
    auto simple_goal_sub = node->create_subscription<geometry_msgs::msg::PoseStamped>(
        "openmover/navigation/simple_goal", 2, simple_goal_callback);
    // button 订阅器
    auto button_sub = node->create_subscription<std_msgs::msg::Bool>(
        "openmover/hardware/button", rclcpp::QoS(1).reliable().transient_local(), button_callback);
    // map 订阅器
    auto map_sub = node->create_subscription<nav_msgs::msg::OccupancyGrid>(
        "openmover/mapping/map", rclcpp::QoS(1).reliable().transient_local(), map_callback);
    // emergency 订阅器
    auto emergency_sub = node->create_subscription<std_msgs::msg::Bool>(
        "openmover/hardware/emergency", rclcpp::QoS(1).reliable().transient_local(), emergency_callback);
    // nav_to_request 服务
    auto nav_to_server = node->create_service<openmover_msgs::srv::NavToRequest>(
        "openmover/navigation/request", nav_to_request_callback);
    // nav_to_simple_request 服务
    auto nav_to_simple_server = node->create_service<openmover_msgs::srv::NavToSimpleRequest>(
        "openmover/navigation/simple_request", nav_to_simple_request_callback);
    // 全局规划服务（替代 ROS 1 的 global_planner_handler 节点）
    auto make_plan_srv = node->create_service<nav_msgs::srv::GetPlan>(
        "openmover/navigation/global_planner/make_plan", make_plan_service_callback);

    // cmd_vel 话题发布器
    auto cmd_vel_pub = node->create_publisher<geometry_msgs::msg::Twist>("openmover/control/cmd_vel", 1);
    // nav_to_state 话题发布器（ROS 1 为 latched，使用 transient_local）
    nav_to_state_pub = node->create_publisher<openmover_msgs::msg::NavToState>(
        "openmover/navigation/state", rclcpp::QoS(1).reliable().transient_local());
    // 插补发布器
    linear_path_pub = node->create_publisher<nav_msgs::msg::Path>("openmover/navigation/linear_path", 1);
    // 接管速度服务客户端（挂在独立节点上，避免阻塞主执行器）
    cmd_vel_mode_client = client_node->create_client<openmover_msgs::srv::CmdVelModeRequest>(
        "openmover/control/cmd_vel_mode/request");

    // 定义传感器数据超时周期
    rclcpp::Duration sensor_msg_timeout_duration = rclcpp::Duration::from_seconds(sensor_msg_timeout);

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
                                                                           planner_min_dist_to_obs,
                                                                           node.get()));

    try
    {
        auto grid = openmover::wait_for_message<nav_msgs::msg::OccupancyGrid>(
            node.get(), "openmover/mapping/map", rclcpp::QoS(1).reliable().transient_local(), std::chrono::seconds(60));

        if (grid != nullptr)
        {
            map_data = *grid;

            map_received = true;
        }
    }
    catch (...)
    {
        cout << "could not get global map." << endl;
    }

    // 定义节点循环频率控制器
    rclcpp::Rate loop_rate(control_freq);

    while (rclcpp::ok())
    {
        // 处理回调
        executor->spin_some();

        // 初始化数据
        nav_to_state_data.header.stamp = node->now();
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

        tf2::Quaternion quat;

        tf2::fromMsg(nav_to_state_data.pose.pose.orientation, quat);

        double roll = 0, pitch = 0, yaw = 0;

        tf2::Matrix3x3(quat).getRPY(roll, pitch, yaw);

        nav_to_state_data.pos.roll = roll * 180.0 / M_PI;
        nav_to_state_data.pos.pitch = pitch * 180.0 / M_PI;
        nav_to_state_data.pos.yaw = yaw * 180.0 / M_PI;

        nav_to_state_data.vel.vx = nav_to_state_data.twist.twist.linear.x;
        nav_to_state_data.vel.vyaw = nav_to_state_data.twist.twist.angular.z;

        // 导航策略消息循环
        static rclcpp::Time current_time = node->now();

        if (node->now() >= current_time)
        {
            current_time = node->now();
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
                    nav_to_state_pub->publish(nav_to_state_data);

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
                        RCLCPP_INFO(node->get_logger(), "%s：切换为手动控制模式。", TAG);

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
                        RCLCPP_INFO(node->get_logger(), "%s：切换为手动控制模式。", TAG);

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
                                RCLCPP_INFO(node->get_logger(), "%s：切换为自动控制模式。", TAG);

                                set_cmd_vel_mode(false);
                            }

                            if (button_required)
                            {
                                rclcpp::sleep_for(std::chrono::seconds(2));
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
                    nav_to_state_pub->publish(nav_to_state_data);

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
                        RCLCPP_INFO(node->get_logger(), "%s：切换为手动控制模式。", TAG);

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
                        RCLCPP_INFO(node->get_logger(), "%s：切换为手动控制模式。", TAG);

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
                                RCLCPP_INFO(node->get_logger(), "%s：切换为自动控制模式。", TAG);

                                set_cmd_vel_mode(false);
                            }

                            if (button_required)
                            {
                                rclcpp::sleep_for(std::chrono::seconds(2));
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
            nav_to_state_pub->publish(nav_to_state_data);

            break;
        }
        case navigation_state::BLOCKED:
        {
            nav_to_state_data.state = NAV_STATE_BLOCKED;
            nav_to_state_pub->publish(nav_to_state_data);

            break;
        }
        case navigation_state::PAUSING:
        case navigation_state::PROCESSING:
        {
            nav_to_state_data.state = NAV_STATE_PAUSE;
            nav_to_state_pub->publish(nav_to_state_data);

            break;
        }
        case navigation_state::REACHED:
        {
            nav_to_state_data.state = NAV_STATE_REACHED;
            nav_to_state_pub->publish(nav_to_state_data);

            RCLCPP_INFO(node->get_logger(), "%s：已到达目标容差内，导航完成。", TAG);

            break;
        }
        case navigation_state::READY:
        {
            mode = navigation_mode::UNKNOW;

            nav_to_state_data.state = NAV_STATE_REACHED;
            nav_to_state_pub->publish(nav_to_state_data);

            break;
        }
        case navigation_state::ERROR:
        {
            nav_to_state_data.state = NAV_STATE_ERROR;
            nav_to_state_pub->publish(nav_to_state_data);

            RCLCPP_ERROR(node->get_logger(), "%s：数据异常或传感器失效，导航失败。", TAG);

            state = navigation_state::READY;
            mode = navigation_mode::UNKNOW;

            break;
        }
        }

        nav_to_state_data.cmd_twist.twist = twist_data;
        nav_to_state_data.cmd_vel.vx = twist_data.linear.x;
        nav_to_state_data.cmd_vel.vyaw = twist_data.angular.z;

        // 发布速度
        cmd_vel_pub->publish(twist_data);

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

    global_planner_instance.reset();
    global_planner_static_instance.reset();

    // 停止代价地图及其专属线程
    lcr_global->deactivate();
    lcr_global_static->deactivate();
    global_costmap_thread.reset();
    global_costmap_static_thread.reset();
    lcr_global.reset();
    lcr_global_static.reset();

    executor->remove_node(node);
    executor.reset();

    rclcpp::shutdown();

    return 0;
}
