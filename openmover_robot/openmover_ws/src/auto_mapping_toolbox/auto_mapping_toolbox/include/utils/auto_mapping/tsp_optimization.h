#ifndef TSP_OPTIMIZATION_H
#define TSP_OPTIMIZATION_H

#include <ros/ros.h>
#include <random>
#include <map>
#include <unordered_map>
#include <unordered_set>
#include <utils/math_utils.h>
#include <utils/auto_mapping/rrt_common.h>
#include <nav_msgs/OccupancyGrid.h>
#include <visualization_msgs/MarkerArray.h>
#include <tf/tf.h>
#include <tf2_ros/transform_listener.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.h>
#include <geometry_msgs/PoseStamped.h>

using namespace std;

namespace tsp_optimization
{
    class tsp_solver
    {
    public:
        tsp_solver() {};
        ~tsp_solver() {};

        vector<geometry_msgs::Point32> optimize(const geometry_msgs::Point32 &p_start,
                                                const geometry_msgs::Point32 &p_goal,
                                                const vector<geometry_msgs::Point32> &waypoints);
    };
}

#endif