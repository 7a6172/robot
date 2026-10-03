/**
 * @author
 *   ZHANG Muhua
 * @affiliation
 *   Southwest Jiaotong University
 * @license
 *   GPL-3.0 License
 *
 * ROS 2 Jazzy port by zar (zar@my.swjtu.edu.cn)
 */

#ifndef SUBMAP_SET_2D_H
#define SUBMAP_SET_2D_H

#include <rclcpp/rclcpp.hpp>
#include <random>
#include <map>
#include <unordered_map>
#include <utils/math_utils.h>
#include <utils/2d/sector_query_2d.h>
#include <utils/2d/sampling_2d.h>
#include <nav_msgs/msg/occupancy_grid.hpp>
#include <visualization_msgs/msg/marker_array.hpp>
#include <tf2/utils.hpp>
#include <tf2/LinearMath/Quaternion.h>
#include <tf2_ros/transform_listener.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.hpp>
#include <sensor_msgs/msg/laser_scan.hpp>
#include <geometry_msgs/msg/pose_with_covariance_stamped.hpp>
#include <geometry_msgs/msg/transform_stamped.hpp>
#include <sensor_msgs/msg/point_cloud2.hpp>
#include <sensor_msgs/point_cloud2_iterator.hpp>
#include <atomic>

using namespace std;

namespace submap_set_2d
{
    class submap_set_2d
    {
    public:
        submap_set_2d(rclcpp::Node::SharedPtr node, const bool &use_reachability_sampling = false,
                      const float &rrt_min_expand_dist = 0.5, const float &rrt_max_expand_dist = 1.0, const int &reachability_sampling_duration = 5,
                      const int &map_free_threshold = 30, const int &map_occupied_threshold = 50,
                      const float &sensing_radius = 10.0f, const float &anchor_point_min_dist = 2.0f,
                      const float &angle_search_step = 0.174);
        ~submap_set_2d() {};

        vector<tuple<geometry_msgs::msg::Point32, nav_msgs::msg::OccupancyGrid, vector<float>>> get_submap_set(
            const nav_msgs::msg::OccupancyGrid &map,
            const sensor_msgs::msg::LaserScan &scan,
            const bool &lidar_reverted,
            const int &lidar_sampling_step,
            const vector<float> &min_dist_to_obs_table,
            float &min_dist_to_obstacle,
            const bool &enable_visualization = false);

    private:
        bool use_reachability_sampling_;
        float rrt_min_expand_dist_, rrt_max_expand_dist_;
        int reachability_sampling_duration_;

        int map_free_threshold_;
        int map_occupied_threshold_;
        float sensing_radius_;
        float anchor_point_min_dist_;
        float angle_search_step_;

        rclcpp::Node::SharedPtr node_;
        rclcpp::Publisher<sensor_msgs::msg::PointCloud2>::SharedPtr anchor_point_pub_;

        nav_msgs::msg::OccupancyGrid get_submap(const nav_msgs::msg::OccupancyGrid &map,
                                           const sensor_msgs::msg::LaserScan &scan,
                                           const bool &lidar_reverted,
                                           const int &lidar_sampling_step,
                                           const geometry_msgs::msg::Point32 &anchor_point,
                                           const float &max_radius);

        vector<float> get_mean_dist_list(const nav_msgs::msg::OccupancyGrid &map,
                                         const sensor_msgs::msg::LaserScan &scan,
                                         const bool &lidar_reverted,
                                         const int &lidar_sampling_step,
                                         const geometry_msgs::msg::Point32 &anchor_point,
                                         const float &max_radius);
    };
}

#endif