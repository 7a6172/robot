// 2023-10-8 0.0.0.8A

#ifndef PATH_FOLLOWER
#define PATH_FOLLOWER

#include <string>
#include <vector>
#include <math.h>
#include <ros/ros.h>
#include <limits.h>
#include <vector>
#include <tf/tf.h>
#include <angles/angles.h>
#include <nav_msgs/Odometry.h>
#include <nav_msgs/Path.h>
#include <geometry_msgs/Twist.h>
#include <geometry_msgs/PoseStamped.h>
#include <geometry_msgs/PoseWithCovarianceStamped.h>
#include <geometry_msgs/TwistWithCovarianceStamped.h>
#include <openmover_msgs/obstacle.h>
#include <navigation/utils/controllers.h>
#include <navigation/navigation_state_code.h>
#include <navigation/utils/local_planner/mover.h>
#include <navigation/utils/path_checker/path_checker.h>
#include <navigation/utils/collision_checker/collision_checker.h>
#include <navigation/utils/global_planner/planner_with_costmap.h>
#include <omp.h>

#define PF_DEBUG 1

using namespace std;
using namespace navigation_ns;

class path_follower
{
public:
    path_follower(float max_x_vel, float min_x_vel, float max_x_acc, float max_yaw_vel, float min_yaw_vel, float max_yaw_acc, bool allow_reverse_drive,
                  bool use_advanced_evaluation, bool use_kinematic_limits, bool use_find_mode_follower,
                  float velocity_dec_offset_time,
                  float find_mode_x_vel, float find_mode_yaw_vel, float find_mode_radius, float find_mode_min_dist_timeout, bool enable_near_angle_correct,
                  float angle_diff_to_forward, float angle_diff_to_rotate,
                  float xy_tolerance, float yaw_tolerance,
                  float chassis_radius,
                  float sim_time, float find_mode_sim_time, int sim_vx_space_size, int sim_vyaw_space_size, int trajectory_sim_step, float follow_point_weight, float follow_path_weight,
                  float stop_distance, float turning_stop_distance, float ignore_obstacle_dist,
                  float obstacle_acc_ratio, float collision_vel_dec_ratio,
                  int collision_plan_try_count, int collision_trajectory_sampling_ratio, int collision_path_sampling_ratio,
                  float collision_path_dist_error_tolerance, float collision_path_angle_error_tolerance,
                  float collision_obstacle_detection_area_padding_ratio, int collision_narrow_section_padding,
                  geometry_msgs::Polygon footprint,
                  float control_freq,
                  shared_ptr<planner_with_costmap> global_planner_instance,
                  int occupied_threshold,
                  float planner_min_dist_to_obs);
    ~path_follower();
    void set_kinematic_params(float max_x_vel, float max_yaw_vel);
    void set_obstacle_stop_params(float strighting_stop_distance, float turning_stop_distance);
    void set_tolerance_params(float xy_tolerance, float yaw_tolerance);
    bool make_plan(geometry_msgs::PoseWithCovarianceStamped pose, vector<geometry_msgs::PoseStamped> plan, bool ignore_obstacle, bool replan_flag);
    bool start_session();
    bool pause_session();
    bool continue_session();
    navigation_state loop(geometry_msgs::PoseWithCovarianceStamped pose,
                          geometry_msgs::TwistWithCovarianceStamped odom_twist,
                          openmover_msgs::obstacle obstacle,
                          geometry_msgs::Polygon footprint,
                          nav_msgs::OccupancyGrid &grid);
    geometry_msgs::Twist get_current_twist();
    geometry_msgs::PoseWithCovarianceStamped get_current_pose();
    geometry_msgs::PoseStamped get_current_path_point_pose();
    block_state get_obstacle_state();
    void reset_state();
    static float distance(geometry_msgs::Pose pose0, geometry_msgs::Pose pose1);

private:
    float max_x_vel_, min_x_vel_, max_x_acc_, max_yaw_vel_, min_yaw_vel_, max_yaw_acc_;
    bool allow_reverse_drive_;
    bool use_advanced_evaluation_;
    bool use_kinematic_limits_;
    bool use_find_mode_follower_;

    float velocity_dec_offset_time_;

    float find_mode_x_vel_, find_mode_yaw_vel_, find_mode_radius_, find_mode_min_dist_timeout_;
    bool enable_near_angle_correct_;
    float angle_diff_to_forward_, angle_diff_to_rotate_;
    float xy_tolerance_, yaw_tolerance_;
    float chassis_radius_;
    float sim_time_, find_mode_sim_time_;
    int sim_vx_space_size_, sim_vyaw_space_size_, trajectory_sim_step_;
    float follow_point_weight_, follow_path_weight_;
    float stop_distance_, turning_stop_distance_, ignore_obstacle_dist_;

    float obstacle_acc_ratio_, collision_vel_dec_ratio_;
    int collision_plan_try_count_, collision_trajectory_sampling_ratio_, collision_path_sampling_ratio_;
    float collision_path_dist_error_tolerance_, collision_path_angle_error_tolerance_;
    float collision_obstacle_detection_area_padding_ratio_;
    int collision_narrow_section_padding_;
    bool unable_to_find_collision_plan_flag_;
    vector<point_with_collision_marker> path_with_collision_markers_;
    bool pose_out_of_collision_path_;
    bool obstacle_avoid_mode_;

    geometry_msgs::Polygon footprint_;

    float control_freq_;

    geometry_msgs::Pose goal_;
    vector<geometry_msgs::PoseStamped> plan_;
    bool ignore_obstacle_;

    geometry_msgs::PoseWithCovarianceStamped pose_;
    openmover_msgs::obstacle obstacle_;
    int current_point_in_path_;

    unique_ptr<mover> mover_;
    unique_ptr<path_checker> path_checker_;
    unique_ptr<collision_checker> collision_checker_;

    bool reverse_drive_;
    bool find_mode_;
    int find_mode_counter_;
    float dist_;
    float min_dist_;
    bool near_angle_corrected_;
    bool stand_at_goal_;

    bool acc_controlled_;
    bool last_acc_controlled_;
    geometry_msgs::Twist twist_target_;
    geometry_msgs::Twist last_twist_target_;
    geometry_msgs::Twist twist_;
    geometry_msgs::TwistWithCovarianceStamped odom_twist_;
    float vx_delta_;
    float vyaw_delta_;

    block_state obstacle_state_;
    navigation_state state_;
    navigation_state last_state_before_blocked_;
    navigation_state last_state_;

    ros::NodeHandle node_handle_;
    ros::Publisher current_point_in_path_pub_;
    ros::Publisher point_to_track_pub_;
    ros::Publisher all_trajectory_pub_;
    ros::Publisher best_trajectory_pub_;

    nav_msgs::Path current_best_trajectory_;

    robot_pose_index_finder *robot_pose_index_finder_instance_;
    robot_pose_index_finder robot_pose_index_finder_a_;
    robot_pose_index_finder robot_pose_index_finder_b_;
    int robot_pose_index_finder_id_;
    int map_occupied_threshold_;
    float planner_min_dist_to_obs_;
    shared_ptr<planner_with_costmap> global_planner_instance_;

    nav_msgs::OccupancyGrid grid_;

    bool replan_flag_;

    enum rotation_state
    {
        READY,
        RUNNING,
        REACHED
    };

    rotation_state rotation_state_;

    std::mutex global_planner_mutex_;
    bool global_planner_flag_;

    void update_current_point_in_path();
    bool rotate(float angle = 0.0f, float tolerance = 0.0f, float max_yaw_vel = 0.0f, bool yaw_servo_mode = false);
    int get_max_sim_distance_point_index();
    int get_max_sim_angle_point_index(int point_index);
    tuple<float, float> calc_goal_angle();
    tuple<float, float> calc_global_plan_angle(int point_index);
    nav_msgs::Path trajectory_simulation(float &vx, float &vyaw,
                                         int max_sim_point_index,
                                         float max_x_vel, float max_yaw_vel,
                                         float sim_time);
    block_state is_obstacle_detected();
    void replan_global_plan();
};

#endif