#ifndef TSP_OPTIMIZATION_H
#define TSP_OPTIMIZATION_H

#include <rclcpp/rclcpp.hpp>
#include <random>
#include <map>
#include <unordered_map>
#include <unordered_set>
#include <utils/math_utils.h>
#include <utils/auto_mapping/rrt_common.h>
#include <nav_msgs/msg/occupancy_grid.hpp>
#include <visualization_msgs/msg/marker_array.hpp>
#include <tf2_ros/buffer.h>
#include <tf2_ros/transform_listener.hpp>
#include <tf2_geometry_msgs/tf2_geometry_msgs.hpp>
#include <geometry_msgs/msg/pose_stamped.hpp>

using namespace std;

namespace tsp_optimization
{
    class tsp_solver
    {
    public:
        tsp_solver() {};
        ~tsp_solver() {};

        vector<geometry_msgs::msg::Point32> optimize(const geometry_msgs::msg::Point32 &p_start,
                                                const geometry_msgs::msg::Point32 &p_goal,
                                                const vector<geometry_msgs::msg::Point32> &waypoints);
    };
}

#endif