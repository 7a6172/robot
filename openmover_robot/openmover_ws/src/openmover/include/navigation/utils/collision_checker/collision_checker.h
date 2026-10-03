#ifndef COLLISION_CHECKER
#define COLLISION_CHECKER

#include <ros/ros.h>
#include <geometry_msgs/PoseStamped.h>
#include <geometry_msgs/PoseWithCovarianceStamped.h>
#include <geometry_msgs/PolygonStamped.h>
#include <geometry_msgs/Polygon.h>
#include <visualization_msgs/MarkerArray.h>
#include <nav_msgs/Path.h>
#include <tf/tf.h>
#include <openmover_msgs/obstacle.h>
#include <navigation/utils/math_utils.h>

using namespace std;

class collision_checker
{
public:
    collision_checker();
    ~collision_checker();
    tuple<bool, vector<float>> check(geometry_msgs::PoseWithCovarianceStamped &pose,
                                     geometry_msgs::PoseWithCovarianceStamped &obstacle_pose,
                                     geometry_msgs::Polygon &footprint,
                                     nav_msgs::Path &trajectory,
                                     openmover_msgs::obstacle &obstacle,
                                     int trajectory_sampling_ratio = 1,
                                     bool visualization = true);
    bool check(geometry_msgs::PoseWithCovarianceStamped &pose,
               geometry_msgs::PoseWithCovarianceStamped &obstacle_pose,
               geometry_msgs::Polygon &footprint,
               vector<geometry_msgs::PoseStamped> &path,
               int current_point_index,
               float sim_time, float max_vel_x,
               openmover_msgs::obstacle &obstacle,
               int trajectory_sampling_ratio = 1);

private:
    ros::NodeHandle node_handle_;
    ros::Publisher footprint_transformed_pub_;
    ros::Publisher obstacle_lines_pub_;

    string frame_id_;
};

#endif