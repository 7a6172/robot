#ifndef PATH_CHECKER
#define PATH_CHECKER

#include <rclcpp/rclcpp.hpp>
#include <geometry_msgs/msg/pose_with_covariance_stamped.hpp>
#include <nav_msgs/msg/path.hpp>
#include <sensor_msgs/msg/laser_scan.hpp>
#include <geometry_msgs/msg/polygon.hpp>
#include <visualization_msgs/msg/marker_array.hpp>
#include <nav_msgs/msg/occupancy_grid.hpp>
#include <navigation/utils/math_utils.h>
#include <localization/localization_sources.h>

#define PC_DEBUG 1

using namespace std;

enum point_collision_mode
{
    undefined = 0,
    normal = 1,
    narrow = 2
};

struct point_with_collision_marker
{
    point_collision_mode mode_forward_drive;
    point_collision_mode mode_reverse_drive;
    geometry_msgs::msg::PoseStamped pose;
};

class path_checker
{
public:
    path_checker(rclcpp::Node *node = nullptr);
    ~path_checker();
    vector<point_with_collision_marker> check(nav_msgs::msg::Path path,
                                              geometry_msgs::msg::Polygon &footprint,
                                              float stop_distance,
                                              float obstacle_detection_area_padding_ratio = 1.2,
                                              int narrow_section_padding = 20,
                                              int sampling_ratio = 1);

private:
    rclcpp::Node *node_ = nullptr;
    rclcpp::Publisher<visualization_msgs::msg::MarkerArray>::SharedPtr visual_marker_array_pub_;
    rclcpp::Publisher<nav_msgs::msg::Path>::SharedPtr path_with_orientation_pub_;

    string frame_id_;
    nav_msgs::msg::OccupancyGrid::ConstSharedPtr map_;
};

#endif