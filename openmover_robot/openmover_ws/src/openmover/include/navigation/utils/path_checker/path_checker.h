#ifndef PATH_CHECKER
#define PATH_CHECKER

#include <ros/ros.h>
#include <geometry_msgs/PoseWithCovarianceStamped.h>
#include <nav_msgs/Path.h>
#include <sensor_msgs/LaserScan.h>
#include <geometry_msgs/Polygon.h>
#include <visualization_msgs/MarkerArray.h>
#include <nav_msgs/OccupancyGrid.h>
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
    geometry_msgs::PoseStamped pose;
};

class path_checker
{
public:
    path_checker();
    ~path_checker();
    vector<point_with_collision_marker> check(nav_msgs::Path path,
                                              geometry_msgs::Polygon &footprint,
                                              float stop_distance,
                                              float obstacle_detection_area_padding_ratio = 1.2,
                                              int narrow_section_padding = 20,
                                              int sampling_ratio = 1);

private:
    ros::NodeHandle node_handle_;
    ros::Publisher visual_marker_array_pub_;
    ros::Publisher path_with_orientation_pub_;

    string frame_id_;
    nav_msgs::OccupancyGridConstPtr map_;
};

#endif