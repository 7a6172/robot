#ifndef COLLISION_CHECKER
#define COLLISION_CHECKER

#include <rclcpp/rclcpp.hpp>
#include <geometry_msgs/msg/pose_stamped.hpp>
#include <geometry_msgs/msg/pose_with_covariance_stamped.hpp>
#include <geometry_msgs/msg/polygon_stamped.hpp>
#include <geometry_msgs/msg/polygon.hpp>
#include <visualization_msgs/msg/marker_array.hpp>
#include <nav_msgs/msg/path.hpp>
#include <tf2/utils.hpp>
#include <tf2_geometry_msgs/tf2_geometry_msgs.hpp>
#include <openmover_msgs/msg/obstacle.hpp>
#include <navigation/utils/math_utils.h>

using namespace std;

class collision_checker
{
public:
    collision_checker(rclcpp::Node *node = nullptr);
    ~collision_checker();
    tuple<bool, vector<float>> check(geometry_msgs::msg::PoseWithCovarianceStamped &pose,
                                     geometry_msgs::msg::PoseWithCovarianceStamped &obstacle_pose,
                                     geometry_msgs::msg::Polygon &footprint,
                                     nav_msgs::msg::Path &trajectory,
                                     openmover_msgs::msg::Obstacle &obstacle,
                                     int trajectory_sampling_ratio = 1,
                                     bool visualization = true);
    bool check(geometry_msgs::msg::PoseWithCovarianceStamped &pose,
               geometry_msgs::msg::PoseWithCovarianceStamped &obstacle_pose,
               geometry_msgs::msg::Polygon &footprint,
               vector<geometry_msgs::msg::PoseStamped> &path,
               int current_point_index,
               float sim_time, float max_vel_x,
               openmover_msgs::msg::Obstacle &obstacle,
               int trajectory_sampling_ratio = 1);

private:
    rclcpp::Node *node_ = nullptr;
    rclcpp::Publisher<geometry_msgs::msg::PolygonStamped>::SharedPtr footprint_transformed_pub_;
    rclcpp::Publisher<visualization_msgs::msg::MarkerArray>::SharedPtr obstacle_lines_pub_;

    string frame_id_;
};

#endif