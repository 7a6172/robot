#ifndef NAVIGATION_HANDLER_H
#define NAVIGATION_HANDLER_H

#include <rclcpp/rclcpp.hpp>
#include <math.h>
#include <unistd.h>
#include <fcntl.h>
#include <signal.h>
#include <termios.h>
#include <fstream>
#include <map>
#include <geometry_msgs/msg/pose_with_covariance_stamped.hpp>
#include <geometry_msgs/msg/twist.hpp>
#include <geometry_msgs/msg/twist_with_covariance_stamped.hpp>
#include <geometry_msgs/msg/polygon.hpp>
#include <nav_msgs/msg/occupancy_grid.hpp>
#include <nav_msgs/msg/path.hpp>
#include <nav_msgs/srv/get_plan.hpp>
#include <openmover_msgs/msg/nav_to_state.hpp>
#include <openmover_msgs/msg/obstacle.hpp>
#include <openmover_msgs/srv/nav_to_request.hpp>
#include <openmover_msgs/srv/nav_to_simple_request.hpp>
#include <openmover_msgs/srv/cmd_vel_mode_request.hpp>
#include <std_msgs/msg/bool.hpp>
#include <std_msgs/msg/int8.hpp>
#include <nav2_costmap_2d/costmap_2d_ros.hpp>
#include <nav2_util/node_thread.hpp>
#include "common/common_state_code.h"
#include "navigation/utils/local_planner/path_follower.h"
#include "navigation/utils/local_planner/mover.h"
#include "navigation/navigation_state_code.h"
#include "localization/localization_sources.h"
#include "navigation/utils/global_planner/planner_with_costmap.h"

#define NAV_DEBUG 0

#define SERVICE_WAIT_DURATION 30
#define SERVICE_RETRY_DURATION 1

using namespace std;
using namespace navigation_ns;

// 全局变量
// 定义全局节点与执行器（执行器必须在 rclcpp::init 之后创建，故使用指针）
rclcpp::Node::SharedPtr node;
rclcpp::Node::SharedPtr client_node;
std::unique_ptr<rclcpp::executors::SingleThreadedExecutor> executor;

// 定义代价地图（nav2 Costmap2DROS 本身是 LifecycleNode，由专属线程驱动）
shared_ptr<nav2_costmap_2d::Costmap2DROS> lcr_global;
shared_ptr<nav2_costmap_2d::Costmap2DROS> lcr_global_static;
unique_ptr<nav2_util::NodeThread> global_costmap_thread;
unique_ptr<nav2_util::NodeThread> global_costmap_static_thread;

// 定义全局规划器
shared_ptr<planner_with_costmap> global_planner_instance;
shared_ptr<planner_with_costmap> global_planner_static_instance;

// 定义状态
enum navigation_mode
{
    NAVIGATION_MAP,
    NAVIGATION_ODOM,
    MOVE_MAP,
    MOVE_ODOM,
    UNKNOW
};

navigation_state state = navigation_state::READY;
navigation_mode mode = navigation_mode::UNKNOW;

// 定义参数
// 通用部分
float control_freq;
float max_x_vel, min_x_vel, max_x_acc;
float max_yaw_vel, min_yaw_vel, max_yaw_acc;
float velocity_dec_line_offset_time, velocity_dec_angle_offset_time;
float strighting_stop_distance, turning_stop_distance, ignore_obstacle_dist;
float obstacle_acc_ratio, collision_vel_dec_ratio;
int collision_plan_try_count, collision_trajectory_sampling_ratio, collision_path_sampling_ratio;
float collision_path_dist_error_tolerance, collision_path_angle_error_tolerance;
float collision_obstacle_detection_area_padding_ratio;
int collision_narrow_section_padding;
float strighting_tolerance, turning_tolerance;
float sensor_msg_timeout;

// 自主导航部分
int map_free_threshold, map_occupied_threshold;
bool use_global_planner;
bool always_replan;
float planner_min_dist_to_obs;
bool use_advanced_evaluation;
bool use_kinematic_limits;
bool use_find_mode_follower;
bool use_obstacle_avoid;
bool allow_reverse_drive;
float find_mode_x_vel, find_mode_yaw_vel, find_mode_radius, find_mode_min_dist_timeout;
bool enable_near_angle_correct;
float angle_diff_to_forward, angle_diff_to_rotate;
float xy_tolerance, yaw_tolerance;
float chassis_radius;
float sim_time, find_mode_sim_time;
int sim_vx_space_size, sim_vyaw_space_size, trajectory_sim_step;
float follow_point_weight, follow_path_weight, obstacle_avoid_weight;
int max_global_plan_try_count;

bool replan_flag = false;

// 足迹部分
geometry_msgs::msg::Polygon footprint_polygon;

// 标识部分
bool pose_received = false;
bool odom_received = false;
bool odom_twist_received = false;
bool obstacle_received = false;
bool request_from_simple_goal = false;
bool button_received = false;
bool button_required = false;
bool map_received = false;

// 命令接收时间
rclcpp::Time cmd_received_time = rclcpp::Time(0, 0, RCL_ROS_TIME);

// nav_to_state 话题发布器
rclcpp::Publisher<openmover_msgs::msg::NavToState>::SharedPtr nav_to_state_pub;

// 插补数据发布器
rclcpp::Publisher<nav_msgs::msg::Path>::SharedPtr linear_path_pub;

// 接管速度控制服务
rclcpp::Client<openmover_msgs::srv::CmdVelModeRequest>::SharedPtr cmd_vel_mode_client;

// 定义机器人全局位姿数据
geometry_msgs::msg::PoseWithCovarianceStamped pose_data;
rclcpp::Time pose_data_last_received_time = rclcpp::Time(0, 0, RCL_ROS_TIME);

// 定义机器人里程计数据
geometry_msgs::msg::PoseWithCovarianceStamped odom_data;
rclcpp::Time odom_data_last_received_time = rclcpp::Time(0, 0, RCL_ROS_TIME);

// 定义机器人里程计速度数据
geometry_msgs::msg::TwistWithCovarianceStamped odom_twist_data;

// 定义obstacle数据
openmover_msgs::msg::Obstacle obstacle_data;
rclcpp::Time obstacle_data_last_received_time = rclcpp::Time(0, 0, RCL_ROS_TIME);

// 定义cmd_vel数据
geometry_msgs::msg::Twist twist_data;

// 定义button数据
std_msgs::msg::Bool button_data;

nav_msgs::msg::OccupancyGrid map_data;

// 定义目标点数据
openmover_msgs::srv::NavToRequest::Request nav_to_request_data;

// 定义导航状态数据
openmover_msgs::msg::NavToState nav_to_state_data;
block_state obstacle_state_data;

// 定义紧急制动状态
std_msgs::msg::Bool emergency_data;
bool emergency_data_received = false;

// 定义移动控制器
unique_ptr<mover> mover_controller;

// 定义自主导航控制器
unique_ptr<path_follower> path_follower_controller;

#endif
