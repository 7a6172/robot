#include <ros/ros.h>
#include <geometry_msgs/Twist.h>
#include <geometry_msgs/TwistWithCovarianceStamped.h>
#include <geometry_msgs/PoseWithCovarianceStamped.h>
#include <tf/tf.h>
#include <tf2_ros/transform_broadcaster.h>
#include <tf2_ros/transform_listener.h>
#include <nav_msgs/Odometry.h>
#include <math.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <termios.h>
#include <angles/angles.h>
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
#include <auto_mapping_toolbox_msgs/auto_mapping_request.h>
#include <auto_mapping_toolbox_msgs/auto_mapping_state.h>
#include <utils/auto_mapping_state_code.h>

#define NODE_NAME "auto_mapping_handler"
#define TAG "自动建图系统"

using namespace std;
using namespace global_exploration;
using namespace local_exploration;
using namespace tsp_optimization;
using namespace collision_prediction;

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

nav_msgs::OccupancyGrid map_data;
vector<float> obs_dist_table;

vector<geometry_msgs::Point32> backtracking_points;
geometry_msgs::TransformStamped tf_map_to_base_link;
geometry_msgs::PoseStamped robot_origin_pose, robot_current_pose;
geometry_msgs::Point32 robot_origin_position, robot_current_position;
vector<geometry_msgs::PoseStamped> current_global_plan;
rrt_nodes global_frontier_points;
rrt_nodes local_frontier_points;

ros::Subscriber map_sub;

ros::Publisher auto_mapping_state_pub;

auto_mapping_toolbox_msgs::auto_mapping_request::Request auto_mapping_request_data;
auto_mapping_toolbox_msgs::auto_mapping_state auto_mapping_state_data;

bool cancel_token = false;

void update_current_pose()
{
    try
    {
        tf_map_to_base_link = tf_buffer->lookupTransform(
            LOCALIZATION_MAP,
            LOCALIZATION_BASE_LINK,
            ros::Time(0), ros::Duration(60.0));
    }
    catch (...)
    {
        cout << "no tf data from map to base_link." << endl;

        return;
    }

    mutex_data.lock();

    robot_current_pose.header.stamp = ros::Time::now();
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

void map_callback(const nav_msgs::OccupancyGrid::ConstPtr &msg)
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

bool auto_mapping_request_callback(auto_mapping_toolbox_msgs::auto_mapping_request::Request &req,
                                   auto_mapping_toolbox_msgs::auto_mapping_request::Response &res)
{
    bool ret = false;

    if (req.cmd == AUTO_MAPPING_CMD_START &&
        mapping_state == auto_mapping_state::MAPPING_FINISH)
    {
        ROS_INFO("%s：准备开始自动建图。", TAG);

        res.result = CMD_RESPONSE_OK;

        cancel_token = false;
        enable_waypoint_backtracking = req.waypoint_retracing;

        update_current_pose();
        robot_origin_pose = robot_current_pose;
        robot_origin_position = robot_current_position;

        ROS_INFO("%s：重置导航控制。", TAG);

        nav_functions_instance->cancel();

        ROS_INFO("%s：重置全局探索上下文。", TAG);

        global_explorer_instance.reset();
        global_explorer_instance = make_unique<global_explorer>(
            global_min_expand_dist, global_max_expand_dist, exploration_min_dist_to_obs,
            global_frontier_points_min_dist, global_sensing_radius,
            map_free_threshold, map_occupied_threshold);
        global_explorer_instance->initialize();
        global_explorer_instance->stop();

        ROS_INFO("%s：开始自动建图。", TAG);

        mapping_state = auto_mapping_state::FIRST_ROTATION;
    }
    else if (req.cmd == AUTO_MAPPING_CMD_CANCEL)
    {
        res.result = CMD_RESPONSE_OK;

        ROS_INFO("%s：停止自动建图。", TAG);

        if (mapping_state != auto_mapping_state::MAPPING_FINISH)
        {
            cancel_token = true;
        }
    }
    else if (req.cmd == AUTO_MAPPING_CMD_START &&
             mapping_state != auto_mapping_state::MAPPING_FINISH)
    {
        res.result = CMD_RESPONSE_BUSY;

        ROS_WARN("%s：当前正在进行自动建图。", TAG);
    }
    else
    {
        res.result = CMD_RESPONSE_ERROR;
    }

    ret = true;

    return ret;
}

void thread_loop()
{
    ros::Rate rate(100);

    while (ros::ok())
    {
        ros::spinOnce();

        auto_mapping_state_data.header.stamp = ros::Time::now();

        auto_mapping_state_pub.publish(auto_mapping_state_data);

        rate.sleep();
    }
}

void global_exploration_memory_check()
{
    while (ros::ok())
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

                ROS_INFO("%s：当前全局节点内存占用：%.1f MB。", TAG, global_rrt_memory_in_mb);
            }
            catch (...)
            {
                continue;
            }
        }

        ros::Duration(2.0).sleep();
    }
}

int main(int argc, char **argv)
{
    ros::init(argc, argv, NODE_NAME);

    setlocale(LC_CTYPE, "zh_CN.utf8");

    ROS_INFO("%s：节点已启动。", TAG);

    ros::NodeHandle node_handle;

    ros::NodeHandle node_handle_param("~/auto_mapping");

    node_handle_param.param<bool>("share_common_distance_table", share_common_distance_table, true);
    node_handle_param.param<bool>("enable_collision_precheck", enable_collision_precheck, true);

    node_handle_param.param<float>("max_x_vel", max_x_vel, 1.0);
    node_handle_param.param<float>("max_yaw_vel", max_yaw_vel, 1.57);

    node_handle_param.param<int>("map_free_threshold", map_free_threshold, 30);
    node_handle_param.param<int>("map_occupied_threshold", map_occupied_threshold, 55);

    node_handle_param.param<float>("polyline_path_max_length", polyline_path_max_length, 1.2);
    node_handle_param.param<float>("exploration_min_dist_to_obs", exploration_min_dist_to_obs, 0.26);

    node_handle_param.param<float>("global_min_expand_dist", global_min_expand_dist, 0.2);
    node_handle_param.param<float>("global_max_expand_dist", global_max_expand_dist, 1.0);
    node_handle_param.param<float>("global_frontier_points_min_dist", global_frontier_points_min_dist, 0.5);
    node_handle_param.param<float>("global_sensing_radius", global_sensing_radius, 20.0);
    node_handle_param.param<int>("global_sampling_timeout_secs", global_sampling_timeout_secs, 2);
    node_handle_param.param<int>("global_rrt_memory_limit", global_rrt_memory_limit, 1024);

    node_handle_param.param<float>("local_min_expand_dist", local_min_expand_dist, 0.1);
    node_handle_param.param<float>("local_max_expand_dist", local_max_expand_dist, 1.0);
    node_handle_param.param<float>("local_rrt_coverage_check_density", local_rrt_coverage_check_density, 0.2);
    node_handle_param.param<float>("local_frontier_points_min_dist", local_frontier_points_min_dist, 0.3);
    node_handle_param.param<float>("local_sensing_radius", local_sensing_radius, 20.0);
    node_handle_param.param<float>("local_prefer_near_frontier_point_dist_threshold", local_prefer_near_frontier_point_dist_threshold, 0.5);
    node_handle_param.param<int>("local_sampling_timeout_secs", local_sampling_timeout_secs, 10);

    node_handle_param.param<float>("planner_min_dist_to_obs", planner_min_dist_to_obs, 0.26);

    node_handle_param.param<float>("info_gain", info_gain, 0.5);
    node_handle_param.param<float>("dist_gain_far", dist_gain_far, 1.0);
    node_handle_param.param<float>("dist_gain_near", dist_gain_near, 2.0);
    node_handle_param.param<float>("dir_gain", dir_gain, 5.0);
    node_handle_param.param<float>("free_gain", free_gain, 0.8);

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

    tf2_ros::Buffer buffer_global(ros::Duration(10));
    tf2_ros::TransformListener tf_global(buffer_global);

    costmap_2d::Costmap2DROS lcr_global("global_costmap", buffer_global);

    global_planner_instance = make_shared<planner_with_costmap>("global_planner", &lcr_global, ros::Time::now());

    ROS_INFO("global planner ok.");

    tsp_solver_instance = make_unique<tsp_solver>();

    nav_functions_instance = make_unique<nav_functions>();

    nav_functions_instance->initialize();

    ROS_INFO("navigation functions ok.");

    global_explorer_instance->initialize();
    global_explorer_instance->stop();

    ROS_INFO("global explorer ok.");

    local_explorer_instance->initialize();

    ROS_INFO("local explorer ok.");

    collision_predictor_instance->initialize();

    ROS_INFO("collision predictor ok.");

    tf_buffer = make_unique<tf2_ros::Buffer>();
    tf_listener = make_unique<tf2_ros::TransformListener>(*tf_buffer);

    map_sub = node_handle.subscribe("map", 2, map_callback);

    ros::ServiceServer auto_mapping_server = node_handle.advertiseService("auto_mapping/request", auto_mapping_request_callback);
    auto_mapping_state_pub = node_handle.advertise<auto_mapping_toolbox_msgs::auto_mapping_state>("auto_mapping/state", 1, true);

    auto_mapping_state_data.state = AUTO_MAPPING_STATE_MAPPING_FINISH;

    boost::thread spin_thread(thread_loop);

    update_current_pose();
    robot_origin_pose = robot_current_pose;
    robot_origin_position = robot_current_position;

    boost::thread memory_check_thread(global_exploration_memory_check);

    ros::Rate rate(50);

    while (ros::ok())
    {
        if (mapping_state == auto_mapping_state::FIRST_ROTATION)
        {
            ROS_INFO("Rotating to initialize...");

            auto_mapping_state_data.state = AUTO_MAPPING_STATE_ROTATION;

            nav_functions_instance->move(0, 360, max_x_vel, (max_yaw_vel * 180.0f / M_PI) / 4.0, false, false);

            global_explorer_instance->reset();
            global_explorer_instance->stop();

            prefer_near_dist = false;

            mapping_state = auto_mapping_state::FIND_LOCAL_FRONTIER_POINTS;
        }
        else if (mapping_state == auto_mapping_state::FIND_LOCAL_FRONTIER_POINTS)
        {
            ROS_INFO("Finding local frontier points...");

            auto_mapping_state_data.state = AUTO_MAPPING_STATE_FIND_LOCAL_FRONTIER_POINTS;

            local_frontier_points = local_explorer_instance->get_frontier_points(local_sampling_timeout_secs);

            ROS_INFO("%d local frontier points found.", (int)(local_frontier_points.points.size()));

            if (local_frontier_points.points.size() > 0)
            {
                ROS_INFO("Switching to local navigation...");

                mapping_state = auto_mapping_state::LOCAL_NAVIGATION;
            }
            else
            {
                ROS_INFO("Switching to navigate to the origin...");

                mapping_state = auto_mapping_state::BACK_TO_ORIGIN_NAVIGATION;
            }
        }
        else if (mapping_state == auto_mapping_state::LOCAL_NAVIGATION ||
                 mapping_state == auto_mapping_state::GLOBAL_NAVIGATION)
        {
            rrt_nodes frontier_points;

            if (mapping_state == auto_mapping_state::LOCAL_NAVIGATION)
            {
                ROS_INFO("Performing local navigation...");

                auto_mapping_state_data.state = AUTO_MAPPING_STATE_LOCAL_NAVIGATION;

                frontier_points = local_frontier_points;

                ROS_INFO("Selecting best local frontier point...");
            }
            else
            {
                ROS_INFO("Performing global navigation...");

                auto_mapping_state_data.state = AUTO_MAPPING_STATE_GLOBAL_NAVIGATION;

                frontier_points = global_frontier_points;

                ROS_INFO("Selecting best global frontier point...");
            }

            update_current_pose();

            vector<pair<int, float>> index_score_pairs;
            index_score_pairs.reserve(frontier_points.points.size());

            if (mapping_state == auto_mapping_state::LOCAL_NAVIGATION)
            {
                for (int i = 0; i < static_cast<int>(frontier_points.points.size()); i++)
                {
                    geometry_msgs::Point32 point = frontier_points.points[i];

                    float dist_to_current_pose = calculate_distance(robot_current_position, point);

                    if (dist_to_current_pose <= local_prefer_near_frontier_point_dist_threshold)
                    {
                        prefer_near_dist = true;

                        break;
                    }
                }

                if (prefer_near_dist)
                {
                    ROS_INFO("We prefer near frontier points.");
                }
                else
                {
                    ROS_INFO("We prefer far frontier points.");
                }
            }

            for (int i = 0; i < static_cast<int>(frontier_points.points.size()); i++)
            {
                geometry_msgs::Point32 point = frontier_points.points[i];

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

            ROS_INFO("Frontier points sorted, best point index: %d, max score: %f.",
                     index_score_pairs[0].first, index_score_pairs[0].second);

            ROS_INFO("Planning initial polyline path...");

            update_current_pose();
            geometry_msgs::PoseStamped start = robot_current_pose;
            geometry_msgs::PoseStamped goal = start;

            ROS_INFO("Planning...");

            current_global_plan.clear();
            tuple<bool, vector<geometry_msgs::PoseStamped>, vector<geometry_msgs::PoseStamped>> plan_result;

            for (const auto &candidate_point : index_score_pairs)
            {
                update_current_pose();
                start = robot_current_pose;

                goal.pose.position.x = frontier_points.points[candidate_point.first].x;
                goal.pose.position.y = frontier_points.points[candidate_point.first].y;
                goal.pose.position.z = frontier_points.points[candidate_point.first].z;
                goal.pose.orientation = tf::createQuaternionMsgFromYaw(
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
                    ROS_INFO("Replanning...");

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
                                ROS_INFO("Checking collision...");

                                if (share_common_distance_table ? (collision_predictor_instance->check(robot_current_pose,
                                                                                                       current_global_plan[i], 4, exploration_min_dist_to_obs,
                                                                                                       map_data, obs_dist_table,
                                                                                                       map_free_threshold, map_occupied_threshold))
                                                                : (collision_predictor_instance->check(robot_current_pose,
                                                                                                       current_global_plan[i], 4, exploration_min_dist_to_obs)))
                                {
                                    ROS_INFO("Future collision detected, replanning...");

                                    current_global_plan.clear();

                                    replanning_by_collision_counter++;

                                    break;
                                }
                            }
                        }

                        ROS_INFO("Navigating to way point %d (%lf, %lf)...", i,
                                 current_global_plan[i].pose.position.x,
                                 current_global_plan[i].pose.position.y);

                        if (calculate_distance(robot_current_pose.pose, current_global_plan[current_global_plan.size() - 1].pose) > exploration_min_dist_to_obs * 1.4)
                        {
                            if (i == current_global_plan.size() - 1 && i > 0 && enable_waypoint_backtracking)
                            {
                                geometry_msgs::Point32 p0, dir, pg;
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

                                    ROS_INFO("Checking collision...");

                                    if (share_common_distance_table ? (collision_predictor_instance->check(robot_current_pose,
                                                                                                           current_global_plan[i], 4, exploration_min_dist_to_obs * 1.5,
                                                                                                           map_data, obs_dist_table,
                                                                                                           map_free_threshold, map_occupied_threshold))
                                                                    : collision_predictor_instance->check(robot_current_pose,
                                                                                                          current_global_plan[i], 4, exploration_min_dist_to_obs * 1.5))
                                    {
                                        ROS_INFO("Future collision detected, replanning...");

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
                                    ROS_INFO("Future collision detected, replanning...");

                                    current_global_plan.clear();

                                    replanning_by_collision_counter++;

                                    break;
                                }
                            }

                            nav_functions_instance->cancel();
                            ros::Duration(0.2).sleep();

                            bool nav_req_result = nav_functions_instance->nav_to(
                                current_global_plan[i].pose.position.x,
                                current_global_plan[i].pose.position.y,
                                angles::to_degrees(tf::getYaw(current_global_plan[i].pose.orientation)),
                                max_x_vel, max_yaw_vel * 180.0f / M_PI, false, false, true);
                            ros::Duration(0.2).sleep();

                            bool blocked_in_running = false;

                            if (nav_req_result)
                            {
                                while (ros::ok())
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

                                    ros::Duration(0.1).sleep();
                                }

                                backtracking_points.push_back(robot_current_position);
                            }

                            if (blocked_in_running && !enable_collision_precheck && i != current_global_plan.size() - 1)
                            {
                                ROS_INFO("Future collision detected, replanning...");

                                current_global_plan.clear();

                                replanning_by_collision_counter++;

                                break;
                            }

                            ros::Duration(0.2).sleep();

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
                            ROS_INFO("No feasible path, refreshing frontier points...");

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
                ROS_INFO("No feasible path, refreshing frontier points...");

                current_global_plan.clear();

                mapping_state = auto_mapping_state::FIND_LOCAL_FRONTIER_POINTS;
            }
        }
        else if (mapping_state == auto_mapping_state::FIND_GLOBAL_FRONTIER_POINTS)
        {
            ROS_INFO("Finding global frontier points...");

            auto_mapping_state_data.state = AUTO_MAPPING_STATE_FIND_GLOBAL_FRONTIER_POINTS;

            ros::Time start_time = ros::Time::now();

            do
            {
                global_frontier_points = global_explorer_instance->get_frontier_points();

                if (global_frontier_points.points.size() > 0)
                {
                    break;
                }
                else
                {
                    ros::Duration(1.0).sleep();
                }

            } while ((ros::Time::now() - start_time).toSec() <= global_sampling_timeout_secs);

            ROS_INFO("%d global frontier points found.", (int)(global_frontier_points.points.size()));

            if (global_frontier_points.points.size() > 0)
            {
                ROS_INFO("Switching to global navigation...");

                mapping_state = auto_mapping_state::GLOBAL_NAVIGATION;
            }
            else
            {
                ROS_INFO("Exploration finished, please save the map.");

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
            ROS_INFO("Performing back-to-origin navigation...");

            auto_mapping_state_data.state = AUTO_MAPPING_STATE_BACK_TO_ORIGIN_NAVIGATION;

            ROS_INFO("Starting global exploration...");

            global_explorer_instance->reset();

            ROS_INFO("Resampling backtracking points. origin size: %d...",
                     (int)backtracking_points.size());

            update_current_pose();

            auto backtracking_points_reversed = backtracking_points;

            reverse(backtracking_points_reversed.begin(), backtracking_points_reversed.end());

            auto backtracking_points_resampled = resample_points(
                backtracking_points_reversed, polyline_path_max_length * 2.0f);
            vector<geometry_msgs::Point32> goal_positions;

            if (!enable_waypoint_backtracking)
            {
                backtracking_points_resampled.clear();
            }

            if (backtracking_points_resampled.size() > 0)
            {
                ROS_INFO("Backtracking points exist, size: %d, solving tsp optimization...",
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

            ROS_INFO("%d goal points set.", (int)goal_positions.size());

            for (int i = 0; i < goal_positions.size(); i++)
            {
                ROS_INFO("Planning initial polyline path to backtracking point %d...", i);

                update_current_pose();
                geometry_msgs::PoseStamped start = robot_current_pose;
                geometry_msgs::PoseStamped goal = start;
                goal.pose.position.x = goal_positions[i].x;
                goal.pose.position.y = goal_positions[i].y;
                goal.pose.position.z = goal_positions[i].z;
                goal.pose.orientation =
                    i == goal_positions.size() - 1 ? robot_origin_pose.pose.orientation : tf::createQuaternionMsgFromYaw(angles::normalize_angle(calc_seg_direction(start, goal_positions[i])));

                ROS_INFO("Planning...");

                current_global_plan.clear();
                tuple<bool, vector<geometry_msgs::PoseStamped>, vector<geometry_msgs::PoseStamped>> plan_result;
                plan_result = global_planner_instance->plan(
                    start, goal, map_data, planner_min_dist_to_obs, true, 1, true, polyline_path_max_length, 2, map_occupied_threshold);

                if (get<0>(plan_result))
                {
                    current_global_plan = get<2>(plan_result);
                }
                else if (i == goal_positions.size() - 1)
                {
                    ROS_INFO("Replanning...");

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
                    ROS_INFO("Replanning...");

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
                                ROS_INFO("Checking collision...");

                                if (share_common_distance_table ? (collision_predictor_instance->check(robot_current_pose,
                                                                                                       current_global_plan[j], 4, exploration_min_dist_to_obs,
                                                                                                       map_data, obs_dist_table,
                                                                                                       map_free_threshold, map_occupied_threshold))
                                                                : (collision_predictor_instance->check(robot_current_pose,
                                                                                                       current_global_plan[j], 4, exploration_min_dist_to_obs)))
                                {
                                    ROS_INFO("Future collision detected, replanning...");

                                    current_global_plan.clear();

                                    replanning_by_collision_counter++;

                                    break;
                                }
                            }

                            ROS_INFO("Navigating to way point %d (%lf, %lf)...", j,
                                     current_global_plan[j].pose.position.x,
                                     current_global_plan[j].pose.position.y);

                            nav_functions_instance->cancel();
                            ros::Duration(0.2).sleep();

                            bool nav_req_result = nav_functions_instance->nav_to(
                                current_global_plan[j].pose.position.x,
                                current_global_plan[j].pose.position.y,
                                angles::to_degrees(tf::getYaw(current_global_plan[j].pose.orientation)),
                                max_x_vel, max_yaw_vel * 180.0f / M_PI, false, false, true);
                            ros::Duration(0.2).sleep();

                            bool blocked_in_running = false;

                            if (nav_req_result)
                            {
                                while (ros::ok())
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

                                    ros::Duration(0.1).sleep();
                                }
                            }

                            if (blocked_in_running && !enable_collision_precheck)
                            {
                                ROS_INFO("Future collision detected, replanning...");

                                current_global_plan.clear();

                                replanning_by_collision_counter++;

                                break;
                            }

                            ros::Duration(0.2).sleep();

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
                                ROS_INFO("No feasible polyline path, using normal navigation to the point...");

                                nav_functions_instance->cancel();
                                ros::Duration(0.2).sleep();

                                nav_functions_instance->nav_to(
                                    goal.pose.position.x,
                                    goal.pose.position.y,
                                    angles::to_degrees(tf::getYaw(goal.pose.orientation)),
                                    max_x_vel / 2.0f, (max_yaw_vel * 180.0f / M_PI) / 2.0f, true, false, false);

                                navigation_done = true;
                            }
                            else
                            {
                                ROS_INFO("No feasible path, skip this point...");

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
                    ROS_INFO("No feasible path, skip this backtracking point...");

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
                ROS_INFO("Exploration stopping...");

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

        rate.sleep();
    }

    return 0;
}