#ifndef RRT_COMMON_H
#define RRT_COMMON_H

#include <unordered_map>
#include <utils/math_utils.h>
#include <localization/localization_sources.h>
#include <geometry_msgs/msg/point.hpp>
#include <geometry_msgs/msg/point32.hpp>

using namespace std;

struct rrt_nodes
{
    vector<int> indices;
    vector<geometry_msgs::msg::Point32> points;
    vector<int> prev_indices;
    vector<geometry_msgs::msg::Point32> prev_points;
    vector<vector<int>> next_indices;
    vector<vector<geometry_msgs::msg::Point32>> next_points;
    vector<float> info_gains;
    vector<bool> del_states;
};

#endif