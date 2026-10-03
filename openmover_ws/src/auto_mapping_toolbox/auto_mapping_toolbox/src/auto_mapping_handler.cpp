#include <rclcpp/rclcpp.hpp>
#include <geometry_msgs/msg/twist.hpp>
#include <geometry_msgs/msg/twist_with_covariance_stamped.hpp>
#include <geometry_msgs/msg/pose_with_covariance_stamped.hpp>
#include <tf2_ros/transform_broadcaster.h>
#include <nav2_util/node_thread.hpp>
#include <tf2_ros/buffer.h>
#include <tf2_ros/transform_listener.hpp>
#include <nav_msgs/msg/odometry.hpp>
#include <math.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <termios.h>
#include <angles/angles/angles.h>
#include "common/common_state_code.h"
#include "localization/localization_sources.h"
#include <utils/nav_functions.h>
#include <utils/auto_mapping/global_exploration.h>
#include <utils/auto_mapping/local_exploration.h>
#include <utils/auto_mapping/rrt_common.h>
#include <utils/auto_mapping/tsp_optimization.h>
#include <utils/auto_mapping/collision_prediction.h>
#include "utils/global_planner/planner_with_costmap.h"
#include <navigation/navigation_state_code.h>
#include <auto_mapping_toolbox_msgs/srv/auto_mapping_request.hpp>
#include <auto_mapping_toolbox_msgs/msg/auto_mapping_state.hpp>
#include <utils/auto_mapping_state_code.h>

#define NODE_NAME "auto_mapping_handler"
#define TAG "自动建图系统"

using namespace std;
using namespace global_exploration;
using namespace local_exploration;
using namespace tsp_optimization;
using namespace collision_prediction;

rclcpp::Node::SharedPtr node;
shared_ptr<nav2_costmap_2d::Costmap2DROS> lcr_global;
unique_ptr<nav2_util::NodeThread> global_costmap_thread;
unique_ptr<tf2_ros::Buffer> tf_buffer;
unique_ptr<tf2_ros::TransformListener> tf_listener;

unique_ptr<global_explorer> global_explorer_instance;
unique_ptr<local_explorer> local_explorer_instance;
unique_ptr<tsp_solver> tsp_solver_instance;
unique_ptr<nav_functions> nav_functions_instance;
unique_ptr<collision_predictor> collision_predictor_instance;
shared_ptr<planner_with_costmap> global_planner_instance;

mutex mutex_data;

float max_x_vel, max_yaw_vel;

int map_free_threshold, map_occupied_threshold;

bool share_common_distance_table;
bool enable_collision_precheck;
bool enable_waypoint_backtracking = true;
float polyline_path_max_length;
float global_min_expand_dist, global_max_expand_dist, local_min_expand_dist, local_max_expand_dist;
float exploration_min_dist_to_obs;
float local_rrt_coverage_check_density;
float global_frontier_points_min_dist, local_frontier_points_min_dist;
float global_sensing_radius, local_sensing_radius;
int global_sampling_timeout_secs, local_sampling_timeout_secs;
float local_prefer_near_frontier_point_dist_threshold;
int global_rrt_memory_limit;
float planner_min_dist_to_obs;

float info_gain, dist_gain_far, dist_gain_near, dir_gain, free_gain;

bool prefer_near_dist = false;

enum auto_mapping_state
{
    FIRST_ROTATION = 0,
    FIND_LOCAL_FRONTIER_POINTS = 1,
    LOCAL_NAVIGATION = 2,
    FIND_GLOBAL_FRONTIER_POINTS = 3,
    GLOBAL_NAVIGATION = 4,
    BACK_TO_ORIGIN_NAVIGATION = 5,
    MAPPING_FINISH = 6
};

auto_mapping_state mapping_state = auto_mapping_state::MAPPING_FINISH;

nav_msgs::msg::OccupancyGrid map_data;
vector<float> obs_dist_table;

vector<geometry_msgs::msg::Point32> backtracking_points;
geometry_msgs::msg::TransformStamped tf_map_to_base_link;
geometry_msgs::msg::PoseStamped robot_origin_pose, robot_current_pose;
geometry_msgs::msg::Point32 robot_origin_position, robot_current_position;
vector<geometry_msgs::msg::PoseStamped> current_global_plan;
rrt_nodes global_frontier_points;
rrt_nodes local_frontier_points;

rclcpp::Subscription<nav_msgs::msg::OccupancyGrid>::SharedPtr map_sub;

rclcpp::Publisher<auto_mapping_toolbox_msgs::msg::AutoMappingState>::SharedPtr auto_mapping_state_pub;

auto_mapping_toolbox_msgs::srv::AutoMappingRequest::Request auto_mapping_request_data;
auto_mapping_toolbox_msgs::msg::AutoMappingState auto_mapping_state_data;

bool cancel_token = false;

void update_current_pose()
{
    try
    {
        tf_map_to_base_link = tf_buffer->lookupTransform(
            LOCALIZATION_MAP,
            LOCALIZATION_BASE_LINK,
            tf2::TimePointZero, std::chrono::seconds(60));
    }
    catch (...)
    {
        cout << "no tf data from map to base_link." << endl;

        return;
    }

    mutex_data.lock();

    robot_current_pose.header.stamp = node->now();
    robot_current_pose.header.frame_id = LOCALIZATION_MAP;
    robot_current_pose.pose.position.x = tf_map_to_base_link.transform.translation.x;
    robot_current_pose.pose.position.y = tf_map_to_base_link.transform.translation.y;
    robot_current_pose.pose.position.z = tf_map_to_base_link.transform.translation.z;
    robot_current_pose.pose.orientation = tf_map_to_base_link.transform.rotation;
    robot_current_position.x = robot_current_pose.pose.position.x;
    robot_current_position.y = robot_current_pose.pose.position.y;
    robot_current_position.z = robot_current_pose.pose.position.z;

    mutex_data.unlock();
}

void map_callback(const nav_msgs::msg::OccupancyGrid::ConstSharedPtr &msg)
{
    auto map_data_new = *msg;
    auto obs_dist_table_new = calc_min_dist_to_obs_table(map_data_new, map_occupied_threshold);
    auto area_new = calc_map_area(map_data_new, map_free_threshold, map_occupied_threshold);

    mutex_data.lock();

    map_data = map_data_new;
    obs_dist_table = obs_dist_table_new;
    auto_mapping_state_data.area = area_new;

    mutex_data.unlock();
}

void auto_mapping_request_callback(const std::shared_ptr<auto_mapping_toolbox_msgs::srv::AutoMappingRequest::Request> req,
                                     std::shared_ptr<auto_mapping_toolbox_msgs::srv::AutoMappingRequest::Response> res)
{

    if (req->cmd == AUTO_MAPPING_CMD_START &&
        mapping_state == auto_mapping_state::MAPPING_FINISH)
    {
        RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "%s：准备开始自动建图。", TAG);

        res->result = CMD_RESPONSE_OK;

        cancel_token = false;
        enable_waypoint_backtracking = req->waypoint_retracing;

        update_current_pose();
        robot_origin_pose = robot_current_pose;
        robot_origin_position = robot_current_position;

        RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "%s：重置导航控制。", TAG);

        nav_functions_instance->cancel();

        RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "%s：重置全局探索上下文。", TAG);

        global_explorer_instance.reset();
        global_explorer_instance = make_unique<global_explorer>(
            global_min_expand_dist, global_max_expand_dist, exploration_min_dist_to_obs,
            global_frontier_points_min_dist, global_sensing_radius,
            map_free_threshold, map_occupied_threshold);
        global_explorer_instance->initialize(node);
        global_explorer_instance->stop();

        RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "%s：开始自动建图。", TAG);

        mapping_state = auto_mapping_state::FIRST_ROTATION;
    }
    else if (req->cmd == AUTO_MAPPING_CMD_CANCEL)
    {
        res->result = CMD_RESPONSE_OK;

        RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "%s：停止自动建图。", TAG);

        if (mapping_state != auto_mapping_state::MAPPING_FINISH)
        {
            cancel_token = true;
        }
    }
    else if (req->cmd == AUTO_MAPPING_CMD_START &&
             mapping_state != auto_mapping_state::MAPPING_FINISH)
    {
        res->result = CMD_RESPONSE_BUSY;

        RCLCPP_WARN(rclcpp::get_logger(NODE_NAME), "%s：当前正在进行自动建图。", TAG);
    }
    else
    {
        res->result = CMD_RESPONSE_ERROR;
    }

}

void thread_loop()
{
    while (rclcpp::ok())
    {
        auto_mapping_state_data.header.stamp = node->now();

        auto_mapping_state_pub->publish(auto_mapping_state_data);

        rclcpp::sleep_for(std::chrono::milliseconds(10));
    }
}

void global_exploration_memory_check()
{
    while (rclcpp::ok())
    {
        if (global_explorer_instance != NULL && (mapping_state == auto_mapping_state::BACK_TO_ORIGIN_NAVIGATION ||
                                                 mapping_state == auto_mapping_state::FIND_GLOBAL_FRONTIER_POINTS))
        {
            try
            {
                float global_rrt_memory_in_mb = global_explorer_instance->get_rrt_memory_in_mb();

                if (global_rrt_memory_in_mb > (float)global_rrt_memory_limit)
                {
                    global_explorer_instance->stop();
                }

                RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "%s：当前全局节点内存占用：%.1f MB。", TAG, global_rrt_memory_in_mb);
            }
            catch (...)
            {
                continue;
            }
        }

        rclcpp::sleep_for(std::chrono::seconds(2));
    }
}

int main(int argc, char **argv)
{
    rclcpp::init(argc, argv);

    setlocale(LC_CTYPE, "zh_CN.utf8");

    RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "%s：节点已启动。", TAG);

    node = rclcpp::Node::make_shared(NODE_NAME);

    share_common_distance_table = node->declare_parameter<bool>("auto_mapping.share_common_distance_table", true);
    enable_collision_precheck = node->declare_parameter<bool>("auto_mapping.enable_collision_precheck", true);

    max_x_vel = static_cast<float>(node->declare_parameter<double>("auto_mapping.max_x_vel", 1.0));
    max_yaw_vel = static_cast<float>(node->declare_parameter<double>("auto_mapping.max_yaw_vel", 1.57));

    map_free_threshold = node->declare_parameter<int>("auto_mapping.map_free_threshold", 30);
    map_occupied_threshold = node->declare_parameter<int>("auto_mapping.map_occupied_threshold", 55);

    polyline_path_max_length = static_cast<float>(node->declare_parameter<double>("auto_mapping.polyline_path_max_length", 1.2));
    exploration_min_dist_to_obs = static_cast<float>(node->declare_parameter<double>("auto_mapping.exploration_min_dist_to_obs", 0.26));

    global_min_expand_dist = static_cast<float>(node->declare_parameter<double>("auto_mapping.global_min_expand_dist", 0.2));
    global_max_expand_dist = static_cast<float>(node->declare_parameter<double>("auto_mapping.global_max_expand_dist", 1.0));
    global_frontier_points_min_dist = static_cast<float>(node->declare_parameter<double>("auto_mapping.global_frontier_points_min_dist", 0.5));
    global_sensing_radius = static_cast<float>(node->declare_parameter<double>("auto_mapping.global_sensing_radius", 20.0));
    global_sampling_timeout_secs = node->declare_parameter<int>("auto_mapping.global_sampling_timeout_secs", 2);
    global_rrt_memory_limit = node->declare_parameter<int>("auto_mapping.global_rrt_memory_limit", 1024);

    local_min_expand_dist = static_cast<float>(node->declare_parameter<double>("auto_mapping.local_min_expand_dist", 0.1));
    local_max_expand_dist = static_cast<float>(node->declare_parameter<double>("auto_mapping.local_max_expand_dist", 1.0));
    local_rrt_coverage_check_density = static_cast<float>(node->declare_parameter<double>("auto_mapping.local_rrt_coverage_check_density", 0.2));
    local_frontier_points_min_dist = static_cast<float>(node->declare_parameter<double>("auto_mapping.local_frontier_points_min_dist", 0.3));
    local_sensing_radius = static_cast<float>(node->declare_parameter<double>("auto_mapping.local_sensing_radius", 20.0));
    local_prefer_near_frontier_point_dist_threshold = static_cast<float>(node->declare_parameter<double>("auto_mapping.local_prefer_near_frontier_point_dist_threshold", 0.5));
    local_sampling_timeout_secs = node->declare_parameter<int>("auto_mapping.local_sampling_timeout_secs", 10);

    planner_min_dist_to_obs = static_cast<float>(node->declare_parameter<double>("auto_mapping.planner_min_dist_to_obs", 0.26));

    info_gain = static_cast<float>(node->declare_parameter<double>("auto_mapping.info_gain", 0.5));
    dist_gain_far = static_cast<float>(node->declare_parameter<double>("auto_mapping.dist_gain_far", 1.0));
    dist_gain_near = static_cast<float>(node->declare_parameter<double>("auto_mapping.dist_gain_near", 2.0));
    dir_gain = static_cast<float>(node->declare_parameter<double>("auto_mapping.dir_gain", 5.0));
    free_gain = static_cast<float>(node->declare_parameter<double>("auto_mapping.free_gain", 0.8));

    global_explorer_instance = make_unique<global_explorer>(
        global_min_expand_dist, global_max_expand_dist, exploration_min_dist_to_obs,
        global_frontier_points_min_dist, global_sensing_radius,
        map_free_threshold, map_occupied_threshold);

    local_explorer_instance = make_unique<local_explorer>(
        local_min_expand_dist, local_max_expand_dist, exploration_min_dist_to_obs,
        local_rrt_coverage_check_density,
        local_frontier_points_min_dist, local_sensing_radius,
        map_free_threshold, map_occupied_threshold);

    collision_predictor_instance =
        share_common_distance_table ? make_unique<collision_predictor>(true) : make_unique<collision_predictor>(false, map_free_threshold, map_occupied_threshold);

    lcr_global = make_shared<nav2_costmap_2d::Costmap2DROS>("global_costmap", false);

    // 配置代价地图参数（静态地图回退到全局 map_topic 参数；代价地图节点位于自身命名空间内，故使用绝对话题名）
    lcr_global->set_parameter(rclcpp::Parameter("map_topic", string("/openmover/mapping/map")));
    lcr_global->set_parameter(rclcpp::Parameter("robot_base_frame", string(LOCALIZATION_BASE_LINK)));

    lcr_global->configure();

    // 代价地图由专属线程驱动（与 nav2 planner_server 的用法一致）
    global_costmap_thread = make_unique<nav2_util::NodeThread>(lcr_global);

    lcr_global->activate();

    global_planner_instance = make_shared<planner_with_costmap>("global_planner", lcr_global.get(), node->now(), node.get());

    RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "global planner ok.");

    tsp_solver_instance = make_unique<tsp_solver>();

    nav_functions_instance = make_unique<nav_functions>();

    nav_functions_instance->initialize(node);

    RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "navigation functions ok.");

    global_explorer_instance->initialize(node);
    global_explorer_instance->stop();

    RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "global explorer ok.");

    local_explorer_instance->initialize(node);

    RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "local explorer ok.");

    collision_predictor_instance->initialize(node);

    RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "collision predictor ok.");

    tf_buffer = make_unique<tf2_ros::Buffer>(node->get_clock());
    tf_listener = make_unique<tf2_ros::TransformListener>(*tf_buffer);

    map_sub = node->create_subscription<nav_msgs::msg::OccupancyGrid>("map", 2, map_callback);

    auto auto_mapping_server = node->create_service<auto_mapping_toolbox_msgs::srv::AutoMappingRequest>("auto_mapping/request", auto_mapping_request_callback);
    auto_mapping_state_pub = node->create_publisher<auto_mapping_toolbox_msgs::msg::AutoMappingState>("auto_mapping/state", rclcpp::QoS(1).transient_local());

    auto_mapping_state_data.state = AUTO_MAPPING_STATE_MAPPING_FINISH;

    // 后台执行器：处理订阅与服务回调（主循环在工作线程中运行）
    auto executor = make_unique<rclcpp::executors::SingleThreadedExecutor>();
    executor->add_node(node);
    thread executor_thread([&executor]() { executor->spin(); });

    thread spin_thread(thread_loop);

    update_current_pose();
    robot_origin_pose = robot_current_pose;
    robot_origin_position = robot_current_position;

    thread memory_check_thread(global_exploration_memory_check);

    while (rclcpp::ok())
    {
        if (mapping_state == auto_mapping_state::FIRST_ROTATION)
        {
            RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Rotating to initialize...");

            auto_mapping_state_data.state = AUTO_MAPPING_STATE_ROTATION;

            nav_functions_instance->move(0, 360, max_x_vel, (max_yaw_vel * 180.0f / M_PI) / 4.0, false, false);

            global_explorer_instance->reset();
            global_explorer_instance->stop();

            prefer_near_dist = false;

            mapping_state = auto_mapping_state::FIND_LOCAL_FRONTIER_POINTS;
        }
        else if (mapping_state == auto_mapping_state::FIND_LOCAL_FRONTIER_POINTS)
        {
            RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Finding local frontier points...");

            auto_mapping_state_data.state = AUTO_MAPPING_STATE_FIND_LOCAL_FRONTIER_POINTS;

            local_frontier_points = local_explorer_instance->get_frontier_points(local_sampling_timeout_secs);

            RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "%d local frontier points found.", (int)(local_frontier_points.points.size()));

            if (local_frontier_points.points.size() > 0)
            {
                RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Switching to local navigation...");

                mapping_state = auto_mapping_state::LOCAL_NAVIGATION;
            }
            else
            {
                RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Switching to navigate to the origin...");

                mapping_state = auto_mapping_state::BACK_TO_ORIGIN_NAVIGATION;
            }
        }
        else if (mapping_state == auto_mapping_state::LOCAL_NAVIGATION ||
                 mapping_state == auto_mapping_state::GLOBAL_NAVIGATION)
        {
            rrt_nodes frontier_points;

            if (mapping_state == auto_mapping_state::LOCAL_NAVIGATION)
            {
                RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Performing local navigation...");

                auto_mapping_state_data.state = AUTO_MAPPING_STATE_LOCAL_NAVIGATION;

                frontier_points = local_frontier_points;

                RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Selecting best local frontier point...");
            }
            else
            {
                RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Performing global navigation...");

                auto_mapping_state_data.state = AUTO_MAPPING_STATE_GLOBAL_NAVIGATION;

                frontier_points = global_frontier_points;

                RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Selecting best global frontier point...");
            }

            update_current_pose();

            vector<pair<int, float>> index_score_pairs;
            index_score_pairs.reserve(frontier_points.points.size());

            if (mapping_state == auto_mapping_state::LOCAL_NAVIGATION)
            {
                for (int i = 0; i < static_cast<int>(frontier_points.points.size()); i++)
                {
                    geometry_msgs::msg::Point32 point = frontier_points.points[i];

                    float dist_to_current_pose = calculate_distance(robot_current_position, point);

                    if (dist_to_current_pose <= local_prefer_near_frontier_point_dist_threshold)
                    {
                        prefer_near_dist = true;

                        break;
                    }
                }

                if (prefer_near_dist)
                {
                    RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "We prefer near frontier points.");
                }
                else
                {
                    RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "We prefer far frontier points.");
                }
            }

            for (int i = 0; i < static_cast<int>(frontier_points.points.size()); i++)
            {
                geometry_msgs::msg::Point32 point = frontier_points.points[i];

                float dist_to_current_pose = calculate_distance(robot_current_position, point);

                float info_gain_val = frontier_points.info_gains[i];

                int obs_table_index = position_to_grid_index(frontier_points.points[i], map_data);
                if (obs_table_index < 0)
                    obs_table_index = 0;
                else if (obs_table_index > static_cast<int>(obs_dist_table.size()) - 1)
                    obs_table_index = obs_dist_table.size() - 1;
                float dist_to_obs = obs_dist_table[obs_table_index];

                float score = info_gain * info_gain_val + free_gain * dist_to_obs;

                if (prefer_near_dist && mapping_state == auto_mapping_state::LOCAL_NAVIGATION)
                {
                    score += dist_gain_near / (dist_to_current_pose + 0.1);
                }
                else
                {
                    score += dist_gain_far * dist_to_current_pose;
                }

                if (backtracking_points.size() >= 2)
                {
                    float dir_diff = calc_orientation_diff(
                        backtracking_points[backtracking_points.size() - 2],
                        backtracking_points[backtracking_points.size() - 1],
                        point);
                    score += dir_gain * (M_PI - dir_diff);
                }

                index_score_pairs.emplace_back(i, score);
            }

            sort(index_score_pairs.begin(), index_score_pairs.end(),
                 [](const pair<int, float> &a, const pair<int, float> &b)
                 {
                     return a.second > b.second;
                 });

            RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Frontier points sorted, best point index: %d, max score: %f.",
                     index_score_pairs[0].first, index_score_pairs[0].second);

            RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Planning initial polyline path...");

            update_current_pose();
            geometry_msgs::msg::PoseStamped start = robot_current_pose;
            geometry_msgs::msg::PoseStamped goal = start;

            RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Planning...");

            current_global_plan.clear();
            tuple<bool, vector<geometry_msgs::msg::PoseStamped>, vector<geometry_msgs::msg::PoseStamped>> plan_result;

            for (const auto &candidate_point : index_score_pairs)
            {
                update_current_pose();
                start = robot_current_pose;

                goal.pose.position.x = frontier_points.points[candidate_point.first].x;
                goal.pose.position.y = frontier_points.points[candidate_point.first].y;
                goal.pose.position.z = frontier_points.points[candidate_point.first].z;
                goal.pose.orientation = quaternion_msg_from_yaw(
                    angles::normalize_angle(calc_seg_direction(start, frontier_points.points[candidate_point.first])));

                plan_result = global_planner_instance->plan(
                    start, goal, map_data, planner_min_dist_to_obs, true, 1, true, polyline_path_max_length, 2, map_occupied_threshold);

                if (get<0>(plan_result))
                {
                    current_global_plan = get<2>(plan_result);

                    break;
                }
                else
                {
                    RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Replanning...");

                    bool plan_successful = false;

                    auto alt_poses = get_round_points(goal,
                                                      local_frontier_points_min_dist, 12,
                                                      map_data,
                                                      exploration_min_dist_to_obs, obs_dist_table);

                    for (int i = 0; i < alt_poses.size(); i++)
                    {
                        goal = alt_poses[i];

                        update_current_pose();

                        plan_result = global_planner_instance->plan(
                            robot_current_pose, goal, map_data, planner_min_dist_to_obs, true, 1, true, polyline_path_max_length, 2, map_occupied_threshold);

                        if (get<0>(plan_result))
                        {
                            plan_successful = true;

                            current_global_plan = get<2>(plan_result);

                            break;
                        }
                        else
                        {
                            current_global_plan.clear();
                        }
                    }

                    if (plan_successful)
                    {
                        break;
                    }
                }
            }

            if (current_global_plan.size() > 0)
            {
                int replanning_by_collision_counter = 0;

                do
                {
                    bool navigation_done = false;

                    for (int i = 1; i < current_global_plan.size(); i++)
                    {
                        update_current_pose();

                        if (enable_collision_precheck)
                        {
                            if (i != current_global_plan.size() - 1)
                            {
                                RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Checking collision...");

                                if (share_common_distance_table ? (collision_predictor_instance->check(robot_current_pose,
                                                                                                       current_global_plan[i], 4, exploration_min_dist_to_obs,
                                                                                                       map_data, obs_dist_table,
                                                                                                       map_free_threshold, map_occupied_threshold))
                                                                : (collision_predictor_instance->check(robot_current_pose,
                                                                                                       current_global_plan[i], 4, exploration_min_dist_to_obs)))
                                {
                                    RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Future collision detected, replanning...");

                                    current_global_plan.clear();

                                    replanning_by_collision_counter++;

                                    break;
                                }
                            }
                        }

                        RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Navigating to way point %d (%lf, %lf)...", i,
                                 current_global_plan[i].pose.position.x,
                                 current_global_plan[i].pose.position.y);

                        if (calculate_distance(robot_current_pose.pose, current_global_plan[current_global_plan.size() - 1].pose) > exploration_min_dist_to_obs * 1.4)
                        {
                            if (i == current_global_plan.size() - 1 && i > 0 && enable_waypoint_backtracking)
                            {
                                geometry_msgs::msg::Point32 p0, dir, pg;
                                float dist_k = 1.0f;

                                p0.x = current_global_plan[i].pose.position.x;
                                p0.y = current_global_plan[i].pose.position.y;
                                p0.z = current_global_plan[i].pose.position.z;

                                do
                                {
                                    dir.x =
                                        current_global_plan[i - 1].pose.position.x - p0.x;
                                    dir.y =
                                        current_global_plan[i - 1].pose.position.y - p0.y;
                                    dir.z =
                                        current_global_plan[i - 1].pose.position.z - p0.z;
                                    pg = generate_point_on_segment(p0, dir, exploration_min_dist_to_obs * dist_k);
                                    current_global_plan[i].pose.position.x = pg.x;
                                    current_global_plan[i].pose.position.y = pg.y;
                                    current_global_plan[i].pose.position.z = pg.z;

                                    RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Checking collision...");

                                    if (share_common_distance_table ? (collision_predictor_instance->check(robot_current_pose,
                                                                                                           current_global_plan[i], 4, exploration_min_dist_to_obs * 1.5,
                                                                                                           map_data, obs_dist_table,
                                                                                                           map_free_threshold, map_occupied_threshold))
                                                                    : collision_predictor_instance->check(robot_current_pose,
                                                                                                          current_global_plan[i], 4, exploration_min_dist_to_obs * 1.5))
                                    {
                                        RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Future collision detected, replanning...");

                                        dist_k += 0.2;

                                        continue;
                                    }
                                    else
                                    {
                                        break;
                                    }
                                } while (dist_k <= 1.6);

                                if (share_common_distance_table ? (collision_predictor_instance->check(robot_current_pose,
                                                                                                       current_global_plan[i], 4, exploration_min_dist_to_obs * 1.5,
                                                                                                       map_data, obs_dist_table,
                                                                                                       map_free_threshold, map_occupied_threshold))
                                                                : (collision_predictor_instance->check(robot_current_pose,
                                                                                                       current_global_plan[i], 4, exploration_min_dist_to_obs * 1.5)))
                                {
                                    RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Future collision detected, replanning...");

                                    current_global_plan.clear();

                                    replanning_by_collision_counter++;

                                    break;
                                }
                            }

                            nav_functions_instance->cancel();
                            rclcpp::sleep_for(std::chrono::milliseconds(200));

                            bool nav_req_result = nav_functions_instance->nav_to(
                                current_global_plan[i].pose.position.x,
                                current_global_plan[i].pose.position.y,
                                angles::to_degrees(tf2::getYaw(current_global_plan[i].pose.orientation)),
                                max_x_vel, max_yaw_vel * 180.0f / M_PI, false, false, true);
                            rclcpp::sleep_for(std::chrono::milliseconds(200));

                            bool blocked_in_running = false;

                            if (nav_req_result)
                            {
                                while (rclcpp::ok())
                                {
                                    auto nav_to_state_code = nav_functions_instance->get_nav_state();

                                    if (nav_to_state_code == NAV_STATE_REACHED ||
                                        nav_to_state_code == NAV_STATE_ERROR)
                                    {
                                        nav_functions_instance->set_cmd_vel_mode(true);

                                        break;
                                    }

                                    update_current_pose();

                                    if (calculate_distance(robot_current_pose.pose, current_global_plan[current_global_plan.size() - 1].pose) <= exploration_min_dist_to_obs * 1.2 ||
                                        nav_to_state_code == NAV_STATE_BLOCKED)
                                    {
                                        nav_functions_instance->cancel();

                                        nav_functions_instance->set_cmd_vel_mode(true);

                                        blocked_in_running = true;

                                        break;
                                    }

                                    rclcpp::sleep_for(std::chrono::milliseconds(100));
                                }

                                backtracking_points.push_back(robot_current_position);
                            }

                            if (blocked_in_running && !enable_collision_precheck && i != current_global_plan.size() - 1)
                            {
                                RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Future collision detected, replanning...");

                                current_global_plan.clear();

                                replanning_by_collision_counter++;

                                break;
                            }

                            rclcpp::sleep_for(std::chrono::milliseconds(200));

                            update_current_pose();
                        }

                        prefer_near_dist = !(i == current_global_plan.size() - 1);

                        if (i == current_global_plan.size() - 1 ||
                            current_global_plan.size() == 0)
                        {
                            nav_functions_instance->move(0, 360, max_x_vel, max_yaw_vel * 180.0f / M_PI, false, false);

                            navigation_done = true;
                        }
                    }

                    if (current_global_plan.size() <= 0 && !navigation_done)
                    {
                        update_current_pose();

                        plan_result = global_planner_instance->plan(
                            robot_current_pose, goal, map_data, planner_min_dist_to_obs + replanning_by_collision_counter * 0.02, true, 1, true, polyline_path_max_length, 2, map_occupied_threshold);

                        if (get<0>(plan_result) && replanning_by_collision_counter <= 5)
                        {
                            current_global_plan = get<2>(plan_result);

                            continue;
                        }
                        else
                        {
                            RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "No feasible path, refreshing frontier points...");

                            navigation_done = true;
                        }
                    }

                    if (navigation_done)
                    {
                        current_global_plan.clear();

                        mapping_state = auto_mapping_state::FIND_LOCAL_FRONTIER_POINTS;

                        break;
                    }
                } while (true);
            }
            else
            {
                RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "No feasible path, refreshing frontier points...");

                current_global_plan.clear();

                mapping_state = auto_mapping_state::FIND_LOCAL_FRONTIER_POINTS;
            }
        }
        else if (mapping_state == auto_mapping_state::FIND_GLOBAL_FRONTIER_POINTS)
        {
            RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Finding global frontier points...");

            auto_mapping_state_data.state = AUTO_MAPPING_STATE_FIND_GLOBAL_FRONTIER_POINTS;

            auto start_time = std::chrono::steady_clock::now();

            do
            {
                global_frontier_points = global_explorer_instance->get_frontier_points();

                if (global_frontier_points.points.size() > 0)
                {
                    break;
                }
                else
                {
                    rclcpp::sleep_for(std::chrono::seconds(1));
                }

            } while (std::chrono::duration<double>(std::chrono::steady_clock::now() - start_time).count() <= global_sampling_timeout_secs);

            RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "%d global frontier points found.", (int)(global_frontier_points.points.size()));

            if (global_frontier_points.points.size() > 0)
            {
                RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Switching to global navigation...");

                mapping_state = auto_mapping_state::GLOBAL_NAVIGATION;
            }
            else
            {
                RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Exploration finished, please save the map.");

                auto_mapping_state_data.state = AUTO_MAPPING_STATE_MAPPING_FINISH;

                enable_waypoint_backtracking = true;
                cancel_token = false;

                mapping_state = auto_mapping_state::MAPPING_FINISH;
            }

            global_explorer_instance->reset();
            global_explorer_instance->stop();
        }
        else if (mapping_state == auto_mapping_state::BACK_TO_ORIGIN_NAVIGATION)
        {
            RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Performing back-to-origin navigation...");

            auto_mapping_state_data.state = AUTO_MAPPING_STATE_BACK_TO_ORIGIN_NAVIGATION;

            RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Starting global exploration...");

            global_explorer_instance->reset();

            RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Resampling backtracking points. origin size: %d...",
                     (int)backtracking_points.size());

            update_current_pose();

            auto backtracking_points_reversed = backtracking_points;

            reverse(backtracking_points_reversed.begin(), backtracking_points_reversed.end());

            auto backtracking_points_resampled = resample_points(
                backtracking_points_reversed, polyline_path_max_length * 2.0f);
            vector<geometry_msgs::msg::Point32> goal_positions;

            if (!enable_waypoint_backtracking)
            {
                backtracking_points_resampled.clear();
            }

            if (backtracking_points_resampled.size() > 0)
            {
                RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Backtracking points exist, size: %d, solving tsp optimization...",
                         (int)backtracking_points_resampled.size());

                goal_positions = tsp_solver_instance->optimize(
                    robot_current_position,
                    robot_origin_position,
                    backtracking_points_resampled);
            }
            else
            {
                goal_positions.push_back(robot_origin_position);
            }

            RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "%d goal points set.", (int)goal_positions.size());

            for (int i = 0; i < goal_positions.size(); i++)
            {
                RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Planning initial polyline path to backtracking point %d...", i);

                update_current_pose();
                geometry_msgs::msg::PoseStamped start = robot_current_pose;
                geometry_msgs::msg::PoseStamped goal = start;
                goal.pose.position.x = goal_positions[i].x;
                goal.pose.position.y = goal_positions[i].y;
                goal.pose.position.z = goal_positions[i].z;
                goal.pose.orientation =
                    i == goal_positions.size() - 1 ? robot_origin_pose.pose.orientation : quaternion_msg_from_yaw(angles::normalize_angle(calc_seg_direction(start, goal_positions[i])));

                RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Planning...");

                current_global_plan.clear();
                tuple<bool, vector<geometry_msgs::msg::PoseStamped>, vector<geometry_msgs::msg::PoseStamped>> plan_result;
                plan_result = global_planner_instance->plan(
                    start, goal, map_data, planner_min_dist_to_obs, true, 1, true, polyline_path_max_length, 2, map_occupied_threshold);

                if (get<0>(plan_result))
                {
                    current_global_plan = get<2>(plan_result);
                }
                else if (i == goal_positions.size() - 1)
                {
                    RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Replanning...");

                    auto alt_poses = get_round_points(goal,
                                                      global_frontier_points_min_dist, 24,
                                                      map_data,
                                                      exploration_min_dist_to_obs, obs_dist_table);

                    for (int j = 0; j < alt_poses.size(); j++)
                    {
                        goal = alt_poses[j];

                        update_current_pose();

                        plan_result = global_planner_instance->plan(
                            robot_current_pose, goal, map_data, planner_min_dist_to_obs, true, 1, true, polyline_path_max_length, 2, map_occupied_threshold);

                        if (get<0>(plan_result))
                        {
                            current_global_plan = get<2>(plan_result);

                            break;
                        }
                    }
                }
                else
                {
                    RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Replanning...");

                    update_current_pose();

                    plan_result = global_planner_instance->plan(
                        robot_current_pose, goal, map_data, planner_min_dist_to_obs, true, 1, true, polyline_path_max_length, 2, map_occupied_threshold);

                    if (get<0>(plan_result))
                    {
                        current_global_plan = get<2>(plan_result);
                    }
                }

                if (current_global_plan.size() > 0)
                {
                    int replanning_by_collision_counter = 0;

                    do
                    {
                        bool navigation_done = false;

                        for (int j = 1; j < current_global_plan.size(); j++)
                        {
                            if (global_explorer_instance->get_frontier_points().indices.size() > 0)
                            {
                                mapping_state = auto_mapping_state::FIND_GLOBAL_FRONTIER_POINTS;

                                navigation_done = true;

                                break;
                            }

                            update_current_pose();

                            if (enable_collision_precheck)
                            {
                                RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Checking collision...");

                                if (share_common_distance_table ? (collision_predictor_instance->check(robot_current_pose,
                                                                                                       current_global_plan[j], 4, exploration_min_dist_to_obs,
                                                                                                       map_data, obs_dist_table,
                                                                                                       map_free_threshold, map_occupied_threshold))
                                                                : (collision_predictor_instance->check(robot_current_pose,
                                                                                                       current_global_plan[j], 4, exploration_min_dist_to_obs)))
                                {
                                    RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Future collision detected, replanning...");

                                    current_global_plan.clear();

                                    replanning_by_collision_counter++;

                                    break;
                                }
                            }

                            RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Navigating to way point %d (%lf, %lf)...", j,
                                     current_global_plan[j].pose.position.x,
                                     current_global_plan[j].pose.position.y);

                            nav_functions_instance->cancel();
                            rclcpp::sleep_for(std::chrono::milliseconds(200));

                            bool nav_req_result = nav_functions_instance->nav_to(
                                current_global_plan[j].pose.position.x,
                                current_global_plan[j].pose.position.y,
                                angles::to_degrees(tf2::getYaw(current_global_plan[j].pose.orientation)),
                                max_x_vel, max_yaw_vel * 180.0f / M_PI, false, false, true);
                            rclcpp::sleep_for(std::chrono::milliseconds(200));

                            bool blocked_in_running = false;

                            if (nav_req_result)
                            {
                                while (rclcpp::ok())
                                {
                                    auto nav_to_state_code = nav_functions_instance->get_nav_state();

                                    if (nav_to_state_code == NAV_STATE_REACHED ||
                                        nav_to_state_code == NAV_STATE_ERROR)
                                    {
                                        nav_functions_instance->set_cmd_vel_mode(true);

                                        break;
                                    }

                                    if (nav_to_state_code == NAV_STATE_BLOCKED)
                                    {
                                        nav_functions_instance->cancel();

                                        nav_functions_instance->set_cmd_vel_mode(true);

                                        blocked_in_running = true;

                                        break;
                                    }

                                    update_current_pose();

                                    rclcpp::sleep_for(std::chrono::milliseconds(100));
                                }
                            }

                            if (blocked_in_running && !enable_collision_precheck)
                            {
                                RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Future collision detected, replanning...");

                                current_global_plan.clear();

                                replanning_by_collision_counter++;

                                break;
                            }

                            rclcpp::sleep_for(std::chrono::milliseconds(200));

                            update_current_pose();

                            if (j == current_global_plan.size() - 1 ||
                                current_global_plan.size() == 0)
                            {
                                navigation_done = true;
                            }
                        }

                        if (current_global_plan.size() <= 0 && !navigation_done)
                        {
                            update_current_pose();

                            plan_result = global_planner_instance->plan(
                                robot_current_pose, goal, map_data, planner_min_dist_to_obs, true, 1, true, polyline_path_max_length, 2, map_occupied_threshold);

                            if (get<0>(plan_result) && replanning_by_collision_counter <= 5)
                            {
                                current_global_plan = get<2>(plan_result);

                                continue;
                            }
                            else if (get<0>(plan_result))
                            {
                                RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "No feasible polyline path, using normal navigation to the point...");

                                nav_functions_instance->cancel();
                                rclcpp::sleep_for(std::chrono::milliseconds(200));

                                nav_functions_instance->nav_to(
                                    goal.pose.position.x,
                                    goal.pose.position.y,
                                    angles::to_degrees(tf2::getYaw(goal.pose.orientation)),
                                    max_x_vel / 2.0f, (max_yaw_vel * 180.0f / M_PI) / 2.0f, true, false, false);

                                navigation_done = true;
                            }
                            else
                            {
                                RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "No feasible path, skip this point...");

                                navigation_done = true;
                            }
                        }

                        if (navigation_done)
                        {
                            current_global_plan.clear();

                            break;
                        }
                    } while (true);
                }
                else
                {
                    RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "No feasible path, skip this backtracking point...");

                    current_global_plan.clear();
                }
            }

            backtracking_points.clear();

            nav_functions_instance->move(0, 360, max_x_vel, max_yaw_vel * 180.0f / M_PI, false, false);

            mapping_state = auto_mapping_state::FIND_GLOBAL_FRONTIER_POINTS;
        }

        if (mapping_state != auto_mapping_state::MAPPING_FINISH)
        {
            if (cancel_token)
            {
                RCLCPP_INFO(rclcpp::get_logger(NODE_NAME), "Exploration stopping...");

                backtracking_points.clear();

                enable_waypoint_backtracking = true;
                cancel_token = false;

                global_explorer_instance->reset();
                global_explorer_instance->stop();

                prefer_near_dist = false;

                auto_mapping_state_data.state = AUTO_MAPPING_STATE_MAPPING_FINISH;

                mapping_state = auto_mapping_state::MAPPING_FINISH;
            }
        }

        rclcpp::sleep_for(std::chrono::milliseconds(20));
    }

    // 清理后台线程
    executor->cancel();
    if (executor_thread.joinable())
    {
        executor_thread.join();
    }
    if (spin_thread.joinable())
    {
        spin_thread.join();
    }
    if (memory_check_thread.joinable())
    {
        memory_check_thread.join();
    }

    rclcpp::shutdown();

    return 0;
}